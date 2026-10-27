"""Unit tests for spira_freshener/runner.py.

Covers:
- _fetch_context() calls the right API endpoints
- run() with dry_run=True skips all inject calls
- run() calls _print_summary after processing
- run() handles context fetch failure gracefully
- _print_summary prints per-type counts

Requirements: 3.1, 5.1, 8.3, 8.6, 8.7, 9.1, 9.2, 9.3
"""

from __future__ import annotations

import json
import os
import tempfile
from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest

from spira_freshener.config import (
    AllocationConfig,
    FreshenerConfig,
    IncidentConfig,
    StatusWeights,
    TaskConfig,
    TestRunConfig,
)
from spira_freshener.models import (
    InjectionResult,
    ProjectContext,
    RunOptions,
)
from spira_freshener.runner import _fetch_context, _print_summary, run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(count: int = 2, recency: int = 30) -> FreshenerConfig:
    cfg = FreshenerConfig(project_id=42, recency_window_days=recency)
    cfg.test_runs = TestRunConfig(
        count=count,
        status_weights=StatusWeights({"Passed": 60, "Failed": 20, "Blocked": 10, "Caution": 10}),
    )
    cfg.incidents = IncidentConfig(
        count=count,
        types=["Bug"],
        priority_weights=StatusWeights({"Critical": 10, "High": 25, "Medium": 45, "Low": 20}),
        statuses=["Open", "Closed"],
    )
    cfg.tasks = TaskConfig(
        count=count,
        status_weights=StatusWeights(
            {"Not Started": 20, "In Progress": 40, "Completed": 25, "Blocked": 10, "Deferred": 5}
        ),
        min_effort_hours=1.0,
        max_effort_hours=4.0,
    )
    cfg.allocations = AllocationConfig(
        min_allocation_hours=20.0,
        max_allocation_hours=40.0,
        time_entry_count=count,
        min_time_entry_hours=0.5,
        max_time_entry_hours=4.0,
    )
    return cfg


def _make_dry_run_options(output_path: str) -> RunOptions:
    return RunOptions(
        dry_run=True,
        output_path=output_path,
        verbose=False,
        log_file=None,
    )


def _make_live_run_options(output_path: str) -> RunOptions:
    return RunOptions(
        dry_run=False,
        output_path=output_path,
        verbose=False,
        log_file=None,
    )


def _make_mock_client_with_context() -> MagicMock:
    """Return a mock SpiraClient that returns minimal valid context."""
    client = MagicMock()

    def fake_get(path, **kwargs):
        if "test-cases" in path:
            return [{"TestCaseId": 1, "Name": "TC-1"}]
        if "requirements" in path:
            return [{"RequirementId": 1, "Name": "Req-1"}]
        if "releases" in path:
            return [{"ReleaseId": 1, "Name": "Release-1"}]
        if "users" in path:
            return [{"UserId": 1, "FullName": "User One", "Active": True}]
        return []

    client.get.side_effect = fake_get
    client.post.return_value = {"IncidentId": 99, "TaskId": 88}
    return client


# ---------------------------------------------------------------------------
# _fetch_context() tests
# ---------------------------------------------------------------------------


