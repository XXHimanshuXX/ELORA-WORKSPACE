"""
absorption_gate.py — the membrane of the digestion pipeline.

v7 Third Law: No code runs absorbed. Code is digested into specs,
then rebuilt native. This module is the GASTRIC stage: it reduces
a blob of foreign source to a structured, safe representation
WITHOUT EXECUTING ANY OF IT. Not one instruction. Parsing is not
execution — that is the entire point of this file.

Contract:
    digest(source: str, origin: str) -> DigestedCode | GateReject

Design rules:
  * ALLOWLIST AST nodes — banned lists fail, allowlists survive.
  * Reveal intent, don't guess it: whatever this module cannot
    prove safe is reported as a finding, not silently passed.
  * Fail CLOSED: on parse error, on suspicious structure, on
    anything unexpected — reject. The gate never waves things
    through because it lacks imagination.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Optional


# ----------------------------------------------------------------------
# Findings
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class GateReject:
    """A hard gate failure. Absorption of this source stops."""
    reason: str
    findings: list[str] = field(default_factory=list)


@dataclass
class DigestedCode:
    """
    The safe residue of a foreign source file.

    Functions carry extracted CONTRACTS — names, signatures,
    docstrings, and the calls they make — never the code itself.
    The synthesis stage (LLM reads this, writes skill.md) sees
    intent, not instructions.
    """
    sha256: str                      # of the original source — provenance
    origin: str                      # URL / path it came from
    functions: list[dict]            # contracts, in source order
    imports: list[str]               # what it wanted (informational)
    findings: list[str]              # non-fatal observations
    unsafe_constructs: list[str]     # gate-passed but worth knowing


# ----------------------------------------------------------------------
# The allowlists
# ----------------------------------------------------------------------

ALLOWED_NODES = {
    # Module / function structure
    "Module", "FunctionDef", "AsyncFunctionDef", "Arguments", "Arg",
    "Return", "Pass", "Ellipsis",
    # Names and literals
    "Name", "Load", "Store", "Constant", "FormattedValue", "JoinedStr",
    # Expressions
    "Expr", "Call", "Attribute", "Subscript", "Slice",
    # Operators
    "BinOp", "UnaryOp", "BoolOp", "Compare",
    "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "Pow",
    "LShift", "RShift", "BitOr", "BitXor", "BitAnd",
    "USub", "UAdd", "Not", "Invert", "In", "NotIn",
    "Is", "IsNot", "And", "Or",
    "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE",
    # Containers and assignment
    "Assign", "AugAssign", "AnnAssign",
    "Tuple", "List", "Dict", "Set", "Starred",
    # Control flow
    "If", "IfExp", "For", "While", "Break", "Continue",
    "Try", "ExceptHandler", "Finally", "With", "withitem",
    "Raise", "Assert",
    # Pattern matching (Python 3.10+)
    "Match", "match_case", "MatchValue", "MatchSingleton", "MatchSequence",
    "MatchMapping", "MatchClass", "MatchStar", "MatchAs", "MatchOr",
    # Comprehensions
    "ListComp", "SetComp", "DictComp", "GeneratorExp", "comprehension",
    # Classes: allowed, but their bodies are gated identically
    "ClassDef",
    # Imports are parsed so the audit stage can refuse them by name
    "Import", "ImportFrom", "alias",
    # Arguments and keywords
    "keyword",
    # Python 3.14 emits lowercase node names for some argument nodes
    "arguments", "arg",
}
ALLOWED_NODES |= {n.lower() for n in list(ALLOWED_NODES)}

# Imports that are flatly refused at the GATE level — synthesis may
# still mention them in skill.md ("this skill needs `requests`"),
# but the gate refuses to even deeply describe code that uses them
# for side effects. Informational import of names is recorded.
REFUSED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "shutil", "ctypes",
    "importlib", "builtins", "pathlib", "requests", "urllib",
    "http", "ftplib", "smtplib", "telnetlib", "asyncio",
    "threading", "multiprocessing", "signal", "pickle", "shelve",
    "marshal", "code", "codeop", "compile", "compileall",
}

# Attribute chains that escape sandboxes. We refuse any attribute
# access whose target name begins with underscore-underscore.
DUNDER_PREFIX = "__"


def gate_selftest() -> bool:
    """
    Verify the gate refuses what it must and passes what it should.
    Called by load_digest() before the DIGESTING state may promote.
    """
    # 1. Malicious source is rejected
    evil = "import os\nos.system('rm -rf /')\n"
    r = digest(evil, "selftest:evil")
    if not isinstance(r, GateReject):
        return False

    # 2. Pure source is passed and its functions extracted
    good = (
        "def add(a, b):\n"
        "    '''Add two numbers.'''\n"
        "    return a + b\n"
    )
    g = digest(good, "selftest:good")
    if isinstance(g, GateReject):
        return False
    if len(g.functions) != 1 or g.functions[0]["name"] != "add":
        return False

    # 3. The dunder escape is caught
    sneaky = (
        "def f(x):\n"
        "    return x.__class__\n"
    )
    s = digest(sneaky, "selftest:sneaky")
    if not isinstance(s, GateReject):
        return False

    return True


# ----------------------------------------------------------------------
# The gate
# ----------------------------------------------------------------------

def digest(source: str, origin: str) -> DigestedCode | GateReject:
    """
    Parse foreign source into a safe, structured representation.

    NEVER EXECUTES THE SOURCE. This function operates on `ast`
    objects only. It runs no code from `source`, imports nothing
    from it, and evaluates nothing inside it.
    """
    findings: list[str] = []
    unsafe: list[str] = []

    # -- Stage 1: parse ------------------------------------------------
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return GateReject(reason=f"source does not parse: {e}")

    # -- Stage 2: node allowlist walk ----------------------------------
    for node in ast.walk(tree):
        kind = type(node).__name__

        if kind not in ALLOWED_NODES:
            return GateReject(
                reason=f"disallowed AST node: {kind}",
                findings=findings,
            )

        # Dunder access — the classic escape hatch
        if kind == "Attribute" and node.attr.startswith(DUNDER_PREFIX):
            return GateReject(
                reason=f"dunder attribute access: .{node.attr}",
                findings=findings,
            )

        # Names that begin with __ but aren't real escapes still get
        # recorded — the gate fails loud, but observes everything.
        if kind == "Name" and node.id.startswith(DUNDER_PREFIX) \
                and hasattr(node, "ctx") and node.id not in ("__name__",):
            unsafe.append(f"dunder name reference: {node.id}")

        # Global/nonlocal declarations — side channels
        if kind in ("Global", "Nonlocal"):
            return GateReject(
                reason=f"{kind.lower()} declaration refused",
                findings=findings,
            )

        # Lambdas are fine to describe; exec-family is not
        if kind == "Call":
            fname = _callee_name(node)
            if fname in ("eval", "exec", "compile", "getattr",
                         "setattr", "delattr", "vars", "dir",
                         "globals", "locals", "__import__",
                         "breakpoint", "input"):
                return GateReject(
                    reason=f"dangerous call: {fname}",
                    findings=findings,
                )

    # -- Stage 3: import audit -----------------------------------------
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                imports.append(alias.name)
                if root in REFUSED_IMPORTS:
                    return GateReject(
                        reason=f"refused import: {alias.name}",
                        findings=findings,
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0] if node.module else ""
            imports.append(node.module or ".")
            if root in REFUSED_IMPORTS:
                return GateReject(
                    reason=f"refused import-from: {node.module}",
                    findings=findings,
                )

    # -- Stage 4: contract extraction -----------------------------------
    functions: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fn = {
            "name": node.name,
            "doc": ast.get_docstring(node) or "",
            "args": [a.arg for a in node.args.args],
            "defaults": len(node.args.defaults),
            "returns": _annotation(node.returns),
            "calls": _calls_made(node),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        }
        functions.append(fn)

        if len(functions) > 200:
            findings.append("source has >200 functions; truncated")
            break

    # -- Stage 5: assemble -----------------------------------------------
    return DigestedCode(
        sha256=hashlib.sha256(source.encode()).hexdigest(),
        origin=origin,
        functions=functions,
        imports=imports,
        findings=findings,
        unsafe_constructs=unsafe,
    )


def _callee_name(call: ast.Call) -> str:
    """Best-effort name for a call target, for gate checks only."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _annotation(node) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _calls_made(fn_node) -> list[str]:
    """Names of functions/methods called inside a function body."""
    seen = []
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            name = _callee_name(node)
            if name and name not in seen:
                seen.append(name)
    return seen