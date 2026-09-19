#!/usr/bin/env python3
"""Model Context Protocol (MCP) Server for Azure Time Tracker & Personal Assistant.

Exposes Time Tracking (Azure Table Storage), Financial Data (Purchase-Calc on Cloud Run),
Todos, and Location History as MCP tools for Cline, Claude Desktop, Cursor, and other
MCP-compatible AI coding assistants.
"""

import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Suppress noisy library loggers so they don't pollute stdout (critical for MCP stdio transport)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Load environment variables (.env in time_tracker/ or root)
env_paths = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]
for p in env_paths:
    if p.exists():
        load_dotenv(dotenv_path=p)
        break
load_dotenv()

from storage import TimeTrackerStorage
from purchase_client import PurchaseCalcClient

# Support both mcp 2.x (MCPServer) and mcp 1.x (FastMCP)
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

# Initialize MCP Server
mcp = MCPServer("Azure Time Tracker & Personal Assistant")

# Initialize backend services
storage = TimeTrackerStorage()
pcalc = PurchaseCalcClient()


# -----------------------------------------------------------------------------
# 1. Live Activity Metering Tools ("started X" / "end")
# -----------------------------------------------------------------------------

@mcp.tool()
def start_activity_timer(target_name: str, notes: str = "", overwrite: bool = False) -> str:
    """Start live metering of time for an activity or project (e.g. 'started Website Redesign', 'start Backend Refactor').
    
    The active timer is persisted in Azure Table Storage (ActiveTimers table) so it survives restarts.
    """
    res = storage.start_timer(target_name=target_name, notes=notes, overwrite=overwrite)
    return json.dumps(res)


@mcp.tool()
def stop_activity_timer(notes: str = "") -> str:
    """Stop the active running timer, compute elapsed duration in minutes and hours,
    record into Azure Table Storage (TimeLogs and TimeTargets), and return a completion summary.
    """
    res = storage.stop_timer(notes=notes)
    return json.dumps(res)


@mcp.tool()
def get_active_timer() -> str:
    """Check if a timer is currently active and get its target name, start time, and elapsed minutes/hours."""
    res = storage.get_active_timer()
    if not res:
        return json.dumps({"status": "no_active_timer", "message": "No active timer is currently running."})
    return json.dumps({"status": "active", **res})


@mcp.tool()
def cancel_activity_timer() -> str:
    """Cancel and discard the currently running timer without logging any time to Azure Table Storage."""
    res = storage.cancel_timer()
    return json.dumps(res)


# -----------------------------------------------------------------------------
# 2. Time Tracking & Project Target Tools
# -----------------------------------------------------------------------------

@mcp.tool()
def log_work_time(target_name: str, minutes: int, notes: str = "") -> str:
    """Log a manual amount of time (in minutes) against a project target in Azure Table Storage.
    
    Target will be created automatically if it doesn't already exist.
    """
    res = storage.log_time(target_name=target_name, minutes=minutes, notes=notes)
    return json.dumps(res)


@mcp.tool()
def list_tracked_targets() -> str:
    """List all registered project targets and their total tracked minutes and hours from Azure Table Storage."""
    targets = storage.list_targets()
    return json.dumps({"targets": targets})


@mcp.tool()
def create_tracked_target(target_name: str, description: str = "") -> str:
    """Create a new project target/category in Azure Table Storage."""
    res = storage.create_target(target_name=target_name, description=description)
    return json.dumps(res)


@mcp.tool()
def get_time_summary(target_name: str = "") -> str:
    """Retrieve time summary report (overall total or for a specific project target) from Azure Table Storage."""
    res = storage.get_summary(target_name=target_name or None)
    return json.dumps(res)


# -----------------------------------------------------------------------------
# 3. Financial & Expense Tools (Purchase-Calc on GCP Cloud Run)
# -----------------------------------------------------------------------------

@mcp.tool()
def get_spending_summary(start_date: str, end_date: str, location: str = "") -> str:
    """Query and summarize expenses from purchase-calc on Cloud Run between start_date and end_date (YYYY-MM-DD).
    
    Returns total spent in EUR, transaction count, and breakdown by merchant/location.
    """
    res = pcalc.get_spending_summary(
        start_date=start_date,
        end_date=end_date,
        location=location or None
    )
    return json.dumps(res)


