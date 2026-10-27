"""Allocation and Time Entry generation and injection services.

This module handles Resource Allocation and Time Entry artifacts, which both
relate to resource/release/time tracking within a Spira project.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import requests

from spira_freshener.config import FreshenerConfig
from spira_freshener.models import (
    AllocationRecord,
    InjectionResult,
    ProjectContext,
    TimeEntryRecord,
)

if TYPE_CHECKING:
    from spira_freshener.client import SpiraClient

logger = logging.getLogger(__name__)


def generate_allocations(
    context: ProjectContext,
    config: FreshenerConfig,
) -> list[AllocationRecord]:
    """Generate one AllocationRecord per (resource, release) combination.

    Produces a cartesian product of all active resources and all releases.
    For each pair, draws planned hours uniformly from
    [config.allocations.min_allocation_hours, config.allocations.max_allocation_hours]
    and derives availability_percentage as (hours / 40.0) * 100, capped at 100.0.

    Args:
        context: Project context containing resources and releases fetched from Spira.
        config:  Freshener configuration controlling allocation hour ranges.

    Returns:
        A list of AllocationRecord objects (one per resource/release pair), or an
        empty list if resources or releases are absent (with a warning logged).
    """
    if not context.resources:
        logger.warning(
            "No active resources found in project %d — skipping Resource Allocation generation.",
            context.project_id,
        )
        return []

    if not context.releases:
        logger.warning(
            "No releases found in project %d — skipping Resource Allocation generation.",
            context.project_id,
        )
        return []

    min_hours = config.allocations.min_allocation_hours
    max_hours = config.allocations.max_allocation_hours

    records: list[AllocationRecord] = []
    for resource in context.resources:
        for release in context.releases:
            hours = random.uniform(min_hours, max_hours)
            availability_percentage = min((hours / 40.0) * 100, 100.0)
            records.append(
                AllocationRecord(
                    user_id=resource["UserId"],
                    release_id=release["ReleaseId"],
                    availability_percentage=availability_percentage,
                )
            )

    return records


def generate_time_entries(
    context: ProjectContext,
    config: FreshenerConfig,
    now: datetime,
    injected_task_ids: list[int],
    injected_incident_ids: list[int],
) -> list[TimeEntryRecord]:
    """Generate a list of TimeEntryRecord objects distributed across tasks and incidents.

    Args:
        context:               Project context containing active resources.
        config:                Freshener configuration controlling time entry counts
                               and hour ranges.
        now:                   Reference datetime for the recency window (UTC).
        injected_task_ids:     IDs of successfully injected Task artifacts.
        injected_incident_ids: IDs of successfully injected Incident artifacts.

    Returns:
        A list of ``config.allocations.time_entry_count`` TimeEntryRecord objects,
        or an empty list if there are no target artifacts or no active resources
        (with a warning logged).
    """
    all_artifact_ids = (
        [(aid, 6) for aid in injected_task_ids]
        + [(aid, 3) for aid in injected_incident_ids]
    )

    if not all_artifact_ids:
        logger.warning(
            "No injected tasks or incidents in project %d — skipping Time Entry generation.",
            context.project_id,
        )
        return []

    if not context.resources:
        logger.warning(
            "No active resources found in project %d — skipping Time Entry generation.",
            context.project_id,
        )
        return []

    alloc_cfg = config.allocations
    window_start = now - timedelta(days=config.recency_window_days)
    window_seconds = int((now - window_start).total_seconds())

    records: list[TimeEntryRecord] = []

    for _ in range(alloc_cfg.time_entry_count):
        # Draw artifact uniformly at random from the combined pool
        artifact_id, artifact_type_id = random.choice(all_artifact_ids)

        # Draw hours uniformly from [min_time_entry_hours, max_time_entry_hours]
        hours = random.uniform(alloc_cfg.min_time_entry_hours, alloc_cfg.max_time_entry_hours)

        # Draw date uniformly from [now - recency_window_days, now]
        offset_seconds = random.randint(0, window_seconds)
        entry_dt = window_start + timedelta(seconds=offset_seconds)
        entry_date = entry_dt.date().isoformat()

        # Select resource uniformly at random
        resource = random.choice(context.resources)

        records.append(
            TimeEntryRecord(
                user_id=resource["UserId"],
                artifact_type_id=artifact_type_id,
                artifact_id=artifact_id,
                hours=hours,
                entry_date=entry_date,
            )
        )

    return records


def inject_allocations(
    records: list[AllocationRecord],
    client: "SpiraClient",
    project_id: int,
) -> InjectionResult:
    """Resource allocations cannot be created via the Spira REST API v7.

    This function logs a warning and returns a zero-count result.
    """
    if records:
        logger.warning(
            "Resource allocations cannot be created via the Spira REST API. "
            "Skipping %d allocation(s). Configure allocations manually in the Spira UI.",
            len(records),
        )
    return InjectionResult(
        artifact_type="resource_allocations", created=0, failed=0
    )


def inject_time_entries(
    records: list[TimeEntryRecord],
    client: "SpiraClient",
    project_id: int,
) -> InjectionResult:
    """POST each TimeEntryRecord to the Spira REST API using the two-step flow.

    Spira requires creating a Timesheet first, then adding entries to it:
      1. POST /timesheets/new?timesheet_date=YYYY-MM-DDT00:00:00
         body: {"SubmitterUserId": user_id}  → returns RemoteTimesheet with TimesheetId
      2. POST /timesheets/entries
         body: includes TimesheetId from step 1

    Entries are grouped by (user_id, entry_date) so that each unique
    combination gets its own Timesheet.

    Args:
        records:    The list of TimeEntryRecord objects to inject.
        client:     A SpiraClient instance.
        project_id: The Spira project ID to inject into.

    Returns:
        An InjectionResult with created/failed counts.
    """
    import time
    from itertools import groupby
    from operator import attrgetter

    created = 0
    failed = 0

    # Group entries by (user_id, entry_date) — each combo needs its own timesheet
    def group_key(r: TimeEntryRecord) -> tuple[int, str]:
        return (r.user_id, r.entry_date)

    sorted_records = sorted(records, key=group_key)

    for (user_id, entry_date), group in groupby(sorted_records, key=group_key):
        entries = list(group)
        timesheet_date = f"{entry_date}T00:00:00.000"

        # Step 1: Create the timesheet (as the authenticated user)
        # Note: Spira only allows creating timesheets for the authenticated user
        try:
            timesheet_response = client.post(
                f"timesheets/new",
                body={},
                params={"timesheet_date": timesheet_date},
            )
            timesheet_id = timesheet_response.get("TimesheetId") if timesheet_response else None
            if timesheet_id is None:
                logger.error(
                    "Failed to create timesheet for user %d on %s: no TimesheetId in response",
                    user_id,
                    entry_date,
                )
                failed += len(entries)
                continue
            # Brief pause to avoid overwhelming the API
            time.sleep(1.0)
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.error(
                "Failed to create timesheet for user %d on %s (status=%s): %s",
                user_id,
                entry_date,
                status_code,
                exc,
            )
            failed += len(entries)
            continue
        except Exception as exc:
            logger.error(
                "Failed to create timesheet for user %d on %s: %s",
                user_id,
                entry_date,
                exc,
            )
            failed += len(entries)
            continue

        # Step 2: POST each entry with the TimesheetId
        for index, record in enumerate(entries):
            body = {
                "TimesheetId": timesheet_id,
                "ProjectId": project_id,
                "EntryArtifactTypeId": record.artifact_type_id,
                "ArtifactId": record.artifact_id,
                "Effort": int(record.hours * 60),
                "EffortDate": f"{record.entry_date}T00:00:00.000",
                "UserId": record.user_id,
            }
            try:
                client.post("timesheets/entries", body)
                created += 1
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
                logger.error(
                    "Failed to inject time entry (type=time_entry, user=%d, date=%s, index=%d, status=%s): %s",
                    user_id,
                    entry_date,
                    index,
                    status_code,
                    exc,
                )
                failed += 1

    return InjectionResult(
        artifact_type="time_entries", created=created, failed=failed
    )
