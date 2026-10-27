# Feature: spira-freshener, Property 1: Config round-trip
"""Property test for FreshenerConfig serialisation round-trip.

For any valid FreshenerConfig object, serialising it to JSON and
deserialising it back should produce an equivalent config object.

Validates: Requirements 1.2
"""

import json
import tempfile
import os

import pytest
from hypothesis import given, settings, strategies as st

from spira_freshener.config import (
    FreshenerConfig,
    TestRunConfig,
    IncidentConfig,
    TaskConfig,
    AllocationConfig,
    StatusWeights,
    load_config,
)

# ---------------------------------------------------------------------------
# Strategies for valid weight dicts
# ---------------------------------------------------------------------------

_TEST_RUN_STATUSES = ["Passed", "Failed", "Blocked", "Caution"]
_INCIDENT_PRIORITIES = ["Critical", "High", "Medium", "Low"]
_TASK_STATUSES = ["Not Started", "In Progress", "Completed", "Blocked", "Deferred"]


def _weights_summing_to_100(keys: list[str]) -> st.SearchStrategy:
    """Generate a dict mapping each key to a non-negative int, summing to 100."""

    @st.composite
    def _strategy(draw):
        n = len(keys)
        # Draw n-1 non-negative integers that sum to at most 100, then derive the last.
        parts = draw(
            st.lists(
                st.integers(min_value=0, max_value=100),
                min_size=n - 1,
                max_size=n - 1,
            ).filter(lambda lst: sum(lst) <= 100)
        )
        last = 100 - sum(parts)
        values = parts + [last]
        return dict(zip(keys, values))

    return _strategy()


# ---------------------------------------------------------------------------
# Strategies for each config section
# ---------------------------------------------------------------------------

@st.composite
def valid_test_run_config_dict(draw) -> dict:
    count = draw(st.integers(min_value=1, max_value=10_000))
    weights = draw(_weights_summing_to_100(_TEST_RUN_STATUSES))
    return {"count": count, "status_weights": weights}


@st.composite
def valid_incident_config_dict(draw) -> dict:
    count = draw(st.integers(min_value=1, max_value=1_000))
    # types: 1–20 non-empty strings
    types = draw(
        st.lists(
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
                min_size=1,
                max_size=50,
            ).filter(lambda s: s.strip()),
            min_size=1,
            max_size=20,
        )
    )
    priority_weights = draw(_weights_summing_to_100(_INCIDENT_PRIORITIES))
    statuses = draw(
        st.lists(
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
                min_size=1,
                max_size=50,
            ).filter(lambda s: s.strip()),
            min_size=1,
            max_size=20,
        )
    )
    return {
        "count": count,
        "types": types,
        "priority_weights": priority_weights,
        "statuses": statuses,
    }


@st.composite
def valid_task_config_dict(draw) -> dict:
    count = draw(st.integers(min_value=1, max_value=1_000))
    weights = draw(_weights_summing_to_100(_TASK_STATUSES))
    # min_effort_hours >= 0.5, max_effort_hours <= 200, max >= min
    min_effort = draw(st.floats(min_value=0.5, max_value=199.0, allow_nan=False, allow_infinity=False))
    max_effort = draw(st.floats(min_value=min_effort, max_value=200.0, allow_nan=False, allow_infinity=False))
    return {
        "count": count,
        "status_weights": weights,
        "min_effort_hours": min_effort,
        "max_effort_hours": max_effort,
    }


@st.composite
def valid_allocation_config_dict(draw) -> dict:
    time_entry_count = draw(st.integers(min_value=1, max_value=5_000))
    # min_allocation_hours > 0, max_allocation_hours > 0, min <= max
    min_alloc = draw(st.floats(min_value=0.01, max_value=999.0, allow_nan=False, allow_infinity=False))
    max_alloc = draw(st.floats(min_value=min_alloc, max_value=1000.0, allow_nan=False, allow_infinity=False))
    # min_time_entry_hours >= 0.5, max_time_entry_hours <= 24, min <= max
    min_te = draw(st.floats(min_value=0.5, max_value=23.9, allow_nan=False, allow_infinity=False))
    max_te = draw(st.floats(min_value=min_te, max_value=24.0, allow_nan=False, allow_infinity=False))
    return {
        "time_entry_count": time_entry_count,
        "min_allocation_hours": min_alloc,
        "max_allocation_hours": max_alloc,
        "min_time_entry_hours": min_te,
        "max_time_entry_hours": max_te,
    }


@st.composite
def valid_freshener_config_dict(draw) -> dict:
    project_id = draw(st.integers(min_value=1, max_value=1_000_000))
    recency_window_days = draw(st.integers(min_value=1, max_value=365))
    dry_run = draw(st.booleans())
    test_runs = draw(valid_test_run_config_dict())
    incidents = draw(valid_incident_config_dict())
    tasks = draw(valid_task_config_dict())
    allocations = draw(valid_allocation_config_dict())
    return {
        "project_id": project_id,
        "recency_window_days": recency_window_days,
        "dry_run": dry_run,
        "test_runs": test_runs,
        "incidents": incidents,
        "tasks": tasks,
        "allocations": allocations,
    }


# ---------------------------------------------------------------------------
# Helper: serialise a config dict to a temp file and load it back
# ---------------------------------------------------------------------------

def _roundtrip(config_dict: dict) -> FreshenerConfig:
    """Write config_dict to a temp JSON file and load it with load_config."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as fh:
        json.dump(config_dict, fh)
        tmp_path = fh.name
    try:
        return load_config(tmp_path)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Property 1: Config round-trip
# ---------------------------------------------------------------------------

@given(config_dict=valid_freshener_config_dict())
@settings(max_examples=100)
def test_config_roundtrip(config_dict: dict) -> None:
    """For any valid FreshenerConfig dict, serialising to JSON and deserialising
    back via load_config should produce a structurally equivalent FreshenerConfig.

    Validates: Requirements 1.2
    """
    result = _roundtrip(config_dict)

    # Top-level scalar fields
    assert result.project_id == config_dict["project_id"]
    assert result.recency_window_days == config_dict["recency_window_days"]
    assert result.dry_run == config_dict["dry_run"]

    # test_runs section
    tr = config_dict["test_runs"]
    assert result.test_runs.count == tr["count"]
    assert result.test_runs.status_weights.weights == tr["status_weights"]

    # incidents section
    inc = config_dict["incidents"]
    assert result.incidents.count == inc["count"]
    assert result.incidents.types == inc["types"]
    assert result.incidents.priority_weights.weights == inc["priority_weights"]
    assert result.incidents.statuses == inc["statuses"]

    # tasks section
    tsk = config_dict["tasks"]
    assert result.tasks.count == tsk["count"]
    assert result.tasks.status_weights.weights == tsk["status_weights"]
    assert result.tasks.min_effort_hours == pytest.approx(tsk["min_effort_hours"])
    assert result.tasks.max_effort_hours == pytest.approx(tsk["max_effort_hours"])

    # allocations section
    alloc = config_dict["allocations"]
    assert result.allocations.time_entry_count == alloc["time_entry_count"]
    assert result.allocations.min_allocation_hours == pytest.approx(alloc["min_allocation_hours"])
    assert result.allocations.max_allocation_hours == pytest.approx(alloc["max_allocation_hours"])
    assert result.allocations.min_time_entry_hours == pytest.approx(alloc["min_time_entry_hours"])
    assert result.allocations.max_time_entry_hours == pytest.approx(alloc["max_time_entry_hours"])
