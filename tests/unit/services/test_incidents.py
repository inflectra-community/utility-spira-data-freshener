"""Unit tests for spira_freshener.services.incidents."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

from spira_freshener.config import FreshenerConfig, IncidentConfig, StatusWeights
from spira_freshener.models import IncidentRecord, InjectionResult, ProjectContext
from spira_freshener.services.incidents import generate, inject


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_config(count: int = 5) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1)
    cfg.incidents = IncidentConfig(
        count=count,
        types=["Bug", "Enhancement"],
        priority_weights=StatusWeights({"Critical": 10, "High": 25, "Medium": 45, "Low": 20}),
        statuses=["Open", "In Progress", "Resolved", "Closed"],
    )
    return cfg


def _make_context(
    num_releases: int = 2,
    num_resources: int = 2,
) -> ProjectContext:
    releases = [{"ReleaseId": 200 + i, "Name": f"Release {i}"} for i in range(num_releases)]
    resources = [{"UserId": 100 + i, "FullName": f"User {i}"} for i in range(num_resources)]
    return ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=releases,
        resources=resources,
    )


def _make_http_error() -> requests.HTTPError:
    response = MagicMock()
    response.status_code = 422
    exc = requests.HTTPError("422 Unprocessable Entity")
    exc.response = response
    return exc


def _make_incident_records(n: int) -> list[IncidentRecord]:
    return [
        IncidentRecord(
            name=f"Incident {i}",
            description=f"Description for incident {i}",
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


# ---------------------------------------------------------------------------
# generate() — count tests
# ---------------------------------------------------------------------------


def test_generate_returns_correct_count():
    """generate() should return exactly config.incidents.count records."""
    context = _make_context()
    config = _make_config(count=6)

    result = generate(context, config, _NOW)

    assert len(result) == 6


def test_generate_returns_all_incident_records():
    """All returned items should be IncidentRecord instances."""
    context = _make_context()
    config = _make_config(count=3)

    result = generate(context, config, _NOW)

    assert all(isinstance(r, IncidentRecord) for r in result)


# ---------------------------------------------------------------------------
# generate() — empty-context guard tests
# ---------------------------------------------------------------------------


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
# generate() — field constraint tests
# ---------------------------------------------------------------------------


def test_generate_name_length_in_bounds():
    """All generated incident names should be between 1 and 255 characters."""
    context = _make_context()
    config = _make_config(count=20)

    result = generate(context, config, _NOW)

    for record in result:
        assert 1 <= len(record.name) <= 255, f"Name length {len(record.name)} out of bounds"


def test_generate_description_length_in_bounds():
    """All generated incident descriptions should be between 1 and 2000 characters."""
    context = _make_context()
    config = _make_config(count=20)

    result = generate(context, config, _NOW)

    for record in result:
        assert 1 <= len(record.description) <= 2000, (
            f"Description length {len(record.description)} out of bounds"
        )


# ---------------------------------------------------------------------------
# inject() — count tests
# ---------------------------------------------------------------------------


def test_inject_returns_correct_created_count():
    """inject() should return created == len(records) when all POSTs succeed."""
    records = _make_incident_records(4)
    client = MagicMock()
    client.post.return_value = MagicMock()

    result = inject(records, client, project_id=1)

    assert result.created == 4
    assert result.failed == 0
    assert isinstance(result, InjectionResult)


def test_inject_returns_correct_failed_count():
    """inject() should return failed == len(records) when all POSTs raise HTTPError."""
    records = _make_incident_records(3)
    client = MagicMock()
    client.post.side_effect = _make_http_error()

    result = inject(records, client, project_id=1)

    assert result.created == 0
    assert result.failed == 3


def test_inject_skips_failed_artifacts_and_continues():
    """inject() should skip failed POSTs and continue processing remaining records."""
    records = _make_incident_records(5)
    client = MagicMock()
    # Fail on indices 0 and 2, succeed on 1, 3, 4
    client.post.side_effect = [
        _make_http_error(),   # index 0: failure
        MagicMock(),          # index 1: success
        _make_http_error(),   # index 2: failure
        MagicMock(),          # index 3: success
        MagicMock(),          # index 4: success
    ]

    result = inject(records, client, project_id=1)

    assert result.created == 3
    assert result.failed == 2
    # All 5 records were attempted
    assert client.post.call_count == 5


def test_inject_artifact_type_is_incidents():
    """inject() result should have artifact_type == 'incidents'."""
    records = _make_incident_records(2)
    client = MagicMock()
    client.post.return_value = MagicMock()

    result = inject(records, client, project_id=1)

    assert result.artifact_type == "incidents"
