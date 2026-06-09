"""Unit tests for the pure grading helpers in the settlement service."""

from __future__ import annotations

import pytest

from app.db.enums import LegDirection, ParlayMode
from app.db.models import Parlay
from app.services.settlement import (
    _is_final_status,
    _leg_stat_hit,
    _normalize_persisted_outcome,
    _resolve_ticket,
    _ui_from_eval_result,
)


class TestIsFinalStatus:
    @pytest.mark.parametrize("status", ["Final", "FINAL/OT", "Game Over", "F/OT", "f 100-98"])
    def test_final_statuses(self, status: str) -> None:
        assert _is_final_status(status) is True

    @pytest.mark.parametrize("status", [None, "", "Q3 2:00", "7:30 pm ET", "Halftime"])
    def test_non_final_statuses(self, status: str | None) -> None:
        assert _is_final_status(status) is False


class TestLegStatHit:
    def test_over_strictly_greater(self) -> None:
        assert _leg_stat_hit(25.0, 24.5, LegDirection.OVER) is True
        assert _leg_stat_hit(24.0, 24.5, LegDirection.OVER) is False

    def test_over_on_the_line_is_miss(self) -> None:
        assert _leg_stat_hit(24.0, 24.0, LegDirection.OVER) is False

    def test_under_strictly_less(self) -> None:
        assert _leg_stat_hit(20.0, 24.5, LegDirection.UNDER) is True
        assert _leg_stat_hit(25.0, 24.5, LegDirection.UNDER) is False

    def test_under_on_the_line_is_miss(self) -> None:
        assert _leg_stat_hit(24.0, 24.0, LegDirection.UNDER) is False


class TestUiFromEvalResult:
    def test_mapping(self) -> None:
        assert _ui_from_eval_result("pending") == "pending"
        assert _ui_from_eval_result("void") == "void"
        assert _ui_from_eval_result("win") == "hit"
        assert _ui_from_eval_result("loss") == "miss"


class TestNormalizePersistedOutcome:
    @pytest.mark.parametrize("value", ["pending", "hit", "miss", "void"])
    def test_valid_values_pass_through(self, value: str) -> None:
        assert _normalize_persisted_outcome(value) == value

    def test_trims_and_lowercases(self) -> None:
        assert _normalize_persisted_outcome("  HIT ") == "hit"

    def test_none_and_unknown_return_none(self) -> None:
        assert _normalize_persisted_outcome(None) is None
        assert _normalize_persisted_outcome("garbage") is None


def _parlay(mode: ParlayMode, *, wager_on_hit: bool, k_required: int | None = None) -> Parlay:
    return Parlay(mode=mode, wager_on_hit=wager_on_hit, k_required=k_required)


class TestResolveTicketStandard:
    def test_all_wins_is_win(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=True)
        assert _resolve_ticket(p, ["win", "win"]) == "win"

    def test_any_loss_is_loss(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=True)
        assert _resolve_ticket(p, ["win", "loss"]) == "loss"

    def test_anti_all_wins_is_loss(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=False)
        assert _resolve_ticket(p, ["win", "win"]) == "loss"

    def test_anti_any_loss_is_win(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=False)
        assert _resolve_ticket(p, ["win", "loss"]) == "win"


class TestResolveTicketGating:
    def test_empty_legs_void(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=True)
        assert _resolve_ticket(p, []) == "void"

    def test_pending_leg_keeps_pending(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=True)
        assert _resolve_ticket(p, ["win", "pending"]) == "pending"

    def test_void_leg_voids_ticket(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=True)
        assert _resolve_ticket(p, ["win", "void"]) == "void"

    def test_pending_takes_priority_over_void(self) -> None:
        p = _parlay(ParlayMode.STANDARD, wager_on_hit=True)
        assert _resolve_ticket(p, ["pending", "void"]) == "pending"


class TestResolveTicketXOfY:
    def test_meets_threshold_is_win(self) -> None:
        p = _parlay(ParlayMode.X_OF_Y, wager_on_hit=True, k_required=2)
        assert _resolve_ticket(p, ["win", "win", "loss"]) == "win"

    def test_below_threshold_is_loss(self) -> None:
        p = _parlay(ParlayMode.X_OF_Y, wager_on_hit=True, k_required=3)
        assert _resolve_ticket(p, ["win", "win", "loss"]) == "loss"

    def test_missing_k_voids(self) -> None:
        p = _parlay(ParlayMode.X_OF_Y, wager_on_hit=True, k_required=None)
        assert _resolve_ticket(p, ["win", "win"]) == "void"

    def test_anti_x_of_y_is_voided(self) -> None:
        p = _parlay(ParlayMode.X_OF_Y, wager_on_hit=False, k_required=2)
        assert _resolve_ticket(p, ["win", "win", "loss"]) == "void"