class TestFetchContext:
    """_fetch_context() should call the correct API endpoints."""

    def test_fetch_context_calls_test_cases_endpoint(self):
        """_fetch_context() must GET test-cases for the project."""
        client = _make_mock_client_with_context()
        config = _make_config()

        _fetch_context(config, client)

        paths_called = [str(c.args[0]) for c in client.get.call_args_list]
        assert any("test-cases" in p for p in paths_called), (
            f"test-cases endpoint not called; paths: {paths_called}"
        )

    def test_fetch_context_calls_requirements_endpoint(self):
        """_fetch_context() must GET requirements for the project."""
        client = _make_mock_client_with_context()
        config = _make_config()

        _fetch_context(config, client)

        paths_called = [str(c.args[0]) for c in client.get.call_args_list]
        assert any("requirements" in p for p in paths_called), (
            f"requirements endpoint not called; paths: {paths_called}"
        )

    def test_fetch_context_calls_releases_endpoint(self):
        """_fetch_context() must GET releases for the project."""
        client = _make_mock_client_with_context()
        config = _make_config()

        _fetch_context(config, client)

        paths_called = [str(c.args[0]) for c in client.get.call_args_list]
        assert any("releases" in p for p in paths_called), (
            f"releases endpoint not called; paths: {paths_called}"
        )

    def test_fetch_context_calls_users_endpoint(self):
        """_fetch_context() must GET project users for the project."""
        client = _make_mock_client_with_context()
        config = _make_config()

        _fetch_context(config, client)

        paths_called = [str(c.args[0]) for c in client.get.call_args_list]
        assert any("users" in p for p in paths_called), (
            f"users endpoint not called; paths: {paths_called}"
        )

    def test_fetch_context_uses_correct_project_id(self):
        """_fetch_context() must use config.project_id in all API paths."""
        client = _make_mock_client_with_context()
        config = _make_config()
        config.project_id = 99

        _fetch_context(config, client)

        paths_called = [str(c.args[0]) for c in client.get.call_args_list]
        assert all("projects/99" in p for p in paths_called), (
            f"Not all paths use project_id=99; paths: {paths_called}"
        )

    def test_fetch_context_filters_active_users_only(self):
        """_fetch_context() must filter resources to active users only."""
        client = MagicMock()

        def fake_get(path, **kwargs):
            if "test-cases" in path:
                return []
            if "requirements" in path:
                return []
            if "releases" in path:
                return []
            if "users" in path:
                return [
                    {"UserId": 1, "FullName": "Active User", "Active": True},
                    {"UserId": 2, "FullName": "Inactive User", "Active": False},
                    {"UserId": 3, "FullName": "IsActive User", "IsActive": True},
                ]
            return []

        client.get.side_effect = fake_get
        config = _make_config()

        context = _fetch_context(config, client)

        active_ids = {r["UserId"] for r in context.resources}
        assert 1 in active_ids, "Active user (Active=True) should be included"
        assert 2 not in active_ids, "Inactive user (Active=False) should be excluded"
        assert 3 in active_ids, "Active user (IsActive=True) should be included"

    def test_fetch_context_returns_project_context(self):
        """_fetch_context() must return a ProjectContext with the correct project_id."""
        client = _make_mock_client_with_context()
        config = _make_config()
        config.project_id = 7

        context = _fetch_context(config, client)

        assert context.project_id == 7
        assert isinstance(context.test_cases, list)
        assert isinstance(context.requirements, list)
        assert isinstance(context.releases, list)
        assert isinstance(context.resources, list)


# ---------------------------------------------------------------------------
# run() with dry_run=True
# ---------------------------------------------------------------------------


