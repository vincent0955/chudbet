"""Unit tests for MLB player-prop odds differentiation."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import Sport
from app.db.models import Game, MLBPlayerGameStat, Player, Team
from app.mlb.prop_lines import build_mlb_game_prop_lines_bundle


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return factory()


def _implied(american: str) -> float:
    """Implied (with-vig) probability from an American-odds string."""
    n = int(american.lstrip("+"))
    return 100.0 / (n + 100.0) if n > 0 else abs(n) / (abs(n) + 100.0)


def test_prop_odds_vary_by_player_history() -> None:
    """Different hitting profiles should produce different milestone prices."""
    session = _session()
    try:
        home = Team(sport=Sport.MLB, mlb_team_id=1, name="Home", abbreviation="HOM")
        away = Team(sport=Sport.MLB, mlb_team_id=2, name="Away", abbreviation="AWY")
        session.add_all([home, away])
        session.flush()

        slugger = Player(
            sport=Sport.MLB,
            mlb_player_id=101,
            full_name="Slugger",
            primary_position="OF",
            team_id=home.id,
        )
        contact = Player(
            sport=Sport.MLB,
            mlb_player_id=102,
            full_name="Contact",
            primary_position="CF",
            team_id=away.id,
        )
        session.add_all([slugger, contact])
        session.flush()

        target = Game(
            sport=Sport.MLB,
            mlb_game_id="9000",
            home_team_id=home.id,
            away_team_id=away.id,
            game_date=date(2024, 7, 20),
            status="Scheduled",
        )
        session.add(target)
        session.flush()

        for i in range(5):
            g = Game(
                sport=Sport.MLB,
                mlb_game_id=f"800{i}",
                home_team_id=home.id,
                away_team_id=away.id,
                game_date=date(2024, 7, 10) + timedelta(days=i),
                status="Final",
                home_score=4,
                away_score=3,
            )
            session.add(g)
            session.flush()
            session.add_all(
                [
                    MLBPlayerGameStat(player_id=slugger.id, game_id=g.id, hits=3, total_bases=5, rbi=2, runs=1),
                    MLBPlayerGameStat(player_id=contact.id, game_id=g.id, hits=0, total_bases=0, rbi=0, runs=0),
                ]
            )
        session.flush()

        bundle = build_mlb_game_prop_lines_bundle(session, target)
        slugger_hits = next(
            s
            for p in bundle.players
            if p.full_name == "Slugger"
            for s in p.stat_lines
            if s.stat_type == "HITS"
        )
        contact_hits = next(
            s
            for p in bundle.players
            if p.full_name == "Contact"
            for s in p.stat_lines
            if s.stat_type == "HITS"
        )

        # Each stat exposes the fixed 1+/2+/3+ ladder at half-point lines.
        assert [t.threshold for t in slugger_hits.thresholds] == [1, 2, 3]
        assert [t.line for t in slugger_hits.thresholds] == [0.5, 1.5, 2.5]

        slugger_by_t = {t.threshold: t for t in slugger_hits.thresholds}
        contact_by_t = {t.threshold: t for t in contact_hits.thresholds}

        # The 3-hits-per-game slugger is far likelier to reach each milestone
        # than the hitless contact bat, so prices must differ and rank correctly.
        for threshold in (1, 2, 3):
            assert slugger_by_t[threshold].american != contact_by_t[threshold].american
            assert _implied(slugger_by_t[threshold].american) > _implied(
                contact_by_t[threshold].american
            )

        # Within a player, higher milestones are progressively less likely.
        assert (
            _implied(slugger_by_t[1].american)
            > _implied(slugger_by_t[2].american)
            > _implied(slugger_by_t[3].american)
        )
    finally:
        session.close()
