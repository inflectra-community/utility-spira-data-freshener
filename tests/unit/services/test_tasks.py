"""Unit tests for spira_freshener.services.tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

from spira_freshener.config import FreshenerConfig, TaskConfig, StatusWeights
from spira_freshener.models import InjectionResult, ProjectContext, TaskRecord
from spira_freshener.services.tasks import generate, inject


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_config(count: int = 5) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1)
    cfg.tasks = TaskConfig(
        count=count,
        status_weights=StatusWeights(
            {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5}
        ),
        min_effort_hours=1.0,
        max_effort_hours=8.0,
    )
    return cfg


def _make_context(
    num_requirements: int = 3,
    num_releases: int = 2,
    num_resources: int = 2,
) -> ProjectContext:
    requirements = [{"RequirementId": 300 + i, "Name": f"Req {i}"} for i in range(num_requirements)]
    releases = [{"ReleaseId": 200 + i, "Name": f"Release {i}"} for i in range(num_releases)]
    resources = [{"UserId": 100 + i, "FullName": f"User {i}"} for i in range(num_resources)]
    return ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=requirements,
        releases=releases,
        resources=resources,
    )


def _make_http_error() -> requests.HTTPError:
    response = MagicMock()
    response.status_code = 400
    exc = requests.HTTPError("400 Bad Request")
    exc.response = response
    return exc


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


# ---------------------------------------------------------------------------
# generate() — count tests
# ---------------------------------------------------------------------------


def test_generate_returns_correct_count():
    """generate() should return exactly config.tasks.count records."""
    context = _make_context()
    config = _make_config(count=8)

    result = generate(context, config, _NOW)

    assert len(result) == 8


def test_generate_returns_all_task_records():
    """All returned items should be TaskRecord instances."""
    context = _make_context()
    config = _make_config(count=4)

    result = generate(context, config, _NOW)

    assert all(isinstance(r, TaskRecord) for r in result)


# ---------------------------------------------------------------------------
# generate() — empty-context guard tests
# ---------------------------------------------------------------------------


def test_generate_returns_empty_when_no_requirements(caplog):
    """Should return [] and log a warning when context.requirements is empty."""
    context = _make_context(num_requirements=0)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate(context, config, _NOW)

    assert result == []
    assert any("requirement" in msg.lower() for msg in caplog.messages)


def test_generate_returns_empty_when_no_releases(caplog):
    """Should return [] and log a warning when context.releases is empty."""
    context = _make_context(num_releases=0)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate(context, config, _NOW)

    assert result == []
    assert any("release" in msg.lower() for msg in caplog.messages)


def test_generate_returns_empty_when_no_resources(caplog):
    """Should return [] and log a warning when context.resources is empty."""
    context = _make_context(num_resources=0)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate(context, config, _NOW)

    assert result == []
    assert any("resource" in msg.lower() for msg in caplog.messages)


# ---------------------------------------------------------------------------
# generate() — date ordering invariant
# ---------------------------------------------------------------------------


def test_generate_end_date_gte_start_date():
    """end_date should be >= start_date for every generated TaskRecord."""
    context = _make_context()
    config = _make_config(count=20)

    result = generate(context, config, _NOW)

    for record in result:
        assert record.end_date >= record.start_date, (
            f"end_date {record.end_date!r} < start_date {record.start_date!r}"
        )


# ---------------------------------------------------------------------------
# inject() — count tests
# ---------------------------------------------------------------------------


def test_inject_returns_correct_created_count():
    """inject() should return created == len(records) when all POSTs succeed."""
    records = _make_task_records(5)
    client = MagicMock()
    client.post.return_value = MagicMock()

    result = inject(records, client, project_id=1)

    assert result.created == 5
    assert result.failed == 0
    assert isinstance(result, InjectionResult)


def test_inject_returns_correct_failed_count():
    """inject() should return failed == len(records) when all POSTs raise HTTPError."""
    records = _make_task_records(3)
    client = MagicMock()
    client.post.side_effect = _make_http_error()

    result = inject(records, client, project_id=1)

    assert result.created == 0
    assert result.failed == 3


def test_inject_skips_failed_artifacts_and_continues():
    """inject() should skip failed POSTs and continue processing remaining records."""
    records = _make_task_records(6)
    client = MagicMock()
    # Fail on indices 1, 4; succeed on 0, 2, 3, 5
    client.post.side_effect = [
        MagicMock(),          # index 0: success
        _make_http_error(),   # index 1: failure
        MagicMock(),          # index 2: success
        MagicMock(),          # index 3: success
        _make_http_error(),   # index 4: failure
        MagicMock(),          # index 5: success
    ]

    result = inject(records, client, project_id=1)

    assert result.created == 4
    assert result.failed == 2
    # All 6 records were attempted
    assert client.post.call_count == 6


def test_inject_artifact_type_is_tasks():
    """inject() result should have artifact_type == 'tasks'."""
    records = _make_task_records(2)
    client = MagicMock()
    client.post.return_value = MagicMock()

    result = inject(records, client, project_id=1)

    assert result.artifact_type == "tasks"
