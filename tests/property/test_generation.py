# Feature: spira-freshener, Properties 4–12: Generation invariants
"""Property-based tests for artifact generation services.

Properties covered:
  4  — Test run count matches config
  5  — Artifact dates within recency window
  6  — Artifact status values from valid set
  7  — Release and Resource IDs from valid sets
  8  — Incident name and description length invariant
  9  — Task date ordering invariant
  10 — Task effort within configured range
  11 — Allocation count equals Resources × Releases
  12 — Allocation and time-entry hours within configured ranges

Validates: Requirements 3.3, 3.4, 3.5, 3.7, 3.9, 4.1, 4.3, 4.4, 4.5,
           4.7, 4.9, 5.3, 5.4, 5.5, 5.9, 6.1, 6.2, 6.6, 6.7, 6.8
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from spira_freshener.config import (
    AllocationConfig,
    FreshenerConfig,
    IncidentConfig,
    StatusWeights,
    TaskConfig,
    TestRunConfig,
)
from spira_freshener.models import ProjectContext
from spira_freshener.services import allocations, incidents, tasks, test_runs

# ---------------------------------------------------------------------------
# Fixed reference time (UTC)
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Small positive integer for counts
count_strategy = st.integers(min_value=1, max_value=50)

# Recency window in days
recency_strategy = st.integers(min_value=1, max_value=90)

# Lists of minimal context dicts
test_case_strategy = st.lists(
    st.fixed_dictionaries({"TestCaseId": st.integers(min_value=1, max_value=9999), "Name": st.just("TC")}),
    min_size=1,
    max_size=10,
)

release_strategy = st.lists(
    st.fixed_dictionaries({"ReleaseId": st.integers(min_value=1, max_value=9999), "Name": st.just("R")}),
    min_size=1,
    max_size=5,
)

resource_strategy = st.lists(
    st.fixed_dictionaries({"UserId": st.integers(min_value=1, max_value=9999), "FullName": st.just("U")}),
    min_size=1,
    max_size=5,
)

requirement_strategy = st.lists(
    st.fixed_dictionaries({"RequirementId": st.integers(min_value=1, max_value=9999), "Name": st.just("Req")}),
    min_size=1,
    max_size=5,
)


def _make_test_run_config(count: int, recency: int) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1, recency_window_days=recency)
    cfg.test_runs = TestRunConfig(
        count=count,
        status_weights=StatusWeights({"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}),
    )
    return cfg


def _make_incident_config(count: int, recency: int) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1, recency_window_days=recency)
    cfg.incidents = IncidentConfig(
        count=count,
        types=["Bug", "Enhancement"],
        priority_weights=StatusWeights({"Critical": 10, "High": 25, "Medium": 45, "Low": 20}),
        statuses=["Open", "In Progress", "Resolved", "Closed"],
    )
    return cfg


def _make_task_config(
    count: int,
    recency: int,
    min_effort: float = 1.0,
    max_effort: float = 8.0,
) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1, recency_window_days=recency)
    cfg.tasks = TaskConfig(
        count=count,
        status_weights=StatusWeights(
            {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5}
        ),
        min_effort_hours=min_effort,
        max_effort_hours=max_effort,
    )
    return cfg


def _make_allocation_config(
    min_alloc: float = 20.0,
    max_alloc: float = 40.0,
    min_te: float = 0.5,
    max_te: float = 8.0,
    te_count: int = 5,
) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1, recency_window_days=30)
    cfg.allocations = AllocationConfig(
        min_allocation_hours=min_alloc,
        max_allocation_hours=max_alloc,
        time_entry_count=te_count,
        min_time_entry_hours=min_te,
        max_time_entry_hours=max_te,
    )
    return cfg


# ---------------------------------------------------------------------------
# Property 4: Test run count matches config
# ---------------------------------------------------------------------------

# Property 4: For any valid test_run_count in [1,50] and non-empty test_cases,
# generate() produces exactly test_run_count records.
# Validates: Requirements 3.3


@given(
    count=count_strategy,
    recency=recency_strategy,
    test_case_list=test_case_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_4_test_run_count_matches_config(
    count: int,
    recency: int,
    test_case_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 4: Test run count matches config.

    **Validates: Requirements 3.3**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=test_case_list,
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_test_run_config(count, recency)

    result = test_runs.generate(context, config, _NOW)

    assert len(result) == count


# ---------------------------------------------------------------------------
# Property 5: Artifact dates within recency window
# ---------------------------------------------------------------------------

# Property 5: For any generated artifact (Test Run, Incident, Task, Time Entry),
# its primary date field falls within [now - recency_window_days, now].
# Validates: Requirements 3.4, 4.1, 6.7


@given(
    count=count_strategy,
    recency=recency_strategy,
    test_case_list=test_case_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_5_test_run_dates_within_window(
    count: int,
    recency: int,
    test_case_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 5 (test runs): execution_date within recency window.

    **Validates: Requirements 3.4**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=test_case_list,
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_test_run_config(count, recency)
    window_start = _NOW - timedelta(days=recency)

    result = test_runs.generate(context, config, _NOW)

    for record in result:
        # Parse ISO 8601 UTC string
        dt = datetime.strptime(record.execution_date, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        assert window_start <= dt <= _NOW, (
            f"execution_date {record.execution_date!r} outside window "
            f"[{window_start.isoformat()}, {_NOW.isoformat()}]"
        )


@given(
    count=count_strategy,
    recency=recency_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_5_incident_dates_within_window(
    count: int,
    recency: int,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 5 (incidents): creation_date within recency window.

    **Validates: Requirements 4.1**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_incident_config(count, recency)
    window_start = _NOW - timedelta(days=recency)

    result = incidents.generate(context, config, _NOW)

    for record in result:
        dt = datetime.strptime(record.creation_date, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        assert window_start <= dt <= _NOW, (
            f"creation_date {record.creation_date!r} outside window"
        )


@given(
    count=count_strategy,
    recency=recency_strategy,
    requirement_list=requirement_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_5_task_dates_within_window(
    count: int,
    recency: int,
    requirement_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 5 (tasks): start_date within recency window.

    **Validates: Requirements 5.3**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=requirement_list,
        releases=release_list,
        resources=resource_list,
    )
    config = _make_task_config(count, recency)
    window_start = (_NOW - timedelta(days=recency)).date()
    now_date = _NOW.date()

    result = tasks.generate(context, config, _NOW)

    for record in result:
        from datetime import date
        start = date.fromisoformat(record.start_date)
        assert window_start <= start <= now_date, (
            f"start_date {record.start_date!r} outside window"
        )


# ---------------------------------------------------------------------------
# Property 6: Artifact status values from valid set
# ---------------------------------------------------------------------------

# Property 6: For any generated artifact, its status value is a key present
# in the configured weights/list.
# Validates: Requirements 3.5, 4.3, 4.4, 5.4

_TEST_RUN_STATUS_IDS = {2, 1, 5, 6}  # Passed=2, Failed=1, Blocked=5, Caution=6


@given(
    count=count_strategy,
    recency=recency_strategy,
    test_case_list=test_case_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_6_test_run_status_from_valid_set(
    count: int,
    recency: int,
    test_case_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 6 (test runs): execution_status_id from valid Spira IDs.

    **Validates: Requirements 3.5**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=test_case_list,
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_test_run_config(count, recency)

    result = test_runs.generate(context, config, _NOW)

    for record in result:
        assert record.execution_status_id in _TEST_RUN_STATUS_IDS, (
            f"execution_status_id {record.execution_status_id} not in {_TEST_RUN_STATUS_IDS}"
        )


@given(
    count=count_strategy,
    recency=recency_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_6_incident_status_from_valid_set(
    count: int,
    recency: int,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 6 (incidents): incident_status_id index within statuses list.

    **Validates: Requirements 4.3, 4.4**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_incident_config(count, recency)
    # Status IDs are 1-based indices into the statuses list
    valid_status_ids = set(range(1, len(config.incidents.statuses) + 1))

    result = incidents.generate(context, config, _NOW)

    for record in result:
        assert record.incident_status_id in valid_status_ids, (
            f"incident_status_id {record.incident_status_id} not in {valid_status_ids}"
        )


@given(
    count=count_strategy,
    recency=recency_strategy,
    requirement_list=requirement_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_6_task_status_from_valid_set(
    count: int,
    recency: int,
    requirement_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 6 (tasks): task_status_id from valid Spira task status IDs.

    **Validates: Requirements 5.4**
    """
    from spira_freshener.services.tasks import STATUS_IDS

    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=requirement_list,
        releases=release_list,
        resources=resource_list,
    )
    config = _make_task_config(count, recency)
    valid_status_ids = set(STATUS_IDS.values())

    result = tasks.generate(context, config, _NOW)

    for record in result:
        assert record.task_status_id in valid_status_ids, (
            f"task_status_id {record.task_status_id} not in {valid_status_ids}"
        )


