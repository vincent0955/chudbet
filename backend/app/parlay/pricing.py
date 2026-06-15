"""Server-authoritative pricing engine for parlays and wagers.

This module is the single choke point for recomputing authoritative leg lines
and odds, validating client-supplied lines (rejecting on drift), substituting
server-computed odds for client values, and applying the house margin once at
the ticket level.

Task 2 scope: pricing exceptions and odds-math helpers. The line lookups,
``apply_house_margin``, and ``price_ticket`` orchestration are implemented in
later tasks.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.core.config import get_book_margin, get_line_drift_tolerance
from app.db.enums import (
    GameMarketType,
    GameSelection,
    LegDirection,
    ParlayMode,
    Sport,
    StatType,
)
from app.db.models import Game
from app.mlb.enums import MLBStatType
from app.mlb.game_markets import build_mlb_game_markets
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle
from app.parlay.math import (
    fair_decimal_odds,
    joint_probability_standard,
    joint_probability_x_of_y,
    leg_win_probability,
    sample_mean_std,
)
from app.services.game_markets import build_game_markets
from app.services.game_prop_lines import build_game_prop_lines_bundle
from app.services.game_wager_gate import require_pre_game_game_for_wager

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.api.parlay_schemas import ParlayCreate
    from app.api.schemas import GameMarketsRead

# Tiny edge kept above an even-money payout so that, for any fair_decimal > 1,
# the margined payout is always strictly greater than 1.0.
MIN_EDGE = 1e-6


class PricingError(ValueError):
    """Base for pricing/validation failures.

    ``http_status`` drives the API response. Subclasses ``ValueError`` so that
    existing ``except ValueError`` catch-sites keep mapping to HTTP 400.
    """

    http_status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PricingValidationError(PricingError):
    """HTTP 400 — selection not offered, bad input, or insufficient history."""

    http_status = 400


class LineDriftError(PricingError):
    """HTTP 409 — client line moved beyond the configured tolerance."""

    http_status = 409


def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal odds.

    Positive American odds: ``1 + american / 100``.
    Negative American odds: ``1 + 100 / abs(american)``.

    Raises ``ValueError`` for ``0`` (American odds are always non-zero in
    practice; guard against div-by-zero).
    """
    if american == 0:
        raise ValueError("american odds must be non-zero")
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def implied_prob_from_american(american: int) -> float:
    """Implied (with-vig) win probability from American odds.

    Positive American odds: ``100 / (american + 100)``.
    Negative American odds: ``abs(american) / (abs(american) + 100)``.
    """
    if american == 0:
        raise ValueError("american odds must be non-zero")
    if american > 0:
        return 100.0 / (american + 100.0)
    a = abs(american)
    return a / (a + 100.0)


def devig_two_way(american_a: int, american_b: int) -> tuple[float, float]:
    """No-vig fair probabilities for a two-way market.

    Computes implied probabilities for each side and normalizes them so they
    sum to 1.0, removing the bookmaker's vig.

    Returns ``(p_a, p_b)`` with ``p_a + p_b == 1.0`` (within float tolerance).
    """
    q_a = implied_prob_from_american(american_a)
    q_b = implied_prob_from_american(american_b)
    total = q_a + q_b
    return q_a / total, q_b / total


def apply_house_margin(fair_decimal: float, margin: float | None = None) -> float:
    """Reduce fair decimal odds by the house margin to produce payout odds.

    The margin is converted to an overround multiplier and applied exactly once
    to the aggregated ticket's fair odds::

        overround = 1 + margin / (2 + margin)        # 0.14 -> ~1.0654
        payout    = fair_decimal / overround

    The result is clamped to ``1 < payout <= fair_decimal`` via
    ``min(fair_decimal, max(payout, 1 + MIN_EDGE))``. For any
    ``fair_decimal > 1`` this guarantees the payout pays out on a win (strictly
    greater than 1) and never exceeds the fair odds. For degenerate near-certain
    tickets where ``fair_decimal <= 1 + MIN_EDGE``, the ``min`` clamp keeps
    ``payout = fair_decimal``.

    When ``margin`` is ``None`` it is read from ``get_book_margin()``.
    """
    if margin is None:
        margin = get_book_margin()
    overround = 1.0 + margin / (2.0 + margin)
    payout = fair_decimal / overround
    payout = min(fair_decimal, max(payout, 1.0 + MIN_EDGE))
    return payout


def _parse_american(s: str) -> int:
    """Parse an American-odds string like ``"-114"`` or ``"+120"`` to an int.

    Strips surrounding whitespace and a single leading ``+`` before ``int()``.
    """
    return int(s.strip().lstrip("+"))


