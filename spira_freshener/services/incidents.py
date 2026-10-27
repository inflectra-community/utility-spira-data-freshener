"""Incident generation service for SpiraFreshener.

Generates realistic IncidentRecord objects from project context and config.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import requests

from spira_freshener.models import IncidentRecord, InjectionResult, ProjectContext
from spira_freshener.config import FreshenerConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority ID mapping (placeholder IDs used at generation time)
# ---------------------------------------------------------------------------

PRIORITY_IDS: dict[str, int] = {
    "Critical": 1,
    "High": 2,
    "Medium": 3,
    "Low": 4,
}

# ---------------------------------------------------------------------------
# Name and description templates
# ---------------------------------------------------------------------------

_NAME_TEMPLATES = [
    "{type}: {component} {issue}",
    "{type} in {component} — {issue}",
    "[{type}] {component} {issue}",
    "{component} {issue} ({type})",
    "{type}: {issue} when using {component}",
]

_COMPONENTS = [
    "Login page",
    "Dashboard",
    "User profile",
    "Search module",
    "Reporting engine",
    "API gateway",
    "Notification service",
    "File upload handler",
    "Authentication service",
    "Data export feature",
    "Settings panel",
    "Admin console",
    "Payment module",
    "Email integration",
    "Audit log viewer",
]

_ISSUES = [
    "throws 500 on empty input",
    "returns incorrect results",
    "fails silently under load",
    "does not validate input correctly",
    "causes session timeout unexpectedly",
    "displays stale data after refresh",
    "crashes on special characters",
    "ignores user permissions",
    "leaks memory over time",
    "produces duplicate records",
    "fails on concurrent requests",
    "does not handle null values",
    "breaks pagination logic",
    "sends incorrect HTTP status codes",
    "does not log errors properly",
]

_DESCRIPTION_TEMPLATES = [
    (
        "Reproducible on {browser}. Steps to reproduce:\n"
        "1. Navigate to {component}.\n"
        "2. {action}.\n"
        "3. Observe that {observation}.\n\n"
        "Expected: {expected}.\n"
        "Actual: {actual}."
    ),
    (
        "This {type_lower} was identified during {phase} testing.\n\n"
        "Component: {component}\n"
        "Severity: {severity}\n\n"
        "Description:\n{observation}. "
        "This occurs consistently when {action_lower}. "
        "{expected}."
    ),
    (
        "Summary: {component} {issue_lower}.\n\n"
        "Steps:\n"
        "- {action}.\n"
        "- {observation}.\n\n"
        "Impact: {impact}. "
        "Workaround: {workaround}."
    ),
]

_BROWSERS = ["Chrome 120", "Firefox 121", "Safari 17", "Edge 119", "Chrome 119"]

_ACTIONS = [
    "Submit the form with an empty required field",
    "Click the Save button rapidly twice",
    "Navigate away and return to the page",
    "Enter a value exceeding 255 characters",
    "Log in with a newly created account",
    "Filter results by date range",
    "Export data to CSV format",
    "Upload a file larger than 10 MB",
    "Switch between user roles",
    "Trigger a concurrent API request",
]

_OBSERVATIONS = [
    "the application throws an unhandled exception",
    "the page displays a blank screen",
    "the data is not saved correctly",
    "an incorrect error message is shown",
    "the operation completes but produces wrong output",
    "the UI becomes unresponsive",
    "the request times out after 30 seconds",
    "duplicate entries appear in the list",
    "the user is redirected to an unexpected page",
    "the system logs an error but shows success to the user",
]

_EXPECTED_OUTCOMES = [
    "The operation should complete successfully with a confirmation message",
    "The system should validate input and display a helpful error",
    "The data should be persisted and reflected immediately",
    "The user should remain on the current page",
    "The API should return HTTP 200 with the correct payload",
]

_ACTUAL_OUTCOMES = [
    "An HTTP 500 error is returned instead",
    "The page goes blank with no error message",
    "The record is saved with incorrect values",
    "The user is logged out unexpectedly",
    "A generic error message is displayed",
]

_PHASES = ["regression", "exploratory", "integration", "smoke", "acceptance"]
_SEVERITIES = ["High", "Medium", "Low", "Critical"]
_IMPACTS = [
    "Affects all users in the affected module",
    "Blocks the release of the current sprint",
    "Causes data inconsistency in reports",
    "Prevents users from completing key workflows",
    "Degrades performance for concurrent users",
]
_WORKAROUNDS = [
    "Refresh the page and retry",
    "Use the legacy interface as a temporary measure",
    "Clear browser cache and cookies",
    "Perform the operation in smaller batches",
    "No known workaround at this time",
]


def _generate_name(incident_type: str) -> str:
    """Generate a realistic incident name (1–255 chars)."""
    template = random.choice(_NAME_TEMPLATES)
    component = random.choice(_COMPONENTS)
    issue = random.choice(_ISSUES)
    name = template.format(type=incident_type, component=component, issue=issue)
    # Clamp to 255 characters
    return name[:255]


def _generate_description(incident_type: str) -> str:
    """Generate a realistic incident description (1–2000 chars)."""
    template = random.choice(_DESCRIPTION_TEMPLATES)
    component = random.choice(_COMPONENTS)
    action = random.choice(_ACTIONS)
    observation = random.choice(_OBSERVATIONS)
    expected = random.choice(_EXPECTED_OUTCOMES)
    actual = random.choice(_ACTUAL_OUTCOMES)
    issue = random.choice(_ISSUES)

    description = template.format(
        browser=random.choice(_BROWSERS),
        component=component,
        action=action,
        observation=observation,
        expected=expected,
        actual=actual,
        type_lower=incident_type.lower(),
        phase=random.choice(_PHASES),
        severity=random.choice(_SEVERITIES),
        issue_lower=issue.lower(),
        action_lower=action.lower(),
        impact=random.choice(_IMPACTS),
        workaround=random.choice(_WORKAROUNDS),
    )
    # Clamp to 2000 characters
    return description[:2000]


def generate(
    context: ProjectContext,
    config: FreshenerConfig,
    now: datetime,
) -> list[IncidentRecord]:
    """Generate a list of IncidentRecord objects.

    Args:
        context: Project context fetched from Spira (releases, resources, etc.).
        config: FreshenerConfig controlling counts, types, weights, etc.
        now: The reference datetime for the recency window (UTC).

    Returns:
        A list of exactly ``config.incidents.count`` IncidentRecord objects,
        or an empty list if context is missing required data.
    """
    if not context.releases:
        logger.warning(
            "No releases found in project %d — skipping Incident generation.",
            context.project_id,
        )
        return []

    if not context.resources:
        logger.warning(
            "No active resources found in project %d — skipping Incident generation.",
            context.project_id,
        )
        return []

    incident_cfg = config.incidents
    count = incident_cfg.count
    window_start = now - timedelta(days=config.recency_window_days)

    # Build weighted priority selection lists
    priority_names = list(incident_cfg.priority_weights.weights.keys())
    priority_weights_values = list(incident_cfg.priority_weights.weights.values())

    # Build status index mapping: status name → placeholder ID (index + 1)
    statuses = incident_cfg.statuses

    records: list[IncidentRecord] = []

    for _ in range(count):
        # --- Creation date: uniform random in [window_start, now] ---
        window_seconds = int((now - window_start).total_seconds())
        offset_seconds = random.randint(0, window_seconds)
        creation_dt = window_start + timedelta(seconds=offset_seconds)
        # Ensure UTC and format as ISO 8601
        creation_date = creation_dt.replace(tzinfo=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        # --- Type: uniform random from config.incidents.types ---
        incident_type = random.choice(incident_cfg.types)

        # --- Priority: weighted random from config.incidents.priority_weights ---
        priority_name = random.choices(priority_names, weights=priority_weights_values, k=1)[0]
        priority_id = PRIORITY_IDS.get(priority_name, 3)  # default Medium if unknown

        # --- Status: uniform random from config.incidents.statuses ---
        status_index = random.randrange(len(statuses))
        status_id = status_index + 1  # placeholder: index + 1

        # --- Release: uniform random from context.releases ---
        release = random.choice(context.releases)
        release_id = release["ReleaseId"]

        # --- Owner / detector: uniform random from context.resources ---
        owner = random.choice(context.resources)
        owner_id = owner["UserId"]
        detector = random.choice(context.resources)
        detector_id = detector["UserId"]

        # --- Name and description ---
        name = _generate_name(incident_type)
        description = _generate_description(incident_type)

        records.append(
            IncidentRecord(
                name=name,
                description=description,
                incident_type_id=1,  # placeholder; resolved during injection
                priority_id=priority_id,
                incident_status_id=status_id,
                detected_release_id=release_id,
                owner_id=owner_id,
                detected_by_id=detector_id,
                creation_date=creation_date,
            )
        )

    return records


def inject(
    records: list[IncidentRecord],
    client,  # SpiraClient — imported lazily to avoid circular deps
    project_id: int,
) -> InjectionResult:
    """POST each IncidentRecord to the Spira REST API.

    Args:
        records:    The list of IncidentRecord objects to inject.
        client:     A SpiraClient instance.
        project_id: The Spira project ID to inject into.

    Returns:
        An InjectionResult with created/failed counts.
    """
    created = 0
    failed = 0

    for index, record in enumerate(records):
        body = {
            "Name": record.name,
            "Description": record.description,
            "IncidentTypeId": record.incident_type_id,
            "PriorityId": record.priority_id,
            "IncidentStatusId": record.incident_status_id,
            "DetectedReleaseId": record.detected_release_id,
            "OwnerId": record.owner_id,
            "DetectedById": record.detected_by_id,
            "CreationDate": record.creation_date,
        }
        try:
            client.post(f"projects/{project_id}/incidents", body)
            created += 1
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.error(
                "incidents[%d]: HTTP %s — %s",
                index,
                status_code,
                exc,
            )
            failed += 1

    return InjectionResult(artifact_type="incidents", created=created, failed=failed)


def inject(
    records: list[IncidentRecord],
    client,  # SpiraClient — imported lazily to avoid circular deps
    project_id: int,
) -> "InjectionResult":
    """POST each IncidentRecord to the Spira REST API.

    Args:
        records:    The list of IncidentRecord objects to inject.
        client:     A SpiraClient instance.
        project_id: The Spira project ID to inject into.

    Returns:
        An InjectionResult with created/failed counts and the IDs of
        successfully created incidents.
    """
    from spira_freshener.models import InjectionResult

    created = 0
    failed = 0
    created_ids: list[int] = []

    for index, record in enumerate(records):
        body = {
            "Name": record.name,
            "Description": record.description,
            "IncidentTypeId": record.incident_type_id,
            "PriorityId": record.priority_id,
            "IncidentStatusId": record.incident_status_id,
            "DetectedReleaseId": record.detected_release_id,
            "OwnerId": record.owner_id,
            "DetectedById": record.detected_by_id,
            "CreationDate": record.creation_date,
        }
        try:
            response = client.post(f"projects/{project_id}/incidents", body)
            created += 1
            if response and isinstance(response, dict):
                incident_id = response.get("IncidentId")
                if incident_id is not None:
                    created_ids.append(incident_id)
        except Exception as exc:  # noqa: BLE001
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.error(
                "Failed to inject incident at index %d (status %s): %s",
                index,
                status_code,
                exc,
            )
            failed += 1

    result = InjectionResult(artifact_type="incidents", created=created, failed=failed)
    result.created_ids = created_ids  # type: ignore[attr-defined]
    return result
