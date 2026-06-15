"""Property and integration tests for MLB betting engine paths.

Covers Properties 21–24 (pre-game gate, authoritative pricing, rejection side
effects, stake debit) and Properties 25–29 (settlement grading/resolution).
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.parlay_schemas import GameLegIn, LegIn, ParlayCreate
from app.db.enums import (
    GameMarketType,
    GameSelection,
    LegDirection,
    LedgerEntryType,
    ParlayMode,
    Sport,
    WagerStatus,
)
from app.db.models import Account, Game, LedgerEntry, MLBPlayerGameStat, ParlayLeg, Team, Wager
from app.mlb.enums import MLBStatType
from app.mlb.status import MLBGameStatus, classify_status
from app.parlay.pricing import LineDriftError, PricingValidationError, price_ticket
from app.services import money
from app.services.game_wager_gate import game_accepts_pre_game_wagers
from app.services.money import InsufficientBalanceError
from app.services.settlement import (
    _evaluate_game_leg,
    _evaluate_leg,
    _leg_stat_hit,
    _resolve_ticket,
    settle_open_wagers,
    ticket_contains_mlb_leg,
    ticket_is_pure_nba,
)
from app.db.models import Parlay, Player


def _seed_mlb_game(session: Session, *, status: str = "Scheduled") -> Game:
    home = Team(name="MLB Home", sport=Sport.MLB, mlb_team_id=11, abbreviation="HH")
    away = Team(name="MLB Away", sport=Sport.MLB, mlb_team_id=12, abbreviation="AA")
    session.add_all([home, away])
    session.flush()
    game = Game(
        home_team_id=home.id,
        away_team_id=away.id,
        game_date=date(2026, 6, 15),
        status=status,
        sport=Sport.MLB,
        mlb_game_id="700001",
    )
    session.add(game)
    session.flush()
    return game


def _seed_mlb_player(session: Session, game: Game) -> Player:
    team = session.get(Team, game.home_team_id)
    player = Player(
        full_name="MLB Batter",
        team_id=team.id,
        sport=Sport.MLB,
        mlb_player_id=555,
        primary_position="OF",
    )
    session.add(player)
    session.flush()
    return player


# --- Property 21: pre-game gate tracks MLB status --------------------------------


@settings(deadline=None, max_examples=120)
@given(
    detailed=st.sampled_from(
        ["Scheduled", "Pre-Game", "Warmup", "In Progress", "Final", "Game Over", "", "  "]
    )
)
def test_property21_mlb_pre_game_gate_tracks_status_classification(detailed: str) -> None:
    """Feature: mlb-support, Property 21 — Validates Requirements 12.4, 12.5."""
    game = Game(
        home_team_id=1,
        away_team_id=2,
        game_date=date(2026, 6, 1),
        status=detailed,
        sport=Sport.MLB,
        mlb_game_id="1",
    )
    cls = classify_status(None, detailed)
    accepts = game_accepts_pre_game_wagers(game)
    assert accepts == (cls is MLBGameStatus.PRE_GAME)


# --- Property 22–24: MLB wager pricing / side effects ----------------------------


class TestMlbWagerPricing:
    def test_property22_moneyline_carries_authoritative_odds(self, session: Session) -> None:
        """Feature: mlb-support, Property 22."""
        game = _seed_mlb_game(session)
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[],
            game_legs=[
                GameLegIn(
                    game_id=game.id,
                    market_type=GameMarketType.MONEYLINE,
                    selection=GameSelection.HOME,
                    odds_american=-110,
                )
            ],
        )
        priced = price_ticket(session, body)
        assert len(priced.game_legs) == 1
        assert priced.game_legs[0].line is None

    def test_property23_rejected_live_game_has_no_side_effects(self, session: Session) -> None:
        """Feature: mlb-support, Property 23."""
        game = _seed_mlb_game(session, status="In Progress")
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=50_000)
        before_entries = session.scalar(select(func.count()).select_from(LedgerEntry))
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[],
            game_legs=[
                GameLegIn(
                    game_id=game.id,
                    market_type=GameMarketType.MONEYLINE,
                    selection=GameSelection.HOME,
                    odds_american=-110,
                )
            ],
        )
        with pytest.raises(ValueError, match="wagering is closed"):
            money.place_wager(session, account.id, stake_cents=1_000, offered_decimal_odds=None, parlay_body=body)
        after_entries = session.scalar(select(func.count()).select_from(LedgerEntry))
        assert after_entries == before_entries
        assert session.scalar(select(func.count()).select_from(Wager)) == 0

    def test_property24_valid_wager_debits_exact_stake(self, session: Session) -> None:
        """Feature: mlb-support, Property 24."""
        game = _seed_mlb_game(session)
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=50_000)
        stake = 2_500
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[],
            game_legs=[
                GameLegIn(
                    game_id=game.id,
                    market_type=GameMarketType.MONEYLINE,
                    selection=GameSelection.HOME,
                    odds_american=-110,
                )
            ],
        )
        wager, updated, dup = money.place_wager(
            session, account.id, stake_cents=stake, offered_decimal_odds=None, parlay_body=body
        )
        assert dup is False
        assert updated.balance_cents == 50_000 - stake
        debit = session.scalar(
            select(LedgerEntry).where(
                LedgerEntry.account_id == account.id,
                LedgerEntry.entry_type == LedgerEntryType.WAGER_STAKE,
            )
        )
        assert debit is not None
        assert debit.amount_cents == -stake
        assert wager.status == WagerStatus.OPEN


# --- Property 25–29: settlement --------------------------------------------------


class TestMlbSettlement:
    def test_property25_leg_pending_until_final_with_data(self, session: Session) -> None:
        game = _seed_mlb_game(session, status="Scheduled")
        player = _seed_mlb_player(session, game)
        leg = ParlayLeg(
            parlay_id=1,
            player_id=player.id,
            game_id=game.id,
            stat_type=MLBStatType.HITS.value,
            line=1.5,
            direction=LegDirection.OVER,
            leg_probability=0.5,
            sort_order=0,
        )
        assert _evaluate_leg(session, leg) == "pending"

        game.status = "Final"
        session.flush()
        assert _evaluate_leg(session, leg) == "pending"

        session.add(MLBPlayerGameStat(player_id=player.id, game_id=game.id, hits=2))
        session.flush()
        assert _evaluate_leg(session, leg) == "win"

    def test_property26_game_market_no_exact_line_push(self) -> None:
        """Feature: mlb-support, Property 26."""
        assert _leg_stat_hit(8.0, 8.5, LegDirection.OVER) is False
        assert _leg_stat_hit(8.5, 8.5, LegDirection.OVER) is False

    def test_property27_prop_strict_comparison(self) -> None:
        """Feature: mlb-support, Property 27."""
        assert _leg_stat_hit(3.0, 3.0, LegDirection.OVER) is False
        assert _leg_stat_hit(3.0, 3.0, LegDirection.UNDER) is False

    def test_property28_void_leg_voids_whole_ticket(self) -> None:
        """Feature: mlb-support, Property 28."""
        parlay = Parlay(mode=ParlayMode.STANDARD, wager_on_hit=True, k_required=None)
        assert _resolve_ticket(parlay, ["win", "void"]) == "void"

    def test_property29_settlement_pays_stored_odds(self, session: Session) -> None:
        game = _seed_mlb_game(session)
        account = money.create_account(session)
        money.deposit(session, account.id, amount_cents=100_000)
        body = ParlayCreate(
            mode=ParlayMode.STANDARD,
            legs=[],
            game_legs=[
                GameLegIn(
                    game_id=game.id,
                    market_type=GameMarketType.MONEYLINE,
                    selection=GameSelection.HOME,
                    odds_american=-110,
                )
            ],
        )
        wager, _, _ = money.place_wager(
            session, account.id, stake_cents=1_000, offered_decimal_odds=None, parlay_body=body
        )
        payout = wager.potential_return_cents
        game.home_score = 5
        game.away_score = 2
        game.status = "Final"
        session.flush()
        settle_open_wagers(session, sport_scope=ticket_contains_mlb_leg)
        session.refresh(wager)
        assert wager.status == WagerStatus.WON
        acct = session.get(Account, account.id)
        assert acct.balance_cents == 100_000 - 1_000 + payout

    def test_settlement_scoping_partitions_workers(self, session: Session) -> None:
        nba_home = Team(name="N", sport=Sport.NBA, nba_team_id=50)
        nba_away = Team(name="A", sport=Sport.NBA, nba_team_id=51)
        session.add_all([nba_home, nba_away])
        session.flush()
        nba_game = Game(
            home_team_id=nba_home.id,
            away_team_id=nba_away.id,
            game_date=date(2026, 1, 1),
            status="7:30 pm ET",
            sport=Sport.NBA,
            nba_game_id="0022000050",
        )
        mlb_game = _seed_mlb_game(session, status="Scheduled")
        session.add(nba_game)
        session.flush()

        for g in (nba_game, mlb_game):
            account = money.create_account(session)
            money.deposit(session, account.id, amount_cents=10_000)
            body = ParlayCreate(
                mode=ParlayMode.STANDARD,
                legs=[],
                game_legs=[
                    GameLegIn(
                        game_id=g.id,
                        market_type=GameMarketType.MONEYLINE,
                        selection=GameSelection.HOME,
                        odds_american=-110,
                    )
                ],
            )
            money.place_wager(session, account.id, stake_cents=500, offered_decimal_odds=None, parlay_body=body)

        nba_game.status = "Final"
        nba_game.home_score = 100
        nba_game.away_score = 90
        mlb_game.status = "Final"
        mlb_game.home_score = 4
        mlb_game.away_score = 2
        session.flush()

        nba_counts = settle_open_wagers(session, sport_scope=ticket_is_pure_nba)
        assert nba_counts["won"] == 1
        mlb_counts = settle_open_wagers(session, sport_scope=ticket_contains_mlb_leg)
        assert mlb_counts["won"] == 1