class TestRunDryRun:
    """run() with dry_run=True must skip all inject calls."""

    def test_dry_run_skips_test_run_inject(self):
        """dry_run=True must not call test_runs.inject."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)

            with patch("spira_freshener.runner.test_runs.inject") as mock_inject:
                run(config, client, options)
                mock_inject.assert_not_called()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_dry_run_skips_incidents_inject(self):
        """dry_run=True must not call incidents.inject."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)

            with patch("spira_freshener.runner.incidents.inject") as mock_inject:
                run(config, client, options)
                mock_inject.assert_not_called()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_dry_run_skips_tasks_inject(self):
        """dry_run=True must not call tasks.inject."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)

            with patch("spira_freshener.runner.tasks.inject") as mock_inject:
                run(config, client, options)
                mock_inject.assert_not_called()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_dry_run_skips_allocations_inject(self):
        """dry_run=True must not call allocations.inject_allocations."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)

            with patch("spira_freshener.runner.allocations.inject_allocations") as mock_inject:
                run(config, client, options)
                mock_inject.assert_not_called()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_dry_run_returns_exit_code_0(self):
        """dry_run=True must return exit code 0."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)
            exit_code = run(config, client, options)
            assert exit_code == 0
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_dry_run_writes_payload_file(self):
        """dry_run=True must still write the payload JSON file."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)
            run(config, client, options)

            assert os.path.exists(tmp_path), "Payload file should be written in dry-run mode"
            with open(tmp_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            assert "test_runs" in data
            assert "incidents" in data
            assert "tasks" in data
            assert "resource_allocations" in data
            assert "time_entries" in data
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# run() calls _print_summary
# ---------------------------------------------------------------------------


class TestRunPrintsSummary:
    """run() must call _print_summary after processing."""

    def test_dry_run_calls_print_summary(self, capsys):
        """run() with dry_run=True must print a summary to stdout."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)
            run(config, client, options)

            captured = capsys.readouterr()
            # Summary should contain artifact type names
            assert "test_runs" in captured.out or "DRY RUN" in captured.out
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_live_run_calls_print_summary(self, capsys):
        """run() without dry_run must print a summary to stdout."""
        config = _make_config()
        client = _make_mock_client_with_context()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_live_run_options(tmp_path)
            run(config, client, options)

            captured = capsys.readouterr()
            assert "test_runs" in captured.out or "Injection summary" in captured.out
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# run() handles context fetch failure gracefully
# ---------------------------------------------------------------------------


class TestRunContextFetchFailure:
    """run() must handle _fetch_context() failures gracefully."""

    def test_context_fetch_failure_returns_exit_code_1(self, capsys):
        """If _fetch_context() raises, run() must return exit code 1."""
        import requests

        config = _make_config()
        client = MagicMock()
        client.get.side_effect = requests.HTTPError("401 Unauthorized")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)
            exit_code = run(config, client, options)
            assert exit_code == 1
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_context_fetch_failure_writes_to_stderr(self, capsys):
        """If _fetch_context() raises, run() must write an error to stderr."""
        import requests

        config = _make_config()
        client = MagicMock()
        client.get.side_effect = requests.HTTPError("401 Unauthorized")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            tmp_path = fh.name

        try:
            options = _make_dry_run_options(tmp_path)
            run(config, client, options)

            captured = capsys.readouterr()
            assert "ERROR" in captured.err or len(captured.err) > 0
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# _print_summary tests
# ---------------------------------------------------------------------------


class TestPrintSummary:
    """_print_summary() must print per-type counts."""

    def test_print_summary_dry_run_shows_would_inject(self, capsys):
        """In dry-run mode, _print_summary must show 'DRY RUN' header."""
        results = [
            InjectionResult("test_runs", 5, 0),
            InjectionResult("incidents", 3, 0),
            InjectionResult("tasks", 2, 0),
            InjectionResult("resource_allocations", 4, 0),
            InjectionResult("time_entries", 10, 0),
        ]

        _print_summary(results, dry_run=True)

        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    def test_print_summary_dry_run_shows_artifact_counts(self, capsys):
        """In dry-run mode, _print_summary must show counts for each artifact type."""
        results = [
            InjectionResult("test_runs", 5, 0),
            InjectionResult("incidents", 3, 0),
        ]

        _print_summary(results, dry_run=True)

        captured = capsys.readouterr()
        assert "test_runs" in captured.out
        assert "incidents" in captured.out
        assert "5" in captured.out
        assert "3" in captured.out

    def test_print_summary_live_shows_created_and_failed(self, capsys):
        """In live mode, _print_summary must show created and failed counts."""
        results = [
            InjectionResult("test_runs", 8, 2),
            InjectionResult("incidents", 5, 1),
        ]

        _print_summary(results, dry_run=False)

        captured = capsys.readouterr()
        assert "8" in captured.out
        assert "2" in captured.out
        assert "5" in captured.out
        assert "1" in captured.out

    def test_print_summary_live_warns_on_failures(self, capsys):
        """In live mode with failures, _print_summary must print a warning."""
        results = [
            InjectionResult("test_runs", 8, 2),
        ]

        _print_summary(results, dry_run=False)

        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "failed" in captured.out.lower()

    def test_print_summary_live_success_message_when_no_failures(self, capsys):
        """In live mode with no failures, _print_summary must print a success message."""
        results = [
            InjectionResult("test_runs", 10, 0),
            InjectionResult("incidents", 5, 0),
        ]

        _print_summary(results, dry_run=False)

        captured = capsys.readouterr()
        assert "success" in captured.out.lower() or "All artifacts" in captured.out
