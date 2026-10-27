"""Configuration dataclasses for SpiraFreshener.

These models represent the structure of the freshener-config.json file and
are used throughout the tool to control artifact generation behaviour.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StatusWeights:
    """Weighted distribution for a set of status strings.

    The values in the weights dict must each be >= 0 and must sum to 100.
    """

    weights: dict[str, int]


@dataclass
class TestRunConfig:
    """Configuration for Test Run generation."""

    count: int = 20  # valid range: 1–10,000
    status_weights: StatusWeights = field(
        default_factory=lambda: StatusWeights(
            {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}
        )
    )


@dataclass
class IncidentConfig:
    """Configuration for Incident generation."""

    count: int = 10  # valid range: 1–1,000
    types: list[str] = field(
        default_factory=lambda: ["Bug", "Enhancement", "Issue", "Risk"]
    )
    priority_weights: StatusWeights = field(
        default_factory=lambda: StatusWeights(
            {"Critical": 10, "High": 25, "Medium": 45, "Low": 20}
        )
    )
    statuses: list[str] = field(
        default_factory=lambda: ["Open", "In Progress", "Resolved", "Closed"]
    )


@dataclass
class TaskConfig:
    """Configuration for Task generation."""

    count: int = 10  # valid range: 1–1,000
    status_weights: StatusWeights = field(
        default_factory=lambda: StatusWeights(
            {
                "Not Started": 20,
                "In Progress": 40,
                "Completed": 25,
                "Blocked": 10,
                "Deferred": 5,
            }
        )
    )
    min_effort_hours: float = 1.0   # >= 0.5
    max_effort_hours: float = 16.0  # <= 200


@dataclass
class AllocationConfig:
    """Configuration for Resource Allocation and Time Entry generation."""

    min_allocation_hours: float = 20.0
    max_allocation_hours: float = 40.0
    time_entry_count: int = 20       # valid range: 1–5,000
    min_time_entry_hours: float = 0.5
    max_time_entry_hours: float = 8.0


@dataclass
class RiskConfig:
    """Configuration for Risk generation."""

    count: int = 5  # valid range: 1–1,000
    impact_weights: StatusWeights = field(
        default_factory=lambda: StatusWeights(
            {"Critical": 10, "High": 25, "Medium": 40, "Low": 20, "Very Low": 5}
        )
    )
    probability_weights: StatusWeights = field(
        default_factory=lambda: StatusWeights(
            {"Very High": 5, "High": 20, "Medium": 40, "Low": 25, "Very Low": 10}
        )
    )


@dataclass
class FreshenerConfig:
    """Top-level configuration for a SpiraFreshener execution.

    Corresponds directly to the structure of freshener-config.json.
    """

    project_id: int
    recency_window_days: int = 30  # valid range: 1–365
    release_id: int | None = None  # optional: pin all artifacts to this release
    dry_run: bool = False
    test_runs: TestRunConfig = field(default_factory=TestRunConfig)
    incidents: IncidentConfig = field(default_factory=IncidentConfig)
    tasks: TaskConfig = field(default_factory=TaskConfig)
    allocations: AllocationConfig = field(default_factory=AllocationConfig)
    risks: RiskConfig = field(default_factory=RiskConfig)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_TEST_RUN_STATUSES = {"Passed", "Failed", "Blocked", "Caution"}
_VALID_INCIDENT_PRIORITIES = {"Critical", "High", "Medium", "Low"}
_VALID_TASK_STATUSES = {"Not Started", "In Progress", "Completed", "Blocked", "Deferred"}
_VALID_RISK_IMPACTS = {"Critical", "High", "Medium", "Low", "Very Low"}
_VALID_RISK_PROBABILITIES = {"Very High", "High", "Medium", "Low", "Very Low"}


def _validate_status_weights(
    weights: Any,
    field_path: str,
    valid_keys: set[str],
    errors: list[str],
) -> StatusWeights | None:
    """Validate a status_weights / priority_weights dict.

    Checks:
    - Must be a dict
    - Keys must be a subset of *valid_keys*
    - Each value must be an integer >= 0
    - All values must sum to 100
    """
    if not isinstance(weights, dict):
        errors.append(f"{field_path}: must be an object (dict), got {type(weights).__name__}")
        return None

    bad_keys = set(weights.keys()) - valid_keys
    if bad_keys:
        errors.append(
            f"{field_path}: unrecognised keys {sorted(bad_keys)}; "
            f"allowed keys are {sorted(valid_keys)}"
        )

    for key, val in weights.items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            errors.append(f"{field_path}.{key}: must be a number, got {type(val).__name__}")
        elif val < 0:
            errors.append(f"{field_path}.{key}: must be >= 0, got {val}")

    total = sum(v for v in weights.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
    if total != 100:
        errors.append(f"{field_path}: weights must sum to 100, got {total}")

    if errors:
        return None
    return StatusWeights({k: int(v) for k, v in weights.items()})


def _validate_string_list(
    value: Any,
    field_path: str,
    errors: list[str],
) -> list[str] | None:
    """Validate a list of 1–20 non-empty strings."""
    if not isinstance(value, list):
        errors.append(f"{field_path}: must be a list, got {type(value).__name__}")
        return None
    if not (1 <= len(value) <= 20):
        errors.append(f"{field_path}: must contain 1–20 items, got {len(value)}")
    bad = [i for i, s in enumerate(value) if not isinstance(s, str) or not s.strip()]
    if bad:
        errors.append(f"{field_path}: items at indices {bad} are not non-empty strings")
    if errors:
        return None
    return [str(s) for s in value]


def _require_int_in_range(
    value: Any,
    field_path: str,
    lo: int,
    hi: int,
    errors: list[str],
) -> int | None:
    """Validate that *value* is an integer in [lo, hi]."""
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{field_path}: must be an integer, got {type(value).__name__}")
        return None
    if not (lo <= value <= hi):
        errors.append(f"{field_path}: must be in [{lo}, {hi}], got {value}")
        return None
    return value


def _require_float_ge(
    value: Any,
    field_path: str,
    minimum: float,
    errors: list[str],
) -> float | None:
    """Validate that *value* is a number >= *minimum*."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field_path}: must be a number, got {type(value).__name__}")
        return None
    fval = float(value)
    if fval < minimum:
        errors.append(f"{field_path}: must be >= {minimum}, got {fval}")
        return None
    return fval