@dataclass(frozen=True)
class GameLineQuote:
    """Authoritative quote for a single game-market selection.

    ``side_american`` is the authoritative American odds for the chosen side and
    ``other_american`` is the opposite side's American odds; both are returned so
    callers can de-vig the two-way market. ``line`` is ``None`` for moneyline.
    """

    line: float | None
    odds_american: int
    side_american: int
    other_american: int


# Map a StatType to the prop-bundle attribute names for line and both americans.
_PROP_STAT_FIELDS: dict[StatType, tuple[str, str, str]] = {
    StatType.PTS: ("pts_line", "pts_over_american", "pts_under_american"),
    StatType.REB: ("reb_line", "reb_over_american", "reb_under_american"),
    StatType.AST: ("ast_line", "ast_over_american", "ast_under_american"),
}


def authoritative_prop_line(
    session: "Session", game: "Game", player_id: int, stat: StatType
) -> float | None:
    """Authoritative player-prop line for ``(player, game, stat)``.

    Builds the prop bundle via ``build_game_prop_lines_bundle`` and returns the
    player's line for the requested stat. Returns ``None`` when the player is not
    in the bundle or when the line is ``None`` (insufficient samples).
    """
    fields = _PROP_STAT_FIELDS.get(stat)
    if fields is None:
        return None
    line_attr, _over_attr, _under_attr = fields

    bundle = build_game_prop_lines_bundle(session, game)
    player = next((p for p in bundle.players if p.id == player_id), None)
    if player is None:
        return None
    return getattr(player, line_attr)


def authoritative_prop_quote(
    session: "Session", game: "Game", player_id: int, stat: StatType
) -> tuple[float, int, int] | None:
    """Authoritative prop line plus over/under americans for ``(player, game, stat)``.

    Returns ``(line, over_american, under_american)`` with the americans parsed to
    ints, or ``None`` when the player is absent or the line is ``None``.
    """
    fields = _PROP_STAT_FIELDS.get(stat)
    if fields is None:
        return None
    line_attr, over_attr, under_attr = fields

    bundle = build_game_prop_lines_bundle(session, game)
    player = next((p for p in bundle.players if p.id == player_id), None)
    if player is None:
        return None
    line = getattr(player, line_attr)
    if line is None:
        return None
    over_american = _parse_american(getattr(player, over_attr))
    under_american = _parse_american(getattr(player, under_attr))
    return float(line), over_american, under_american


def _game_line_quote_from_markets(
    markets: "GameMarketsRead",
    market_type: GameMarketType,
    selection: GameSelection,
) -> GameLineQuote | None:
    """Parse a ``GameMarketsRead`` into a ``GameLineQuote`` for the selection.

    Shared by the NBA and MLB pricers: both build the same ``GameMarketsRead``
    shape (moneyline/spread/total) so the parsing logic is identical. Returns
    ``None`` when the ``(market_type, selection)`` combination is
    unrecognized/mismatched.
    """
    if market_type == GameMarketType.MONEYLINE:
        ml = markets.moneyline
        home = _parse_american(ml.home_american)
        away = _parse_american(ml.away_american)
        if selection == GameSelection.HOME:
            return GameLineQuote(line=None, odds_american=home, side_american=home, other_american=away)
        if selection == GameSelection.AWAY:
            return GameLineQuote(line=None, odds_american=away, side_american=away, other_american=home)
        return None

    if market_type == GameMarketType.SPREAD:
        sp = markets.spread
        home = _parse_american(sp.home_american)
        away = _parse_american(sp.away_american)
        if selection == GameSelection.HOME:
            return GameLineQuote(
                line=float(sp.home_line), odds_american=home, side_american=home, other_american=away
            )
        if selection == GameSelection.AWAY:
            return GameLineQuote(
                line=float(sp.away_line), odds_american=away, side_american=away, other_american=home
            )
        return None

    if market_type == GameMarketType.TOTAL:
        tot = markets.total
        over = _parse_american(tot.over_american)
        under = _parse_american(tot.under_american)
        if selection == GameSelection.OVER:
            return GameLineQuote(
                line=float(tot.line), odds_american=over, side_american=over, other_american=under
            )
        if selection == GameSelection.UNDER:
            return GameLineQuote(
                line=float(tot.line), odds_american=under, side_american=under, other_american=over
            )
        return None

    return None


def authoritative_game_line(
    session: "Session",
    game: "Game",
    market_type: GameMarketType,
    selection: GameSelection,
) -> GameLineQuote | None:
    """Authoritative quote for ``(game, market_type, selection)`` (NBA path).

    Builds markets via ``build_game_markets`` and returns a ``GameLineQuote`` for
    the requested selection, parsing American strings to ints. Returns ``None``
    when the ``(market_type, selection)`` combination is unrecognized/mismatched.
    """
    markets = build_game_markets(session, game)
    return _game_line_quote_from_markets(markets, market_type, selection)


