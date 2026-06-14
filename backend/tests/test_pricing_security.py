"""Anti-scam / substitution-invariance integration tests (DB-backed).

These tests prove that client-supplied odds values never influence pricing:
the server always re-prices authoritatively. A moneyline game leg works without
any score history because ``build_game_markets`` returns default markets, so a
``GameLegIn(market_type=MONEYLINE, selection=HOME, odds_american=<anything>)``
is priced authoritatively regardless of the client's ``odds_american``.

Validates design Properties 4 and 5.
Requirements satisfied: 1.2, 2.2, 2.3, 4.7.
"""

from __future__ import annotations

import math
from datetime import date

from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, ParlayCreate
from app.db.enums import GameMarketType, GameSelection, ParlayMode
from app.db.models import Parlay, Team, Wager
from app.parlay.service import create_parlay
from app.services import money


# --- Local seeding helpers (copied, not imported, per task instructions) ------


def _seed_game(
    session: Session, *, nba_game_id: str = "0022000001", status: str = "7:30 pm ET"
) -> "object":
    home = Team(name="Home Town", nba_team_id=int(nba_game_id[-3:]) + 100)
    away = Team(name="Away City", nba_team_id=int(nba_game_id[-3:]) + 200)
    session.add_all([home, away])
    session.flush()
    from app.db.models import Game

    game = Game(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2026, 1, 15),
        status=status,
        nba_game_id=nba_game_id,
    )
    session.add(game)
    session.flush()
    return game


def _moneyline_body(game_id: int, *, odds_american: int = -110) -> ParlayCreate:
    return ParlayCreate(
        mode=ParlayMode.STANDARD,
        legs=[],
        game_legs=[
            GameLegIn(
                game_id=game_id,
                market_type=GameMarketType.MONEYLINE,
                selection=GameSelection.HOME,
                odds_american=odds_american,
            )
        ],
    )


# --- Tests --------------------------------------------------------------------


class TestPayoutOverrideIgnored:
    """Property 4 / Req 2.2, 2.3: a client payout-override is never used."""

    def test_offered_decimal_odds_override_is_ignored(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=10_000)
        game = _seed_game(session)

        stake_cents = 2_000
        wager, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=stake_cents,
            # Absurd client value that must NOT be persisted.
            offered_decimal_odds=1_000_000,
            parlay_body=_moneyline_body(game.id),
        )

        # The stored odds are the server payout, not the client's 1_000_000.
        assert wager.offered_decimal_odds != 1_000_000
        assert wager.offered_decimal_odds < 100

        # And they match the parlay's server-priced payout odds.
        parlay = session.get(Parlay, wager.parlay_id)
        server_payout = parlay.metadata_json["payout_decimal_odds"]
        assert wager.offered_decimal_odds == server_payout

        # potential_return is derived from the server odds via floor().
        assert wager.potential_return_cents == math.floor(
            stake_cents * wager.offered_decimal_odds
        )


class TestGameLegOddsSpoofIgnored:
    """Property 4 / Req 4.7: client GameLegIn.odds_american never influences pricing."""

    def test_wildly_different_client_odds_produce_identical_pricing(
        self, session: Session
    ) -> None:
        game = _seed_game(session)

        parlay_low = create_parlay(session, _moneyline_body(game.id, odds_american=-110))
        parlay_high = create_parlay(session, _moneyline_body(game.id, odds_american=10000))

        # Persisted leg odds are authoritative and identical for both tickets.
        leg_low = parlay_low.game_legs[0]
        leg_high = parlay_high.game_legs[0]
        assert leg_low.odds_american == leg_high.odds_american

        # Probability (and therefore pricing) is unaffected by the client odds.
        assert parlay_low.p_hit == parlay_high.p_hit
        assert leg_low.leg_probability == leg_high.leg_probability


class TestOfferedOddsInvarianceAcrossValues:
    """Property 4: identical wagers with different client odds price identically."""

    def test_same_wager_same_server_pricing(self, session: Session) -> None:
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=100_000)
        game = _seed_game(session)

        stake_cents = 1_500
        wager_a, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=stake_cents,
            offered_decimal_odds=2.0,
            parlay_body=_moneyline_body(game.id),
        )
        wager_b, _, _ = money.place_wager(
            session,
            account.id,
            stake_cents=stake_cents,
            offered_decimal_odds=50.0,
            parlay_body=_moneyline_body(game.id),
        )

        assert wager_a.offered_decimal_odds == wager_b.offered_decimal_odds
        assert wager_a.potential_return_cents == wager_b.potential_return_cents
