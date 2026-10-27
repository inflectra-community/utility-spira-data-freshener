"""Unit tests for spira_freshener.services.test_runs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

from spira_freshener.config import FreshenerConfig, TestRunConfig, StatusWeights
from spira_freshener.models import InjectionResult, ProjectContext, TestRunRecord
from spira_freshener.services.test_runs import generate, inject


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_config(count: int = 5) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1)
    cfg.test_runs = TestRunConfig(
        count=count,
        status_weights=StatusWeights({"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}),
    )
    return cfg


def _make_context(
    num_test_cases: int = 3,
    num_releases: int = 2,
    num_resources: int = 2,
) -> ProjectContext:
    test_cases = [{"TestCaseId": 10 + i, "Name": f"TC-{i}"} for i in range(num_test_cases)]
    releases = [{"ReleaseId": 200 + i, "Name": f"Release {i}"} for i in range(num_releases)]
    resources = [{"UserId": 100 + i, "FullName": f"User {i}"} for i in range(num_resources)]
    return ProjectContext(
        project_id=1,
        test_cases=test_cases,
        requirements=[],
        releases=releases,
        resources=resources,
    )


def _make_http_error() -> requests.HTTPError:
    """Return an HTTPError with a mock response attached."""
    response = MagicMock()
    response.status_code = 500
    exc = requests.HTTPError("500 Server Error")
    exc.response = response
    return exc


# ---------------------------------------------------------------------------
# generate() — count tests
# ---------------------------------------------------------------------------


def test_generate_returns_correct_count():
    """generate() should return exactly config.test_runs.count records."""
    context = _make_context()
    config = _make_config(count=7)

    result = generate(context, config, _NOW)

    assert len(result) == 7


def test_generate_returns_all_test_run_records():
    """All returned items should be TestRunRecord instances."""
    context = _make_context()
    config = _make_config(count=4)

    result = generate(context, config, _NOW)

    assert all(isinstance(r, TestRunRecord) for r in result)


# ---------------------------------------------------------------------------
# generate() — empty-context guard tests
# ---------------------------------------------------------------------------


def test_generate_returns_empty_when_no_test_cases(caplog):
    """Should return [] and log a warning when context.test_cases is empty."""
    context = _make_context(num_test_cases=0)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate(context, config, _NOW)

    assert result == []
    assert any("test case" in msg.lower() for msg in caplog.messages)


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
# generate() — multiple runs per test case
# ---------------------------------------------------------------------------


def test_generate_allows_multiple_runs_per_test_case():
    """When count > len(test_cases), test cases should be cycled (repeats allowed)."""
    # 2 test cases, 10 runs requested — each test case must appear multiple times
    context = _make_context(num_test_cases=2)
    config = _make_config(count=10)

    result = generate(context, config, _NOW)

    assert len(result) == 10
    valid_tc_ids = {tc["TestCaseId"] for tc in context.test_cases}
    for record in result:
        assert record.test_case_id in valid_tc_ids


# ---------------------------------------------------------------------------
# inject() — count tests
# ---------------------------------------------------------------------------


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


def test_inject_returns_correct_created_count():
    """inject() should return created == len(records) when all POSTs succeed."""
    records = _make_test_run_records(5)
    client = MagicMock()
    client.post.return_value = MagicMock()

    result = inject(records, client, project_id=1)

    assert result.created == 5
    assert result.failed == 0
    assert isinstance(result, InjectionResult)


def test_inject_returns_correct_failed_count():
    """inject() should return failed == len(records) when all POSTs raise HTTPError."""
    records = _make_test_run_records(3)
    client = MagicMock()
    client.post.side_effect = _make_http_error()

    result = inject(records, client, project_id=1)

    assert result.created == 0
    assert result.failed == 3


def test_inject_skips_failed_artifacts_and_continues():
    """inject() should skip failed POSTs and continue processing remaining records."""
    records = _make_test_run_records(4)
    client = MagicMock()
    # Fail on index 1 and 3, succeed on 0 and 2
    client.post.side_effect = [
        MagicMock(),          # index 0: success
        _make_http_error(),   # index 1: failure
        MagicMock(),          # index 2: success
        _make_http_error(),   # index 3: failure
    ]

    result = inject(records, client, project_id=1)

    assert result.created == 2
    assert result.failed == 2
    # All 4 records were attempted
    assert client.post.call_count == 4


def test_inject_artifact_type_is_test_runs():
    """inject() result should have artifact_type == 'test_runs'."""
    records = _make_test_run_records(2)
    client = MagicMock()
    client.post.return_value = MagicMock()

    result = inject(records, client, project_id=1)

    assert result.artifact_type == "test_runs"