@mcp.tool()
def add_spending(sum_amount: float, location: str, payment_type: str = "", date: str = "") -> str:
    """Record a new purchase or expense entry in purchase-calc in EUR (e.g. 14.50 at 'Prisma')."""
    res = pcalc.add_spending(
        sum_amount=sum_amount,
        location=location,
        payment_type=payment_type or None,
        date=date or None
    )
    return json.dumps(res)


@mcp.tool()
def get_purchases(start_date: str = "", end_date: str = "", origin: str = "") -> str:
    """Fetch purchase transaction records from purchase-calc with optional date range (YYYY-MM-DD) and origin filter."""
    res = pcalc.get_purchases(
        start_date=start_date or None,
        end_date=end_date or None,
        origin=origin or None
    )
    return json.dumps(res)


# -----------------------------------------------------------------------------
# 4. Tasks & Todos Tools (Purchase-Calc on GCP Cloud Run)
# -----------------------------------------------------------------------------

@mcp.tool()
def list_todos(status: str = "all") -> str:
    """List tasks and todos from purchase-calc on Cloud Run.
    
    Parameters:
      status: 'pending' (uncompleted), 'completed', or 'all'. Defaults to 'all'.
    """
    res = pcalc.list_todos(status=status)
    return json.dumps(res)


@mcp.tool()
def create_todo(task: str, due_date: str = "") -> str:
    """Create a new task or todo in purchase-calc on Cloud Run."""
    res = pcalc.create_todo(task=task, due_date=due_date or None)
    return json.dumps(res)


@mcp.tool()
def toggle_todo(todo_id: int) -> str:
    """Toggle or complete a task in purchase-calc on Cloud Run by its numeric ID."""
    res = pcalc.toggle_todo(todo_id=todo_id)
    return json.dumps(res)


@mcp.tool()
def log_time_on_todo(todo_id: int, minutes: int, notes: str = "", mark_completed: bool = False) -> str:
    """Log work time in Azure Table Storage against a purchase-calc todo task, and optionally mark it completed in Cloud Run."""
    todos = pcalc.list_todos()
    matched = next((t for t in todos if isinstance(t, dict) and t.get("id") == todo_id), None)
    task_name = matched.get("task") if matched else f"Task #{todo_id}"

    storage.create_target(task_name, description=f"Imported from purchase-calc todo #{todo_id}")
    time_res = storage.log_time(target_name=task_name, minutes=minutes, notes=notes)

    todo_res = None
    if mark_completed and matched and not matched.get("isCompleted"):
        todo_res = pcalc.toggle_todo(todo_id)

    return json.dumps({
        "status": "success",
        "time_tracking": time_res,
        "todo_updated": todo_res if todo_res else ("Already completed" if matched and matched.get("isCompleted") else "Unchanged")
    })


# -----------------------------------------------------------------------------
# 5. Location & Timeline Tools
# -----------------------------------------------------------------------------

@mcp.tool()
def get_places_visited(start_date: str, end_date: str = "") -> str:
    """Retrieve places and locations visited on a specific day or date range (YYYY-MM-DD) from Google Timeline and purchase-calc."""
    effective_end = end_date or start_date
    timeline_visits = storage.get_timeline_visits(start_date=start_date, end_date=effective_end)
    pcalc_visits = pcalc.get_visits(start_date=start_date, end_date=effective_end)

    combined = []
    seen = set()
    for v in timeline_visits:
        key = (v.get("date"), (v.get("place_name") or "").lower(), v.get("time"))
        if key not in seen:
            seen.add(key)
            combined.append(v)

    for v in pcalc_visits:
        key = (v.get("date"), (v.get("place_name") or "").lower(), v.get("time"))
        if key not in seen:
            seen.add(key)
            combined.append(v)

    combined.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))

    return json.dumps({
        "start_date": start_date,
        "end_date": effective_end,
        "total_visits": len(combined),
        "visits": combined
    })


# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Run over standard input/output (stdio) transport for Cline / Claude Desktop
    mcp.run(transport="stdio")
