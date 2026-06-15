"""Module-boundary enforcement for MLB/NBA isolation (Requirements 2.x, 15.1)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

NBA_IMPORTER_MODULES = [
    BACKEND / "app" / "ingestion" / "nba_sync.py",
    BACKEND / "app" / "worker" / "main.py",
    BACKEND / "app" / "worker" / "jobs.py",
]

SHARED_UTILITY_MODULES = [
    BACKEND / "app" / "services" / "odds_math.py",
    BACKEND / "app" / "services" / "money.py",
]

MLB_INGESTION_ROOT = BACKEND / "app" / "mlb"
STATSAPI_CLIENT = BACKEND / "app" / "mlb" / "stats_api_client.py"


def _imports_mlb(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app.mlb"):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("app.mlb"):
                offenders.append(node.module)
    return offenders


class TestModuleBoundaries:
    def test_nba_modules_do_not_import_app_mlb(self) -> None:
        for path in NBA_IMPORTER_MODULES:
            assert path.exists(), f"missing module under test: {path}"
            offenders = _imports_mlb(path)
            assert offenders == [], f"{path} imports MLB modules: {offenders}"

    def test_statsapi_host_only_in_client_module(self) -> None:
        hits: list[str] = []
        for path in BACKEND.rglob("*.py"):
            if "tests" in path.parts:
                continue
            if path == STATSAPI_CLIENT:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "statsapi.mlb.com" in text or "import statsapi" in text or "from statsapi" in text:
                hits.append(str(path.relative_to(BACKEND)))
        assert hits == []

    def test_shared_utilities_contain_no_sport_literals(self) -> None:
        for path in SHARED_UTILITY_MODULES:
            text = path.read_text(encoding="utf-8")
            assert '"NBA"' not in text and "'NBA'" not in text
            assert '"MLB"' not in text and "'MLB'" not in text

    def test_nba_modules_do_not_reference_mlb_ingestion(self) -> None:
        for path in NBA_IMPORTER_MODULES:
            text = path.read_text(encoding="utf-8")
            assert "run_full_mlb_ingest" not in text
            assert "from app.mlb" not in text
            assert "import app.mlb" not in text

    def test_checker_reports_importer_on_synthetic_violation(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad_module.py"
        bad.write_text("from app.mlb.ingestion import run_full_mlb_ingest\n", encoding="utf-8")
        assert _imports_mlb(bad) == ["app.mlb.ingestion"]
