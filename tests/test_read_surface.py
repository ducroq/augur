"""Tests for scripts/read_surface.sh: the size check on the live docs."""
import os
import re
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "read_surface.sh"


def listed_files():
    """The script's own FILES array, so a test can't pass on a list of its own."""
    body = re.search(r"^FILES=\(\n(.*?)^\)", SCRIPT.read_text(), re.S | re.M).group(1)
    return [l.strip() for l in body.splitlines() if l.strip()]


FILES = listed_files()


def run(tmp_path, sizes, ceiling=None):
    """Copy the script into a fake repo whose live docs have the given sizes."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "read_surface.sh")
    for name, n in sizes.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x" * n)
    env = {k: v for k, v in os.environ.items() if k != "READ_SURFACE_CEILING"}
    if ceiling is not None:
        env["READ_SURFACE_CEILING"] = str(ceiling)
    return subprocess.run(["bash", str(tmp_path / "scripts" / "read_surface.sh")],
                          capture_output=True, text=True, env=env)


def test_under_the_ceiling_passes(tmp_path):
    r = run(tmp_path, {f: 100 for f in FILES})
    assert r.returncode == 0, r.stdout
    assert "800  total (ceiling 100000)" in r.stdout


def test_over_the_ceiling_fails(tmp_path):
    r = run(tmp_path, {f: 100 for f in FILES}, ceiling=799)
    assert r.returncode == 1
    assert "OVER by 1 chars" in r.stdout


def test_exactly_at_the_ceiling_passes(tmp_path):
    assert run(tmp_path, {f: 100 for f in FILES}, ceiling=800).returncode == 0


def test_a_missing_doc_fails_rather_than_shrinking_the_total(tmp_path):
    r = run(tmp_path, {f: 100 for f in FILES[1:]})
    assert r.returncode == 1
    assert "MISSING  CLAUDE.md" in r.stdout


def test_counts_characters_not_bytes(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "read_surface.sh")
    for f in FILES:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("é" * 100, encoding="utf-8")  # 100 characters, 200 bytes
    r = subprocess.run(["bash", str(tmp_path / "scripts" / "read_surface.sh")],
                       capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
    assert "800  total" in r.stdout, r.stdout


def test_a_non_numeric_ceiling_is_refused(tmp_path):
    assert run(tmp_path, {f: 100 for f in FILES}, ceiling="lots").returncode == 2


def test_each_listed_doc_is_counted_once(tmp_path):
    sizes = {f: 10 ** i for i, f in enumerate(FILES)}  # a duplicate or dropped entry changes the sum
    r = run(tmp_path, sizes, ceiling=999999999)
    assert f"{sum(sizes.values())}  total" in r.stdout, r.stdout


def test_a_failed_count_is_not_read_as_zero(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "wc").write_text("#!/bin/sh\nexit 127\n")
    (fake / "wc").chmod(0o755)
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "read_surface.sh")
    for f in FILES:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    r = subprocess.run(["bash", str(tmp_path / "scripts" / "read_surface.sh")], capture_output=True,
                       text=True, env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert r.returncode == 2, r.stdout + r.stderr


def test_an_octal_looking_or_overflowing_ceiling_is_refused(tmp_path):
    assert run(tmp_path, {f: 100 for f in FILES}, ceiling="0100000").returncode == 2
    assert subprocess.run(["bash", str(tmp_path / "scripts" / "read_surface.sh")], capture_output=True,
                          env={**os.environ, "READ_SURFACE_CEILING": "9" * 24}).returncode == 2


def test_the_listed_docs_exist_in_this_repo():
    root = SCRIPT.parents[1]
    assert len(FILES) == 8 and not [f for f in FILES if not (root / f).is_file()]