# ---------------------------------------------------------------------------
# Property 7: Release and Resource IDs from valid sets
# ---------------------------------------------------------------------------

# Property 7: For any generated artifact referencing a Release or Resource,
# the ID is from the context lists.
# Validates: Requirements 3.7, 3.9, 4.7, 4.9, 5.9, 6.8


@given(
    count=count_strategy,
    recency=recency_strategy,
    test_case_list=test_case_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_7_test_run_ids_from_context(
    count: int,
    recency: int,
    test_case_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 7 (test runs): release_id and tester_id from context.

    **Validates: Requirements 3.7, 3.9**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=test_case_list,
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_test_run_config(count, recency)
    valid_release_ids = {r["ReleaseId"] for r in release_list}
    valid_user_ids = {r["UserId"] for r in resource_list}
    valid_tc_ids = {tc["TestCaseId"] for tc in test_case_list}

    result = test_runs.generate(context, config, _NOW)

    for record in result:
        assert record.release_id in valid_release_ids
        assert record.tester_id in valid_user_ids
        assert record.test_case_id in valid_tc_ids


@given(
    count=count_strategy,
    recency=recency_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_7_incident_ids_from_context(
    count: int,
    recency: int,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 7 (incidents): detected_release_id, owner_id, detected_by_id from context.

    **Validates: Requirements 4.7, 4.9**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_incident_config(count, recency)
    valid_release_ids = {r["ReleaseId"] for r in release_list}
    valid_user_ids = {r["UserId"] for r in resource_list}

    result = incidents.generate(context, config, _NOW)

    for record in result:
        assert record.detected_release_id in valid_release_ids
        assert record.owner_id in valid_user_ids
        assert record.detected_by_id in valid_user_ids


@given(
    count=count_strategy,
    recency=recency_strategy,
    requirement_list=requirement_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_7_task_ids_from_context(
    count: int,
    recency: int,
    requirement_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 7 (tasks): release_id, owner_id, requirement_id from context.

    **Validates: Requirements 5.9**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=requirement_list,
        releases=release_list,
        resources=resource_list,
    )
    config = _make_task_config(count, recency)
    valid_release_ids = {r["ReleaseId"] for r in release_list}
    valid_user_ids = {r["UserId"] for r in resource_list}
    valid_req_ids = {r["RequirementId"] for r in requirement_list}

    result = tasks.generate(context, config, _NOW)

    for record in result:
        assert record.release_id in valid_release_ids
        assert record.owner_id in valid_user_ids
        assert record.requirement_id in valid_req_ids


# ---------------------------------------------------------------------------
# Property 8: Incident name and description length invariant
# ---------------------------------------------------------------------------

# Property 8: For any generated IncidentRecord, name length in [1,255]
# and description in [1,2000].
# Validates: Requirements 4.5


@given(
    count=count_strategy,
    recency=recency_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_8_incident_name_description_length(
    count: int,
    recency: int,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 8: Incident name in [1,255] and description in [1,2000].

    **Validates: Requirements 4.5**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_incident_config(count, recency)

    result = incidents.generate(context, config, _NOW)

    for record in result:
        assert 1 <= len(record.name) <= 255, (
            f"name length {len(record.name)} out of [1, 255]"
        )
        assert 1 <= len(record.description) <= 2000, (
            f"description length {len(record.description)} out of [1, 2000]"
        )


# ---------------------------------------------------------------------------
# Property 9: Task date ordering invariant
# ---------------------------------------------------------------------------

# Property 9: For any generated TaskRecord, end_date >= start_date AND
# end_date <= start_date + 14 days.
# Validates: Requirements 5.3


@given(
    count=count_strategy,
    recency=recency_strategy,
    requirement_list=requirement_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_9_task_date_ordering(
    count: int,
    recency: int,
    requirement_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 9: end_date >= start_date AND end_date <= start_date + 14 days.

    **Validates: Requirements 5.3**
    """
    from datetime import date

    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=requirement_list,
        releases=release_list,
        resources=resource_list,
    )
    config = _make_task_config(count, recency)

    result = tasks.generate(context, config, _NOW)

    for record in result:
        start = date.fromisoformat(record.start_date)
        end = date.fromisoformat(record.end_date)
        assert end >= start, (
            f"end_date {record.end_date!r} < start_date {record.start_date!r}"
        )
        assert end <= start + timedelta(days=14), (
            f"end_date {record.end_date!r} > start_date {record.start_date!r} + 14 days"
        )


# ---------------------------------------------------------------------------
# Property 10: Task effort within configured range
# ---------------------------------------------------------------------------

# Property 10: For any generated TaskRecord, estimated_effort (minutes / 60)
# in [min_effort_hours, max_effort_hours].
# Validates: Requirements 5.5


@given(
    count=count_strategy,
    recency=recency_strategy,
    min_effort=st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False),
    max_effort_delta=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    requirement_list=requirement_strategy,
    release_list=release_strategy,
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_10_task_effort_within_range(
    count: int,
    recency: int,
    min_effort: float,
    max_effort_delta: float,
    requirement_list: list,
    release_list: list,
    resource_list: list,
) -> None:
    """Property 10: estimated_effort (hours) in [min_effort_hours, max_effort_hours].

    **Validates: Requirements 5.5**
    """
    max_effort = min_effort + max_effort_delta

    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=requirement_list,
        releases=release_list,
        resources=resource_list,
    )
    config = _make_task_config(count, recency, min_effort=min_effort, max_effort=max_effort)

    result = tasks.generate(context, config, _NOW)

    for record in result:
        effort_hours = record.estimated_effort / 60.0
        # Allow a small tolerance for floating-point rounding in round()
        assert effort_hours >= min_effort - 0.02, (
            f"effort_hours {effort_hours} < min_effort_hours {min_effort}"
        )
        assert effort_hours <= max_effort + 0.02, (
            f"effort_hours {effort_hours} > max_effort_hours {max_effort}"
        )


# ---------------------------------------------------------------------------
# Property 11: Allocation count equals Resources × Releases
# ---------------------------------------------------------------------------

# Property 11: For any non-empty resources and releases, generate_allocations()
# produces exactly len(resources) * len(releases) records.
# Validates: Requirements 6.1


@given(
    resource_list=resource_strategy,
    release_list=release_strategy,
)
@settings(max_examples=100)
def test_property_11_allocation_count_equals_resources_times_releases(
    resource_list: list,
    release_list: list,
) -> None:
    """Property 11: generate_allocations() count == len(resources) * len(releases).

    **Validates: Requirements 6.1**
    """
    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_allocation_config()

    result = allocations.generate_allocations(context, config)

    expected = len(resource_list) * len(release_list)
    assert len(result) == expected, (
        f"Expected {expected} allocations ({len(resource_list)} resources × "
        f"{len(release_list)} releases), got {len(result)}"
    )


# ---------------------------------------------------------------------------
# Property 12: Allocation and time-entry hours within configured ranges
# ---------------------------------------------------------------------------

# Property 12: AllocationRecord hours in [min_allocation_hours, max_allocation_hours];
# TimeEntryRecord hours in [min_time_entry_hours, max_time_entry_hours].
# Validates: Requirements 6.2, 6.6


@given(
    min_alloc=st.floats(min_value=1.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    alloc_delta=st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    resource_list=resource_strategy,
    release_list=release_strategy,
)
@settings(max_examples=100)
def test_property_12_allocation_hours_within_range(
    min_alloc: float,
    alloc_delta: float,
    resource_list: list,
    release_list: list,
) -> None:
    """Property 12 (allocations): availability_percentage derived from hours in range.

    **Validates: Requirements 6.2**
    """
    max_alloc = min_alloc + alloc_delta

    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=release_list,
        resources=resource_list,
    )
    config = _make_allocation_config(min_alloc=min_alloc, max_alloc=max_alloc)

    result = allocations.generate_allocations(context, config)

    # availability_percentage = min((hours / 40.0) * 100, 100.0)
    # So hours in [min_alloc, max_alloc] means percentage in
    # [min((min_alloc/40)*100, 100), 100]
    min_pct = min((min_alloc / 40.0) * 100, 100.0)
    for record in result:
        assert record.availability_percentage >= min_pct - 0.01, (
            f"availability_percentage {record.availability_percentage} < expected min {min_pct}"
        )
        assert record.availability_percentage <= 100.0, (
            f"availability_percentage {record.availability_percentage} > 100.0"
        )


@given(
    min_te=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    te_delta=st.floats(min_value=0.0, max_value=4.0, allow_nan=False, allow_infinity=False),
    resource_list=resource_strategy,
)
@settings(max_examples=100)
def test_property_12_time_entry_hours_within_range(
    min_te: float,
    te_delta: float,
    resource_list: list,
) -> None:
    """Property 12 (time entries): hours in [min_time_entry_hours, max_time_entry_hours].

    **Validates: Requirements 6.6**
    """
    max_te = min_te + te_delta

    context = ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=[{"ReleaseId": 1, "Name": "R"}],
        resources=resource_list,
    )
    config = _make_allocation_config(min_te=min_te, max_te=max_te, te_count=10)

    # generate_time_entries requires injected artifact IDs
    injected_task_ids = [101, 102, 103]
    injected_incident_ids = [201, 202]

    result = allocations.generate_time_entries(
        context, config, _NOW,
        injected_task_ids=injected_task_ids,
        injected_incident_ids=injected_incident_ids,
    )

    for record in result:
        assert record.hours >= min_te - 0.001, (
            f"hours {record.hours} < min_time_entry_hours {min_te}"
        )
        assert record.hours <= max_te + 0.001, (
            f"hours {record.hours} > max_time_entry_hours {max_te}"
        )
