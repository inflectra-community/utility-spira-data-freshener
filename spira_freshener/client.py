"""
SpiraFreshener HTTP client.

Wraps the Spira REST API v7 with authentication, automatic retries, and
error handling.  All HTTP knowledge lives here; service modules and the
runner call only the public methods (get / post / put / delete).

Authentication is performed via query parameters (``username`` and
``api-key``) appended to every request, matching the SpiraProvisioner
authentication pattern.

Retry policy (matching SpiraProvisioner):
    - total retries : 3
    - backoff factor : 1  (waits 1 s, 2 s, 4 s between attempts)
    - retried status codes : 429, 500, 502, 503, 504
    - retried methods : GET, POST, PUT, DELETE
"""

from __future__ import annotations

from typing import Any

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Suppress InsecureRequestWarning for internal instances with self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Artifact-type look-up tables (mirrored from SpiraProvisioner's client.py)
# ---------------------------------------------------------------------------

ARTIFACT_TYPE: dict[str, int] = {
    "Requirement": 1,
    "TestCase": 2,
    "Incident": 3,
    "Release": 4,
    "TestRun": 5,
    "Task": 6,
    "TestStep": 7,
    "TestSet": 8,
}

ARTIFACT_TYPE_NAME: dict[int, str] = {v: k for k, v in ARTIFACT_TYPE.items()}


class SpiraClient:
    """Thin HTTP client for the Spira REST API v7."""

    #: Base path appended to the host URL after normalisation.
    _API_SUFFIX = "Services/v7_0/RestService.svc/"

    def __init__(self, base_url: str, username: str, api_key: str) -> None:
        """Initialise the client and build a :class:`requests.Session`.

        Parameters
        ----------
        base_url:
            Root URL of the Spira instance, e.g.
            ``https://demo.spiraservice.net/mysite``.  A trailing slash is
            stripped before the API suffix is appended.
        username:
            Spira username used for query-parameter authentication.
        api_key:
            Spira API key (RSS token) used for query-parameter
            authentication.
        """
        # Normalise base URL: strip trailing slash, then append API suffix.
        self.base_url: str = base_url.rstrip("/") + "/" + self._API_SUFFIX
        self.username: str = username
        self.api_key: str = api_key

        # Build retry policy matching SpiraProvisioner's configuration.
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry)

        # Create session and mount the retry adapter for both http and https.
        self._session: requests.Session = requests.Session()
        self._session.verify = False  # Internal instances use self-signed certs
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        # Set default headers for JSON communication.
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        """Return the full URL for *path* relative to :attr:`base_url`.

        Leading slashes on *path* are stripped so that callers can pass
        either ``"projects/1/test-cases"`` or ``"/projects/1/test-cases"``.
        """
        return self.base_url + path.lstrip("/")

    def _auth_params(self) -> dict:
        """Return the authentication query-parameter dict."""
        return {"username": self.username, "api-key": self.api_key}

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: Any = None,
    ) -> Any:
        """Execute an authenticated HTTP request and return parsed JSON.

        Parameters
        ----------
        method:
            HTTP verb, e.g. ``"GET"``, ``"POST"``, ``"PUT"``, ``"DELETE"``.
        path:
            API path relative to :attr:`base_url`.
        params:
            Extra query parameters to merge with the auth params.
        json:
            Request body to serialise as JSON (for POST / PUT).

        Returns
        -------
        Any
            Parsed JSON response body, or ``None`` when the response body
            is empty.

        Raises
        ------
        requests.HTTPError
            Immediately on HTTP 401 or 403 (before any retry fires).
            After retries are exhausted on any other non-2xx status.
        """
        url = self._build_url(path)

        # Merge auth params with any caller-supplied params.
        all_params: dict = {**self._auth_params(), **(params or {})}

        # Retry the whole request when a large response body arrives
        # truncated. The Retry adapter only covers HTTP status codes; a
        # connection dropped mid-body returns 200 with an incomplete
        # payload, which surfaces as a JSONDecodeError, so we handle it
        # here.
        last_decode_error: ValueError | None = None
        for attempt in range(3):
            response = self._session.request(
                method, url, params=all_params, json=json, timeout=60
            )

            # Raise immediately on auth failures — do not wait for retries.
            if response.status_code in (401, 403):
                response.raise_for_status()

            # Raise on any other non-2xx after retries are exhausted.
            if not response.ok:
                raise requests.HTTPError(
                    f"HTTP {response.status_code} for {method} {url}: "
                    f"{response.text}",
                    response=response,
                )

            # Empty body is a valid "no content" response.
            if not response.content:
                return None

            try:
                return response.json()
            except ValueError as exc:
                # Truncated/incomplete JSON body — retry the request.
                last_decode_error = exc
                continue

        raise requests.HTTPError(
            f"Invalid JSON response for {method} {url} after 3 attempts "
            f"(likely a truncated body): {last_decode_error}",
            response=response,
        )

    # ------------------------------------------------------------------
    # Public HTTP methods
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> Any:
        """Perform an authenticated GET request."""
        return self._request("GET", path, params=params)

    def post(self, path: str, body: Any = None, params: dict | None = None) -> Any:
        """Perform an authenticated POST request."""
        return self._request("POST", path, params=params, json=body)

    def put(self, path: str, body: Any = None, params: dict | None = None) -> Any:
        """Perform an authenticated PUT request."""
        return self._request("PUT", path, params=params, json=body)

    def delete(self, path: str, params: dict | None = None) -> Any:
        """Perform an authenticated DELETE request."""
        return self._request("DELETE", path, params=params)
