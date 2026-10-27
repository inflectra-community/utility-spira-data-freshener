# Feature: spira-freshener, Properties 13–14: Payload serialisation
"""Property-based tests for payload serialisation.

Properties covered:
  13 — Payload always contains all five artifact-type keys
  14 — Payload serialise → deserialise round-trip produces equivalent object

Validates: Requirements 7.2, 7.7
"""

from __future__ import annotations

import json
import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from spira_freshener.models import (
    AllocationRecord,
    IncidentRecord,
    Payload,
    PayloadMetadata,
    TaskRecord,
    TestRunRecord,
    TimeEntryRecord,
)
from spira_freshener.payload import deserialise_payload, serialise_payload, write_payload

# ---------------------------------------------------------------------------
# Strategies for individual artifact records
# ---------------------------------------------------------------------------

test_run_strategy = st.builds(
    TestRunRecord,
    test_case_id=st.integers(min_value=1, max_value=9999),
    release_id=st.integers(min_value=1, max_value=9999),
    tester_id=st.integers(min_value=1, max_value=9999),
    execution_status_id=st.sampled_from([1, 2, 5, 6]),
    execution_date=st.just("2025-01-14T09:15:00Z"),
    name=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz "),
)

incident_strategy = st.builds(
    IncidentRecord,
    name=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz "),
    description=st.text(min_size=1, max_size=100, alphabet="abcdefghijklmnopqrstuvwxyz "),
    incident_type_id=st.integers(min_value=1, max_value=10),
    priority_id=st.integers(min_value=1, max_value=4),
    incident_status_id=st.integers(min_value=1, max_value=4),
    detected_release_id=st.integers(min_value=1, max_value=9999),
    owner_id=st.integers(min_value=1, max_value=9999),
    detected_by_id=st.integers(min_value=1, max_value=9999),
    creation_date=st.just("2025-01-10T14:00:00Z"),
)

task_strategy = st.builds(
    TaskRecord,
    name=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz "),
    requirement_id=st.integers(min_value=1, max_value=9999),
    release_id=st.integers(min_value=1, max_value=9999),
    owner_id=st.integers(min_value=1, max_value=9999),
    task_status_id=st.integers(min_value=1, max_value=5),
    estimated_effort=st.integers(min_value=30, max_value=960),
    start_date=st.just("2025-01-08"),
    end_date=st.just("2025-01-10"),
)

allocation_strategy = st.builds(
    AllocationRecord,
    user_id=st.integers(min_value=1, max_value=9999),
    release_id=st.integers(min_value=1, max_value=9999),
    availability_percentage=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)

time_entry_strategy = st.builds(
    TimeEntryRecord,
    user_id=st.integers(min_value=1, max_value=9999),
    artifact_type_id=st.sampled_from([3, 6]),
    artifact_id=st.integers(min_value=1, max_value=9999),
    hours=st.floats(min_value=0.5, max_value=8.0, allow_nan=False, allow_infinity=False),
    entry_date=st.just("2025-01-12"),
)

metadata_strategy = st.builds(
    PayloadMetadata,
    generated_at=st.just("2025-01-15T10:30:00Z"),
    project_id=st.integers(min_value=1, max_value=9999),
    version=st.just("1.0.0"),
)


@st.composite
def payload_strategy(draw) -> Payload:
    """Generate a Payload with arbitrary (possibly empty) artifact lists."""
    metadata = draw(metadata_strategy)
    test_run_list = draw(st.lists(test_run_strategy, min_size=0, max_size=5))
    incident_list = draw(st.lists(incident_strategy, min_size=0, max_size=5))
    task_list = draw(st.lists(task_strategy, min_size=0, max_size=5))
    allocation_list = draw(st.lists(allocation_strategy, min_size=0, max_size=5))
    time_entry_list = draw(st.lists(time_entry_strategy, min_size=0, max_size=5))
    return Payload(
        metadata=metadata,
        test_runs=test_run_list,
        incidents=incident_list,
        tasks=task_list,
        resource_allocations=allocation_list,
        time_entries=time_entry_list,
    )


# ---------------------------------------------------------------------------
# Property 13: Payload always contains all five artifact-type keys
# ---------------------------------------------------------------------------

# Property 13: For any Payload (including empty artifact lists),
# serialise_payload() output always contains all five keys.
# Validates: Requirements 7.2

