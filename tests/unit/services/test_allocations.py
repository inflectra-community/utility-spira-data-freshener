"""Unit tests for spira_freshener.services.allocations.generate_allocations."""

from __future__ import annotations

import pytest

from spira_freshener.config import AllocationConfig, FreshenerConfig
from spira_freshener.models import AllocationRecord, ProjectContext
from spira_freshener.services.allocations import generate_allocations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(min_hours: float = 20.0, max_hours: float = 40.0) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=1)
    cfg.allocations = AllocationConfig(
        min_allocation_hours=min_hours,
        max_allocation_hours=max_hours,
    )
    return cfg


def _make_context(
    num_resources: int = 2,
    num_releases: int = 3,
) -> ProjectContext:
    resources = [{"UserId": 100 + i, "FullName": f"User {i}"} for i in range(num_resources)]
    releases = [{"ReleaseId": 200 + i, "Name": f"Release {i}"} for i in range(num_releases)]
    return ProjectContext(
        project_id=1,
        test_cases=[],
        requirements=[],
        releases=releases,
        resources=resources,
    )


# ---------------------------------------------------------------------------
# Empty-context guard tests
# ---------------------------------------------------------------------------


def test_returns_empty_when_no_resources(caplog):
    """Should return [] and log a warning when context.resources is empty."""
    context = _make_context(num_resources=0, num_releases=3)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate_allocations(context, config)

    assert result == []
    assert any("resource" in msg.lower() for msg in caplog.messages)


def test_returns_empty_when_no_releases(caplog):
    """Should return [] and log a warning when context.releases is empty."""
    context = _make_context(num_resources=2, num_releases=0)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate_allocations(context, config)

    assert result == []
    assert any("release" in msg.lower() for msg in caplog.messages)


def test_returns_empty_when_both_empty(caplog):
    """Should return [] when both resources and releases are empty."""
    context = _make_context(num_resources=0, num_releases=0)
    config = _make_config()

    with caplog.at_level("WARNING"):
        result = generate_allocations(context, config)

    assert result == []


# ---------------------------------------------------------------------------
# Cartesian product count tests
# ---------------------------------------------------------------------------


def test_count_is_resources_times_releases():
    """Should produce exactly len(resources) * len(releases) records."""
    context = _make_context(num_resources=3, num_releases=4)
    config = _make_config()

    result = generate_allocations(context, config)

    assert len(result) == 3 * 4


def test_count_single_resource_single_release():
    """Should produce exactly 1 record for 1 resource and 1 release."""
    context = _make_context(num_resources=1, num_releases=1)
    config = _make_config()

    result = generate_allocations(context, config)

    assert len(result) == 1


def test_count_many_resources_one_release():
    """Should produce exactly N records for N resources and 1 release."""
    context = _make_context(num_resources=5, num_releases=1)
    config = _make_config()

    result = generate_allocations(context, config)

    assert len(result) == 5


# ---------------------------------------------------------------------------
# Record field correctness tests
# ---------------------------------------------------------------------------


def test_all_records_are_allocation_records():
    """All returned items should be AllocationRecord instances."""
    context = _make_context(num_resources=2, num_releases=2)
    config = _make_config()

    result = generate_allocations(context, config)

    assert all(isinstance(r, AllocationRecord) for r in result)


def test_user_ids_come_from_resources():
    """user_id on each record should be a UserId from context.resources."""
    context = _make_context(num_resources=3, num_releases=2)
    config = _make_config()
    valid_user_ids = {r["UserId"] for r in context.resources}

    result = generate_allocations(context, config)

    for record in result:
        assert record.user_id in valid_user_ids


def test_release_ids_come_from_releases():
    """release_id on each record should be a ReleaseId from context.releases."""
    context = _make_context(num_resources=2, num_releases=3)
    config = _make_config()
    valid_release_ids = {r["ReleaseId"] for r in context.releases}

    result = generate_allocations(context, config)

    for record in result:
        assert record.release_id in valid_release_ids


def test_all_resource_release_pairs_covered():
    """Every (UserId, ReleaseId) pair should appear exactly once."""
    context = _make_context(num_resources=2, num_releases=3)
    config = _make_config()
    expected_pairs = {
        (r["UserId"], rel["ReleaseId"])
        for r in context.resources
        for rel in context.releases
    }

    result = generate_allocations(context, config)
    actual_pairs = {(rec.user_id, rec.release_id) for rec in result}

    assert actual_pairs == expected_pairs


# ---------------------------------------------------------------------------
# Availability percentage derivation tests
# ---------------------------------------------------------------------------


def test_availability_percentage_within_bounds():
    """availability_percentage should be in (0, 100] for any valid hour range."""
    context = _make_context(num_resources=2, num_releases=2)
    config = _make_config(min_hours=20.0, max_hours=40.0)

    result = generate_allocations(context, config)

    for record in result:
        assert 0.0 < record.availability_percentage <= 100.0


def test_availability_percentage_capped_at_100():
    """When hours > 40, availability_percentage should be capped at 100.0."""
    context = _make_context(num_resources=1, num_releases=1)
    # Force hours to always be 80 (200% of 40h week) by setting min == max
    config = _make_config(min_hours=80.0, max_hours=80.0)

    result = generate_allocations(context, config)

    assert len(result) == 1
    assert result[0].availability_percentage == 100.0


def test_availability_percentage_exact_40_hours():
    """When hours == 40, availability_percentage should be exactly 100.0."""
    context = _make_context(num_resources=1, num_releases=1)
    config = _make_config(min_hours=40.0, max_hours=40.0)

    result = generate_allocations(context, config)

    assert len(result) == 1
    assert result[0].availability_percentage == 100.0


def test_availability_percentage_20_hours():
    """When hours == 20, availability_percentage should be exactly 50.0."""
    context = _make_context(num_resources=1, num_releases=1)
    config = _make_config(min_hours=20.0, max_hours=20.0)

    result = generate_allocations(context, config)

    assert len(result) == 1
    assert result[0].availability_percentage == pytest.approx(50.0)


def test_availability_percentage_derived_from_hours():
    """availability_percentage should equal (hours / 40.0) * 100 for hours <= 40."""
    context = _make_context(num_resources=1, num_releases=1)
    # Use a fixed value to make the derivation deterministic
    config = _make_config(min_hours=30.0, max_hours=30.0)

    result = generate_allocations(context, config)

    assert len(result) == 1
    expected = (30.0 / 40.0) * 100
    assert result[0].availability_percentage == pytest.approx(expected)
