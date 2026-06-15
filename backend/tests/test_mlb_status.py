"""Property-based and example tests for MLB status classification.

Exercises :func:`app.mlb.status.classify_status`, the total function that maps
the MLB Stats API status fields (``abstractGameState`` / ``detailedState``) into
exactly one of the three :class:`~app.mlb.status.MLBGameStatus` classes.

Feature: mlb-support, Property 6
Validates: Requirements 4.2
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.mlb.status import MLBGameStatus, classify_status

# The set of every valid classification result. Totality means every input
# maps to a member of this set; single-valuedness means exactly one member.
_ALL_STATUSES: frozenset[MLBGameStatus] = frozenset(MLBGameStatus)


# Strategies -----------------------------------------------------------------

# Arbitrary status text: any text or None. Mixing wholly arbitrary strings with
# known status vocabulary (in varied casing / whitespace) exercises both the
# recognized branches and the unknown/blank fallback.
_KNOWN_STATES = [
    "Final",
    "Game Over",
    "Scheduled",
    "Pre-Game",
    "Pregame",
    "Warmup",
    "Preview",
    "In Progress",
    "Manager Challenge",
    "Delayed",
    "Live",
    "",
    "  Final  ",
    "FINAL",
    "  ",
]

_state_strategy = st.one_of(
    st.none(),
    st.text(),
    st.sampled_from(_KNOWN_STATES),
)


# Property 6 (Req 4.2): classification is total and single-valued ------------


@settings(deadline=None, max_examples=200)
@given(abstract_state=_state_strategy, detailed_state=_state_strategy)
def test_property6_status_classification_total_and_single_valued(
    abstract_state: str | None, detailed_state: str | None
) -> None:
    """**Validates: Requirements 4.2**

    Feature: mlb-support, Property 6

    For arbitrary ``abstract_state`` / ``detailed_state`` inputs (including
    ``None`` and blank strings), ``classify_status`` returns exactly one
    ``MLBGameStatus`` value. Totality: it never raises and always yields a
    valid member of the enum. Single-valuedness: the result is one specific
    enum member, and calling the function again with the same inputs yields the
    identical result (the function is deterministic).
    """
    result = classify_status(abstract_state, detailed_state)

    # Totality: the result is a member of the MLBGameStatus enumeration.
    assert isinstance(result, MLBGameStatus)
    assert result in _ALL_STATUSES

    # Single-valuedness / determinism: the same inputs always map to the same
    # single class.
    again = classify_status(abstract_state, detailed_state)
    assert again == result
