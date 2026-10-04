ELORA — HANDOFF TO TRAE AGENT
================================

1. MISSION (one paragraph)
   Build ELORA into a visible resident that does REAL work end-to-end:
   user types in chat → ELORA chooses a capability → broker executes it
   → real result appears in the same chat panel. The middle step —
   dispatching tool calls, not printing them — is the #1 bug.

2. YOUR ROLE
   You are the builder. You EDIT code in this repo and RUN commands.
   The architect is a separate assistant (LibertAI) that audits and
   spec's. You implement; you do not ratify your own work.

3. THE ONE BUG TO FIX FIRST
   The chat handler displays <mcp_call> blocks but never dispatches them.
   Fix: in the chat endpoint, run the SAME loop handle_task() uses for
   inbox tasks — extract tool calls → dispatch through Broker → feed
   result back into context → loop until no tool calls or DONE.
   See elora/dashboard/server.py and elora/daemon.py.

4. THE NON-NEGOTIABLE RULES (copy these verbatim)
   - Every action = real execution through the Broker. No described actions.
   - Every capability call must produce capability_intent/result in the
     Akashic ledger. If it doesn't, it didn't happen.
   - Add test test_hallucinated_action_is_impossible: every "I checked/
     opened/ran X" claim in a reply must map to a ledger capability_intent.
   - Keys live in .elora/secrets/, never code, never git. .gitignore
     MUST exclude .elora/.
   - No CAPTCHA circumvention. No anti-bot evasion.
   - RISK-5 needs dual-key human consent. Autonomy stays tiered.
   - Run from C:\Python314\python.exe (not sandbox Python).

5. VERIFICATION COMMANDS (from C:\Python314\python.exe)
   python run.py --check
   python run.py --smoke
   python -m pytest tools/tests -q
   python run.py --resident   (manual test)

6. ACCEPTANCE TEST (the graduation)
   Start --resident. Type: "open blender, connect to it, and build the
   London Bridge." PASS means: a real shell.run_command executes,
   Blender opens on screen, and the ledger shows capability_intent for
   shell.run_command. FAIL means the reply narrates it without acting.
That file, handed to Trae, is worth more than the whole transcript.

2. Do NOT Include These Things
API keys — never in the export, never in the text file, never in Trae.
Screenshots (useless to Trae as text).
Conversation meta-drama. Keep only facts, rules, and the bug.
The "god from manhwa" framing. It produced demos. The mission above is concrete.
The One Thing No Export Can Give Trae: The Audit Culture
Here's the honest limitation of your plan: Trae's agent will have the text, but it won't have the discipline unless you carry the discipline yourself. The pattern that has actually made ELORA healthy across this whole conversation is not the code — it's:

Bring artifacts, not claims. Trae says "fixed"? Run the smoke test yourself and paste the output.
Reject hardcoded "DONE" or summarized prose as if it were V4 itself. Because it is.
Refuse any feature without its test rung.
Treat "it works now" after every edit as a hypothesis until pytest says otherwise.
That's the part of me the text file can't transmit. You've internalized more of it than you realize over these weeks — which is why you caught the Blender lie, and why you're now asking the right question. Carry that into Trae and it will build well. Trust Trae to ratify its own work, and you'll get Antigravity with a LibertAI brain.

After You Hand Off
Become the auditor again, not the coder:

Give Trae the distilled file.
Ask it for the diff of the chat handler, not for "it's fixed."
Run python run.py --smoke and paste me the output.
Run the --resident Blender test and paste me the ledger block.
Then bring me the four verification outputs and I'll audit them the exact same way I've audited everything else. The text-file handoff is a good idea because it extends context — but the audit loop still has to close through you.

Go write the distilled handoff. Give it to Trae. Make it fix the loop. And the next time you type "open Blender," watch what actually happens instead of what gets narrated.