_REQUIRED_KEYS = {"test_runs", "incidents", "tasks", "resource_allocations", "time_entries"}


@given(payload=payload_strategy())
@settings(max_examples=100)
def test_property_13_payload_always_has_all_five_keys(payload: Payload) -> None:
    """Property 13: serialised payload always contains all five artifact-type keys.

    **Validates: Requirements 7.2**
    """
    json_str = serialise_payload(payload)
    data = json.loads(json_str)

    for key in _REQUIRED_KEYS:
        assert key in data, f"Key '{key}' missing from serialised payload"
        assert isinstance(data[key], list), f"Key '{key}' should map to a list"


@given(payload=payload_strategy())
@settings(max_examples=100)
def test_property_13_payload_keys_present_when_written_to_file(payload: Payload) -> None:
    """Property 13 (file variant): written payload file always has all five keys.

    **Validates: Requirements 7.2**
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        tmp_path = fh.name

    try:
        write_payload(payload, tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        for key in _REQUIRED_KEYS:
            assert key in data, f"Key '{key}' missing from written payload file"
            assert isinstance(data[key], list), f"Key '{key}' should map to a list"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Property 14: Payload serialisation round-trip
# ---------------------------------------------------------------------------

# Property 14: For any Payload, serialise → deserialise round-trip produces
# structurally equivalent object (same field values).
# Validates: Requirements 7.7


@given(payload=payload_strategy())
@settings(max_examples=100)
def test_property_14_payload_roundtrip(payload: Payload) -> None:
    """Property 14: serialise → deserialise round-trip produces equivalent Payload.

    **Validates: Requirements 7.7**
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        tmp_path = fh.name

    try:
        write_payload(payload, tmp_path)
        restored = deserialise_payload(tmp_path)

        # Metadata
        assert restored.metadata.generated_at == payload.metadata.generated_at
        assert restored.metadata.project_id == payload.metadata.project_id
        assert restored.metadata.version == payload.metadata.version

        # Test runs
        assert len(restored.test_runs) == len(payload.test_runs)
        for orig, rest in zip(payload.test_runs, restored.test_runs):
            assert rest.test_case_id == orig.test_case_id
            assert rest.release_id == orig.release_id
            assert rest.tester_id == orig.tester_id
            assert rest.execution_status_id == orig.execution_status_id
            assert rest.execution_date == orig.execution_date
            assert rest.name == orig.name

        # Incidents
        assert len(restored.incidents) == len(payload.incidents)
        for orig, rest in zip(payload.incidents, restored.incidents):
            assert rest.name == orig.name
            assert rest.description == orig.description
            assert rest.incident_type_id == orig.incident_type_id
            assert rest.priority_id == orig.priority_id
            assert rest.incident_status_id == orig.incident_status_id
            assert rest.detected_release_id == orig.detected_release_id
            assert rest.owner_id == orig.owner_id
            assert rest.detected_by_id == orig.detected_by_id
            assert rest.creation_date == orig.creation_date

        # Tasks
        assert len(restored.tasks) == len(payload.tasks)
        for orig, rest in zip(payload.tasks, restored.tasks):
            assert rest.name == orig.name
            assert rest.requirement_id == orig.requirement_id
            assert rest.release_id == orig.release_id
            assert rest.owner_id == orig.owner_id
            assert rest.task_status_id == orig.task_status_id
            assert rest.estimated_effort == orig.estimated_effort
            assert rest.start_date == orig.start_date
            assert rest.end_date == orig.end_date

        # Resource allocations
        assert len(restored.resource_allocations) == len(payload.resource_allocations)
        for orig, rest in zip(payload.resource_allocations, restored.resource_allocations):
            assert rest.user_id == orig.user_id
            assert rest.release_id == orig.release_id
            assert abs(rest.availability_percentage - orig.availability_percentage) < 1e-9

        # Time entries
        assert len(restored.time_entries) == len(payload.time_entries)
        for orig, rest in zip(payload.time_entries, restored.time_entries):
            assert rest.user_id == orig.user_id
            assert rest.artifact_type_id == orig.artifact_type_id
            assert rest.artifact_id == orig.artifact_id
            assert abs(rest.hours - orig.hours) < 1e-9
            assert rest.entry_date == orig.entry_date

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
