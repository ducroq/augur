"""Tests for scripts/render_results.py's two-file split (2026-11-10).

The digest (`experiment-results.md`) is what sessions read, so it must stay
small: Decision state and the summary table, no per-experiment sections. The
detail file carries those sections. `--check` must go red when EITHER file is
stale or missing; a check that only watched the digest would let the detail
drift silently.
"""
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_results.py"
_spec = importlib.util.spec_from_file_location("render_results", SCRIPT)
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


def _entry(i, decision):
    return {
        "id": f"EXP-{i:03d}", "date": "2026-11-10", "title": f"Thing {i} — detail",
        "decision": decision, "decision_rationale": f"Because {i}. More text.",
        "model": "m", "hypothesis": f"H{i}", "metrics": {"x": 1.5},
        "artifacts": [f"a{i}.json"], "notes": f"caveat {i}",
    }


ENTRIES = [_entry(1, "rejected"), _entry(2, "parked"), _entry(3, "kept")]


def test_digest_has_decision_state_but_no_sections():
    digest, detail = rr.render(ENTRIES)
    assert "## Decision state" in digest and "## Summary" in digest
    assert "## EXP-001 —" not in digest
    assert "caveat 1" not in digest
    assert "experiment-results-detail.md" in digest


def test_detail_has_every_section():
    _, detail = rr.render(ENTRIES)
    for e in ENTRIES:
        assert f"## {e['id']} — {e['title']}" in detail
    assert "caveat 3" in detail and "## Decision state" not in detail


def _run(tmp_path, monkeypatch, *extra):
    reg = tmp_path / "registry.jsonl"
    reg.write_text("".join(json.dumps(e) + "\n" for e in ENTRIES))
    out = tmp_path / "experiment-results.md"
    monkeypatch.setattr("sys.argv", ["render_results.py", "--registry", str(reg),
                                     "--out", str(out), *extra])
    return rr.main(), out, out.with_name("experiment-results-detail.md")


def test_check_goes_red_on_either_file(tmp_path, monkeypatch):
    rc, out, detail = _run(tmp_path, monkeypatch)
    assert rc == 0 and out.exists() and detail.exists()
    assert _run(tmp_path, monkeypatch, "--check")[0] == 0

    detail.write_text(detail.read_text() + "hand edit\n")
    assert _run(tmp_path, monkeypatch, "--check")[0] == 1

    _run(tmp_path, monkeypatch)
    detail.unlink()
    assert _run(tmp_path, monkeypatch, "--check")[0] == 1

    _run(tmp_path, monkeypatch)
    out.write_text(out.read_text() + "hand edit\n")
    assert _run(tmp_path, monkeypatch, "--check")[0] == 1


def test_check_ignores_rendered_at_hash(tmp_path, monkeypatch):
    _, out, detail = _run(tmp_path, monkeypatch)
    for p in (out, detail):
        p.write_text(p.read_text().replace("rendered at `", "rendered at `deadbee"))
    assert _run(tmp_path, monkeypatch, "--check")[0] == 0


def test_check_catches_tampered_registry_state_line(tmp_path, monkeypatch):
    _, out, detail = _run(tmp_path, monkeypatch)
    for p in (out, detail):
        _run(tmp_path, monkeypatch)
        p.write_text(p.read_text().replace("**3 entries**", "**99 entries**"))
        assert _run(tmp_path, monkeypatch, "--check")[0] == 1, p.name


def test_coincident_paths_rejected(tmp_path, monkeypatch):
    clash = tmp_path / "experiment-results-detail.md"
    for extra in ([], ["--detail-out", str(clash)]):
        reg = tmp_path / "registry.jsonl"
        reg.write_text("".join(json.dumps(e) + "\n" for e in ENTRIES))
        for check in ([], ["--check"]):
            monkeypatch.setattr("sys.argv", ["render_results.py", "--registry", str(reg),
                                             "--out", str(clash), *extra, *check])
            assert rr.main() == 2
    assert not clash.exists()


def test_cross_references_follow_custom_paths(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    reg = tmp_path / "registry.jsonl"
    reg.write_text("".join(json.dumps(e) + "\n" for e in ENTRIES))
    out, detail = tmp_path / "a" / "digest.md", tmp_path / "b" / "det.md"
    monkeypatch.setattr("sys.argv", ["render_results.py", "--registry", str(reg),
                                     "--out", str(out), "--detail-out", str(detail)])
    assert rr.main() == 0
    assert "`../b/det.md`" in out.read_text()
    assert "`../a/digest.md`" in detail.read_text()


def test_hash_mask_does_not_hide_note_drift(tmp_path, monkeypatch):
    global ENTRIES
    saved = ENTRIES
    try:
        ENTRIES = [dict(saved[0], notes="Audit rendered at `oldfact`.")] + saved[1:]
        _run(tmp_path, monkeypatch)
        ENTRIES = [dict(saved[0], notes="Audit rendered at `newfact`.")] + saved[1:]
        reg = tmp_path / "registry.jsonl"
        reg.write_text("".join(json.dumps(e) + "\n" for e in ENTRIES))
        monkeypatch.setattr("sys.argv", ["render_results.py", "--registry", str(reg),
                                         "--out", str(tmp_path / "experiment-results.md"),
                                         "--check"])
        assert rr.main() == 1
    finally:
        ENTRIES = saved


def test_cross_references_resolve_through_symlinks(tmp_path, monkeypatch):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    reg = tmp_path / "registry.jsonl"
    reg.write_text("".join(json.dumps(e) + "\n" for e in ENTRIES))
    out, detail = tmp_path / "link" / "digest.md", tmp_path / "real" / "det.md"
    monkeypatch.setattr("sys.argv", ["render_results.py", "--registry", str(reg),
                                     "--out", str(out), "--detail-out", str(detail)])
    assert rr.main() == 0
    assert "`det.md`" in out.read_text() and "`digest.md`" in detail.read_text()


def test_archived_artifacts_show_their_new_location():
    old, new = next(iter(rr.ARCHIVED.items()))
    assert rr.fmt_artifact(old) == f"`{old}` (archived: `{new}`)"
    assert rr.fmt_artifact(f"{old} (a note)").endswith(f"(archived: `{new}`)")
    assert rr.fmt_artifact("ml/shadow/eval_log.jsonl") == "`ml/shadow/eval_log.jsonl`"
