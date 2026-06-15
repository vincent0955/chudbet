"""Keyless-access integration smoke test for the MLB Stats API client.

Validates: Requirements 6.1

Requirement 6.1 states the MLB_StatsAPI_Client retrieves MLB data from
``statsapi.mlb.com`` through the ``MLB-StatsAPI`` library **without requiring an
API key or other credential**. This module is an integration-style smoke test
that asserts the client can be constructed and can issue a call end-to-end with
**no credential configured**, exercising the real resilience pipeline
(``_call`` -> timeout/spacing/validate) against a *recorded* transport response
rather than the live network.

The proof of keylessness is twofold:

1. ``MLBStatsAPIClient`` and ``StatsapiTransport`` expose no credential/API-key
   parameter anywhere in their construction surface -- there is nowhere to supply
   one.
2. The underlying keyless ``statsapi`` wrapper is invoked with no auth argument:
   we drive a recorded ``statsapi`` module through the real ``StatsapiTransport``
   and confirm the call succeeds and forwards no credential.
"""

from __future__ import annotations

import inspect
from datetime import date
from typing import Any

import pytest

from app.mlb.config import MLBClientConfig
from app.mlb.stats_api_client import (
    MLBStatsAPIClient,
    StatsapiTransport,
    _validate_boxscore,
    _validate_roster,
    _validate_schedule,
    _validate_teams,
)


# --- Recorded Stats API responses -------------------------------------------
#
# Minimal but shape-valid payloads captured from the keyless statsapi wrapper,
# enough to pass each endpoint's "usable data" validator.

RECORDED_TEAMS: dict[str, Any] = {
    "teams": [
        {"id": 147, "name": "New York Yankees", "abbreviation": "NYY"},
        {"id": 119, "name": "Los Angeles Dodgers", "abbreviation": "LAD"},
    ]
}

RECORDED_ROSTER: dict[str, Any] = {
    "roster": [
        {"person": {"id": 592450, "fullName": "Aaron Judge"},
         "position": {"abbreviation": "RF"}},
    ]
}

RECORDED_SCHEDULE: list[dict[str, Any]] = [
    {"game_id": 717465, "status": "Scheduled",
     "home_name": "New York Yankees", "away_name": "Los Angeles Dodgers"},
]

RECORDED_BOXSCORE: dict[str, Any] = {
    "home": {"team": {"id": 147}, "players": {}},
    "away": {"team": {"id": 119}, "players": {}},
}