# --- Sport-aware pricer registry (Requirement 13) ---------------------------
#
# A single strategy boundary keyed by ``Sport`` so that ``price_ticket`` can
# price NBA and MLB legs through one code path. The NBA pricer wraps the
# existing ``authoritative_*`` functions unchanged so the NBA path stays
# behaviorally identical (Req 15.3/15.4); the MLB pricer wraps the baseball
# market/prop services and the ``MLBStatType`` vocabulary.

_NBA_STAT_VALUES = frozenset(s.value for s in StatType)
_MLB_STAT_VALUES = frozenset(s.value for s in MLBStatType)


class SportPricer(Protocol):
    """Per-sport authoritative pricing strategy used by :func:`price_ticket`."""

    def game_line(
        self,
        session: "Session",
        game: "Game",
        market_type: GameMarketType,
        selection: GameSelection,
    ) -> GameLineQuote | None: ...

    def prop_quote(
        self,
        session: "Session",
        game: "Game",
        player_id: int,
        stat: object,
    ) -> tuple[float, int, int] | None: ...

    def stat_is_offered(self, stat: object) -> bool: ...


class NbaPricer:
    """NBA strategy delegating to the unchanged ``authoritative_*`` functions."""

    def game_line(
        self,
        session: "Session",
        game: "Game",
        market_type: GameMarketType,
        selection: GameSelection,
    ) -> GameLineQuote | None:
        return authoritative_game_line(session, game, market_type, selection)

    def prop_quote(
        self,
        session: "Session",
        game: "Game",
        player_id: int,
        stat: object,
    ) -> tuple[float, int, int] | None:
        try:
            stat_type = stat if isinstance(stat, StatType) else StatType(str(stat))
        except ValueError:
            return None
        return authoritative_prop_quote(session, game, player_id, stat_type)

    def stat_is_offered(self, stat: object) -> bool:
        return str(stat) in _NBA_STAT_VALUES


class MlbPricer:
    """MLB strategy wrapping the baseball market/prop services and vocabulary."""

    def game_line(
        self,
        session: "Session",
        game: "Game",
        market_type: GameMarketType,
        selection: GameSelection,
    ) -> GameLineQuote | None:
        markets = build_mlb_game_markets(session, game)
        return _game_line_quote_from_markets(markets, market_type, selection)

    def prop_quote(
        self,
        session: "Session",
        game: "Game",
        player_id: int,
        stat: object,
    ) -> tuple[float, int, int] | None:
        try:
            stat_type = stat if isinstance(stat, MLBStatType) else MLBStatType(str(stat))
        except ValueError:
            return None
        bundle = build_mlb_game_prop_lines_bundle(session, game)
        player = next((p for p in bundle.players if p.id == player_id), None)
        if player is None:
            return None
        stat_line = next(
            (s for s in player.stat_lines if str(s.stat_type) == stat_type.value), None
        )
        if stat_line is None:
            return None
        over_american = _parse_american(stat_line.over_american)
        under_american = _parse_american(stat_line.under_american)
        return float(stat_line.line), over_american, under_american

    def stat_is_offered(self, stat: object) -> bool:
        return str(stat) in _MLB_STAT_VALUES


PRICER_REGISTRY: dict[Sport, SportPricer] = {
    Sport.NBA: NbaPricer(),
    Sport.MLB: MlbPricer(),
}


# Smallest probability epsilon used to keep derived leg/ticket probabilities
# strictly inside the open interval (0, 1) (Req 3.6).
_PROB_EPS = 1e-9


def _clamp_open_unit(p: float) -> float:
    """Clamp ``p`` into the open interval ``(0, 1)`` so odds math stays finite."""
    return max(min(p, 1.0 - _PROB_EPS), _PROB_EPS)


@dataclass(frozen=True)
class PricedPlayerLeg:
    """Authoritative pricing for a single player-prop leg (same order as body.legs)."""

    line: float
    probability: float


@dataclass(frozen=True)
class PricedGameLeg:
    """Authoritative pricing for a single game leg (same order as body.game_legs)."""

    line: float | None
    odds_american: int
    probability: float


@dataclass(frozen=True)
class PricedTicket:
    """Server-authoritative pricing result carrying everything ``create_parlay`` persists."""

    player_legs: list[PricedPlayerLeg]
    game_legs: list[PricedGameLeg]
    p_hit: float
    fair_decimal_odds: float | None
    payout_decimal_odds: float | None


