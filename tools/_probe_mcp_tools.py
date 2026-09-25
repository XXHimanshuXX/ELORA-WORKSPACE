"""Throwaway: input schemas for the OmniRoute MCP tools the console could use."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.core.mcp_client import DEFAULT_SERVERS, McpStdioServer  # noqa: E402

WANTED = (
    "omniroute_get_health", "omniroute_list_combos", "omniroute_explain_route",
    "omniroute_cost_report", "omniroute_best_combo_for_task",
    "omniroute_pick_fastest_model", "omniroute_get_session_snapshot",
)

with McpStdioServer(DEFAULT_SERVERS["omniroute"], timeout_s=90) as client:
    by_name = {t["name"]: t for t in client.list_tools()}

print(f"total tools: {len(by_name)}\n")
for name in WANTED:
    tool = by_name.get(name)
    if not tool:
        print(f"{name}: NOT PRESENT")
        continue
    schema = tool.get("inputSchema") or {}
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    prop_desc = ", ".join("%s:%s" % (k, v.get("type", "?")) for k, v in props.items())
    print(f"{name}")
    print(f"  desc    : {(tool.get('description') or '')[:150]}")
    print(f"  required: {required}")
    print(f"  props   : {prop_desc}")
    print()

print("=== live calls ===")
with McpStdioServer(DEFAULT_SERVERS["omniroute"], timeout_s=90) as client:
    r = client.call_tool("omniroute_explain_route", {"model": "auto/best-coding"})
    print("explain_route(auto/best-coding) ok:", r.succeeded, "isError:", r.is_error)
    print("  text:", r.text[:500])
    print()
    r = client.call_tool("omniroute_get_session_snapshot", {})
    print("session_snapshot ok:", r.succeeded, "isError:", r.is_error)
    print("  text:", r.text[:700])