class _RecordedStatsapi:
    """Stand-in for the keyless ``statsapi`` module backed by recorded responses.

    Mirrors the ``statsapi`` surface that :class:`StatsapiTransport` uses
    (``get``, ``schedule``, ``boxscore_data``). Every call records the keyword
    arguments it received so the test can assert no credential/API key was ever
    forwarded.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def get(self, endpoint: str, params: dict, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((f"get:{endpoint}", (params, *args), dict(kwargs)))
        if endpoint == "teams":
            return RECORDED_TEAMS
        if endpoint == "team_roster":
            return RECORDED_ROSTER
        raise AssertionError(f"unexpected endpoint {endpoint!r}")

    def schedule(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("schedule", args, dict(kwargs)))
        return RECORDED_SCHEDULE

    def boxscore_data(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("boxscore_data", args, dict(kwargs)))
        return RECORDED_BOXSCORE


@pytest.fixture
def recorded_statsapi(monkeypatch: pytest.MonkeyPatch) -> _RecordedStatsapi:
    """Patch the real ``StatsapiTransport`` import shim to return a recorded module.

    This keeps the genuine ``StatsapiTransport`` -> ``MLBStatsAPIClient`` pipeline
    intact (no network) while substituting the keyless ``statsapi`` dependency.
    """
    fake = _RecordedStatsapi()
    monkeypatch.setattr(StatsapiTransport, "_statsapi", staticmethod(lambda: fake))
    return fake


@pytest.fixture
def fast_config() -> MLBClientConfig:
    """A client config with no inter-request spacing so the smoke test is instant."""
    return MLBClientConfig(
        timeout_sec=10.0,
        max_attempts=3,
        min_interval_sec=0.0,
        backoff_base_sec=0.0,
    )


# --- Keylessness of the construction surface (Req 6.1) ----------------------


def test_client_construction_surface_has_no_credential_parameter() -> None:
    """**Validates: Requirements 6.1**

    Neither the client nor the transport exposes any credential/API-key
    parameter -- there is no way to configure a credential, by construction.
    """
    forbidden = {"key", "api_key", "apikey", "token", "credential",
                 "credentials", "secret", "auth", "password"}

    client_params = set(inspect.signature(MLBStatsAPIClient.__init__).parameters)
    transport_params = set(inspect.signature(StatsapiTransport.__init__).parameters)

    assert forbidden.isdisjoint(client_params), (
        f"MLBStatsAPIClient exposes a credential parameter: "
        f"{forbidden & client_params}"
    )
    assert forbidden.isdisjoint(transport_params), (
        f"StatsapiTransport exposes a credential parameter: "
        f"{forbidden & transport_params}"
    )


# --- Construct + issue a call with no credential configured (Req 6.1) -------


def test_teams_call_succeeds_with_no_credential(
    recorded_statsapi: _RecordedStatsapi, fast_config: MLBClientConfig
) -> None:
    """**Validates: Requirements 6.1**

    The client constructs with no credential and issues a ``teams()`` call that
    succeeds against the recorded response, forwarding no API key/credential to
    the keyless ``statsapi`` wrapper.
    """
    client = MLBStatsAPIClient(config=fast_config)

    teams = client.teams()

    assert teams == RECORDED_TEAMS["teams"]

    # Exactly one underlying call, and it carried no credential anywhere.
    assert len(recorded_statsapi.calls) == 1
    name, args, kwargs = recorded_statsapi.calls[0]
    assert name == "get:teams"
    _assert_no_credential(args, kwargs)


def test_all_endpoints_smoke_with_no_credential(
    recorded_statsapi: _RecordedStatsapi, fast_config: MLBClientConfig
) -> None:
    """**Validates: Requirements 6.1**

    Each typed endpoint constructs+issues a successful call against its recorded
    response with no credential configured, and no underlying call forwards a
    credential.
    """
    client = MLBStatsAPIClient(config=fast_config)

    assert client.teams() == RECORDED_TEAMS["teams"]
    assert client.roster(147) == RECORDED_ROSTER["roster"]
    assert client.schedule(date(2024, 7, 1), date(2024, 7, 2)) == RECORDED_SCHEDULE
    assert client.boxscore(717465) == RECORDED_BOXSCORE

    # Every recorded call must be credential-free.
    assert len(recorded_statsapi.calls) == 4
    for _name, args, kwargs in recorded_statsapi.calls:
        _assert_no_credential(args, kwargs)


def _assert_no_credential(args: tuple, kwargs: dict) -> None:
    """Assert no credential/API-key token appears in the forwarded call."""
    forbidden = {"key", "api_key", "apikey", "token", "credential",
                 "credentials", "secret", "auth", "password"}

    # No credential-like keyword argument.
    offending_kwargs = forbidden & {k.lower() for k in kwargs}
    assert not offending_kwargs, f"credential forwarded as kwarg: {offending_kwargs}"

    # No credential-like key inside a forwarded params dict (e.g. statsapi.get).
    for arg in args:
        if isinstance(arg, dict):
            offending = forbidden & {str(k).lower() for k in arg}
            assert not offending, f"credential forwarded in params: {offending}"


# --- Sanity: the recorded payloads satisfy the real validators --------------


def test_recorded_payloads_are_usable() -> None:
    """The recorded responses pass the client's real 'usable data' validators,
    confirming the smoke test drives the genuine validation path (not a bypass).
    """
    assert _validate_teams(RECORDED_TEAMS)
    assert _validate_roster(RECORDED_ROSTER)
    assert _validate_schedule(RECORDED_SCHEDULE)
    assert _validate_boxscore(RECORDED_BOXSCORE)