def _require_float_le(
    value: Any,
    field_path: str,
    maximum: float,
    errors: list[str],
) -> float | None:
    """Validate that *value* is a number <= *maximum*."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field_path}: must be a number, got {type(value).__name__}")
        return None
    fval = float(value)
    if fval > maximum:
        errors.append(f"{field_path}: must be <= {maximum}, got {fval}")
        return None
    return fval


def _require_float_gt(
    value: Any,
    field_path: str,
    minimum: float,
    errors: list[str],
) -> float | None:
    """Validate that *value* is a number > *minimum*."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field_path}: must be a number, got {type(value).__name__}")
        return None
    fval = float(value)
    if fval <= minimum:
        errors.append(f"{field_path}: must be > {minimum}, got {fval}")
        return None
    return fval


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_test_runs(data: dict, errors: list[str]) -> TestRunConfig:
    """Parse and validate the ``test_runs`` section, returning a TestRunConfig."""
    count = _require_int_in_range(data.get("count", 20), "test_runs.count", 1, 10000, errors)
    raw_weights = data.get(
        "status_weights",
        {"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10},
    )
    sw = _validate_status_weights(raw_weights, "test_runs.status_weights", _VALID_TEST_RUN_STATUSES, errors)
    return TestRunConfig(
        count=count if count is not None else 20,
        status_weights=sw if sw is not None else StatusWeights({"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}),
    )


def _parse_incidents(data: dict, errors: list[str]) -> IncidentConfig:
    """Parse and validate the ``incidents`` section, returning an IncidentConfig."""
    count = _require_int_in_range(data.get("count", 10), "incidents.count", 1, 1000, errors)

    raw_types = data.get("types", ["Bug", "Enhancement", "Issue", "Risk"])
    types = _validate_string_list(raw_types, "incidents.types", errors)

    raw_pw = data.get(
        "priority_weights",
        {"Critical": 10, "High": 25, "Medium": 45, "Low": 20},
    )
    pw = _validate_status_weights(raw_pw, "incidents.priority_weights", _VALID_INCIDENT_PRIORITIES, errors)

    raw_statuses = data.get("statuses", ["Open", "In Progress", "Resolved", "Closed"])
    statuses = _validate_string_list(raw_statuses, "incidents.statuses", errors)

    return IncidentConfig(
        count=count if count is not None else 10,
        types=types if types is not None else ["Bug", "Enhancement", "Issue", "Risk"],
        priority_weights=pw if pw is not None else StatusWeights({"Critical": 10, "High": 25, "Medium": 45, "Low": 20}),
        statuses=statuses if statuses is not None else ["Open", "In Progress", "Resolved", "Closed"],
    )


def _parse_tasks(data: dict, errors: list[str]) -> TaskConfig:
    """Parse and validate the ``tasks`` section, returning a TaskConfig."""
    count = _require_int_in_range(data.get("count", 10), "tasks.count", 1, 1000, errors)

    raw_sw = data.get(
        "status_weights",
        {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5},
    )
    sw = _validate_status_weights(raw_sw, "tasks.status_weights", _VALID_TASK_STATUSES, errors)

    min_effort = _require_float_ge(data.get("min_effort_hours", 1.0), "tasks.min_effort_hours", 0.5, errors)
    max_effort = _require_float_le(data.get("max_effort_hours", 16.0), "tasks.max_effort_hours", 200.0, errors)

    # Cross-field: max_effort_hours must be >= min_effort_hours
    if min_effort is not None and max_effort is not None and max_effort < min_effort:
        errors.append(
            f"tasks.max_effort_hours: must be >= tasks.min_effort_hours "
            f"({min_effort}), got {max_effort}"
        )

    return TaskConfig(
        count=count if count is not None else 10,
        status_weights=sw if sw is not None else StatusWeights(
            {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5}
        ),
        min_effort_hours=min_effort if min_effort is not None else 1.0,
        max_effort_hours=max_effort if max_effort is not None else 16.0,
    )


def _parse_allocations(data: dict, errors: list[str]) -> AllocationConfig:
    """Parse and validate the ``allocations`` section, returning an AllocationConfig."""
    time_entry_count = _require_int_in_range(
        data.get("time_entry_count", 20), "allocations.time_entry_count", 1, 5000, errors
    )

    min_alloc = _require_float_gt(
        data.get("min_allocation_hours", 20.0), "allocations.min_allocation_hours", 0.0, errors
    )
    max_alloc = _require_float_gt(
        data.get("max_allocation_hours", 40.0), "allocations.max_allocation_hours", 0.0, errors
    )

    # Cross-field: min_allocation_hours must be <= max_allocation_hours
    if min_alloc is not None and max_alloc is not None and min_alloc > max_alloc:
        errors.append(
            f"allocations.min_allocation_hours: must be <= allocations.max_allocation_hours "
            f"({max_alloc}), got {min_alloc}"
        )

    min_te = _require_float_ge(
        data.get("min_time_entry_hours", 0.5), "allocations.min_time_entry_hours", 0.5, errors
    )
    max_te = _require_float_le(
        data.get("max_time_entry_hours", 8.0), "allocations.max_time_entry_hours", 24.0, errors
    )

    # Cross-field: min_time_entry_hours must be <= max_time_entry_hours
    if min_te is not None and max_te is not None and min_te > max_te:
        errors.append(
            f"allocations.min_time_entry_hours: must be <= allocations.max_time_entry_hours "
            f"({max_te}), got {min_te}"
        )

    return AllocationConfig(
        time_entry_count=time_entry_count if time_entry_count is not None else 20,
        min_allocation_hours=min_alloc if min_alloc is not None else 20.0,
        max_allocation_hours=max_alloc if max_alloc is not None else 40.0,
        min_time_entry_hours=min_te if min_te is not None else 0.5,
        max_time_entry_hours=max_te if max_te is not None else 8.0,
    )


def _parse_risks(data: dict, errors: list[str]) -> RiskConfig:
    """Parse and validate the ``risks`` section, returning a RiskConfig."""
    count = _require_int_in_range(data.get("count", 5), "risks.count", 1, 1000, errors)

    raw_impact = data.get(
        "impact_weights",
        {"Critical": 10, "High": 25, "Medium": 40, "Low": 20, "Very Low": 5},
    )
    iw = _validate_status_weights(raw_impact, "risks.impact_weights", _VALID_RISK_IMPACTS, errors)

    raw_prob = data.get(
        "probability_weights",
        {"Very High": 5, "High": 20, "Medium": 40, "Low": 25, "Very Low": 10},
    )
    pw = _validate_status_weights(raw_prob, "risks.probability_weights", _VALID_RISK_PROBABILITIES, errors)

    return RiskConfig(
        count=count if count is not None else 5,
        impact_weights=iw if iw is not None else StatusWeights(
            {"Critical": 10, "High": 25, "Medium": 40, "Low": 20, "Very Low": 5}
        ),
        probability_weights=pw if pw is not None else StatusWeights(
            {"Very High": 5, "High": 20, "Medium": 40, "Low": 25, "Very Low": 10}
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: str) -> FreshenerConfig:
    """Load and validate a SpiraFreshener config file.

    Args:
        path: Filesystem path to the JSON config file.

    Returns:
        A fully populated :class:`FreshenerConfig` instance.

    Raises:
        FileNotFoundError: If the file at *path* does not exist.
        ValueError: If the file cannot be parsed as JSON, or if any field
            violates its documented constraint.
    """
    # --- File existence ---
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: '{path}'"
        )

    # --- JSON parsing ---
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw: Any = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Config file '{path}' is not valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"Config file '{path}' must contain a JSON object at the top level"
        )

    errors: list[str] = []

    # --- project_id (required, positive integer) ---
    project_id_raw = raw.get("project_id")
    if project_id_raw is None:
        errors.append("project_id: required field is missing")
        project_id = 0  # placeholder; will not be used if errors are raised
    elif not isinstance(project_id_raw, int) or isinstance(project_id_raw, bool):
        errors.append(f"project_id: must be a positive integer, got {type(project_id_raw).__name__}")
        project_id = 0
    elif project_id_raw <= 0:
        errors.append(f"project_id: must be a positive integer, got {project_id_raw}")
        project_id = 0
    else:
        project_id = project_id_raw

    # --- recency_window_days (optional, integer in [1, 365]) ---
    recency_raw = raw.get("recency_window_days", 30)
    recency = _require_int_in_range(recency_raw, "recency_window_days", 1, 365, errors)

    # --- release_id (optional, positive integer or null) ---
    release_id_raw = raw.get("release_id")
    release_id: int | None = None
    if release_id_raw is not None:
        if not isinstance(release_id_raw, int) or isinstance(release_id_raw, bool):
            errors.append(f"release_id: must be a positive integer or null, got {type(release_id_raw).__name__}")
        elif release_id_raw <= 0:
            errors.append(f"release_id: must be a positive integer, got {release_id_raw}")
        else:
            release_id = release_id_raw

    # --- dry_run (optional bool, default False) ---
    dry_run_raw = raw.get("dry_run", False)
    if not isinstance(dry_run_raw, bool):
        errors.append(f"dry_run: must be a boolean, got {type(dry_run_raw).__name__}")
        dry_run = False
    else:
        dry_run = dry_run_raw

    # --- Section: test_runs ---
    test_runs_raw = raw.get("test_runs", {})
    if not isinstance(test_runs_raw, dict):
        errors.append(f"test_runs: must be an object, got {type(test_runs_raw).__name__}")
        test_runs_raw = {}
    test_runs_cfg = _parse_test_runs(test_runs_raw, errors)

    # --- Section: incidents ---
    incidents_raw = raw.get("incidents", {})
    if not isinstance(incidents_raw, dict):
        errors.append(f"incidents: must be an object, got {type(incidents_raw).__name__}")
        incidents_raw = {}
    incidents_cfg = _parse_incidents(incidents_raw, errors)

    # --- Section: tasks ---
    tasks_raw = raw.get("tasks", {})
    if not isinstance(tasks_raw, dict):
        errors.append(f"tasks: must be an object, got {type(tasks_raw).__name__}")
        tasks_raw = {}
    tasks_cfg = _parse_tasks(tasks_raw, errors)

    # --- Section: allocations ---
    allocations_raw = raw.get("allocations", {})
    if not isinstance(allocations_raw, dict):
        errors.append(f"allocations: must be an object, got {type(allocations_raw).__name__}")
        allocations_raw = {}
    allocations_cfg = _parse_allocations(allocations_raw, errors)

    # --- Section: risks ---
    risks_raw = raw.get("risks", {})
    if not isinstance(risks_raw, dict):
        errors.append(f"risks: must be an object, got {type(risks_raw).__name__}")
        risks_raw = {}
    risks_cfg = _parse_risks(risks_raw, errors)

    # --- Raise if any validation errors were collected ---
    if errors:
        bullet_list = "\n  - ".join(errors)
        raise ValueError(
            f"Config file '{path}' has {len(errors)} validation error(s):\n  - {bullet_list}"
        )

    return FreshenerConfig(
        project_id=project_id,
        recency_window_days=recency if recency is not None else 30,
        release_id=release_id,
        dry_run=dry_run,
        test_runs=test_runs_cfg,
        incidents=incidents_cfg,
        tasks=tasks_cfg,
        allocations=allocations_cfg,
        risks=risks_cfg,
    )
