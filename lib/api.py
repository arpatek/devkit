#!/usr/bin/env python3
"""api.py - HTTP client for devkit service integrations
========================================================================================

Thin urllib wrapper covering the auth patterns used across devkit modules:
  - Static header auth (Proxmox API token, Gitea bearer token)
  - Dynamic bearer token (Pi-hole v6 session SID)
  - Session cookie auth (FreeIPA XML-RPC)

All SSL verification is optional — homelab services use self-signed certs.
Stdlib only (urllib, json, ssl). No requests, no httpx.

Author: Juan Garcia (arpatek)
"""

__version__ = "1.0.0"

# ──[ Imports ]─────────────────────────────────────────────────────────────────────────
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from typing import Any, Optional

# ──[ SSL ]─────────────────────────────────────────────────────────────────────────────


def _insecure_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ──[ Errors ]──────────────────────────────────────────────────────────────────────────


class APIError(Exception):
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


# ──[ Session ]─────────────────────────────────────────────────────────────────────────


@dataclass
class Session:
    """Reusable HTTP session with auth headers, cookie jar, and optional SSL bypass."""

    headers: dict = field(default_factory=dict)
    verify_ssl: bool = True
    _jar: CookieJar = field(default_factory=CookieJar, init=False, repr=False)
    _opener: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        handlers: list = [urllib.request.HTTPCookieProcessor(self._jar)]
        if not self.verify_ssl:
            handlers.append(urllib.request.HTTPSHandler(context=_insecure_ctx()))
        self._opener = urllib.request.build_opener(*handlers)

    def get(self, url: str, timeout: float = 10.0) -> Any:
        req = urllib.request.Request(url, headers=self.headers)
        return self._send(req, timeout)

    def post(self, url: str, data: Any, timeout: float = 10.0) -> Any:
        body = json.dumps(data).encode()
        headers = {"Content-Type": "application/json", **self.headers}
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        return self._send(req, timeout)

    def post_form(self, url: str, fields: dict, timeout: float = 10.0) -> Any:
        """POST application/x-www-form-urlencoded — used by IPA session login."""
        body = urllib.parse.urlencode(fields).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", **self.headers}
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        return self._send(req, timeout)

    def _send(self, req: urllib.request.Request, timeout: float) -> Any:
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                ct = resp.headers.get("Content-Type", "")
                if "json" in ct and raw:
                    return json.loads(raw)
                return {"_raw": raw.decode(errors="replace"), "_status": resp.status}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                body = json.loads(raw)
            except Exception:
                body = {"_raw": raw.decode(errors="replace")}
            raise APIError(e.code, body) from e
        except urllib.error.URLError as e:
            raise APIError(0, {"_reason": str(e.reason)}) from e

    def cookie(self, name: str) -> Optional[str]:
        for c in self._jar:
            if c.name == name:
                return c.value
        return None


# ──[ IPA XML-RPC ]─────────────────────────────────────────────────────────────────────


class IPAClient:
    """FreeIPA JSON-RPC client. Authenticates via login_password session cookie.

    The session cookie is captured automatically by the Session's CookieJar.
    A Referer header matching the IPA web UI origin is required for the API
    to accept JSON-RPC requests.
    """

    def __init__(self, host: str, user: str, password: str) -> None:
        self._base = f"https://{host}/ipa"
        self._session = Session(
            headers={"Referer": f"https://{host}/ipa/ui/"},
            verify_ssl=False,
        )
        self._login(user, password)

    def _login(self, user: str, password: str) -> None:
        url = f"{self._base}/session/login_password"
        try:
            self._session.post_form(url, {"user": user, "password": password})
        except APIError as e:
            if e.status == 401:
                raise RuntimeError(
                    "IPA authentication failed — check IPA_USER and IPA_PASSWORD"
                ) from e
            raise

    def call(self, method: str, args: Optional[list] = None, options: Optional[dict] = None) -> Any:
        """Invoke an IPA JSON-RPC method. Returns the result value or raises IPAError."""
        payload = {
            "method": method,
            "params": [args or [], options or {}],
            "id": 0,
        }
        resp = self._session.post(f"{self._base}/session/json", payload)
        if resp.get("error"):
            raise IPAError(resp["error"])
        return resp.get("result", {})


class IPAError(Exception):
    def __init__(self, err: dict) -> None:
        self.code = err.get("code")
        self.message = err.get("message", str(err))
        super().__init__(f"IPA {self.code}: {self.message}")
