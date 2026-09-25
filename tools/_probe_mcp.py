"""Throwaway: prove the real MCP stdio client against live MCP servers."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.core.mcp_client import DEFAULT_SERVERS, describe  # noqa: E402

for name in ("omniroute",):
    print(f"=== {name} ===")
    info = describe(DEFAULT_SERVERS[name], timeout=90)
    print("reachable:", info["reachable"])
    print("protocol:", info["protocol_version"])
    print("server_info:", info["server_info"])
    print("tool_count:", info["tool_count"])
    print("error:", info["error"])
    print("first_20:", info["tools"][:20])
