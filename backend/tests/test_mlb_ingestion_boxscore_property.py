"""Property-based test for MLB box-score status and stat-shape rules.

Exercises ``app.mlb.ingestion.ingest_box_score_for_game`` over arbitrary stat
values and game statuses, asserting Property 7: after ingestion there is exactly
one ``MLBPlayerGameStat`` per player with a box entry keyed by
``(player_id, game_id)``, every ``MLBStatType`` is a non-negative integer with
unreported stats set to ``0``; while ``LIVE`` each stat updates to
``max(stored, new)``; while ``FINAL`` each stat is overwritten with the final
value even if lower; and while ``PRE_GAME`` no stat row is created or modified.

Uses an in-process fake MLB Stats API client (no network) and a fresh in-memory
SQLite session per generated example so worlds never leak into one another.

Feature: mlb-support, Property 7
Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

# Importing the models package registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import Sport
from app.db.models import Game, Player, Team
from app.db.models.mlb_player_game_stats import MLBPlayerGameStat
from app.mlb.ingestion import ingest_box_score_for_game
from app.mlb.status import MLBGameStatus, classify_status

# Model column -> (box-score section, box-score payload key). Mirrors the
# ``_STAT_COLUMNS`` / parsing in ``app.mlb.ingestion`` so the test's model of
# the reported shape matches what the service reads.
_STAT_KEYS: dict[str, tuple[str, str]] = {
    "hits": ("batting", "hits"),
    "total_bases": ("batting", "totalBases"),
    "rbi": ("batting", "rbi"),
    "runs": ("batting", "runs"),
    "strikeouts_pitcher": ("pitching", "strikeOuts"),
}

# Status texts that classify to each coarse class (see app.mlb.status).
_PRE_GAME_TEXTS = ["Scheduled", "Pre-Game", "Warmup", ""]
_LIVE_TEXTS = ["In Progress", "Manager Challenge", "Delayed"]
_FINAL_TEXTS = ["Final", "Game Over"]
_STATUS_TEXTS = _PRE_GAME_TEXTS + _LIVE_TEXTS + _FINAL_TEXTS


class FakeClient:
    """In-process stand-in for ``MLBStatsAPIClient`` returning a canned box score."""

    def __init__(self, boxscore: dict) -> None:
        self._boxscore = boxscore
        self.calls = 0

    def boxscore(self, mlb_game_id):  # noqa: ANN001 - matches client signature
        self.calls += 1
        return self._boxscore


def _fresh_session() -> Iterator[Session]:
    """Yield an isolated in-memory SQLite session (fresh engine per example)."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _normalize(raw: int | None) -> int:
    """Model of ``_box_stat_value``: unreported / non-positive -> 0, else value."""
    if raw is None:
        return 0
    return raw if raw > 0 else 0


def _box_player(mlb_player_id: int, values: dict[str, int | None]) -> dict:
    """Build one player's box-score entry from model-column values."""
    sections: dict[str, dict] = {"batting": {}, "pitching": {}}
    for column, (section, key) in _STAT_KEYS.items():
        raw = values[column]
        if raw is not None:
            sections[section][key] = raw
    return {
        "person": {"id": mlb_player_id, "fullName": f"Player {mlb_player_id}"},
        "stats": {"batting": sections["batting"], "pitching": sections["pitching"]},
    }


def _boxscore(players: list[dict]) -> dict:
    """Wrap player entries into the home/away ``players`` map shape."""
    home = {f"ID{p['person']['id']}": p for p in players}
    return {"home": {"players": home}, "away": {"players": {}}}


# Strategies -----------------------------------------------------------------

# A single reported stat: either unreported (None) or an integer. Negatives are
# included to assert the non-negative-integer shape invariant holds (the service
# clamps them to 0).
_stat_value = st.one_of(st.none(), st.integers(min_value=-3, max_value=40))

_player_values = st.fixed_dictionaries({col: _stat_value for col in _STAT_KEYS})

# One player scenario: a native id plus a first (baseline) and second
# (follow-up) set of reported values.
_player_scenario = st.fixed_dictionaries(
    {
        "mlb_id": st.integers(min_value=1, max_value=10_000),
        "first": _player_values,
        "second": _player_values,
    }
)

_scenario = st.fixed_dictionaries(
    {
        "players": st.lists(
            _player_scenario, min_size=1, max_size=4, unique_by=lambda s: s["mlb_id"]
        ),
        "second_status": st.sampled_from(_STATUS_TEXTS),
    }
)


