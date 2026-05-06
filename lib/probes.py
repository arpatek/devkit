#!/usr/bin/env python3
"""probes.py - Reusable network and service health probes for devkit.
========================================================================================

Each probe returns a ProbeResult so callers never need try/except — a failed probe
shows up as ok=False with a brief detail string. Designed to be the I/O layer for
modules/status.py and any future homelab module that needs a lightweight health
check (Proxmox, K3s, Pi-hole helpers, etc.).

Author: Juan J. Garcia (arpatek)

Dependencies:
-------------
- Python 3.9+
- ping binary on PATH (for check_icmp)
- stdlib only beyond that: socket, ssl, urllib.request, subprocess

Sample Usage:
-------------
>>> from probes import check_icmp, check_tcp, check_http
>>> check_icmp("10.0.0.1")
ProbeResult(ok=True, latency_ms=1.2, detail=None)
>>> check_tcp("10.0.0.1", 22)
ProbeResult(ok=True, latency_ms=2.4, detail=None)
>>> check_http("https://gitea.home.arpa/")
ProbeResult(ok=True, latency_ms=42.0, detail="200")
"""

# ——[ Imports ]—————————————————————————————————————————————————————————————————————————
import re
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# ——[ Result Type ]—————————————————————————————————————————————————————————————————————


@dataclass
class ProbeResult:
    """Outcome of a single probe — uniform shape for every check function."""

    ok: bool
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


# ——[ Probes ]——————————————————————————————————————————————————————————————————————————


def check_icmp(host: str, timeout: float = 1.0) -> ProbeResult:
    """Single ICMP echo. Parses ping's reported latency on success."""
    try:
        result = subprocess.run(
            ["ping", "-c1", "-W", str(max(1, int(timeout))), host],
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(ok=False, detail="timeout")
    except FileNotFoundError:
        return ProbeResult(ok=False, detail="ping not found")

    if result.returncode != 0:
        return ProbeResult(ok=False, detail="unreachable")

    match = re.search(r"time=([\d.]+)\s*ms", result.stdout)
    latency = float(match.group(1)) if match else None
    return ProbeResult(ok=True, latency_ms=latency)


def check_tcp(host: str, port: int, timeout: float = 2.0) -> ProbeResult:
    """Open a TCP socket to host:port. Used for ssh, postgres, redis, etc."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ProbeResult(ok=True, latency_ms=elapsed_ms)
    except socket.timeout:
        return ProbeResult(ok=False, detail="timeout")
    except socket.gaierror:
        return ProbeResult(ok=False, detail="dns")
    except ConnectionRefusedError:
        return ProbeResult(ok=False, detail="refused")
    except OSError as e:
        err = (e.strerror or str(e)).lower()
        if "unreachable" in err:
            return ProbeResult(ok=False, detail="unreachable")
        return ProbeResult(ok=False, detail=err.split(":")[0].strip() or "down")


def check_http(url: str, timeout: float = 5.0) -> ProbeResult:
    """HTTP/HTTPS GET. Self-signed certs accepted (homelab pragma)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "devkit-status/0.1"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ProbeResult(
                ok=200 <= resp.status < 400,
                latency_ms=elapsed_ms,
                detail=str(resp.status),
            )
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ProbeResult(ok=False, latency_ms=elapsed_ms, detail=str(e.code))
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return ProbeResult(ok=False, detail="timeout")
        if isinstance(reason, socket.gaierror):
            return ProbeResult(ok=False, detail="dns")
        if isinstance(reason, ConnectionRefusedError):
            return ProbeResult(ok=False, detail="refused")
        if isinstance(reason, OSError):
            err = (reason.strerror or str(reason)).lower()
            if "unreachable" in err:
                return ProbeResult(ok=False, detail="unreachable")
            return ProbeResult(ok=False, detail=err.split(":")[0].strip() or "down")
        return ProbeResult(ok=False, detail=str(reason).lower())
    except (socket.timeout, TimeoutError):
        return ProbeResult(ok=False, detail="timeout")
    except Exception as e:
        return ProbeResult(ok=False, detail=type(e).__name__.lower())
