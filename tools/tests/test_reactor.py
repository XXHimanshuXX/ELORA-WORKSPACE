"""
test_reactor.py — full task-loop CI with zero model, zero network.

This is WIRE-2's proof: the entire path
    inbox file → brain → tool call → broker → armored run → vault → akashic
runs hermetically. Manual end-to-end runs are no longer the only
inspection of the loop.
"""
import os
import time

import pytest

from elora.brain import ScriptedBrain, extract_tool_calls
from elora.core.broker import Broker, SkillToken
from elora.core.capabilities import Tier
from elora.core.metabolism import Metabolism, State
from conftest import FakeLedger, FakeVault


@pytest.fixture
def loop(tmp_path):
    """A fully wired system under test, all fakes where reality
    would be expensive."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"),
                            ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"))
    brain = ScriptedBrain(script=[])      # filled per-test
    from elora.daemon import Daemon
    d = Daemon(brain=brain, broker=broker, metabolism=metabolism,
               ledger=ledger, vault=vault, inbox_dir=str(inbox))
    d.skills_token = SkillToken(skill_id="reactor-test", tier=Tier.TRUSTED,
                                workspace=str(tmp_path / "ws"), issued_at=0.0)
    yield {"daemon": d, "brain": brain, "ledger": ledger,
           "vault": vault, "inbox": inbox, "metabolism": metabolism}
    metabolism.shutdown()


def drop(inbox, text, name="task.txt"):
    (inbox / name).write_text(text)


class TestFullLoop:

    def test_happy_path_end_to_end(self, loop):
        loop["brain"].script = [
            '<mcp_call server="elora" tool="shell.run_command">'
            '{"command": "echo hello > proof.txt"}</mcp_call>',
            "DONE",
        ]
        drop(loop["inbox"], "run a test command")
        tasks = loop["daemon"].tick()

        assert tasks[0].state.name == "DONE"
        # The loop is honest: ledger saw task lifecycle, intent AND result
        kinds = [e["kind"] for e in loop["ledger"].events]
        assert "task_started" in kinds
        assert "capability_intent" in kinds
        assert "capability_result" in kinds
        assert "task_finished" in kinds

    def test_real_names_injected_v4_regression(self, loop):
        """The V4 killer bug, now a permanent regression test: the
        real capability names MUST appear in every system prompt."""
        drop(loop["inbox"], "anything")
        loop["daemon"].tick()
        assert loop["brain"].saw_capability_names(
            ["shell.run_command", "generate.image", "fs.write"])

    def test_hallucinated_name_fails_gracefully(self, loop):
        """A model saying execute_command survives to try again —
        the rejection reason teaches it the real name."""
        loop["brain"].script = [
            '<mcp_call server="elora" tool="execute_command">'
            '{"command": "echo hi"}</mcp_call>',
            '<mcp_call server="elora" tool="shell.run_command">'
            '{"command": "echo corrected"}</mcp_call>',
            "DONE",
        ]
        drop(loop["inbox"], "test command")
        tasks = loop["daemon"].tick()
        assert tasks[0].state.name == "DONE"
        # The hallucination is in the trace, identified and survived
        tr = str(tasks[0].trace)
        assert "unknown capability" in tr or "rejected" in tr

    def test_malformed_json_does_not_crash(self, loop):
        loop["brain"].script = [
            '<mcp_call server="elora" tool="shell.run_command">'
            '{"command": "echo hi"</mcp_call>',        # broken JSON
            "DONE",
        ]
        drop(loop["inbox"], "test malformed")
        tasks = loop["daemon"].tick()
        assert tasks[0].state.name == "DONE"

    def test_iteration_budget_stops_runaway(self, loop):
        loop["brain"].script = [
            '<mcp_call server="elora" tool="shell.run_command">'
            '{"command": "echo again"}</mcp_call>',
        ] * 50                                                       # never DONE
        drop(loop["inbox"], "runaway test")
        tasks = loop["daemon"].tick()
        assert tasks[0].state.name == "FAILED"
        assert tasks[0].iterations <= 9      # max_iterations + 1

    def test_urgency_orders_execution(self, loop, tmp_path):
        drop(loop["inbox"], "do this eventually", "low.txt")
        drop(loop["inbox"], "handle this URGENT now", "high.txt")
        # ScriptedBrain doesn't care; the scheduler does.
        loop["brain"].script = ["DONE", "DONE"]
        tasks = loop["daemon"].tick()
        urgencies = [t.event.urgency for t in tasks]
        assert urgencies == sorted(urgencies, reverse=True)

    def test_claimed_file_removed_on_done(self, loop):
        loop["brain"].script = ["DONE"]
        drop(loop["inbox"], "quick one")
        loop["daemon"].tick()
        processing = loop["inbox"] / ".processing"
        assert not any(processing.iterdir()) if processing.exists() else True

    def test_episodes_are_content_addressed(self, loop):
        loop["brain"].script = [
            '<mcp_call server="elora" tool="ledger.verify">{}</mcp_call>',
            '<mcp_call server="elora" tool="vault.save">'
            '{"content": "unique-alpha"}</mcp_call>',
            "DONE"]
        drop(loop["inbox"], "distinctness test")
        loop["daemon"].tick()
        episodes = loop["vault"].episodes
        assert len(set(episodes)) == len(episodes)   # no duplicates
        assert "iter" in episodes[-2]                 # real content, real shape


class TestExtractToolCalls:
    def test_multiple_calls_extracted(self):
        reply = (
            'First: <mcp_call server="elora" tool="a">{"x": 1}</mcp_call>'
            'Then: <mcp_call server="elora" tool="b">{"y": 2}</mcp_call>'
        )
        calls, failures = extract_tool_calls(reply)
        assert len(calls) == 2
        assert calls[0]["tool"] == "a"
        assert calls[1]["args"] == {"y": 2}
        assert not failures

    def test_malformed_reported(self):
        reply = '<mcp_call server="elora" tool="a">{"x": </mcp_call>'
        calls, failures = extract_tool_calls(reply)
        assert calls == []
        assert len(failures) == 1