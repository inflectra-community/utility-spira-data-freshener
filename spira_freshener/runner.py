"""SpiraFreshener runner — orchestrates generation and injection phases.

This module is the single orchestration point between ``main.py`` and the
per-artifact service modules.  It has no HTTP knowledge of its own; all
network calls go through ``SpiraClient``.

Execution proceeds in two sequential phases:

1. **Generation phase** — fetch project context from Spira, call each
   service's ``generate()`` function, assemble a ``Payload`` dataclass, and
   write it to disk as JSON.

2. **Injection phase** (skipped when ``options.dry_run`` is ``True``) — POST
   each artifact to the Spira REST API via the service ``inject()`` functions,
   collect per-type success/failure counts, and print a summary report.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from spira_freshener.client import SpiraClient
from spira_freshener.config import FreshenerConfig
from spira_freshener.models import (
    InjectionResult,
    Payload,
    PayloadMetadata,
    ProjectContext,
    RunOptions,
)
from spira_freshener.payload import write_payload
from spira_freshener.services import allocations, incidents, risks, tasks, test_runs

logger = logging.getLogger(__name__)

# SpiraFreshener version embedded in every payload's metadata block.
_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Context fetch
# ---------------------------------------------------------------------------


def _fetch_context(config: FreshenerConfig, client: SpiraClient) -> ProjectContext:
    """Fetch project context from the Spira REST API.

    Retrieves Test Cases, Requirements, Releases, and active project members
    for the project identified by ``config.project_id``.

    Args:
        config: Freshener configuration (provides ``project_id``).
        client: Authenticated ``SpiraClient`` instance.

    Returns:
        A ``ProjectContext`` populated with the four lists.

    Raises:
        requests.HTTPError: If any of the four GET requests fails after
            retries are exhausted.
    """
    project_id = config.project_id

    logger.info("Fetching project context for project %d …", project_id)

    test_case_list: list[dict] = client.get(
        f"projects/{project_id}/test-cases",
        params={"starting_row": 1, "number_of_rows": 10000},
    ) or []
    logger.debug("  test cases   : %d", len(test_case_list))

    requirement_list: list[dict] = client.get(
        f"projects/{project_id}/requirements",
        params={"starting_row": 1, "number_of_rows": 10000},
    ) or []
    logger.debug("  requirements : %d", len(requirement_list))

    release_list: list[dict] = client.get(
        f"projects/{project_id}/releases",
        params={"active_only": "false"},
    ) or []

    # If a specific release_id is configured, filter to just that release
    if config.release_id is not None:
        release_list = [r for r in release_list if r.get("ReleaseId") == config.release_id]
        if not release_list:
            logger.warning(
                "Configured release_id %d not found in project %d. "
                "Falling back to all releases.",
                config.release_id,
                project_id,
            )
            release_list = client.get(
                f"projects/{project_id}/releases",
                params={"active_only": "false"},
            ) or []

    logger.debug("  releases     : %d", len(release_list))

    all_users: list[dict] = client.get(
        f"projects/{project_id}/users",
        params={"starting_row": 1, "number_of_rows": 10000},
    ) or []
    # Filter to active users only.  The Spira API returns a field called
    # "Active" (bool) or "IsActive" depending on the endpoint version; we
    # accept either.
    resource_list = [
        u for u in all_users
        if u.get("Active") is True or u.get("IsActive") is True
    ]
    logger.debug("  resources    : %d (active of %d total)", len(resource_list), len(all_users))

    return ProjectContext(
        project_id=project_id,
        test_cases=test_case_list,
        requirements=requirement_list,
        releases=release_list,
        resources=resource_list,
    )


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(results: list[InjectionResult], dry_run: bool) -> None:
    """Print a SpiraProvisioner-style injection summary to stdout.

    In dry-run mode the counts shown are the *would-inject* totals derived
    from the generated payload rather than actual API results.

    Args:
        results:  List of per-artifact-type ``InjectionResult`` objects.
        dry_run:  When ``True``, print a dry-run header instead of actuals.
    """
    separator = "=" * 60

    print(separator)
    if dry_run:
        print("  DRY RUN — would inject:")
        print(separator)
        for result in results:
            print(f"  {result.artifact_type:<25}  {result.created:>5} artifact(s)")
    else:
        print("  Injection summary:")
        print(separator)
        for result in results:
            print(
                f"  {result.artifact_type:<25}  "
                f"created: {result.created:>4}   "
                f"failed: {result.failed:>4}"
            )
    print(separator)

    if not dry_run:
        total_failed = sum(r.failed for r in results)
        if total_failed:
            print(f"  WARNING: {total_failed} artifact(s) failed to inject.")
        else:
            print("  All artifacts injected successfully.")
        print(separator)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(config: FreshenerConfig, client: SpiraClient, options: RunOptions) -> int:
    """Orchestrate the generation and injection phases.

    Phase 1 — Generation:
      1. Fetch project context (Test Cases, Requirements, Releases, Resources).
      2. Call each service ``generate()`` function.
      3. Assemble a ``Payload`` dataclass with metadata.
      4. Write the payload to ``options.output_path``.

    Phase 2 — Injection (skipped when ``options.dry_run`` is ``True``):
      1. Call each service ``inject()`` function in order.
      2. Pass the IDs of successfully created Tasks and Incidents to the
         time-entry injector.
      3. Collect ``InjectionResult`` objects.

    Finally, print a summary and return an exit code.

    Args:
        config:  Freshener configuration.
        client:  Authenticated ``SpiraClient`` instance.
        options: CLI options (dry_run, output_path, verbose, log_file).

    Returns:
        ``0`` on success, ``1`` on fatal error.
    """
    now = datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # Phase 1: Generation
    # ------------------------------------------------------------------
    logger.info("=== Phase 1: Generation ===")

    try:
        context = _fetch_context(config, client)
    except Exception as exc:
        logger.error("Failed to fetch project context: %s", exc)
        print(f"ERROR: Failed to fetch project context: {exc}", file=sys.stderr)
        return 1

    # Generate each artifact type.
    test_run_records = test_runs.generate(context, config, now)
    incident_records = incidents.generate(context, config, now)
    task_records = tasks.generate(context, config, now)
    risk_records = risks.generate(context, config, now)
    allocation_records = allocations.generate_allocations(context, config)
    # Time entries reference injected IDs; at generation time we pass empty
    # lists — the actual IDs are only known after injection.
    time_entry_records = allocations.generate_time_entries(
        context, config, now,
        injected_task_ids=[],
        injected_incident_ids=[],
    )

    logger.info(
        "Generated: %d test runs, %d incidents, %d tasks, %d risks, "
        "%d allocations, %d time entries",
        len(test_run_records),
        len(incident_records),
        len(task_records),
        len(risk_records),
        len(allocation_records),
        len(time_entry_records),
    )

    # Assemble payload.
    metadata = PayloadMetadata(
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        project_id=config.project_id,
        version=_VERSION,
    )
    payload = Payload(
        metadata=metadata,
        test_runs=test_run_records,
        incidents=incident_records,
        tasks=task_records,
        resource_allocations=allocation_records,
        time_entries=time_entry_records,
        risks=risk_records,
    )

    # Write payload to disk.
    try:
        write_payload(payload, options.output_path)
        logger.info("Payload written to: %s", options.output_path)
    except OSError as exc:
        logger.error("Failed to write payload to '%s': %s", options.output_path, exc)
        print(
            f"ERROR: Failed to write payload to '{options.output_path}': {exc}",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # Phase 2: Injection (skipped in dry-run mode)
    # ------------------------------------------------------------------
    if options.dry_run:
        logger.info("Dry-run mode — skipping injection phase.")
        # Build synthetic results from generated counts for the summary.
        dry_run_results = [
            InjectionResult("test_runs", len(test_run_records), 0),
            InjectionResult("incidents", len(incident_records), 0),
            InjectionResult("tasks", len(task_records), 0),
            InjectionResult("risks", len(risk_records), 0),
            InjectionResult("resource_allocations", len(allocation_records), 0),
            InjectionResult("time_entries", len(time_entry_records), 0),
        ]
        _print_summary(dry_run_results, dry_run=True)
        return 0

    logger.info("=== Phase 2: Injection ===")

    injection_results: list[InjectionResult] = []

    # Inject test runs.
    tr_result = test_runs.inject(test_run_records, client, config.project_id)
    injection_results.append(tr_result)
    logger.info("Test runs: %d created, %d failed", tr_result.created, tr_result.failed)

    # Inject incidents — capture created IDs for time entries.
    inc_result = incidents.inject(incident_records, client, config.project_id)
    injection_results.append(inc_result)
    logger.info("Incidents: %d created, %d failed", inc_result.created, inc_result.failed)
    injected_incident_ids: list[int] = getattr(inc_result, "created_ids", [])

    # Inject tasks — capture created IDs for time entries.
    task_result = tasks.inject(task_records, client, config.project_id)
    injection_results.append(task_result)
    logger.info("Tasks: %d created, %d failed", task_result.created, task_result.failed)
    injected_task_ids: list[int] = getattr(task_result, "created_ids", [])

    # Inject risks.
    risk_result = risks.inject(risk_records, client, config.project_id)
    injection_results.append(risk_result)
    logger.info("Risks: %d created, %d failed", risk_result.created, risk_result.failed)

    # Inject resource allocations.
    alloc_result = allocations.inject_allocations(allocation_records, client, config.project_id)
    injection_results.append(alloc_result)
    logger.info(
        "Resource allocations: %d created, %d failed",
        alloc_result.created,
        alloc_result.failed,
    )

    # Generate and inject time entries using the real injected IDs.
    real_time_entries = allocations.generate_time_entries(
        context, config, now,
        injected_task_ids=injected_task_ids,
        injected_incident_ids=injected_incident_ids,
    )
    te_result = allocations.inject_time_entries(real_time_entries, client, config.project_id)
    injection_results.append(te_result)
    logger.info(
        "Time entries: %d created, %d failed",
        te_result.created,
        te_result.failed,
    )

    _print_summary(injection_results, dry_run=False)

    # Refresh project caches so dashboard widgets reflect the new data
    logger.info("Refreshing project caches …")
    try:
        client.post(
            f"projects/{config.project_id}/refresh-caches",
            body=None,
            params={"run_async": "false"},
        )
        logger.info("Project caches refreshed.")
    except Exception as exc:
        logger.warning("Failed to refresh project caches: %s", exc)

    return 0
