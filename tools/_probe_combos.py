"""Throwaway: why does omniroute_list_combos fail?"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.core.mcp_client import DEFAULT_SERVERS, McpStdioServer  # noqa: E402

for args in ({}, {"includeMetrics": True}, {"includeMetrics": False}):
    with McpStdioServer(DEFAULT_SERVERS["omniroute"], timeout_s=90) as client:
        result = client.call_tool("omniroute_list_combos", args)
        print(f"args={args}")
        print(f"  protocol_ok={result.protocol_ok} is_error={result.is_error}")
        print(f"  text={result.text[:600]!r}")
        print()

with McpStdioServer(DEFAULT_SERVERS["omniroute"], timeout_s=90) as client:
    result = client.call_tool("omniroute_get_health", {})
    print("health text:", result.text[:700])
