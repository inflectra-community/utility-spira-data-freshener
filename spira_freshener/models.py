"""Runtime and payload dataclasses for SpiraFreshener.

These models represent the data flowing through the tool at runtime:
project context fetched from Spira, artifact records produced by the
generators, the serialisable Payload, and execution options/results.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------


@dataclass
class ProjectContext:
    """Context fetched from the Spira project before generation begins.

    Raw Spira API objects are stored as plain dicts so that callers can
    access any field returned by the API without a fixed schema here.

    Key fields used by generators:
      test_cases:   TestCaseId, Name
      requirements: RequirementId, Name
      releases:     ReleaseId, Name, VersionNumber
      resources:    UserId, FullName  (active members only)
    """

    project_id: int
    test_cases: list[dict]
    requirements: list[dict]
    releases: list[dict]
    resources: list[dict]


# ---------------------------------------------------------------------------
# Artifact record models
# ---------------------------------------------------------------------------


@dataclass
class TestRunRecord:
    """A single Test Run artifact to be injected into Spira.

    execution_status_id maps to Spira numeric IDs:
      Passed=2, Failed=1, Blocked=5, Caution=6
    execution_date is an ISO 8601 UTC string, e.g. "2025-01-14T09:15:00Z".
    """

    test_case_id: int
    release_id: int
    tester_id: int
    execution_status_id: int
    execution_date: str  # ISO 8601 UTC
    name: str


@dataclass
class IncidentRecord:
    """A single Incident artifact to be injected into Spira.

    creation_date is an ISO 8601 UTC string.
    incident_type_id, priority_id, and incident_status_id are Spira
    numeric IDs looked up from the project's configured lists.
    """

    name: str
    description: str
    incident_type_id: int
    priority_id: int
    incident_status_id: int
    detected_release_id: int
    owner_id: int
    detected_by_id: int
    creation_date: str  # ISO 8601 UTC


@dataclass
class TaskRecord:
    """A single Task artifact to be injected into Spira.

    estimated_effort is stored in minutes (Spira's native unit).
    start_date and end_date are ISO 8601 date strings (no time component).
    """

    name: str
    requirement_id: int
    release_id: int
    owner_id: int
    task_status_id: int
    estimated_effort: int  # minutes
    start_date: str        # ISO 8601 date
    end_date: str          # ISO 8601 date


@dataclass
class AllocationRecord:
    """A Resource Allocation record linking a user to a release.

    availability_percentage is derived from planned hours divided by
    release duration, multiplied by 100.
    """

    user_id: int
    release_id: int
    availability_percentage: float


@dataclass
class RiskRecord:
    """A single Risk artifact to be injected into Spira.

    risk_impact_id: 1=Critical, 2=High, 3=Medium, 4=Low, 5=Very Low
    risk_probability_id: 1=Very High, 2=High, 3=Medium, 4=Low, 5=Very Low
    """

    name: str
    description: str
    risk_impact_id: int
    risk_probability_id: int
    owner_id: int
    release_id: int


@dataclass
class TimeEntryRecord:
    """A Time Entry record for actual hours worked on a Task or Incident.

    artifact_type_id: 6 = Task, 3 = Incident
    entry_date is an ISO 8601 date string (no time component).
    """

    user_id: int
    artifact_type_id: int  # 6=Task, 3=Incident
    artifact_id: int
    hours: float
    entry_date: str  # ISO 8601 date


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


@dataclass
class PayloadMetadata:
    """Metadata block included at the top of every Payload file."""

    generated_at: str  # ISO 8601 UTC timestamp
    project_id: int
    version: str       # SpiraFreshener version string, e.g. "1.0.0"


@dataclass
class Payload:
    """The complete serialisable payload produced by the Generator.

    All artifact-type lists are always present; they may be empty
    when a given artifact type was skipped due to missing project context.
    """

    metadata: PayloadMetadata
    test_runs: list[TestRunRecord] = field(default_factory=list)
    incidents: list[IncidentRecord] = field(default_factory=list)
    tasks: list[TaskRecord] = field(default_factory=list)
    resource_allocations: list[AllocationRecord] = field(default_factory=list)
    time_entries: list[TimeEntryRecord] = field(default_factory=list)
    risks: list[RiskRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Run options and injection results
# ---------------------------------------------------------------------------


@dataclass
class RunOptions:
    """Options parsed from the CLI and passed to runner.run()."""

    dry_run: bool
    output_path: str
    verbose: bool
    log_file: str | None


@dataclass
class InjectionResult:
    """Success/failure counts for a single artifact type after injection."""

    artifact_type: str
    created: int
    failed: int


@dataclass
class InjectionResults:
    """Aggregated injection results across all artifact types."""

    results: list[InjectionResult] = field(default_factory=list)
