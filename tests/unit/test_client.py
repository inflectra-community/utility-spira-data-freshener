"""
Unit tests for SpiraClient (spira_freshener/client.py).

Covers:
- Auth params (username and api-key) are appended on GET, POST, PUT, DELETE
- HTTP 401 raises requests.HTTPError immediately without retry
- HTTP 403 raises requests.HTTPError immediately without retry
- Retry adapter is mounted on the session with max_retries configured
- _build_url correctly joins base_url with path (with and without leading slash)
- Empty response body returns None
- Non-empty response body returns parsed JSON

Requirements: 1.6, 1.7, 1.8
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.adapters import HTTPAdapter

from spira_freshener.client import SpiraClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "https://demo.spiraservice.net/mysite"
USERNAME = "testuser"
API_KEY = "abc123"


@pytest.fixture
def client() -> SpiraClient:
    """Return a SpiraClient instance with a mocked session."""
    return SpiraClient(base_url=BASE_URL, username=USERNAME, api_key=API_KEY)


def _make_response(status_code: int, content: bytes = b"") -> MagicMock:
    """Build a mock requests.Response with the given status code and body."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.content = content
    resp.ok = 200 <= status_code < 300
    resp.text = content.decode("utf-8") if content else ""
    if content:
        resp.json.return_value = requests.models.complexjson.loads(content)
    return resp


# ---------------------------------------------------------------------------
# Auth params tests (Requirement 1.6)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_auth_params_appended_on_every_method(client: SpiraClient, method: str) -> None:
    """Auth params username and api-key must be present on every HTTP method."""
    ok_response = _make_response(200, b'{"ok": true}')

    with patch.object(client._session, "request", return_value=ok_response) as mock_req:
        if method == "GET":
            client.get("projects/1/test-cases")
        elif method == "POST":
            client.post("projects/1/test-cases", body={"name": "TC"})
        elif method == "PUT":
            client.put("projects/1/test-cases/1", body={"name": "TC"})
        elif method == "DELETE":
            client.delete("projects/1/test-cases/1")

        mock_req.assert_called_once()
        _, kwargs = mock_req.call_args
        params = kwargs.get("params", {})

        assert "username" in params, f"'username' missing from params on {method}"
        assert "api-key" in params, f"'api-key' missing from params on {method}"
        assert params["username"] == USERNAME
        assert params["api-key"] == API_KEY


def test_auth_params_merged_with_extra_params(client: SpiraClient) -> None:
    """Extra caller-supplied params must be merged with auth params, not replace them."""
    ok_response = _make_response(200, b'{"ok": true}')

    with patch.object(client._session, "request", return_value=ok_response) as mock_req:
        client.get("projects/1/test-cases", params={"page": "1", "pageSize": "10"})

        _, kwargs = mock_req.call_args
        params = kwargs.get("params", {})

        assert params["username"] == USERNAME
        assert params["api-key"] == API_KEY
        assert params["page"] == "1"
        assert params["pageSize"] == "10"


# ---------------------------------------------------------------------------
# HTTP 401 / 403 raise immediately (Requirement 1.7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_error_raises_http_error_immediately(client: SpiraClient, status_code: int) -> None:
    """HTTP 401 and 403 must raise requests.HTTPError without waiting for retries."""
    error_response = _make_response(status_code)
    error_response.raise_for_status.side_effect = requests.HTTPError(
        f"{status_code} Client Error", response=error_response
    )

    with patch.object(client._session, "request", return_value=error_response):
        with pytest.raises(requests.HTTPError):
            client.get("projects/1/test-cases")


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_error_does_not_retry(client: SpiraClient, status_code: int) -> None:
    """HTTP 401 and 403 must result in exactly one request — no retries."""
    error_response = _make_response(status_code)
    error_response.raise_for_status.side_effect = requests.HTTPError(
        f"{status_code} Client Error", response=error_response
    )

    with patch.object(client._session, "request", return_value=error_response) as mock_req:
        with pytest.raises(requests.HTTPError):
            client.get("projects/1/test-cases")

        # The session.request should be called exactly once — no retry loop at this layer.
        assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# Retry adapter mounted on session (Requirement 1.8)
# ---------------------------------------------------------------------------

def test_retry_adapter_mounted_for_https(client: SpiraClient) -> None:
    """The session must have a retry-enabled adapter mounted for https://."""
    adapter = client._session.get_adapter("https://")
    assert isinstance(adapter, HTTPAdapter), "Expected an HTTPAdapter for https://"
    assert adapter.max_retries is not None, "max_retries should be configured"


