"""
Property-based tests for SpiraClient authentication and retry behaviour.

Tests:
  - Property 2: Auth params on every request
  - Property 3: Retry on transient errors
"""

from __future__ import annotations

import sys
import os

# Ensure the project root is on the path so spira_freshener can be imported.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import MagicMock, patch
from typing import Any

import pytest
import requests
import urllib3
from hypothesis import given, settings
from hypothesis import strategies as st

from spira_freshener.client import SpiraClient

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Any non-empty string that is a plausible URL path segment.
path_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/-_"),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip("/"))

method_strategy = st.sampled_from(["GET", "POST", "PUT", "DELETE"])

username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-."),
    min_size=1,
    max_size=40,
)

api_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="{}-"),
    min_size=1,
    max_size=80,
)

# ---------------------------------------------------------------------------
# Property 2: Auth params on every request
# ---------------------------------------------------------------------------
# Feature: spira-freshener, Property 2: Auth params on every request
#
# For any HTTP method (GET, POST, PUT, DELETE) and any path, the SpiraClient
# SHALL append `username` and `api-key` as query parameters on the outgoing
# request.
#
# Validates: Requirements 1.6


@given(
    method=method_strategy,
    path=path_strategy,
    username=username_strategy,
    api_key=api_key_strategy,
)
@settings(max_examples=100, deadline=None)
def test_auth_params_on_every_request(
    method: str, path: str, username: str, api_key: str
) -> None:
    """Property 2: Auth params on every request.

    **Validates: Requirements 1.6**
    """
    # Build a mock response that looks like a successful 200 JSON response.
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.content = b'{"ok": true}'
    mock_response.json.return_value = {"ok": True}

    captured_kwargs: dict[str, Any] = {}

    def fake_request(req_method: str, url: str, **kwargs: Any) -> MagicMock:
        captured_kwargs["method"] = req_method
        captured_kwargs["url"] = url
        captured_kwargs["params"] = kwargs.get("params", {})
        return mock_response

    with patch("requests.Session.request", side_effect=fake_request):
        client = SpiraClient(
            base_url="https://example.spiraservice.net/demo",
            username=username,
            api_key=api_key,
        )

        # Call the appropriate public method.
        if method == "GET":
            client.get(path)
        elif method == "POST":
            client.post(path, body={})
        elif method == "PUT":
            client.put(path, body={})
        elif method == "DELETE":
            client.delete(path)

    params = captured_kwargs.get("params", {})
    assert "username" in params, (
        f"'username' query param missing for {method} {path}; got params={params}"
    )
    assert params["username"] == username, (
        f"Expected username={username!r}, got {params['username']!r}"
    )
    assert "api-key" in params, (
        f"'api-key' query param missing for {method} {path}; got params={params}"
    )
    assert params["api-key"] == api_key, (
        f"Expected api-key={api_key!r}, got {params['api-key']!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Retry on transient errors
# ---------------------------------------------------------------------------
# Feature: spira-freshener, Property 3: Retry on transient errors
#
# For any HTTP status code in {429, 500, 502, 503, 504}, the SpiraClient
# SHALL retry the request up to 3 times before raising an error; for any
# status code NOT in that set (and not 401/403), it SHALL NOT retry.
#
# Validates: Requirements 1.8

# Status codes that should trigger retries.
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

# Status codes that should NOT trigger retries (excluding 401/403 which raise
# immediately, and 2xx which succeed).  We test a representative sample of
# non-retry error codes.
NON_RETRY_ERROR_CODES = {400, 404, 405, 409, 410, 422, 501}

retry_status_strategy = st.sampled_from(sorted(RETRY_STATUS_CODES))
non_retry_status_strategy = st.sampled_from(sorted(NON_RETRY_ERROR_CODES))


def _make_fake_make_request(status_code: int) -> tuple[Any, list[int]]:
    """Return a (fake_make_request, call_log) pair.

    ``fake_make_request`` replaces ``urllib3.HTTPConnectionPool._make_request``
    and returns a mock urllib3 response with *status_code*.  Each call appends
    to *call_log* so the caller can count attempts.

    Patching ``_make_request`` is the correct level: urllib3's ``urlopen``
    calls ``_make_request`` once per actual HTTP attempt (including retries),
    so the call count reflects the true number of wire-level attempts.
    """
    call_log: list[int] = []

    def fake_make_request(
        pool_self: Any, conn: Any, method: str, url: str, **kwargs: Any
    ) -> MagicMock:
        call_log.append(status_code)
        resp = MagicMock()
        resp.status = status_code
        resp.headers = {}
        resp.reason = f"Simulated {status_code}"
        resp.version = 11
        resp.length_remaining = 0
        resp.chunked = False
        resp.read.return_value = b"error"
        resp.data = b"error"
        return resp

    return fake_make_request, call_log


@given(status_code=retry_status_strategy)
@settings(max_examples=100, deadline=None)
def test_retry_on_transient_status_codes(status_code: int) -> None:
    """Property 3 (retry branch): SpiraClient retries up to 3 times on
    status codes in {429, 500, 502, 503, 504}.

    **Validates: Requirements 1.8**
    """
    fake_make_request, call_log = _make_fake_make_request(status_code)

    client = SpiraClient(
        base_url="https://example.spiraservice.net/demo",
        username="testuser",
        api_key="{test-api-key}",
    )

    # Patch time.sleep to eliminate backoff delays during testing.
    with patch("time.sleep"), patch.object(
        urllib3.HTTPConnectionPool, "_make_request", new=fake_make_request
    ):
        with pytest.raises(Exception):
            client.get("projects/1/test-cases")

    attempt_count = len(call_log)

    # urllib3 Retry(total=3): 1 original attempt + up to 3 retries = 2–4 total.
    assert attempt_count >= 2, (
        f"Expected at least 2 attempts (1 original + retries) for status {status_code}, "
        f"but got {attempt_count}"
    )
    assert attempt_count <= 4, (
        f"Expected at most 4 attempts (1 original + 3 retries) for status {status_code}, "
        f"but got {attempt_count}"
    )


@given(status_code=non_retry_status_strategy)
@settings(max_examples=100, deadline=None)
def test_no_retry_on_non_transient_status_codes(status_code: int) -> None:
    """Property 3 (no-retry branch): SpiraClient does NOT retry on status
    codes outside {429, 500, 502, 503, 504} (excluding 401/403).

    **Validates: Requirements 1.8**
    """
    fake_make_request, call_log = _make_fake_make_request(status_code)

    client = SpiraClient(
        base_url="https://example.spiraservice.net/demo",
        username="testuser",
        api_key="{test-api-key}",
    )

    with patch("time.sleep"), patch.object(
        urllib3.HTTPConnectionPool, "_make_request", new=fake_make_request
    ):
        with pytest.raises(Exception):
            client.get("projects/1/test-cases")

    attempt_count = len(call_log)

    # For non-retry status codes, urllib3 should NOT retry — exactly 1 attempt.
    assert attempt_count == 1, (
        f"Expected exactly 1 attempt (no retry) for status {status_code}, "
        f"but got {attempt_count}"
    )
