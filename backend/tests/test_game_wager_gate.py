"""Unit tests for pre-game wager eligibility detection."""

from __future__ import annotations

import pytest

from app.db.models import Game
from app.services.game_wager_gate import (
    game_accepts_pre_game_wagers,
    require_pre_game_game_for_wager,
    status_indicates_live_or_finished,
)


def _game(status: str | None) -> Game:
    """A bare Game instance — only ``status`` is read by the gate."""
    return Game(status=status)


class TestStatusIndicatesLiveOrFinished:
    @pytest.mark.parametrize(
        "status",
        [
            "Final",
            "FINAL/OT",
            "Postponed",
            "Cancelled",
            "Halftime",
            "End of 2nd Qtr",
            "1st Qtr 5:00",
            "Q3 2:11",
            "OT 1:00",
            "5:30",  # rolling game clock with no AM/PM/ET
        ],
    )
    def test_live_or_finished_statuses(self, status: str) -> None:
        assert status_indicates_live_or_finished(status) is True

    @pytest.mark.parametrize(
        "status",
        [
            None,
            "",
            "   ",
            "7:30 pm ET",
            "10:00 AM",
            "8:00 PM ET",
            "Scheduled",
        ],
    )
    def test_pre_game_statuses(self, status: str | None) -> None:
        assert status_indicates_live_or_finished(status) is False

    def test_is_case_insensitive(self) -> None:
        assert status_indicates_live_or_finished("final") is True
        assert status_indicates_live_or_finished("FINAL") is True


class TestGameAcceptsPreGameWagers:
    def test_none_game_is_allowed(self) -> None:
        assert game_accepts_pre_game_wagers(None) is True

    def test_scheduled_game_is_allowed(self) -> None:
        assert game_accepts_pre_game_wagers(_game("7:30 pm ET")) is True

    def test_live_game_is_blocked(self) -> None:
        assert game_accepts_pre_game_wagers(_game("Q2 4:10")) is False

    def test_final_game_is_blocked(self) -> None:
        assert game_accepts_pre_game_wagers(_game("Final")) is False


class TestRequirePreGameGameForWager:
    def test_allows_scheduled_game(self) -> None:
        require_pre_game_game_for_wager(_game("8:00 PM ET"))

    def test_raises_for_live_game(self) -> None:
        with pytest.raises(ValueError, match="already started or finished"):
            require_pre_game_game_for_wager(_game("Final"))
