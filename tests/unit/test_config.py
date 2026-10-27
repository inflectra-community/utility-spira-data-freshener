"""Unit tests for spira_freshener/config.py — load_config().

Requirements: 1.2, 1.4, 1.5
"""

import json

import pytest

from spira_freshener.config import (
    AllocationConfig,
    FreshenerConfig,
    IncidentConfig,
    StatusWeights,
    TaskConfig,
    TestRunConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path, data: dict) -> str:
    """Write *data* as JSON to a temp file and return its path string."""
    p = tmp_path / "freshener-config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# Full valid config dict (mirrors freshener-config.example.json)
FULL_VALID_CONFIG = {
    "project_id": 1,
    "recency_window_days": 30,
    "dry_run": False,
    "test_runs": {
        "count": 20,
        "status_weights": {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10},
    },
    "incidents": {
        "count": 10,
        "types": ["Bug", "Enhancement", "Issue", "Risk"],
        "priority_weights": {"Critical": 10, "High": 25, "Medium": 45, "Low": 20},
        "statuses": ["Open", "In Progress", "Resolved", "Closed"],
    },
    "tasks": {
        "count": 10,
        "status_weights": {
            "Not Started": 20,
            "In Progress": 40,
            "Completed": 25,
            "Blocked": 10,
            "Deferred": 5,
        },
        "min_effort_hours": 1.0,
        "max_effort_hours": 16.0,
    },
    "allocations": {
        "min_allocation_hours": 20.0,
        "max_allocation_hours": 40.0,
        "time_entry_count": 20,
        "min_time_entry_hours": 0.5,
        "max_time_entry_hours": 8.0,
    },
}


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestValidConfigLoads:
    """Valid configs should load without error and return correct values."""

    def test_full_config_returns_freshener_config(self, tmp_path):
        """Valid config with all fields loads correctly and returns FreshenerConfig."""
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)

        assert isinstance(cfg, FreshenerConfig)

    def test_full_config_project_id(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert cfg.project_id == 1

    def test_full_config_recency_window_days(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert cfg.recency_window_days == 30

    def test_full_config_dry_run(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert cfg.dry_run is False

    def test_full_config_test_runs(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert isinstance(cfg.test_runs, TestRunConfig)
        assert cfg.test_runs.count == 20
        assert cfg.test_runs.status_weights.weights == {
            "Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10
        }

    def test_full_config_incidents(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert isinstance(cfg.incidents, IncidentConfig)
        assert cfg.incidents.count == 10
        assert cfg.incidents.types == ["Bug", "Enhancement", "Issue", "Risk"]

    def test_full_config_tasks(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert isinstance(cfg.tasks, TaskConfig)
        assert cfg.tasks.count == 10
        assert cfg.tasks.min_effort_hours == 1.0
        assert cfg.tasks.max_effort_hours == 16.0

    def test_full_config_allocations(self, tmp_path):
        path = _write_config(tmp_path, FULL_VALID_CONFIG)
        cfg = load_config(path)
        assert isinstance(cfg.allocations, AllocationConfig)
        assert cfg.allocations.min_allocation_hours == 20.0
        assert cfg.allocations.max_allocation_hours == 40.0
        assert cfg.allocations.time_entry_count == 20

    def test_only_required_field_uses_defaults(self, tmp_path):
        """Valid config with only project_id uses all defaults."""
        path = _write_config(tmp_path, {"project_id": 42})
        cfg = load_config(path)

        assert cfg.project_id == 42
        assert cfg.recency_window_days == 30
        assert cfg.dry_run is False
        assert cfg.test_runs.count == 20
        assert cfg.incidents.count == 10
        assert cfg.tasks.count == 10
        assert cfg.allocations.min_allocation_hours == 20.0
        assert cfg.allocations.max_allocation_hours == 40.0


# ---------------------------------------------------------------------------
# project_id validation
# ---------------------------------------------------------------------------


class TestProjectIdValidation:
    """project_id must be a required positive integer."""

    def test_missing_project_id_raises_value_error(self, tmp_path):
        """Missing project_id raises ValueError with descriptive message."""
        path = _write_config(tmp_path, {"recency_window_days": 30})
        with pytest.raises(ValueError, match="project_id"):
            load_config(path)

    def test_project_id_zero_raises_value_error(self, tmp_path):
        """project_id = 0 raises ValueError."""
        path = _write_config(tmp_path, {"project_id": 0})
        with pytest.raises(ValueError, match="project_id"):
            load_config(path)

    def test_project_id_negative_raises_value_error(self, tmp_path):
        """project_id = -1 raises ValueError."""
        path = _write_config(tmp_path, {"project_id": -1})
        with pytest.raises(ValueError, match="project_id"):
            load_config(path)


# ---------------------------------------------------------------------------
# recency_window_days validation
# ---------------------------------------------------------------------------


class TestRecencyWindowDaysValidation:
    """recency_window_days must be an integer in [1, 365]."""

    def test_recency_window_zero_raises_value_error(self, tmp_path):
        """recency_window_days = 0 raises ValueError."""
        path = _write_config(tmp_path, {"project_id": 1, "recency_window_days": 0})
        with pytest.raises(ValueError, match="recency_window_days"):
            load_config(path)

    def test_recency_window_366_raises_value_error(self, tmp_path):
        """recency_window_days = 366 raises ValueError."""
        path = _write_config(tmp_path, {"project_id": 1, "recency_window_days": 366})
        with pytest.raises(ValueError, match="recency_window_days"):
            load_config(path)

    def test_recency_window_boundary_1_is_valid(self, tmp_path):
        path = _write_config(tmp_path, {"project_id": 1, "recency_window_days": 1})
        cfg = load_config(path)
        assert cfg.recency_window_days == 1

    def test_recency_window_boundary_365_is_valid(self, tmp_path):
        path = _write_config(tmp_path, {"project_id": 1, "recency_window_days": 365})
        cfg = load_config(path)
        assert cfg.recency_window_days == 365


# ---------------------------------------------------------------------------
# test_runs validation
# ---------------------------------------------------------------------------


class TestTestRunsValidation:
    """test_runs.count must be in [1, 10000]; status_weights must sum to 100."""

    def test_count_zero_raises_value_error(self, tmp_path):
        """test_runs.count = 0 raises ValueError."""
        data = {**FULL_VALID_CONFIG, "test_runs": {"count": 0, "status_weights": {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}}}
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="test_runs.count"):
            load_config(path)

    def test_count_10001_raises_value_error(self, tmp_path):
        """test_runs.count = 10001 raises ValueError."""
        data = {**FULL_VALID_CONFIG, "test_runs": {"count": 10001, "status_weights": {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}}}
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="test_runs.count"):
            load_config(path)

    def test_status_weights_not_summing_to_100_raises_value_error(self, tmp_path):
        """test_runs.status_weights not summing to 100 raises ValueError."""
        data = {
            **FULL_VALID_CONFIG,
            "test_runs": {
                "count": 20,
                "status_weights": {"Passed": 50, "Failed": 20, "Blocked": 10, "Caution": 10},
                # sum = 90, not 100
            },
        }
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="status_weights"):
            load_config(path)

    def test_count_boundary_1_is_valid(self, tmp_path):
        data = {**FULL_VALID_CONFIG, "test_runs": {"count": 1, "status_weights": {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}}}
        path = _write_config(tmp_path, data)
        cfg = load_config(path)
        assert cfg.test_runs.count == 1

    def test_count_boundary_10000_is_valid(self, tmp_path):
        data = {**FULL_VALID_CONFIG, "test_runs": {"count": 10000, "status_weights": {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}}}
        path = _write_config(tmp_path, data)
        cfg = load_config(path)
        assert cfg.test_runs.count == 10000


# ---------------------------------------------------------------------------
# incidents validation
# ---------------------------------------------------------------------------


class TestIncidentsValidation:
    """incidents.types must be a list of 1–20 non-empty strings."""

    def test_types_empty_list_raises_value_error(self, tmp_path):
        """incidents.types empty list raises ValueError."""
        data = {
            **FULL_VALID_CONFIG,
            "incidents": {
                **FULL_VALID_CONFIG["incidents"],
                "types": [],
            },
        }
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="incidents.types"):
            load_config(path)

    def test_types_21_items_raises_value_error(self, tmp_path):
        """incidents.types with 21 items raises ValueError."""
        data = {
            **FULL_VALID_CONFIG,
            "incidents": {
                **FULL_VALID_CONFIG["incidents"],
                "types": [f"Type{i}" for i in range(21)],
            },
        }
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="incidents.types"):
            load_config(path)

    def test_types_20_items_is_valid(self, tmp_path):
        """incidents.types with exactly 20 items is valid (boundary)."""
        data = {
            **FULL_VALID_CONFIG,
            "incidents": {
                **FULL_VALID_CONFIG["incidents"],
                "types": [f"Type{i}" for i in range(20)],
            },
        }
        path = _write_config(tmp_path, data)
        cfg = load_config(path)
        assert len(cfg.incidents.types) == 20

    def test_types_1_item_is_valid(self, tmp_path):
        """incidents.types with exactly 1 item is valid (boundary)."""
        data = {
            **FULL_VALID_CONFIG,
            "incidents": {
                **FULL_VALID_CONFIG["incidents"],
                "types": ["Bug"],
            },
        }
        path = _write_config(tmp_path, data)
        cfg = load_config(path)
        assert cfg.incidents.types == ["Bug"]


# ---------------------------------------------------------------------------
# tasks validation
# ---------------------------------------------------------------------------


class TestTasksValidation:
    """tasks.min_effort_hours must be <= tasks.max_effort_hours."""

    def test_min_effort_greater_than_max_effort_raises_value_error(self, tmp_path):
        """tasks.min_effort_hours > tasks.max_effort_hours raises ValueError."""
        data = {
            **FULL_VALID_CONFIG,
            "tasks": {
                **FULL_VALID_CONFIG["tasks"],
                "min_effort_hours": 10.0,
                "max_effort_hours": 5.0,
            },
        }
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="max_effort_hours"):
            load_config(path)

    def test_min_effort_equal_to_max_effort_is_valid(self, tmp_path):
        """tasks.min_effort_hours == tasks.max_effort_hours is valid."""
        data = {
            **FULL_VALID_CONFIG,
            "tasks": {
                **FULL_VALID_CONFIG["tasks"],
                "min_effort_hours": 8.0,
                "max_effort_hours": 8.0,
            },
        }
        path = _write_config(tmp_path, data)
        cfg = load_config(path)
        assert cfg.tasks.min_effort_hours == 8.0
        assert cfg.tasks.max_effort_hours == 8.0


