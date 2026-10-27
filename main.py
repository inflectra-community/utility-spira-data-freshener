"""SpiraFreshener entry point.

Parses CLI arguments, loads environment variables and configuration,
instantiates a SpiraClient, and delegates to runner.run().

Usage
-----
    python main.py [config_file] [--dry-run] [--output PATH]
                   [--verbose] [--log-file PATH]

Environment variables (required, loaded from .env):
    SPIRA_BASE_URL   Root URL of the Spira instance.
    SPIRA_USERNAME   Spira username for API authentication.
    SPIRA_API_KEY    Spira API key (RSS token).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from spira_freshener.client import SpiraClient
from spira_freshener.config import load_config
from spira_freshener.models import RunOptions
from spira_freshener import runner


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(message)s"


def _configure_logging(verbose: bool, log_file: str | None) -> None:
    """Configure the root logger.

    Sets the log level to DEBUG when *verbose* is ``True``, INFO otherwise.
    Always adds a StreamHandler to stdout.  If *log_file* is provided, also
    adds a FileHandler; on failure logs an error to stdout and continues.

    Args:
        verbose:  When ``True``, set log level to DEBUG.
        log_file: Optional path to a log file.
    """
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(_LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler (stdout).
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Optional file handler.
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            # Log to stdout and continue — do not exit.
            print(
                f"WARNING: Could not open log file '{log_file}': {exc}. "
                "Continuing without file logging.",
                file=sys.stdout,
            )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="spira-freshener",
        description=(
            "Generate and inject demo artifacts into a Spira project."
        ),
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        default="./freshener-config.json",
        metavar="config_file",
        help="Path to the freshener-config.json file (default: ./freshener-config.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Generate artifacts but skip injection into Spira.",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help=(
            "Path for the generated payload JSON file. "
            "Defaults to output/payload_<timestamp>.json."
        ),
    )
    parser.add_argument(
        "--inject",
        metavar="PATH",
        default=None,
        help=(
            "Skip generation and inject an existing payload JSON file directly. "
            "Reads the file and POSTs each artifact to Spira."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        default=None,
        help="Write log output to this file in addition to stdout.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for SpiraFreshener."""
    parser = _build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load .env
    # ------------------------------------------------------------------
    load_dotenv()

    required_env_vars = ("SPIRA_BASE_URL", "SPIRA_USERNAME", "SPIRA_API_KEY")
    missing = [var for var in required_env_vars if not os.environ.get(var)]
    if missing:
        print(
            "ERROR: The following required environment variables are missing or blank:",
            file=sys.stderr,
        )
        for var in missing:
            print(f"  - {var}", file=sys.stderr)
        sys.exit(1)

    base_url: str = os.environ["SPIRA_BASE_URL"]
    username: str = os.environ["SPIRA_USERNAME"]
    api_key: str = os.environ["SPIRA_API_KEY"]

    # ------------------------------------------------------------------
    # Determine output path
    # ------------------------------------------------------------------
    if args.output:
        output_path = args.output
    else:
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = os.path.join("output", f"payload_{timestamp}.json")
        os.makedirs("output", exist_ok=True)

    # ------------------------------------------------------------------
    # Configure logging (before any further output)
    # ------------------------------------------------------------------
    _configure_logging(verbose=args.verbose, log_file=args.log_file)
    log = logging.getLogger(__name__)

    log.debug("Config file  : %s", args.config_file)
    log.debug("Output path  : %s", output_path)
    log.debug("Dry run      : %s", args.dry_run)

    # ------------------------------------------------------------------
    # Load config
    # ------------------------------------------------------------------
    try:
        config = load_config(args.config_file)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # CLI --dry-run overrides config dry_run field
    # ------------------------------------------------------------------
    if args.dry_run:
        config.dry_run = True

    # ------------------------------------------------------------------
    # Instantiate SpiraClient and verify connectivity
    # ------------------------------------------------------------------
    client = SpiraClient(base_url=base_url, username=username, api_key=api_key)

    log.info("Verifying connectivity to %s …", base_url)
    try:
        client.get("projects")
    except Exception as exc:
        print(f"ERROR: Cannot connect to Spira at '{base_url}': {exc}", file=sys.stderr)
        sys.exit(1)
    log.info("Connectivity check passed.")

    # ------------------------------------------------------------------
    # Inject-only mode: read an existing payload and inject it
    # ------------------------------------------------------------------
    if args.inject:
        from spira_freshener.payload import deserialise_payload
        from spira_freshener.services import incidents, risks, tasks, test_runs

        log.info("Inject-only mode: reading payload from %s", args.inject)
        try:
            payload = deserialise_payload(args.inject)
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        project_id = payload.metadata.project_id
        log.info("Injecting into project %d …", project_id)

        from spira_freshener.models import InjectionResult

        results: list[InjectionResult] = []

        if payload.test_runs:
            r = test_runs.inject(payload.test_runs, client, project_id)
            results.append(r)
            log.info("Test runs: %d created, %d failed", r.created, r.failed)

        if payload.incidents:
            r = incidents.inject(payload.incidents, client, project_id)
            results.append(r)
            log.info("Incidents: %d created, %d failed", r.created, r.failed)

        if payload.tasks:
            r = tasks.inject(payload.tasks, client, project_id)
            results.append(r)
            log.info("Tasks: %d created, %d failed", r.created, r.failed)

        if payload.risks:
            r = risks.inject(payload.risks, client, project_id)
            results.append(r)
            log.info("Risks: %d created, %d failed", r.created, r.failed)

        # Print summary
        from spira_freshener.runner import _print_summary
        _print_summary(results, dry_run=False)
        sys.exit(0)

    # ------------------------------------------------------------------
    # Build RunOptions and delegate to runner
    # ------------------------------------------------------------------
    options = RunOptions(
        dry_run=config.dry_run,
        output_path=output_path,
        verbose=args.verbose,
        log_file=args.log_file,
    )

    exit_code = runner.run(config, client, options)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
