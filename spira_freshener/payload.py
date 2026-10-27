"""Payload serialisation for SpiraFreshener.

This module converts a ``Payload`` dataclass to a JSON string (and later,
writes it to disk or reads it back).  Serialisation is intentionally kept
separate from disk I/O so that callers can obtain the JSON string without
touching the filesystem (useful for testing and for the dry-run summary).
"""

from __future__ import annotations

import dataclasses
import json

from spira_freshener.models import Payload


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _payload_to_dict(payload: Payload) -> dict:
    """Convert a ``Payload`` dataclass to a plain dict ready for JSON encoding.

    ``dataclasses.asdict()`` recursively converts every nested dataclass to a
    plain dict, which is exactly what we need here.  After conversion we
    guarantee that all five artifact-type keys are present (even when the
    corresponding lists are empty) so that downstream consumers can rely on a
    stable schema.

    Args:
        payload: The ``Payload`` instance to convert.

    Returns:
        A plain dict with the following top-level keys:
        ``metadata``, ``test_runs``, ``incidents``, ``tasks``,
        ``resource_allocations``, ``time_entries``.
    """
    raw: dict = dataclasses.asdict(payload)

    # Guarantee all five artifact-type keys are present, even if empty.
    # dataclasses.asdict() will already include them because Payload defines
    # them with default_factory=list, but we enforce it explicitly here for
    # clarity and robustness.
    artifact_keys = (
        "test_runs",
        "incidents",
        "tasks",
        "resource_allocations",
        "time_entries",
        "risks",
    )
    for key in artifact_keys:
        if key not in raw:
            raw[key] = []

    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def serialise_payload(payload: Payload) -> str:
    """Serialise a ``Payload`` dataclass to a JSON string.

    The returned string uses two-space indentation and preserves non-ASCII
    characters as-is (``ensure_ascii=False``).  All five artifact-type keys
    are always present in the output, even when their lists are empty.

    This function does **not** write to disk; use ``write_payload`` (task 9.2)
    for that.

    Args:
        payload: The ``Payload`` instance to serialise.

    Returns:
        A UTF-8-compatible JSON string representing the payload.
    """
    data = _payload_to_dict(payload)
    return json.dumps(data, indent=2, ensure_ascii=False)


def deserialise_payload(path: str) -> Payload:
    """Read a Payload JSON file and reconstruct a ``Payload`` dataclass.

    Args:
        path: Filesystem path to the JSON payload file.

    Returns:
        A ``Payload`` instance reconstructed from the file.

    Raises:
        FileNotFoundError: If the file at *path* does not exist.
        ValueError: If the file cannot be parsed as valid JSON.
    """
    import os
    from spira_freshener.models import (
        AllocationRecord,
        IncidentRecord,
        PayloadMetadata,
        RiskRecord,
        TaskRecord,
        TestRunRecord,
        TimeEntryRecord,
    )

    if not os.path.exists(path):
        raise FileNotFoundError(f"Payload file not found: '{path}'")

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data: dict = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Payload file '{path}' is not valid JSON: {exc}") from exc

    meta = data.get("metadata", {})
    metadata = PayloadMetadata(
        generated_at=meta.get("generated_at", ""),
        project_id=meta.get("project_id", 0),
        version=meta.get("version", ""),
    )

    test_runs = [
        TestRunRecord(**r) for r in data.get("test_runs", [])
    ]
    incidents = [
        IncidentRecord(**r) for r in data.get("incidents", [])
    ]
    tasks = [
        TaskRecord(**r) for r in data.get("tasks", [])
    ]
    resource_allocations = [
        AllocationRecord(**r) for r in data.get("resource_allocations", [])
    ]
    time_entries = [
        TimeEntryRecord(**r) for r in data.get("time_entries", [])
    ]
    risks_list = [
        RiskRecord(**r) for r in data.get("risks", [])
    ]

    return Payload(
        metadata=metadata,
        test_runs=test_runs,
        incidents=incidents,
        tasks=tasks,
        resource_allocations=resource_allocations,
        time_entries=time_entries,
        risks=risks_list,
    )


def write_payload(payload: Payload, path: str) -> None:
    """Serialise a ``Payload`` dataclass and write it to *path*.

    The file is written as UTF-8 JSON with two-space indentation.  If the
    parent directory does not exist it is created.  On any I/O error the
    partial file is removed before the exception is re-raised.

    Args:
        payload: The ``Payload`` instance to write.
        path:    Filesystem path for the output file.

    Raises:
        OSError: If the file cannot be written (permissions, disk full, etc.).
    """
    import os

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    json_str = serialise_payload(payload)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json_str)
    except OSError:
        # Remove partial file before propagating the error.
        try:
            os.remove(path)
        except OSError:
            pass
        raise
