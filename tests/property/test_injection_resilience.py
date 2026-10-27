# Feature: spira-freshener, Property 16: Injection resilience
"""Property-based test for injection resilience.

Property 16: For N artifacts with k random 4xx/5xx failures, the injector
attempts all N, and InjectionResult shows N-k created and k failed.

Validates: Requirements 8.5
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests
from hypothesis import given, settings
from hypothesis import strategies as st

from spira_freshener.models import (
    IncidentRecord,
    InjectionResult,
    TaskRecord,
    TestRunRecord,
)
from spira_freshener.services import incidents, tasks, test_runs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_error(status_code: int = 422) -> requests.HTTPError:
    """Return an HTTPError with a mock response attached."""
    response = MagicMock()
    response.status_code = status_code
    exc = requests.HTTPError(f"{status_code} Error")
    exc.response = response
    return exc


def _make_test_run_records(n: int) -> list[TestRunRecord]:
    return [
        TestRunRecord(
            test_case_id=10 + i,
            release_id=200,
            tester_id=100,
            execution_status_id=2,
            execution_date="2025-01-14T09:00:00Z",
            name=f"Test Run {i}",
        )
        for i in range(n)
    ]


def _make_incident_records(n: int) -> list[IncidentRecord]:
    return [
        IncidentRecord(
            name=f"Incident {i}",
            description=f"Description {i}",
            incident_type_id=1,
            priority_id=2,
            incident_status_id=1,
            detected_release_id=200,
            owner_id=100,
            detected_by_id=101,
            creation_date="2025-01-10T08:00:00Z",
        )
        for i in range(n)
    ]


def _make_task_records(n: int) -> list[TaskRecord]:
    return [
        TaskRecord(
            name=f"Task {i}",
            requirement_id=300,
            release_id=200,
            owner_id=100,
            task_status_id=1,
            estimated_effort=60,
            start_date="2025-01-10",
            end_date="2025-01-15",
        )
        for i in range(n)
    ]


def _build_side_effects(n: int, k: int) -> list:
    """Build a side_effect list: first k calls raise HTTPError, rest succeed."""
    effects = []
    for i in range(n):
        if i < k:
            effects.append(_make_http_error())
        else:
            effects.append(MagicMock())
    return effects


# ---------------------------------------------------------------------------
# Property 16: Injection resilience
# ---------------------------------------------------------------------------

# Property 16: For N artifacts with k random 4xx/5xx failures, the injector
# attempts all N, and InjectionResult shows N-k created and k failed.
# Validates: Requirements 8.5


@given(
    n=st.integers(min_value=1, max_value=20),
    k=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_property_16_test_runs_injection_resilience(n: int, k: int) -> None:
    """Property 16 (test_runs): all N attempted, N-k created, k failed.

    **Validates: Requirements 8.5**
    """
    # k cannot exceed n
    k = min(k, n)

    records = _make_test_run_records(n)
    client = MagicMock()
    client.post.side_effect = _build_side_effects(n, k)

    result = test_runs.inject(records, client, project_id=1)

    assert isinstance(result, InjectionResult)
    assert client.post.call_count == n, (
        f"Expected {n} POST attempts, got {client.post.call_count}"
    )
    assert result.created == n - k, (
        f"Expected {n - k} created, got {result.created}"
    )
    assert result.failed == k, (
        f"Expected {k} failed, got {result.failed}"
    )


@given(
    n=st.integers(min_value=1, max_value=20),
    k=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_property_16_incidents_injection_resilience(n: int, k: int) -> None:
    """Property 16 (incidents): all N attempted, N-k created, k failed.

    **Validates: Requirements 8.5**
    """
    k = min(k, n)

    records = _make_incident_records(n)
    client = MagicMock()
    client.post.side_effect = _build_side_effects(n, k)

    result = incidents.inject(records, client, project_id=1)

    assert isinstance(result, InjectionResult)
    assert client.post.call_count == n, (
        f"Expected {n} POST attempts, got {client.post.call_count}"
    )
    assert result.created == n - k, (
        f"Expected {n - k} created, got {result.created}"
    )
    assert result.failed == k, (
        f"Expected {k} failed, got {result.failed}"
    )


@given(
    n=st.integers(min_value=1, max_value=20),
    k=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_property_16_tasks_injection_resilience(n: int, k: int) -> None:
    """Property 16 (tasks): all N attempted, N-k created, k failed.

    **Validates: Requirements 8.5**
    """
    k = min(k, n)

    records = _make_task_records(n)
    client = MagicMock()
    client.post.side_effect = _build_side_effects(n, k)

    result = tasks.inject(records, client, project_id=1)

    assert isinstance(result, InjectionResult)
    assert client.post.call_count == n, (
        f"Expected {n} POST attempts, got {client.post.call_count}"
    )
    assert result.created == n - k, (
        f"Expected {n - k} created, got {result.created}"
    )
    assert result.failed == k, (
        f"Expected {k} failed, got {result.failed}"
    )
