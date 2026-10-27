# Feature: spira-freshener, Property 15: Dry-run makes no mutating HTTP calls
"""Property-based test for dry-run mode.

Property 15: With dry_run=True in RunOptions, runner.run() makes zero POST,
PUT, or DELETE calls to SpiraClient.

Validates: Requirements 9.2
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, call

from hypothesis import given, settings
from hypothesis import strategies as st

from spira_freshener.config import FreshenerConfig, TestRunConfig, IncidentConfig, TaskConfig, AllocationConfig, StatusWeights
from spira_freshener.models import RunOptions
from spira_freshener.runner import run

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

count_strategy = st.integers(min_value=1, max_value=10)
recency_strategy = st.integers(min_value=1, max_value=30)


def _make_config(count: int, recency: int) -> FreshenerConfig:
    """Build a minimal FreshenerConfig for dry-run testing."""
    cfg = FreshenerConfig(project_id=1, recency_window_days=recency)
    cfg.test_runs = TestRunConfig(
        count=count,
        status_weights=StatusWeights({"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}),
    )
    cfg.incidents = IncidentConfig(
        count=count,
        types=["Bug"],
        priority_weights=StatusWeights({"Critical": 10, "High": 25, "Medium": 45, "Low": 20}),
        statuses=["Open", "Closed"],
    )
    cfg.tasks = TaskConfig(
        count=count,
        status_weights=StatusWeights(
            {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5}
        ),
        min_effort_hours=1.0,
        max_effort_hours=4.0,
    )
    cfg.allocations = AllocationConfig(
        min_allocation_hours=20.0,
        max_allocation_hours=40.0,
        time_entry_count=count,
        min_time_entry_hours=0.5,
        max_time_entry_hours=4.0,
    )
    return cfg


def _make_mock_client() -> MagicMock:
    """Build a mock SpiraClient that returns realistic empty-ish context."""
    client = MagicMock()
    client.get.side_effect = lambda path, **kwargs: _fake_get(path)
    client.post = MagicMock()
    client.put = MagicMock()
    client.delete = MagicMock()
    return client


def _fake_get(path: str) -> list:
    """Return minimal valid context for any GET path."""
    if "test-cases" in path:
        return [{"TestCaseId": 1, "Name": "TC-1"}]
    if "requirements" in path:
        return [{"RequirementId": 1, "Name": "Req-1"}]
    if "releases" in path:
        return [{"ReleaseId": 1, "Name": "Release-1"}]
    if "users" in path:
        return [{"UserId": 1, "FullName": "User One", "Active": True}]
    return []


# ---------------------------------------------------------------------------
# Property 15: Dry-run makes no mutating HTTP calls
# ---------------------------------------------------------------------------

# Property 15: With dry_run=True in RunOptions, runner.run() makes zero POST,
# PUT, or DELETE calls to SpiraClient.
# Validates: Requirements 9.2


@given(
    count=count_strategy,
    recency=recency_strategy,
)
@settings(max_examples=100, deadline=None)
def test_property_15_dry_run_makes_no_mutating_calls(
    count: int,
    recency: int,
) -> None:
    """Property 15: dry_run=True → zero POST, PUT, DELETE calls.

    **Validates: Requirements 9.2**
    """
    config = _make_config(count, recency)
    client = _make_mock_client()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        tmp_path = fh.name

    try:
        options = RunOptions(
            dry_run=True,
            output_path=tmp_path,
            verbose=False,
            log_file=None,
        )

        exit_code = run(config, client, options)

        assert exit_code == 0, f"run() returned non-zero exit code: {exit_code}"

        # The critical assertion: no mutating calls
        assert client.post.call_count == 0, (
            f"Expected 0 POST calls in dry-run mode, got {client.post.call_count}. "
            f"Calls: {client.post.call_args_list}"
        )
        assert client.put.call_count == 0, (
            f"Expected 0 PUT calls in dry-run mode, got {client.put.call_count}. "
            f"Calls: {client.put.call_args_list}"
        )
        assert client.delete.call_count == 0, (
            f"Expected 0 DELETE calls in dry-run mode, got {client.delete.call_count}. "
            f"Calls: {client.delete.call_args_list}"
        )

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