def price_ticket(session: "Session", body: "ParlayCreate") -> PricedTicket:
    """Recompute authoritative lines, odds, and the ticket payout for a parlay.

    Player legs (``body.legs``) are processed first, then game legs
    (``body.game_legs``), each in submission order. The first offending leg
    rejects the whole request (Req 7.3):

    - ``PricingValidationError`` (HTTP 400) for missing ``game_id``, unknown
      game, unoffered selection, or insufficient stat history.
    - ``LineDriftError`` (HTTP 409) when a client line drifts beyond the
      configured tolerance.
    - ``ValueError`` from ``require_pre_game_game_for_wager`` propagates (HTTP
      400) so the pre-game gate is preserved.

    Client-supplied odds are always ignored in favor of authoritative values
    (Req 1.5, 4.4, 4.7). The house margin is applied once to the aggregated
    fair odds (Req 5.4).
    """
    # Local import avoids a circular import: service.py imports pricing.py.
    from app.parlay.service import fetch_stat_series

    tol = get_line_drift_tolerance()

    player_legs: list[PricedPlayerLeg] = []
    for index, leg in enumerate(body.legs):
        if leg.game_id is None:
            raise PricingValidationError(f"player prop leg {index}: game_id is required")

        game = session.get(Game, leg.game_id)
        if game is None:
            raise PricingValidationError(f"player prop leg {index}: game {leg.game_id} not found")
        require_pre_game_game_for_wager(game)

        pricer = PRICER_REGISTRY[game.sport or Sport.NBA]

        # Validate the stat against the sport's prop vocabulary (Req 13.3). An
        # MLB selection the sport does not offer is rejected as HTTP 400.
        if not pricer.stat_is_offered(leg.stat_type):
            raise PricingValidationError(
                f"player prop leg {index}: stat type not offered for this sport"
            )

        quote = pricer.prop_quote(session, game, leg.player_id, leg.stat_type)
        if quote is None:
            raise PricingValidationError(
                f"player prop leg {index}: no line offered for this player/stat"
            )
        auth_line, over_american, under_american = quote

        if abs(leg.line - auth_line) > tol:
            raise LineDriftError(
                f"player prop leg {index}: line moved from {leg.line} to {auth_line}"
            )

        if (game.sport or Sport.NBA) == Sport.NBA:
            # NBA props derive the leg probability from the player's stat series
            # via the normal approximation (unchanged path, Req 15.3/15.4).
            series = fetch_stat_series(session, leg.player_id, leg.stat_type, body.lookback_games)
            if len(series) < 2:
                raise PricingValidationError(
                    f"player prop leg {index}: insufficient history "
                    f"({len(series)} games) to price this leg"
                )
            mu, sigma = sample_mean_std(series)
            p = _clamp_open_unit(leg_win_probability(auth_line, mu, sigma, leg.direction))
        else:
            # MLB props devig the authoritative over/under American odds to a
            # fair side probability; the single house margin is applied once at
            # the ticket level (Req 13.2).
            p_over, p_under = devig_two_way(over_american, under_american)
            p = _clamp_open_unit(p_over if leg.direction == LegDirection.OVER else p_under)

        player_legs.append(PricedPlayerLeg(line=auth_line, probability=p))

    game_legs: list[PricedGameLeg] = []
    for index, leg in enumerate(body.game_legs):
        game = session.get(Game, leg.game_id)
        if game is None:
            raise PricingValidationError(f"game leg {index}: game {leg.game_id} not found")
        require_pre_game_game_for_wager(game)

        pricer = PRICER_REGISTRY[game.sport or Sport.NBA]
        quote = pricer.game_line(session, game, leg.market_type, leg.selection)
        if quote is None:
            raise PricingValidationError(f"game leg {index}: selection not offered")

        # Spread/total carry a line; moneyline does not. Only drift-check when
        # both an authoritative line and a client line are present.
        if quote.line is not None and leg.line is not None:
            if abs(leg.line - quote.line) > tol:
                raise LineDriftError(
                    f"game leg {index}: line moved from {leg.line} to {quote.line}"
                )

        p_side, _ = devig_two_way(quote.side_american, quote.other_american)
        p_side = _clamp_open_unit(p_side)
        game_legs.append(
            PricedGameLeg(
                line=quote.line,
                odds_american=quote.odds_american,
                probability=p_side,
            )
        )

    all_probs = [pl.probability for pl in player_legs] + [gl.probability for gl in game_legs]

    if body.mode == ParlayMode.STANDARD:
        p_hit = joint_probability_standard(all_probs)
    else:
        p_hit = joint_probability_x_of_y(
            all_probs,
            body.k_required,  # type: ignore[arg-type]
            body.simulation_iterations,
            random.Random(body.rng_seed),
        )

    p_ticket = p_hit if body.wager_on_hit else 1.0 - p_hit
    fair = fair_decimal_odds(p_ticket)
    if fair is None:
        raise PricingValidationError("ticket has no valid payout (probability out of range)")

    payout = apply_house_margin(fair)

    return PricedTicket(
        player_legs=player_legs,
        game_legs=game_legs,
        p_hit=p_hit,
        fair_decimal_odds=fair,
        payout_decimal_odds=payout,
    )
