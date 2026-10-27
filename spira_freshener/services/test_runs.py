"""Test Run service module for SpiraFreshener.

Provides:
  generate(context, config, now) -> list[TestRunRecord]
  inject(records, client, project_id) -> InjectionResult
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from itertools import cycle

import requests

from spira_freshener.config import FreshenerConfig
from spira_freshener.models import InjectionResult, ProjectContext, TestRunRecord

logger = logging.getLogger(__name__)

# Spira numeric execution-status IDs
STATUS_IDS: dict[str, int] = {
    "Passed": 2,
    "Failed": 1,
    "Blocked": 5,
    "Caution": 6,
}


def generate(
    context: ProjectContext,
    config: FreshenerConfig,
    now: datetime,
) -> list[TestRunRecord]:
    """Generate a list of TestRunRecord objects.

    Args:
        context: Project context fetched from Spira (test cases, releases,
                 resources, etc.).
        config:  Freshener configuration controlling counts, weights, and
                 the recency window.
        now:     The reference "current" datetime (UTC).  Execution dates
                 are drawn from [now - recency_window_days, now].

    Returns:
        A list of exactly ``config.test_runs.count`` TestRunRecord objects,
        or an empty list if any required context list is empty.
    """
    project_id = context.project_id

    if not context.test_cases:
        logger.warning(
            "No test cases found in project %s, skipping test run generation",
            project_id,
        )
        return []

    if not context.releases:
        logger.warning(
            "No releases found in project %s, skipping test run generation",
            project_id,
        )
        return []

    if not context.resources:
        logger.warning(
            "No resources found in project %s, skipping test run generation",
            project_id,
        )
        return []

    count = config.test_runs.count
    recency_days = config.recency_window_days
    status_weights_map = config.test_runs.status_weights.weights

    # Prepare weighted-random status selection inputs
    status_names = list(status_weights_map.keys())
    status_weights = [status_weights_map[s] for s in status_names]

    # Cycle through test cases so repeats are allowed when count > len(test_cases)
    test_case_cycle = cycle(context.test_cases)

    records: list[TestRunRecord] = []
    for _ in range(count):
        test_case = next(test_case_cycle)
        test_case_id: int = test_case["TestCaseId"]

        # Select release and tester uniformly at random
        release = random.choice(context.releases)
        release_id: int = release["ReleaseId"]

        resource = random.choice(context.resources)
        tester_id: int = resource["UserId"]

        # Draw execution date uniformly from [now - recency_window_days, now]
        day_offset = random.randint(0, recency_days)
        execution_dt = now - timedelta(days=day_offset)
        # Format as ISO 8601 UTC string, e.g. "2025-01-14T09:15:00Z"
        execution_date = execution_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Draw execution status using weighted random selection
        chosen_status: str = random.choices(status_names, weights=status_weights, k=1)[0]
        execution_status_id: int = STATUS_IDS[chosen_status]

        name = f"Test Run for TC-{test_case_id}"

        records.append(
            TestRunRecord(
                test_case_id=test_case_id,
                release_id=release_id,
                tester_id=tester_id,
                execution_status_id=execution_status_id,
                execution_date=execution_date,
                name=name,
            )
        )

    return records


def inject(
    records: list[TestRunRecord],
    client,  # SpiraClient — imported lazily to avoid circular deps
    project_id: int,
) -> InjectionResult:
    """POST each TestRunRecord to the Spira REST API.

    Args:
        records:    The list of TestRunRecord objects to inject.
        client:     A SpiraClient instance.
        project_id: The Spira project ID to inject into.

    Returns:
        An InjectionResult with created/failed counts.
    """
    created = 0
    failed = 0

    for index, record in enumerate(records):
        body = {
            "TestCaseId": record.test_case_id,
            "ReleaseId": record.release_id,
            "TesterId": record.tester_id,
            "ExecutionStatusId": record.execution_status_id,
            "EndDate": record.execution_date,
            "Name": record.name,
            "TestRunFormatId": 1,
            "RunnerName": "SpiraFreshener",
            "RunnerTestName": record.name,
        }
        try:
            client.post(f"projects/{project_id}/test-runs/record", body)
            created += 1
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.error(
                "test_runs[%d]: HTTP %s — %s",
                index,
                status_code,
                exc,
            )
            failed += 1

    return InjectionResult(artifact_type="test_runs", created=created, failed=failed)