def test_retry_adapter_mounted_for_http(client: SpiraClient) -> None:
    """The session must have a retry-enabled adapter mounted for http://."""
    adapter = client._session.get_adapter("http://")
    assert isinstance(adapter, HTTPAdapter), "Expected an HTTPAdapter for http://"
    assert adapter.max_retries is not None, "max_retries should be configured"


def test_retry_adapter_max_retries_total(client: SpiraClient) -> None:
    """The retry adapter must be configured with total=3 retries."""
    adapter = client._session.get_adapter("https://")
    assert adapter.max_retries.total == 3


def test_retry_adapter_status_forcelist(client: SpiraClient) -> None:
    """The retry adapter must retry on 429, 500, 502, 503, 504."""
    adapter = client._session.get_adapter("https://")
    expected = {429, 500, 502, 503, 504}
    assert set(adapter.max_retries.status_forcelist) == expected


def test_retry_adapter_allowed_methods(client: SpiraClient) -> None:
    """The retry adapter must allow retries on GET, POST, PUT, DELETE."""
    adapter = client._session.get_adapter("https://")
    expected = {"GET", "POST", "PUT", "DELETE"}
    assert set(adapter.max_retries.allowed_methods) == expected


# ---------------------------------------------------------------------------
# _build_url tests
# ---------------------------------------------------------------------------

def test_build_url_without_leading_slash(client: SpiraClient) -> None:
    """_build_url must join base_url and path when path has no leading slash."""
    url = client._build_url("projects/1/test-cases")
    assert url.startswith(client.base_url)
    assert url.endswith("projects/1/test-cases")


def test_build_url_with_leading_slash(client: SpiraClient) -> None:
    """_build_url must strip the leading slash from path before joining."""
    url_with = client._build_url("/projects/1/test-cases")
    url_without = client._build_url("projects/1/test-cases")
    assert url_with == url_without


def test_build_url_base_url_normalised(client: SpiraClient) -> None:
    """base_url must have the API suffix appended and no double slashes."""
    assert "//" not in client.base_url.replace("https://", "").replace("http://", "")


def test_build_url_trailing_slash_stripped_from_input() -> None:
    """A trailing slash on the constructor base_url must be stripped before suffix is added."""
    client_with_slash = SpiraClient(
        base_url=BASE_URL + "/", username=USERNAME, api_key=API_KEY
    )
    client_without_slash = SpiraClient(
        base_url=BASE_URL, username=USERNAME, api_key=API_KEY
    )
    assert client_with_slash.base_url == client_without_slash.base_url


# ---------------------------------------------------------------------------
# Response parsing tests
# ---------------------------------------------------------------------------

def test_empty_response_body_returns_none(client: SpiraClient) -> None:
    """An empty response body must return None, not raise an error."""
    empty_response = _make_response(200, b"")

    with patch.object(client._session, "request", return_value=empty_response):
        result = client.get("projects/1/test-cases")

    assert result is None


def test_non_empty_response_body_returns_parsed_json(client: SpiraClient) -> None:
    """A non-empty response body must be parsed and returned as a Python object."""
    payload = b'[{"TestCaseId": 1, "Name": "Login test"}]'
    json_response = _make_response(200, payload)

    with patch.object(client._session, "request", return_value=json_response):
        result = client.get("projects/1/test-cases")

    assert result == [{"TestCaseId": 1, "Name": "Login test"}]


def test_non_empty_dict_response_returned(client: SpiraClient) -> None:
    """A JSON object response body must be returned as a dict."""
    payload = b'{"ProjectId": 1, "Name": "Demo Project"}'
    json_response = _make_response(200, payload)

    with patch.object(client._session, "request", return_value=json_response):
        result = client.get("projects/1")

    assert result == {"ProjectId": 1, "Name": "Demo Project"}


# ---------------------------------------------------------------------------
# Non-2xx (non-auth) error handling
# ---------------------------------------------------------------------------

def test_non_2xx_non_auth_raises_http_error(client: SpiraClient) -> None:
    """A 500 response (after retries) must raise requests.HTTPError."""
    error_response = _make_response(500)
    error_response.ok = False

    with patch.object(client._session, "request", return_value=error_response):
        with pytest.raises(requests.HTTPError):
            client.get("projects/1/test-cases")
