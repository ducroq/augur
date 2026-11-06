"""Tests for scripts/audit_registry.py's backlog Method-body parser.

Check 5 proves by sha256 that no pre-committed Method was edited after its
result landed, which is the mechanism that makes docs/experiment-backlog.md a
pre-commitment rather than a notebook. That guarantee is only as good as the
parser's notion of where a section ends.

The bug this pins: `re.split(r"\n## ", text)` leaves the LAST section running to
EOF, so appending a new entry silently changed the previous last entry's
captured body and reported it as EDITED. Observed 2026-09-10 adding EXP-036
after EXP-034 -- the entire diff was the "\n\n---\n" separator between them.
A false EDITED verdict is expensive twice over: it blocks a legitimate commit,
and it teaches the reader that check 5 cries wolf.
"""
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_registry.py"
_spec = importlib.util.spec_from_file_location("audit_registry", SCRIPT)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

ENTRY_A = """## EXP-101 — first

**Method (pre-committed).** Do the thing.

**Cost.** Minutes.
"""
ENTRY_B = """## EXP-102 — second

**Method (pre-committed).** Do the other thing.
"""
HEADER = "# Experiment Backlog\n\nPreamble.\n\n"


class TestSectionBoundaries:
    def test_appending_an_entry_does_not_alter_the_previous_one(self):
        before = audit.method_sections(HEADER + ENTRY_A)
        after = audit.method_sections(HEADER + ENTRY_A + "\n---\n\n" + ENTRY_B)
        assert before["EXP-101"] == after["EXP-101"], (
            "a section body must not depend on what follows it, or every "
            "addition to the backlog reports the previous entry as EDITED")
        assert "EXP-102" in after

    def test_a_real_edit_is_still_detected(self):
        """The normalisation must not blunt the check it protects."""
        a = audit.method_sections(HEADER + ENTRY_A)["EXP-101"]
        edited = ENTRY_A.replace("Do the thing.", "Do a different thing.")
        b = audit.method_sections(HEADER + edited)["EXP-101"]
        assert a != b

    def test_trailing_separator_and_whitespace_are_not_content(self):
        plain = audit.method_sections(HEADER + ENTRY_A)["EXP-101"]
        padded = audit.method_sections(HEADER + ENTRY_A + "\n\n---\n\n\n")["EXP-101"]
        assert plain == padded

    def test_only_exp_headings_are_captured(self):
        text = HEADER + ENTRY_A + "\n## Some prose heading\n\nnot an entry\n"
        assert set(audit.method_sections(text)) == {"EXP-101"}


class TestMergedSections:
    def test_an_entry_reads_the_same_from_either_home(self):
        here, _ = audit.merged_sections(HEADER + ENTRY_A + "\n---\n\n" + ENTRY_B, "")
        moved, dup = audit.merged_sections(HEADER + ENTRY_B, HEADER + ENTRY_A)
        assert here == moved and dup == []

    def test_an_entry_in_both_homes_is_reported(self):
        _, dup = audit.merged_sections(HEADER + ENTRY_A, HEADER + ENTRY_A)
        assert dup == ["EXP-101"]


class TestCheckFiveAcrossTheArchive:
    """Seeded positives, run against a real git repo.

    Moving an entry must pass, and every way of losing or altering one in the
    move must fail. EXP-101 is covered by the default pin; EXP-102 by its own,
    which is the case a key set built from HEAD alone cannot see once it is gone.
    """

    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        def git(*a):
            return subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

        def commit(msg):
            git("add", "-A")
            git("commit", "-qm", msg)
            return git("rev-parse", "HEAD")

        (tmp_path / "docs" / "archive").mkdir(parents=True)
        backlog = tmp_path / audit.BACKLOG
        archive = tmp_path / audit.BACKLOG_ARCHIVE
        git("init", "-q")
        backlog.write_text(HEADER + ENTRY_A)
        base = commit("pre-commit A")
        backlog.write_text(HEADER + ENTRY_A + "\n---\n\n" + ENTRY_B)
        pin = commit("pre-commit B")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(audit, "PRECOMMIT_REV", base)
        monkeypatch.setattr(audit, "PRECOMMIT_REV_BY_ID", {"EXP-102": pin})
        return SimpleNamespace(backlog=backlog, archive=archive, commit=commit)

    @staticmethod
    def run():
        fails, warns = [], []
        return audit.check_precommit(fails, warns), fails

    def test_no_archive_at_all_passes(self, repo):
        assert self.run() == (True, [])

    def test_an_uncommitted_move_passes(self, repo):
        repo.backlog.write_text(HEADER)
        repo.archive.write_text(HEADER + ENTRY_A + "\n---\n\n" + ENTRY_B)
        assert self.run() == (True, [])

    def test_a_committed_move_passes(self, repo):
        repo.backlog.write_text(HEADER)
        repo.archive.write_text(HEADER + ENTRY_A + "\n---\n\n" + ENTRY_B)
        repo.commit("move")
        assert self.run() == (True, [])

    def test_an_edit_during_the_move_fails(self, repo):
        repo.backlog.write_text(HEADER + ENTRY_B)
        repo.archive.write_text(HEADER + ENTRY_A.replace("Do the thing.", "Do a thing."))
        ok, fails = self.run()
        assert not ok and "EXP-101: Method body EDITED in the working tree" in fails[0]

    def test_an_edit_committed_in_the_archive_fails(self, repo):
        repo.backlog.write_text(HEADER + ENTRY_B)
        repo.archive.write_text(HEADER + ENTRY_A)
        repo.commit("move")
        repo.archive.write_text(HEADER + ENTRY_A.replace("Do the thing.", "Do a thing."))
        repo.commit("edit")
        ok, fails = self.run()
        assert not ok and "EXP-101: Method body EDITED since" in fails[0]

    def test_a_later_pinned_entry_lost_in_the_move_fails(self, repo):
        repo.backlog.write_text(HEADER)
        repo.archive.write_text(HEADER + ENTRY_A)
        repo.commit("lost EXP-102")
        ok, fails = self.run()
        assert not ok and "EXP-102: Method body EDITED since" in fails[0]

    def test_deleting_the_archive_fails(self, repo):
        repo.backlog.write_text(HEADER)
        repo.archive.write_text(HEADER + ENTRY_A + "\n---\n\n" + ENTRY_B)
        repo.commit("move")
        repo.archive.unlink()
        repo.commit("delete")
        ok, fails = self.run()
        assert not ok and len(fails) == 2

    def test_a_copy_left_in_both_homes_fails(self, repo):
        repo.archive.write_text(HEADER + ENTRY_A)
        ok, fails = self.run()
        assert not ok and fails == [
            f"EXP-101: in both {audit.BACKLOG} and {audit.BACKLOG_ARCHIVE}"]

    def test_the_archive_cannot_establish_a_baseline(self, repo):
        """An entry that first appears in the archive was never pre-committed."""
        repo.archive.write_text(HEADER + "## EXP-103 — late\n\nWritten after.\n")
        repo.commit("archive only")
        ok, fails = self.run()
        assert not ok and "EXP-103: no Method body at its pre-commit" in fails[0]
