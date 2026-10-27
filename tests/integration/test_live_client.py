"""Integration tests for SpiraFreshener against a live Spira instance.

These tests are skipped automatically unless the SPIRA_BASE_URL environment
variable is set.  They require valid credentials in the environment:
  SPIRA_BASE_URL  — base URL of the Spira instance
  SPIRA_USERNAME  — Spira username
  SPIRA_API_KEY   — Spira API key (RSS token)

Requirements: 1.6, 7.7, 9.1
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

# Skip the entire module unless SPIRA_BASE_URL is set.
pytestmark = pytest.mark.skipif(
    not os.getenv("SPIRA_BASE_URL"),
    reason="SPIRA_BASE_URL not set — skipping live integration tests",
)


def _get_client():
    """Build a SpiraClient from environment variables."""
    from spira_freshener.client import SpiraClient

    base_url = os.environ["SPIRA_BASE_URL"]
    username = os.environ.get("SPIRA_USERNAME", "")
    api_key = os.environ.get("SPIRA_API_KEY", "")

    if not username or not api_key:
        pytest.skip("SPIRA_USERNAME or SPIRA_API_KEY not set")

    return SpiraClient(base_url=base_url, username=username, api_key=api_key)


def _get_project_id() -> int:
    """Return the project ID from the environment, defaulting to 1."""
    return int(os.environ.get("SPIRA_PROJECT_ID", "1"))


# ---------------------------------------------------------------------------
# Test 1: SpiraClient.get("projects") returns a list
# ---------------------------------------------------------------------------


def test_live_client_get_projects_returns_list():
    """SpiraClient.get('projects') must return a non-empty list from a live Spira instance.

    Requirements: 1.6
    """
    client = _get_client()

    result = client.get("projects")

    assert isinstance(result, list), (
        f"Expected a list from GET projects, got {type(result).__name__}"
    )
    assert len(result) > 0, "Expected at least one project in the live Spira instance"


# ---------------------------------------------------------------------------
# Test 2: End-to-end run() with dry_run=True writes a valid JSON payload file
# ---------------------------------------------------------------------------


def test_live_dry_run_writes_valid_json_payload():
    """End-to-end run() with dry_run=True must write a valid JSON payload file.

    Requirements: 7.7, 9.1
    """
    from spira_freshener.config import (
        AllocationConfig,
        FreshenerConfig,
        IncidentConfig,
        StatusWeights,
        TaskConfig,
        TestRunConfig,
    )
    from spira_freshener.models import RunOptions
    from spira_freshener.runner import run

    client = _get_client()
    project_id = _get_project_id()

    config = FreshenerConfig(project_id=project_id, recency_window_days=30)
    config.test_runs = TestRunConfig(
        count=3,
        status_weights=StatusWeights({"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}),
    )
    config.incidents = IncidentConfig(
        count=2,
        types=["Bug", "Enhancement"],
        priority_weights=StatusWeights({"Critical": 10, "High": 25, "Medium": 45, "Low": 20}),
        statuses=["Open", "In Progress", "Resolved", "Closed"],
    )
    config.tasks = TaskConfig(
        count=2,
        status_weights=StatusWeights(
            {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5}
        ),
        min_effort_hours=1.0,
        max_effort_hours=4.0,
    )
    config.allocations = AllocationConfig(
        min_allocation_hours=20.0,
        max_allocation_hours=40.0,
        time_entry_count=3,
        min_time_entry_hours=0.5,
        max_time_entry_hours=4.0,
    )

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
        assert os.path.exists(tmp_path), "Payload file was not written"

        with open(tmp_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Validate all five artifact-type keys are present
        for key in ("test_runs", "incidents", "tasks", "resource_allocations", "time_entries"):
            assert key in data, f"Key '{key}' missing from payload"
            assert isinstance(data[key], list), f"Key '{key}' should be a list"

        # Validate metadata
        assert "metadata" in data
        assert "generated_at" in data["metadata"]
        assert "project_id" in data["metadata"]
        assert data["metadata"]["project_id"] == project_id

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
