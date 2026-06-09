#!/usr/bin/env python3
"""gitea.py - Gitea module for devkit
========================================================================================

Act runner status, recent pipeline runs, and container registry image listing.
Connects to the Gitea REST API with a personal access token.

Author: Juan Garcia (arpatek)

Usage:
------
  ./modules/gitea.py                # runner status + recent activity (default)
  ./modules/gitea.py --pipelines    # recent action runs across all repos
  ./modules/gitea.py --registry     # container images in the Gitea registry
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

RUN_COLORS = {
    "success":   "green",
    "failure":   "red",
    "cancelled": "dim",
    "skipped":   "dim",
    "waiting":   "yellow",
    "running":   "yellow",
    "queued":    "yellow",
    "unknown":   "white",
}

# ──[ Helpers ]─────────────────────────────────────────────────────────────────────────


def _ago(ts: str) -> str:
    if not ts:
        return "—"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - t
        d, s = delta.days, delta.seconds
        if d > 0:
            return f"{d}d ago"
        if s >= 3600:
            return f"{s // 3600}h ago"
        if s >= 60:
            return f"{s // 60}m ago"
        return "just now"
    except ValueError:
        return ts[:10]


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ──[ Views ]───────────────────────────────────────────────────────────────────────────


def render_runners(session: Session, base: str) -> None:
    try:
        data = session.get(f"{base}/api/v1/admin/actions/runners?limit=50")
    except APIError as e:
        if e.status == 403:
            err.print("[red]![/red] Runner list requires an admin token.")
            sys.exit(1)
        if e.status == 404:
            err.print("[yellow]~[/yellow] Runner API not available — Actions may be disabled.")
            return
        raise

    runners = data.get("runners", data if isinstance(data, list) else [])

    if not runners:
        console.print("[dim]No runners registered.[/dim]")
        return

    online = sum(1 for r in runners if r.get("status") == "online")
    table = Table(
        title=f"Gitea · Runners   [green]{online}[/green]/{len(runners)} online",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("ID", justify="right", style="dim", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Labels", style="dim")

    for r in sorted(runners, key=lambda x: x.get("name", "")):
        status_str = r.get("status", "unknown")
        if status_str == "online":
            status = "[green]online[/green]"
        elif status_str == "offline":
            status = "[red]offline[/red]"
        else:
            status = f"[dim]{status_str}[/dim]"
        if r.get("disabled"):
            status += " [dim](disabled)[/dim]"
        labels = ", ".join(lbl.get("name", "") for lbl in r.get("labels", [])) or "—"

        table.add_row(str(r.get("id", "—")), r.get("name", "—"), status, labels)

    console.print(table)


def render_pipelines(session: Session, base: str, owner: str) -> None:
    repos_data = session.get(f"{base}/api/v1/repos/search?limit=50")
    repos = repos_data.get("data", [])

    if not repos:
        console.print("[dim]No repositories found.[/dim]")
        return

    table = Table(title="Gitea · Recent Pipeline Runs", header_style="bold cyan", show_lines=False)
    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("Workflow", style="dim", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Branch", style="dim", no_wrap=True)
    table.add_column("Triggered", style="dim", no_wrap=True)

    found = 0
    for repo in repos:
        repo_name = repo.get("name", "")
        repo_owner = repo.get("owner", {}).get("login", owner)
        try:
            runs_data = session.get(f"{base}/api/v1/repos/{repo_owner}/{repo_name}/actions/runs?limit=3")
        except APIError:
            continue

        runs = runs_data.get("workflow_runs", [])
        for run in runs[:3]:
            status = run.get("status", "unknown")
            conclusion = run.get("conclusion") or status
            color = RUN_COLORS.get(conclusion, "white")
            raw_path = run.get("path", "")
            workflow = raw_path.split("@")[0].rsplit("/", 1)[-1] if raw_path else "—"
            table.add_row(
                repo_name,
                workflow or "—",
                f"[{color}]{conclusion}[/{color}]",
                run.get("head_branch", "—"),
                _ago(run.get("started_at", "")),
            )
            found += 1

    if not found:
        console.print("[dim]No pipeline runs found. Actions may not be enabled.[/dim]")
        return

    console.print(table)


def render_registry(session: Session, base: str, owner: str) -> None:
    try:
        data = session.get(f"{base}/api/v1/packages/{owner}?type=container&limit=50")
    except APIError as e:
        if e.status == 404:
            console.print("[dim]No container packages found for this user.[/dim]")
            return
        raise

    packages = [
        p for p in (data if isinstance(data, list) else [])
        if not str(p.get("version", "")).startswith("sha256:")
    ]

    if not packages:
        console.print("[dim]No container images in the registry.[/dim]")
        return

    table = Table(title="Gitea · Container Registry", header_style="bold cyan", show_lines=False)
    table.add_column("Image", style="cyan", no_wrap=True)
    table.add_column("Version", style="dim", no_wrap=True)
    table.add_column("Size", justify="right", style="dim", no_wrap=True)
    table.add_column("Pushed", style="dim", no_wrap=True)

    for pkg in packages:
        name    = pkg.get("name", "—")
        version = pkg.get("version", "—")
        size    = _fmt_size(pkg.get("size", 0))
        created = _ago(pkg.get("created_at", ""))
        table.add_row(name, version, size, created)

    console.print(table)


# ──[ CLI ]─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="gitea.py", description="Gitea homelab module")
    p.add_argument("--pipelines", action="store_true", help="Recent action pipeline runs")
    p.add_argument("--registry", action="store_true", help="Container registry images")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        secrets.load()
        host  = secrets.require("GITEA_HOST")
        port  = os.environ.get("GITEA_PORT", "3000")
        token = secrets.require("GITEA_TOKEN")
        owner = secrets.require("GITEA_USER")
    except RuntimeError as e:
        err.print(f"[red]![/red] {e}")
        sys.exit(1)

    base    = f"http://{host}:{port}"
    session = Session(headers={"Authorization": f"token {token}"})

    try:
        if args.pipelines:
            render_pipelines(session, base, owner)
        elif args.registry:
            render_registry(session, base, owner)
        else:
            render_runners(session, base)
    except (APIError, OSError) as e:
        err.print(f"[red]![/red] Gitea API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