@settings(deadline=None, max_examples=100)
@given(scenario=_scenario)
def test_property7_boxscore_status_and_stat_shape(scenario: dict) -> None:
    """**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

    Feature: mlb-support, Property 7

    Seed a set of MLB players, establish a baseline by ingesting a FINAL box
    score, then ingest a second box score under an arbitrary status. Assert the
    keyed-upsert / non-negative-integer shape (5.1) and the status-driven update
    rules: LIVE -> max(stored, new) (5.2), FINAL -> overwrite (5.3), PRE_GAME ->
    no creation or modification (5.4).
    """
    players: list[dict] = scenario["players"]
    second_text: str = scenario["second_status"]
    second_class = classify_status(None, second_text)

    gen = _fresh_session()
    session = next(gen)
    try:
        home = Team(sport=Sport.MLB, mlb_team_id=147, name="Home", abbreviation="HOM")
        away = Team(sport=Sport.MLB, mlb_team_id=111, name="Away", abbreviation="AWY")
        session.add_all([home, away])
        session.flush()

        # Seed one DB player per scenario player, keyed by mlb_player_id.
        db_id_by_mlb: dict[int, int] = {}
        for idx, p in enumerate(players):
            player = Player(
                sport=Sport.MLB,
                mlb_player_id=p["mlb_id"],
                full_name=f"Player {p['mlb_id']}",
                primary_position="P" if idx % 2 == 0 else "CF",
                team_id=home.id,
            )
            session.add(player)
            session.flush()
            db_id_by_mlb[p["mlb_id"]] = player.id

        game = Game(
            sport=Sport.MLB,
            mlb_game_id="776543",
            home_team_id=home.id,
            away_team_id=away.id,
            game_date=date(2024, 7, 1),
            status="Final",
        )
        session.add(game)
        session.flush()
        session.commit()

        # --- Phase A: establish a FINAL baseline (Req 5.1 keyed upsert/shape) ---
        baseline_box = _boxscore([_box_player(p["mlb_id"], p["first"]) for p in players])
        count_a = ingest_box_score_for_game(session, FakeClient(baseline_box), game)
        session.commit()

        # Exactly one record per player with a box entry, keyed (player_id, game_id).
        assert count_a == len(players)
        assert session.scalar(select(func.count()).select_from(MLBPlayerGameStat)) == len(players)

        # Stored baseline equals the normalized first values (unreported -> 0).
        baseline_stored: dict[int, dict[str, int]] = {}
        for p in players:
            rec = session.scalar(
                select(MLBPlayerGameStat).where(
                    MLBPlayerGameStat.player_id == db_id_by_mlb[p["mlb_id"]],
                    MLBPlayerGameStat.game_id == game.id,
                )
            )
            assert rec is not None
            stored = {col: getattr(rec, col) for col in _STAT_KEYS}
            for col in _STAT_KEYS:
                expected = _normalize(p["first"][col])
                assert stored[col] == expected
                # Every stat is a non-negative integer.
                assert isinstance(stored[col], int) and stored[col] >= 0
            baseline_stored[p["mlb_id"]] = stored

        # --- Phase B: ingest again under an arbitrary status ---
        game.status = second_text
        session.flush()
        follow_box = _boxscore([_box_player(p["mlb_id"], p["second"]) for p in players])
        client_b = FakeClient(follow_box)
        ingest_box_score_for_game(session, client_b, game)
        session.commit()

        # Still exactly one record per player (keyed upsert, never duplicated).
        assert session.scalar(select(func.count()).select_from(MLBPlayerGameStat)) == len(players)

        if second_class is MLBGameStatus.PRE_GAME:
            # Req 5.4: PRE_GAME issues no request and modifies nothing.
            assert client_b.calls == 0

        for p in players:
            rec = session.scalar(
                select(MLBPlayerGameStat).where(
                    MLBPlayerGameStat.player_id == db_id_by_mlb[p["mlb_id"]],
                    MLBPlayerGameStat.game_id == game.id,
                )
            )
            assert rec is not None
            for col in _STAT_KEYS:
                stored = baseline_stored[p["mlb_id"]][col]
                reported = _normalize(p["second"][col])
                actual = getattr(rec, col)

                if second_class is MLBGameStatus.PRE_GAME:
                    expected = stored  # Req 5.4: unchanged
                elif second_class is MLBGameStatus.LIVE:
                    expected = max(stored, reported)  # Req 5.2
                else:  # FINAL
                    expected = reported  # Req 5.3: overwrite even if lower

                assert actual == expected
                assert isinstance(actual, int) and actual >= 0
    finally:
        gen.close()
