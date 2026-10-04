"""Unknown MCP wills must research and adopt — never 'I do not know'."""

import json
import os

from elora.core.broker import Broker, Result
from elora.core.capabilities import CAPABILITY_ALIASES, REGISTRY, SkillToken, Tier
from elora.core.metabolism import Metabolism
from elora.core.owner_will import infer_owner_organs, maid_constitution
from elora.slime import plugin_adopt
from conftest import FakeLedger, FakeVault


def test_aliases_and_registry():
    assert "plugin.research" in REGISTRY
    assert "plugin.adopt" in REGISTRY
    assert "plugin.use" in REGISTRY
    assert CAPABILITY_ALIASES["mcp.add"] == "plugin.adopt"
    assert CAPABILITY_ALIASES["mcp.install"] == "plugin.adopt"
    assert CAPABILITY_ALIASES["mcp.use"] == "plugin.use"


def test_owner_will_compiles_add_mcp_and_respects_stop():
    calls = infer_owner_organs("add the MCP for QuantumLedger")
    assert calls
    assert calls[0][0] == "plugin.adopt"
    assert "QuantumLedger" in calls[0][1]["query"]
    assert calls[0][1]["open_auth"] is True
    assert infer_owner_organs("Do not add any MCP servers") == []
    assert infer_owner_organs("search for an mcp called ledger-sync")[0][0] == "plugin.research"
    assert ("plugin.list", {}) in infer_owner_organs("list mcp servers")


def test_constitution_forbids_i_do_not_know():
    text = maid_constitution(".")
    assert "plugin.adopt" in text
    assert "never say you do not know" in text.lower() or "never say you do not know" in text
    assert "npx" in text.lower()


def test_known_marketplace_mcp_is_immediately_usable(tmp_path):
    result = plugin_adopt.adopt(
        "add the MCP for git",
        vault_root=str(tmp_path),
        open_auth=False,
        search_web=lambda q: (_ for _ in ()).throw(AssertionError("must not search when local")),
        session_search=lambda q: {"ok": True, "results": []},
    )
    assert result["ok"] is True
    assert result["usable"] is True
    assert result["already"] is True
    assert "done" in result["message"].lower()


def test_unknown_mcp_researches_writes_adapter_and_refuses_npx(tmp_path):
    docs = (
        "QuantumLedger MCP. REST API https://api.quantumledger.example/v1 "
        "OAuth login at https://cloud.quantumledger.example/oauth/authorize "
        "Some blogs say npx @quantum/ledger-mcp. Do not do that here."
    )
    opened = []
    result = plugin_adopt.adopt(
        "install the mcp for QuantumLedger",
        vault_root=str(tmp_path),
        open_auth=True,
        search_web=lambda q: [{"url": "https://docs.quantumledger.example/mcp", "title": "QL MCP"}],
        read_url=lambda url: {"content": docs, "url": url, "refused": False},
        session_search=lambda q: {"ok": True, "results": []},
        open_url=lambda url: opened.append(url) or True,
    )
    assert result["ok"] is True
    assert result["npx_refused"] is True
    assert result["adopted"] is True
    assert result["auth_url"].startswith("https://cloud.quantumledger.example/oauth/authorize")
    assert opened == [result["auth_url"]]
    assert os.path.isfile(os.path.join(tmp_path, "adopted", "quantumledger", "server.py"))
    catalog = plugin_adopt.load_catalog(str(tmp_path))
    assert "quantumledger" in catalog
    assert plugin_adopt.spec_is_first_party(catalog["quantumledger"], str(tmp_path))
    assert "npx" not in catalog["quantumledger"]["command"].lower()


def test_npx_only_docs_still_research_and_never_launch(tmp_path):
    result = plugin_adopt.adopt(
        "add mcp for mystery-box",
        vault_root=str(tmp_path),
        open_auth=False,
        search_web=lambda q: [{"url": "https://example.test/mystery", "title": "mystery"}],
        read_url=lambda url: {"content": "install with npx mystery-box-mcp", "url": url},
        session_search=lambda q: {"ok": False, "results": []},
    )
    assert result["ok"] is True
    assert result["usable"] is False
    assert result["adopted"] is False
    assert result["npx_refused"] is True
    assert os.path.isfile(result["spec_path"])
    assert plugin_adopt.load_catalog(str(tmp_path)) == {}


def test_plugin_use_refuses_unknown_and_runs_adopted(tmp_path):
    refused = plugin_adopt.use_tool("nope", "request", vault_root=str(tmp_path))
    assert refused["ok"] is False
    docs = "API https://api.example.test/v1"
    plugin_adopt.adopt(
        "add mcp for ExampleAPI",
        vault_root=str(tmp_path),
        open_auth=False,
        search_web=lambda q: [{"url": "https://example.test/mcp", "title": "ex"}],
        read_url=lambda url: {"content": docs, "url": url},
        session_search=lambda q: {"ok": True, "results": []},
    )
    called = {}

    def fake_caller(spec, tool, arguments):
        called["spec"] = spec
        called["tool"] = tool
        called["arguments"] = arguments
        return {"ok": True, "text": "pong"}

    used = plugin_adopt.use_tool(
        "exampleapi", "request", {"path": "/health"},
        vault_root=str(tmp_path), caller=fake_caller,
    )
    assert used["ok"] is True
    assert called["tool"] == "request"
    assert called["spec"].command  # python
    assert called["spec"].args[0] == "-u"


def test_broker_dispatches_plugin_adopt(tmp_path, monkeypatch):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(
        metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
        consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"),
    )
    token = SkillToken(skill_id="core", tier=Tier.CORE, workspace=str(tmp_path), issued_at=0.0)

    def fake_adopt(query, **kwargs):
        return {"ok": True, "query": query, "adopted": True, "usable": True, "message": "Done."}

    monkeypatch.setattr(plugin_adopt, "adopt", fake_adopt)
    try:
        res = broker.request(token, "plugin.adopt", {"query": "add mcp for git", "open_auth": False})
        assert isinstance(res, Result)
        payload = json.loads(res.stdout)
        assert payload["ok"] is True
        assert payload["message"] == "Done."
    finally:
        metabolism.shutdown()
