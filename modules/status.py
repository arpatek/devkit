#!/usr/bin/env python3
"""status.py - Homelab Status Dashboard
========================================================================================

Reads config/hosts.json and runs configured probes (icmp, ssh, http) against each
host in parallel. Renders a colorized status grid via rich — one row per host,
one column per check type.

Designed to be the first pane you open: answers "is everything up?" at a glance.

Author: Juan J. Garcia (arpatek)

Dependencies:
-------------
- Python 3.9+
- rich (pip install --user rich)
- ping binary on PATH
- lib/probes.py (devkit sibling)

Sample Usage:
-------------
$ ./modules/status.py             # one-shot status grid
$ ./cc.sh                         # via the launcher: Homelab → Status Dashboard
"""

# ——[ venv bootstrap ]——————————————————————————————————————————————————————————————————
import os, sys
from pathlib import Path as _P
_venv = _P(os.environ.get("DEVKIT_ROOT") or _P(__file__).resolve().parent.parent) / ".venv"
if _venv.exists() and sys.prefix != str(_venv):
    os.execv(str(_venv / "bin/python3"), [str(_venv / "bin/python3")] + sys.argv)
del _venv

# ——[ Imports ]—————————————————————————————————————————————————————————————————————————
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEVKIT_ROOT = Path(
    os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent
)
sys.path.insert(0, str(DEVKIT_ROOT / "lib"))

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Missing dependency: rich", file=sys.stderr)
    print("Install with: pip install --user rich", file=sys.stderr)
    sys.exit(2)

from probes import ProbeResult, check_http, check_icmp, check_tcp

# ——[ Constants ]———————————————————————————————————————————————————————————————————————

HOSTS_FILE = DEVKIT_ROOT / "config" / "hosts.json"
EXAMPLE_FILE = DEVKIT_ROOT / "config" / "hosts.json.example"

# Display order for check columns. Anything outside this list is appended
# at the end, alphabetically.
CHECK_ORDER = ("icmp", "ssh", "http")

# Each entry maps a `checks` value in hosts.json to a callable that takes the
# host dict and returns a ProbeResult. Add new check types here as modules grow.
CHECK_DISPATCH = {
    "icmp": lambda h: check_icmp(h.get("ip") or h["host"]),
    "ssh": lambda h: check_tcp(h.get("ip") or h["host"], 22),
    "http": lambda h: check_http(h.get("url") or f"https://{h['host']}/"),
}


# ——[ Core ]————————————————————————————————————————————————————————————————————————————


def run_check(host: dict, check: str) -> ProbeResult:
    """Dispatch a single check for a single host; never raises."""
    fn = CHECK_DISPATCH.get(check)
    if fn is None:
        return ProbeResult(ok=False, detail=f"unknown:{check}")
    try:
        return fn(host)
    except Exception as e:
        return ProbeResult(ok=False, detail=type(e).__name__.lower())


def gather(hosts: list) -> dict:
    """Run every configured (host, check) pair in parallel."""
    pairs = [
        (host["name"], check) for host in hosts for check in host.get("checks", [])
    ]
    by_name = {h["name"]: h for h in hosts}

    results = {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(run_check, by_name[name], check): (name, check)
            for name, check in pairs
        }
        for fut in futures:
            results[futures[fut]] = fut.result()
    return results


# ——[ Rendering ]———————————————————————————————————————————————————————————————————————


def format_cell(r: ProbeResult) -> str:
    """One status cell: ✓/✗ with latency and/or detail."""
    if r.ok:
        parts = ["[green]✓[/green]"]
        if r.latency_ms is not None:
            parts.append(f"{r.latency_ms:.0f}ms")
        if r.detail and r.detail not in ("200", "204"):
            parts.append(r.detail)
        return " ".join(parts)
    return f"[red]✗[/red] {r.detail or 'down'}"


def render(hosts: list, results: dict) -> Table:
    """Build the rich Table from gathered results."""
    seen = {c for h in hosts for c in h.get("checks", [])}
    all_checks = [c for c in CHECK_ORDER if c in seen]
    all_checks.extend(sorted(seen - set(all_checks)))

    up = sum(1 for r in results.values() if r.ok)
    total = len(results)
    title = f"DevKit · Homelab Status   [green]{up}[/green]/{total} up"

    table = Table(title=title, header_style="bold cyan", show_lines=False)
    table.add_column("Host", style="cyan", no_wrap=True)
    table.add_column("FQDN", style="dim", no_wrap=True)
    table.add_column("IP", style="dim", no_wrap=True)
    for check in all_checks:
        table.add_column(check.upper(), justify="left", no_wrap=True)

    for host in hosts:
        configured = set(host.get("checks", []))
        row = [host["name"], host["host"], host.get("ip", "—")]
        for check in all_checks:
            if check not in configured:
                row.append("[dim]—[/dim]")
            else:
                row.append(format_cell(results[(host["name"], check)]))
        table.add_row(*row)
    return table


# ——[ CLI Entry Point ]—————————————————————————————————————————————————————————————————


def main():
    if not HOSTS_FILE.exists():
        print(f"hosts.json not found at {HOSTS_FILE}", file=sys.stderr)
        if EXAMPLE_FILE.exists():
            print(
                f"Copy {EXAMPLE_FILE.name} to hosts.json and customize:",
                file=sys.stderr,
            )
            print(f"  cp {EXAMPLE_FILE} {HOSTS_FILE}", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = json.loads(HOSTS_FILE.read_text())
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {HOSTS_FILE}: {e}", file=sys.stderr)
        sys.exit(1)

    hosts = cfg.get("hosts", [])
    if not hosts:
        print("No hosts configured in hosts.json.", file=sys.stderr)
        sys.exit(1)

    results = gather(hosts)
    Console().print(render(hosts, results))


if __name__ == "__main__":
    main()
