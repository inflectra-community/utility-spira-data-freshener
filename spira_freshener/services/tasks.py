"""Task artifact generation service for SpiraFreshener.

Generates realistic Task records linked to existing Requirements, Releases,
and Resources in the target Spira project.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import requests

from spira_freshener.config import FreshenerConfig
from spira_freshener.models import InjectionResult, ProjectContext, TaskRecord

if TYPE_CHECKING:
    from spira_freshener.client import SpiraClient

logger = logging.getLogger(__name__)

# Spira numeric task status IDs
STATUS_IDS: dict[str, int] = {
    "Not Started": 1,
    "In Progress": 2,
    "Completed": 3,
    "Blocked": 4,
    "Deferred": 5,
}

# Task name templates — produce realistic-sounding task names
_NAME_TEMPLATES = [
    "Implement {feature}",
    "Fix {component} bug",
    "Refactor {component}",
    "Add unit tests for {feature}",
    "Review {feature} implementation",
    "Update {component} documentation",
    "Optimise {feature} performance",
    "Integrate {component} with {feature}",
    "Deploy {feature} to staging",
    "Investigate {component} issue",
    "Write acceptance tests for {feature}",
    "Configure {component} settings",
    "Migrate {component} to new API",
    "Validate {feature} edge cases",
    "Debug {component} error handling",
    "Design {feature} data model",
    "Code review for {feature}",
    "Set up {component} pipeline",
    "Resolve {component} merge conflict",
    "Document {feature} API endpoints",
]

_FEATURES = [
    "user authentication",
    "password reset flow",
    "dashboard widget",
    "reporting module",
    "notification service",
    "search functionality",
    "data export",
    "audit logging",
    "role-based access control",
    "API rate limiting",
    "session management",
    "email integration",
    "file upload handler",
    "payment gateway",
    "analytics pipeline",
    "caching layer",
    "background job queue",
    "webhook dispatcher",
    "multi-tenancy support",
    "dark mode UI",
]

_COMPONENTS = [
    "login page",
    "user profile",
    "database schema",
    "REST client",
    "CI/CD pipeline",
    "test harness",
    "config loader",
    "error handler",
    "middleware stack",
    "ORM layer",
    "message broker",
    "load balancer",
    "monitoring agent",
    "deployment script",
    "migration runner",
    "token validator",
    "event bus",
    "service registry",
    "health check endpoint",
    "rate limiter",
]


def _generate_task_name() -> str:
    """Return a realistic task name using a random template."""
    template = random.choice(_NAME_TEMPLATES)
    name = template.format(
        feature=random.choice(_FEATURES),
        component=random.choice(_COMPONENTS),
    )
    # Clamp to 255 characters as required by Spira
    return name[:255]


def _weighted_choice(weights: dict[str, int]) -> str:
    """Select a key from *weights* using weighted random selection."""
    population = list(weights.keys())
    cumulative_weights = list(weights.values())
    return random.choices(population, weights=cumulative_weights, k=1)[0]


def generate(
    context: ProjectContext,
    config: FreshenerConfig,
    now: datetime,
) -> list[TaskRecord]:
    """Generate a list of TaskRecord objects.

    Args:
        context: Project context fetched from Spira (requirements, releases,
            resources, etc.).
        config: Freshener configuration controlling counts, weights, and
            effort ranges.
        now: The reference datetime for the recency window.

    Returns:
        A list of exactly ``config.tasks.count`` :class:`TaskRecord` objects,
        or an empty list if any required context is missing.
    """
    if not context.requirements:
        logger.warning(
            "No Requirements found in project %d — skipping Task generation.",
            context.project_id,
        )
        return []

    if not context.releases:
        logger.warning(
            "No Releases found in project %d — skipping Task generation.",
            context.project_id,
        )
        return []

    if not context.resources:
        logger.warning(
            "No active Resources found in project %d — skipping Task generation.",
            context.project_id,
        )
        return []

    task_cfg = config.tasks
    window_start = now - timedelta(days=config.recency_window_days)

    # Total seconds in the recency window for uniform date sampling
    window_seconds = int((now - window_start).total_seconds())

    records: list[TaskRecord] = []

    for _ in range(task_cfg.count):
        # --- Start date: uniform in [now - recency_window_days, now] ---
        start_offset_seconds = random.randint(0, window_seconds)
        start_dt = window_start + timedelta(seconds=start_offset_seconds)
        start_date = start_dt.date().isoformat()

        # --- End date: uniform in [start_date, start_date + 14 days] ---
        end_offset_days = random.randint(0, 14)
        end_dt = start_dt + timedelta(days=end_offset_days)
        end_date = end_dt.date().isoformat()

        # --- Status: weighted random selection mapped to Spira numeric ID ---
        status_str = _weighted_choice(task_cfg.status_weights.weights)
        task_status_id = STATUS_IDS[status_str]

        # --- Effort: uniform in [min_effort_hours, max_effort_hours], stored in minutes ---
        effort_hours = random.uniform(task_cfg.min_effort_hours, task_cfg.max_effort_hours)
        estimated_effort = round(effort_hours * 60)

        # --- Requirement, Release, Owner: uniform random selection ---
        requirement = random.choice(context.requirements)
        release = random.choice(context.releases)
        resource = random.choice(context.resources)

        records.append(
            TaskRecord(
                name=_generate_task_name(),
                requirement_id=requirement["RequirementId"],
                release_id=release["ReleaseId"],
                owner_id=resource["UserId"],
                task_status_id=task_status_id,
                estimated_effort=estimated_effort,
                start_date=start_date,
                end_date=end_date,
            )
        )

    return records


def inject(
    records: list[TaskRecord],
    client: "SpiraClient",
    project_id: int,
) -> InjectionResult:
    """POST each TaskRecord to the Spira REST API.

    Args:
        records:    The list of TaskRecord objects to inject.
        client:     A SpiraClient instance.
        project_id: The Spira project ID to inject into.

    Returns:
        An InjectionResult with created/failed counts.
    """
    created = 0
    failed = 0

    for index, record in enumerate(records):
        body = {
            "RequirementId": record.requirement_id,
            "ReleaseId": record.release_id,
            "OwnerId": record.owner_id,
            "TaskStatusId": record.task_status_id,
            "EstimatedEffort": record.estimated_effort,
            "StartDate": record.start_date + "T00:00:00Z",
            "EndDate": record.end_date + "T00:00:00Z",
            "Name": record.name,
        }
        try:
            client.post(f"projects/{project_id}/tasks", body)
            created += 1
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.error(
                "Failed to inject task (type=task, index=%d, status=%s): %s",
                index,
                status_code,
                exc,
            )
            failed += 1

    return InjectionResult(artifact_type="tasks", created=created, failed=failed)