# ---------------------------------------------------------------------------
# allocations validation
# ---------------------------------------------------------------------------


class TestAllocationsValidation:
    """allocations.min_allocation_hours must be <= allocations.max_allocation_hours."""

    def test_min_allocation_greater_than_max_allocation_raises_value_error(self, tmp_path):
        """allocations.min_allocation_hours > allocations.max_allocation_hours raises ValueError."""
        data = {
            **FULL_VALID_CONFIG,
            "allocations": {
                **FULL_VALID_CONFIG["allocations"],
                "min_allocation_hours": 50.0,
                "max_allocation_hours": 20.0,
            },
        }
        path = _write_config(tmp_path, data)
        with pytest.raises(ValueError, match="min_allocation_hours"):
            load_config(path)

    def test_min_allocation_equal_to_max_allocation_is_valid(self, tmp_path):
        """allocations.min_allocation_hours == allocations.max_allocation_hours is valid."""
        data = {
            **FULL_VALID_CONFIG,
            "allocations": {
                **FULL_VALID_CONFIG["allocations"],
                "min_allocation_hours": 30.0,
                "max_allocation_hours": 30.0,
            },
        }
        path = _write_config(tmp_path, data)
        cfg = load_config(path)
        assert cfg.allocations.min_allocation_hours == 30.0
        assert cfg.allocations.max_allocation_hours == 30.0


# ---------------------------------------------------------------------------
# File-level errors
# ---------------------------------------------------------------------------


class TestFileErrors:
    """File not found and invalid JSON should raise appropriate errors."""

    def test_file_not_found_raises_file_not_found_error(self, tmp_path):
        """File not found raises FileNotFoundError."""
        missing_path = str(tmp_path / "does_not_exist.json")
        with pytest.raises(FileNotFoundError):
            load_config(missing_path)

    def test_invalid_json_raises_value_error(self, tmp_path):
        """Invalid JSON raises ValueError."""
        p = tmp_path / "bad.json"
        p.write_text("{ this is not valid json }", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_config(str(p))

    def test_invalid_json_empty_file_raises_value_error(self, tmp_path):
        """Empty file (not valid JSON) raises ValueError."""
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(str(p))
