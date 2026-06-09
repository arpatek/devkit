#!/usr/bin/env python3
"""monitoring.py - Monitoring module for devkit
========================================================================================

Prometheus scrape target health, active alert viewer, and Grafana launcher.
No credentials required — Prometheus and Grafana are open on the internal LAN.

Author: Juan Garcia (arpatek)

Usage:
------
  ./modules/monitoring.py              # scrape target health (default)
  ./modules/monitoring.py --alerts     # active Prometheus alerts
  ./modules/monitoring.py --grafana    # print Grafana URL and attempt xdg-open
"""

__version__ = "1.0.0"

# ──[ venv bootstrap ]─────────────────────────────────────────────────────────────────
import os, sys
from pathlib import Path as _P
_venv = _P(os.environ.get("DEVKIT_ROOT") or _P(__file__).resolve().parent.parent) / ".venv"
if _venv.exists() and sys.prefix != str(_venv):
    os.execv(str(_venv / "bin/python3"), [str(_venv / "bin/python3")] + sys.argv)
del _venv

# ──[ Imports ]─────────────────────────────────────────────────────────────────────────
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEVKIT_ROOT = Path(os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(DEVKIT_ROOT / "lib"))

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Missing dependency: rich  →  pip install --user rich", file=sys.stderr)
    sys.exit(2)

import secrets
from api import APIError, Session

# ──[ Config ]──────────────────────────────────────────────────────────────────────────

console = Console()
err     = Console(stderr=True)

# ──[ Helpers ]─────────────────────────────────────────────────────────────────────────


def _since(ts: str) -> str:
    """Human-readable duration since an RFC3339 timestamp."""
    if not ts:
        return "—"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - t
        d, s = delta.days, delta.seconds
        if d > 0:
            return f"{d}d{s // 3600}h ago"
        if s >= 3600:
            return f"{s // 3600}h{(s % 3600) // 60}m ago"
        return f"{s // 60}m ago"
    except ValueError:
        return ts[:19]


# ──[ Views ]───────────────────────────────────────────────────────────────────────────


def render_targets(session: Session, base: str) -> None:
    data = session.get(f"{base}/api/v1/targets")
    if data.get("status") != "success":
        err.print(f"[red]![/red] Prometheus returned: {data}")
        sys.exit(1)

    targets = data.get("data", {}).get("activeTargets", [])
    if not targets:
        console.print("[dim]No active scrape targets found.[/dim]")
        return

    up   = sum(1 for t in targets if t.get("health") == "up")
    down = len(targets) - up
    title = f"Prometheus · Targets   [green]{up}[/green] up"
    if down:
        title += f"  [red]{down}[/red] down"

    table = Table(title=title, header_style="bold cyan", show_lines=False)
    table.add_column("Job", style="cyan", no_wrap=True)
    table.add_column("Instance", style="dim", no_wrap=True)
    table.add_column("Health", no_wrap=True)
    table.add_column("Last Scrape", style="dim", no_wrap=True)
    table.add_column("Duration", justify="right", style="dim", no_wrap=True)
    table.add_column("Error", style="red")

    for t in sorted(targets, key=lambda x: (x.get("labels", {}).get("job", ""), x.get("labels", {}).get("instance", ""))):
        labels   = t.get("labels", {})
        health   = t.get("health", "unknown")
        color    = "green" if health == "up" else "red" if health == "down" else "yellow"
        last_ms  = t.get("lastScrapeDuration", 0) * 1000

        table.add_row(
            labels.get("job", "—"),
            labels.get("instance", "—"),
            f"[{color}]{health}[/{color}]",
            _since(t.get("lastScrape", "")),
            f"{last_ms:.0f}ms",
            t.get("lastError", "") or "",
        )

    console.print(table)


def render_alerts(session: Session, base: str) -> None:
    data = session.get(f"{base}/api/v1/alerts")
    if data.get("status") != "success":
        err.print(f"[red]![/red] Prometheus returned: {data}")
        sys.exit(1)

    alerts = data.get("data", {}).get("alerts", [])
    active = [a for a in alerts if a.get("state") != "inactive"]

    if not active:
        console.print("[green]✓[/green]  No active alerts.")
        return

    table = Table(title=f"Prometheus · Active Alerts ({len(active)})", header_style="bold cyan")
    table.add_column("Alert", style="cyan", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Instance", style="dim", no_wrap=True)
    table.add_column("Fired", style="dim", no_wrap=True)

    for a in sorted(active, key=lambda x: x.get("labels", {}).get("alertname", "")):
        labels   = a.get("labels", {})
        state    = a.get("state", "unknown")
        severity = labels.get("severity", "—")
        color    = "red" if state == "firing" else "yellow"
        sev_color = "red" if severity == "critical" else "yellow" if severity == "warning" else "white"

        table.add_row(
            labels.get("alertname", "—"),
            f"[{color}]{state}[/{color}]",
            f"[{sev_color}]{severity}[/{sev_color}]",
            labels.get("instance", "—"),
            _since(a.get("activeAt", "")),
        )

    console.print(table)


def render_grafana(grafana_url: str) -> None:
    console.print(f"\n  Grafana: [cyan]{grafana_url}[/cyan]\n")
    try:
        subprocess.Popen(["xdg-open", grafana_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console.print("[dim]  Launched in browser.[/dim]")
    except FileNotFoundError:
        console.print("[dim]  xdg-open not available — open the URL manually.[/dim]")


# ──[ CLI ]─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="monitoring.py", description="Monitoring homelab module")
    p.add_argument("--alerts", action="store_true", help="Show active Prometheus alerts")
    p.add_argument("--grafana", action="store_true", help="Open Grafana in browser")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    secrets.load()
    prom_host  = os.environ.get("PROMETHEUS_HOST", "netwatch.home.arpa")
    prom_port  = os.environ.get("PROMETHEUS_PORT", "9090")
    graf_host  = os.environ.get("GRAFANA_HOST", "netwatch.home.arpa")
    graf_port  = os.environ.get("GRAFANA_PORT", "3000")

    prom_base    = f"http://{prom_host}:{prom_port}"
    grafana_url  = f"http://{graf_host}:{graf_port}"

    if args.grafana:
        render_grafana(grafana_url)
        return

    session = Session()

    try:
        if args.alerts:
            render_alerts(session, prom_base)
        else:
            render_targets(session, prom_base)
    except (APIError, OSError) as e:
        err.print(f"[red]![/red] Cannot reach Prometheus at {prom_base}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
