"""Unit tests for environment-driven configuration helpers."""

from __future__ import annotations

import pytest

from app.core import config


@pytest.fixture(autouse=True)
def _clear_config_caches() -> None:
    """``get_database_url`` / ``get_cors_origins`` memoize via ``lru_cache``."""
    config.get_database_url.cache_clear()
    config.get_cors_origins.cache_clear()


class TestGetDatabaseUrl:
    def test_prefers_explicit_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://x/y")
        assert config.get_database_url() == "postgresql+psycopg2://x/y"

    def test_builds_url_from_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("POSTGRES_USER", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_HOST", "db")
        monkeypatch.setenv("POSTGRES_PORT", "6543")
        monkeypatch.setenv("POSTGRES_DB", "chud")
        assert config.get_database_url() == "postgresql+psycopg2://user:pass@db:6543/chud"

    def test_url_encodes_special_characters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("POSTGRES_USER", "u@ser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:word/!")
        monkeypatch.setenv("POSTGRES_HOST", "localhost")
        monkeypatch.setenv("POSTGRES_PORT", "5432")
        monkeypatch.setenv("POSTGRES_DB", "chudbet")
        url = config.get_database_url()
        assert "u%40ser" in url
        assert "p%40ss%3Aword%2F%21" in url

    def test_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ("DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB"):
            monkeypatch.delenv(key, raising=False)
        assert config.get_database_url() == "postgresql+psycopg2://chudbet:chudbet@localhost:5432/chudbet"


class TestGetCorsOrigins:
    def test_defaults_to_localhost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CHUDBET_CORS_ORIGINS", raising=False)
        origins = config.get_cors_origins()
        assert "http://localhost:5173" in origins
        assert "http://127.0.0.1:5173" in origins
        assert "http://localhost:5174" in origins

    def test_parses_comma_separated_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHUDBET_CORS_ORIGINS", "https://a.com, https://b.com")
        assert config.get_cors_origins() == ["https://a.com", "https://b.com"]

    def test_strips_trailing_slashes_and_blanks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHUDBET_CORS_ORIGINS", "https://a.com/, ,https://b.com/")
        assert config.get_cors_origins() == ["https://a.com", "https://b.com"]
