#!/usr/bin/env python3
"""proxmox.py - Proxmox VE module for devkit
========================================================================================

VM list, node resource overview, and lifecycle operations (start/stop/restart/snapshot).
Connects to the Proxmox REST API using a scoped API token — no SSH required.

Author: Juan Garcia (arpatek)

Usage:
------
  ./modules/proxmox.py                              # VM list + node summary (default)
  ./modules/proxmox.py --resources                  # node resource panel only
  ./modules/proxmox.py --action start --vmid 100    # start VM 100 (with confirmation)
  ./modules/proxmox.py --action stop  --vmid 100    # stop VM 100
  ./modules/proxmox.py --action restart --vmid 100  # restart VM 100
  ./modules/proxmox.py --snapshot --vmid 100        # create snapshot of VM 100
  ./modules/proxmox.py --interactive                # pick VM and action from menus
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
from pathlib import Path

DEVKIT_ROOT = Path(os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(DEVKIT_ROOT / "lib"))

try:
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError:
    print("Missing dependency: rich  →  pip install --user rich", file=sys.stderr)
    sys.exit(2)

import secrets
from api import APIError, Session

# ──[ Config ]──────────────────────────────────────────────────────────────────────────

console = Console()
err = Console(stderr=True)

ACTION_MAP = {
    "start":   "status/start",
    "stop":    "status/stop",
    "restart": "status/reboot",
}

# ──[ Helpers ]─────────────────────────────────────────────────────────────────────────


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _fmt_uptime(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def _bar(pct: float, width: int = 22) -> str:
    filled = int(pct / 100 * width)
    color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
    return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/{color}] {pct:5.1f}%"


# ──[ API helpers ]─────────────────────────────────────────────────────────────────────


def _get(session: Session, base: str, path: str) -> dict:
    resp = session.get(f"{base}/{path.lstrip('/')}")
    return resp.get("data", resp)


def _post(session: Session, base: str, path: str, data: dict = None) -> dict:
    resp = session.post(f"{base}/{path.lstrip('/')}", data or {})
    return resp.get("data", resp)


def _get_node(session: Session, base: str) -> str:
    nodes = _get(session, base, "nodes")
    if not nodes:
        err.print("[red]![/red] No Proxmox nodes found.")
        sys.exit(1)
    return nodes[0]["node"]


# ──[ Views ]───────────────────────────────────────────────────────────────────────────


def render_vm_list(session: Session, base: str) -> list:
    node = _get_node(session, base)
    vms = sorted(_get(session, base, f"nodes/{node}/qemu"), key=lambda v: v["vmid"])

    table = Table(title=f"Proxmox · VMs on {node}", header_style="bold cyan", show_lines=False)
    table.add_column("VMID", style="dim", justify="right", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("CPU%", justify="right", no_wrap=True)
    table.add_column("RAM", justify="right", no_wrap=True)
    table.add_column("Disk", justify="right", no_wrap=True)
    table.add_column("Uptime", justify="right", no_wrap=True)

    for vm in vms:
        status = vm.get("status", "unknown")
        color = "green" if status == "running" else "dim"
        cpu_pct = vm.get("cpu", 0) * 100
        mem_used = _fmt_bytes(vm.get("mem", 0))
        mem_max = _fmt_bytes(vm.get("maxmem", 0))
        disk_used = _fmt_bytes(vm.get("disk", 0))
        disk_max = _fmt_bytes(vm.get("maxdisk", 0))
        table.add_row(
            str(vm["vmid"]),
            vm.get("name", "—"),
            f"[{color}]{status}[/{color}]",
            f"{cpu_pct:.1f}%" if status == "running" else "—",
            f"{mem_used}/{mem_max}" if status == "running" else "—",
            f"{disk_used}/{disk_max}",
            _fmt_uptime(vm.get("uptime", 0)) if status == "running" else "—",
        )

    console.print(table)
    return vms


def render_resources(session: Session, base: str) -> None:
    node = _get_node(session, base)
    status = _get(session, base, f"nodes/{node}/status")
    storage_list = _get(session, base, f"nodes/{node}/storage")

    cpu_pct = status.get("cpu", 0) * 100
    mem = status.get("memory", {})
    mem_pct = (mem.get("used", 0) / mem.get("total", 1)) * 100
    swap = status.get("swap", {})
    swap_pct = (swap.get("used", 0) / swap.get("total", 1)) * 100 if swap.get("total") else 0

    lines = [
        f"  [cyan]CPU [/cyan]  {_bar(cpu_pct)}  {_fmt_bytes(status.get('cpuinfo', {}).get('cpus', 0))} vCPUs",
        f"  [cyan]RAM [/cyan]  {_bar(mem_pct)}  {_fmt_bytes(mem.get('used', 0))} / {_fmt_bytes(mem.get('total', 0))}",
    ]
    if swap.get("total"):
        lines.append(
            f"  [cyan]SWAP[/cyan]  {_bar(swap_pct)}  {_fmt_bytes(swap.get('used', 0))} / {_fmt_bytes(swap.get('total', 0))}"
        )

    for pool in storage_list:
        if not pool.get("active"):
            continue
        used = pool.get("used", 0)
        total = pool.get("total", 1)
        pct = (used / total) * 100 if total else 0
        name = pool.get("storage", "?")
        lines.append(
            f"  [cyan]{name:<4}[/cyan]  {_bar(pct)}  {_fmt_bytes(used)} / {_fmt_bytes(total)}"
        )

    console.print(Panel("\n".join(lines), title=f"[bold]Node Resources · {node}[/bold]"))


# ──[ Actions ]─────────────────────────────────────────────────────────────────────────


def do_action(session: Session, base: str, action: str, vmid: int, name: str = "") -> None:
    node = _get_node(session, base)
    label = name or str(vmid)
    color = {"start": "green", "stop": "red", "restart": "yellow"}.get(action, "white")

    if not Confirm.ask(f"[{color}]{action.upper()}[/{color}] VM [cyan]{label}[/cyan] ({vmid})?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    endpoint = f"nodes/{node}/qemu/{vmid}/{ACTION_MAP[action]}"
    try:
        result = _post(session, base, endpoint)
        upid = result if isinstance(result, str) else result.get("data", "submitted")
        console.print(f"[green]✓[/green] {action} submitted — task [dim]{upid}[/dim]")
    except APIError as e:
        err.print(f"[red]![/red] {action} failed (HTTP {e.status}): {e.body}")


def do_snapshot(session: Session, base: str, vmid: int, name: str = "") -> None:
    node = _get_node(session, base)
    label = name or str(vmid)

    snapname = Prompt.ask(f"Snapshot name for [cyan]{label}[/cyan]", default="devkit-snap")
    desc = Prompt.ask("Description", default="")

    if not Confirm.ask(f"Create snapshot [cyan]{snapname}[/cyan] of VM {vmid}?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        _post(session, base, f"nodes/{node}/qemu/{vmid}/snapshot", {"snapname": snapname, "description": desc})
        console.print(f"[green]✓[/green] Snapshot [cyan]{snapname}[/cyan] submitted for VM {vmid}")
    except APIError as e:
        err.print(f"[red]![/red] Snapshot failed (HTTP {e.status}): {e.body}")


def do_interactive(session: Session, base: str) -> None:
    if not sys.stdin.isatty():
        err.print("[red]![/red] --interactive requires a TTY.")
        sys.exit(1)

    vms = render_vm_list(session, base)
    if not vms:
        return

    vmid_str = Prompt.ask("\nEnter VMID")
    try:
        vmid = int(vmid_str)
    except ValueError:
        err.print("[red]![/red] Invalid VMID.")
        sys.exit(1)

    vm_map = {v["vmid"]: v for v in vms}
    if vmid not in vm_map:
        err.print(f"[red]![/red] VMID {vmid} not found.")
        sys.exit(1)

    vm_name = vm_map[vmid].get("name", str(vmid))
    action = Prompt.ask("Action", choices=["start", "stop", "restart", "snapshot"])

    if action == "snapshot":
        do_snapshot(session, base, vmid, vm_name)
    else:
        do_action(session, base, action, vmid, vm_name)


# ──[ CLI ]─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="proxmox.py", description="Proxmox VE homelab module")
    p.add_argument("--resources", action="store_true", help="Show node resource summary only")
    p.add_argument("--interactive", action="store_true", help="Interactive VM action picker")
    p.add_argument("--action", choices=list(ACTION_MAP), help="VM lifecycle action")
    p.add_argument("--vmid", type=int, help="Target VM ID (required for --action, --snapshot)")
    p.add_argument("--snapshot", action="store_true", help="Create VM snapshot")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if (args.action or args.snapshot) and not args.vmid:
        err.print("[red]![/red] --vmid is required with --action and --snapshot.")
        sys.exit(1)

    try:
        secrets.load()
        host         = secrets.require("PROXMOX_HOST")
        user         = secrets.require("PROXMOX_USER")
        token_id     = secrets.require("PROXMOX_TOKEN_ID")
        token_secret = secrets.require("PROXMOX_TOKEN_SECRET")
    except RuntimeError as e:
        err.print(f"[red]![/red] {e}")
        sys.exit(1)

    session = Session(
        headers={"Authorization": f"PVEAPIToken={user}!{token_id}={token_secret}"},
        verify_ssl=False,
    )
    base = f"https://{host}:8006/api2/json"

    try:
        if args.resources:
            render_resources(session, base)
        elif args.action:
            do_action(session, base, args.action, args.vmid)
        elif args.snapshot:
            do_snapshot(session, base, args.vmid)
        elif args.interactive:
            do_interactive(session, base)
        else:
            render_vm_list(session, base)
            render_resources(session, base)
    except APIError as e:
        err.print(f"[red]![/red] Proxmox API error (HTTP {e.status}): {e.body}")
        sys.exit(1)
    except OSError as e:
        err.print(f"[red]![/red] Connection failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
