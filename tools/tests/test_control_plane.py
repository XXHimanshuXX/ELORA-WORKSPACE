"""Hidden IDE controls: repo map, checkpoint/restore, diagnose. No secret files."""

from elora.slime import control_plane, hands


def test_repo_map_reads_symbols(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("class Bridge:\n    pass\n\ndef build():\n    return 1\n", encoding="utf-8")
    res = control_plane.repo_map(query="Bridge", path=str(tmp_path), root=str(tmp_path))
    assert res["ok"] is True
    assert any("Bridge" in f["symbols"] for f in res["files"])


def test_repo_map_matches_multiple_terms(tmp_path):
    src = tmp_path / "app_logic.py"
    src.write_text("def start_server():\n    pass\n\ndef stop_server():\n    pass\n", encoding="utf-8")
    res = control_plane.repo_map(query="app_logic stop_server", path=str(tmp_path), root=str(tmp_path))
    assert res["ok"] is True
    assert len(res["files"]) == 1
    assert "stop_server" in res["files"][0]["symbols"]


def test_repo_map_natural_language_ranking(tmp_path):
    # A focused regression for a natural owner-style question with unrelated words.
    q = "i want to update the london bridge please randomlyyyy"
    impl = tmp_path / "london_bridge.py"
    impl.write_text("class Bridge:\n    pass\n", encoding="utf-8")
    res = control_plane.repo_map(query=q, path=str(tmp_path), root=str(tmp_path))
    assert res["ok"] is True
    assert len(res["files"]) == 1
    assert "london_bridge.py" in res["files"][0]["path"]

def test_repo_map_natural_language_ranking_2(tmp_path):
    impl = tmp_path / "server_bridge.py"
    impl.write_text("class Bridge:\n    pass\n", encoding="utf-8")
    test = tmp_path / "test_server_bridge.py"
    test.write_text("def test_bridge():\n    pass\n", encoding="utf-8")
    
    # "how", "please", etc are stopwords. "bridge" will match both, "server" (if tokenized incorrectly, wait, query has to match tokens in hay).
    # actually, hay is the relative path and symbols.
    # impl hay: "server_bridge.py bridge"
    # test hay: "test_server_bridge.py test_bridge"
    # "bridge" matches both.
    # Both get overlap=1 if query is "how do i update the bridge please".
    q = "how do i update the bridge please"
    res = control_plane.repo_map(query=q, path=str(tmp_path), root=str(tmp_path))
    assert res["ok"] is True
    assert len(res["files"]) == 2
    # Implementation first because it's not a test file.
    assert "server_bridge.py" in res["files"][0]["path"]
    assert "test_server_bridge.py" in res["files"][1]["path"]


def test_repo_map_excludes_elora_quarantine(tmp_path):
    src = tmp_path / "main.py"
    src.write_text("def test_func():\n    pass\n", encoding="utf-8")
    elora_dir = tmp_path / ".elora"
    elora_dir.mkdir(exist_ok=True)
    junk = elora_dir / "junk.py"
    junk.write_text("def test_func():\n    pass\n", encoding="utf-8")
    res = control_plane.repo_map(query="test_func", path=str(tmp_path), root=str(tmp_path))
    assert res["ok"] is True
    assert len(res["files"]) == 1
    assert "main.py" in res["files"][0]["path"]


def test_diagnose_catches_syntax(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def oops(\n", encoding="utf-8")
    res = control_plane.diagnose(str(bad), root=str(tmp_path))
    assert res["ok"] is False
    assert "error" in res


def test_diagnose_javascript_valid(tmp_path):
    js = tmp_path / "ok.js"
    js.write_text("const x = 1;\nconsole.log(x);\n", encoding="utf-8")
    res = control_plane.diagnose(str(js), root=str(tmp_path))
    if res.get("note") == "node unavailable":
        assert res["ok"] is True
        assert res["lang"] == "opaque"
    else:
        assert res["ok"] is True
        assert res["lang"] == "javascript"


def test_diagnose_javascript_invalid(tmp_path):
    js = tmp_path / "bad.js"
    js.write_text("const x = 1\nconsole.log(x", encoding="utf-8")
    res = control_plane.diagnose(str(js), root=str(tmp_path))
    if res.get("note") == "node unavailable":
        assert res["ok"] is True
        assert res["lang"] == "opaque"
    else:
        assert res["ok"] is False
        assert "error" in res


def test_checkpoint_restore_roundtrip(tmp_path):
    f = tmp_path / "keep.py"
    f.write_text("alpha = 1\n", encoding="utf-8")
    snap = control_plane.snapshot_file(str(f), root=str(tmp_path))
    assert snap["ok"] is True
    f.write_text("alpha = 2\n", encoding="utf-8")
    rest = control_plane.restore_file(str(f), root=str(tmp_path))
    assert rest["ok"] is True
    assert f.read_text(encoding="utf-8") == "alpha = 1\n"


def test_restore_selects_requested_checkpoint_hash(tmp_path):
    f = tmp_path / "keep.py"
    f.write_text("alpha = 1\n", encoding="utf-8")
    first = control_plane.snapshot_file(str(f), root=str(tmp_path))
    f.write_text("alpha = 2\n", encoding="utf-8")
    control_plane.snapshot_file(str(f), root=str(tmp_path))
    f.write_text("alpha = 3\n", encoding="utf-8")

    restored = control_plane.restore_file(
        str(f), root=str(tmp_path), sha256=first["sha256"]
    )
    assert restored["ok"] is True
    assert restored["sha256"] == first["sha256"]
    assert f.read_text(encoding="utf-8") == "alpha = 1\n"

    invalid = control_plane.restore_file(str(f), root=str(tmp_path), sha256="bad")
    assert invalid["ok"] is False
    assert f.read_text(encoding="utf-8") == "alpha = 1\n"


def test_checkpoint_refuses_secrets(tmp_path):
    secrets = tmp_path / ".elora" / "secrets"
    secrets.mkdir(parents=True)
    tok = secrets / "github_token"
    tok.write_text("nope", encoding="utf-8")
    res = control_plane.snapshot_file(str(tok), root=str(tmp_path))
    assert res["ok"] is False


def test_code_edit_snapshots_before_write(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("v = 1\n", encoding="utf-8")
    hands.code_edit(str(f), old_string="v = 1", new_string="v = 2", root=str(tmp_path))
    assert f.read_text(encoding="utf-8") == "v = 2\n"
    rest = control_plane.restore_file(str(f), root=str(tmp_path))
    assert rest["ok"] is True
    assert f.read_text(encoding="utf-8") == "v = 1\n"
