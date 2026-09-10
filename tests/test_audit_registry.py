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
from pathlib import Path

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
