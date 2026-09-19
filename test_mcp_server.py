#!/usr/bin/env python3
"""Test script for the Model Context Protocol (MCP) Server.

Verifies that the MCP server initializes correctly, registers all expected tools,
and executes tool calls as expected.
"""

import asyncio
import json
from mcp_server import mcp

EXPECTED_TOOLS = [
    # Time Tracking - Live Timing
    "start_activity_timer",
    "stop_activity_timer",
    "get_active_timer",
    "cancel_activity_timer",
    # Time Tracking - Manual & Targets
    "log_work_time",
    "list_tracked_targets",
    "create_tracked_target",
    "get_time_summary",
    # Finance & Expenses (Purchase-Calc)
    "get_spending_summary",
    "add_spending",
    "get_purchases",
    # Tasks & Todos (Purchase-Calc)
    "list_todos",
    "create_todo",
    "toggle_todo",
    "log_time_on_todo",
    # Location History
    "get_places_visited"
]


async def run_tests():
    print("=" * 65)
    print(" Testing Azure Time Tracker & Assistant MCP Server")
    print("=" * 65)

    # 1. Verify registered tools
    print("\n1. Verifying tool registrations...")
    tools = await mcp.list_tools()
    registered_tool_names = [t.name for t in tools]
    print(f"Total tools registered: {len(registered_tool_names)}")

    missing = [name for name in EXPECTED_TOOLS if name not in registered_tool_names]
    if missing:
        print(f"FAILED: Missing tools: {missing}")
        return False
    print("SUCCESS: All 16 expected tools registered properly.")

    # 2. Test get_active_timer
    print("\n2. Testing MCP tool call: 'get_active_timer'...")
    res = await mcp.call_tool("get_active_timer", {})
    text = res.content[0].text
    print(f"Result: {text}")
    data = json.loads(text)
    assert "status" in data
    print("SUCCESS: 'get_active_timer' returned valid JSON.")

    # 3. Test list_tracked_targets
    print("\n3. Testing MCP tool call: 'list_tracked_targets'...")
    res = await mcp.call_tool("list_tracked_targets", {})
    text = res.content[0].text
    data = json.loads(text)
    assert "targets" in data
    print(f"Found {len(data['targets'])} targets in Azure Table Storage.")
    print("SUCCESS: 'list_tracked_targets' executed successfully.")

    # 4. Test get_spending_summary (Finance)
    print("\n4. Testing MCP tool call: 'get_spending_summary'...")
    res = await mcp.call_tool("get_spending_summary", {
        "start_date": "2026-01-01",
        "end_date": "2026-12-31"
    })
    text = res.content[0].text
    data = json.loads(text)
    print(f"Spending summary query result status: {data.get('totalSpent', 'N/A')} EUR")
    print("SUCCESS: Financial MCP tool executed successfully.")

    print("\n" + "=" * 65)
    print(" ALL MCP SERVER CHECKS PASSED! Ready for Cline integration.")
    print("=" * 65)
    return True


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    if not success:
        exit(1)

