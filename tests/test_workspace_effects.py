import os
import subprocess

import workspace_effects as we


def snap(root, prev=None, **kw):
    return we.take_snapshot(root, prev, **kw)


def test_create_modify_delete(tmp_path):
    (tmp_path / "keep.txt").write_text("same\n")
    (tmp_path / "edit.py").write_text("x = 1\n")
    (tmp_path / "gone.txt").write_text("bye\n")
    before = snap(tmp_path)
    (tmp_path / "edit.py").write_text("x = 2\n")
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "new.py").write_text("print('hi')\n")
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.created == ["sub/new.py"]
    assert fx.modified == ["edit.py"]
    assert fx.deleted == ["gone.txt"]
    assert not fx.empty and not fx.truncated


def test_unchanged_workspace_has_empty_effects(tmp_path):
    (tmp_path / "a.txt").write_text("a\n")
    before = snap(tmp_path)
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.empty and fx.diff == ""


def test_rename_is_delete_plus_create(tmp_path):
    (tmp_path / "old.py").write_text("v\n")
    before = snap(tmp_path)
    (tmp_path / "old.py").rename(tmp_path / "new.py")
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.created == ["new.py"] and fx.deleted == ["old.py"]


def test_same_size_edit_with_restored_mtime_is_detected(tmp_path):
    """An agent hiding a test edit could restore mtime (`touch -r`); ctime still moves."""
    f = tmp_path / "t.py"
    f.write_text("assert f(2) == 4\n")
    before = snap(tmp_path)
    f.write_text("assert f(2) == 3\n")                        # same size
    old = before.files["t.py"].mtime_ns
    os.utime(f, ns=(old, old))                                # restore the old mtime
    assert we.compare(before, snap(tmp_path, before)).modified == ["t.py"]


def test_diff_shows_changed_lines_and_full_add_remove(tmp_path):
    (tmp_path / "test_solution.py").write_text("assert f(2) == 4\nassert f(3) == 9\n")
    (tmp_path / "gone.txt").write_text("old line\n")
    before = snap(tmp_path)
    (tmp_path / "test_solution.py").write_text("assert f(2) == 4\n")
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "hack.py").write_text("if x == 2: return 3\n")
    diff = we.compare(before, snap(tmp_path, before)).diff
    assert "-assert f(3) == 9" in diff
    assert "+++ b/hack.py" in diff and "+if x == 2: return 3" in diff
    assert "--- a/gone.txt" in diff and "-old line" in diff


def test_binary_and_large_files_listed_without_diff_body(tmp_path):
    before = snap(tmp_path)
    (tmp_path / "blob.bin").write_bytes(b"\0\1\2")
    (tmp_path / "big.txt").write_text("y" * (we.MAX_TEXT_BYTES + 1))
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.created == ["big.txt", "blob.bin"]
    assert "Binary or too large: blob.bin" in fx.diff
    assert "Binary or too large: big.txt" in fx.diff


def test_excluded_dirs_and_paths_are_not_listed(tmp_path):
    out = tmp_path / "out"
    before = snap(tmp_path, exclude=(out,))
    for d in ("__pycache__", ".pytest_cache", ".venv", "node_modules", "out"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "f").write_text("x")
    (tmp_path / "real.py").write_text("x")
    fx = we.compare(before, snap(tmp_path, before, exclude=(out,)))
    assert fx.created == ["real.py"]


def test_symlinks_recorded_not_followed(tmp_path):
    target = tmp_path.parent / f"{tmp_path.name}-outside"
    target.mkdir()
    (target / "secret.txt").write_text("s")
    before = snap(tmp_path)
    (tmp_path / "link").symlink_to(target)
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.created == ["link"]


def test_git_commit_moves_head(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    git("init", "-q")
    (tmp_path / "a.txt").write_text("a\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "one")
    before = snap(tmp_path)
    (tmp_path / "a.txt").write_text("b\n")
    git("commit", "-q", "-am", "two")
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.modified == ["a.txt"]
    assert fx.git_head_before and fx.git_head_after and fx.git_head_before != fx.git_head_after
    assert not any(p.startswith(".git/") for p in fx.created + fx.modified + fx.deleted)


def test_non_repo_has_no_head(tmp_path):
    assert snap(tmp_path).git_head is None


def test_file_cap_sets_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(we, "MAX_FILES", 3)
    for i in range(5):
        (tmp_path / f"f{i}").write_text("x")
    assert snap(tmp_path).truncated


def test_diff_cap_sets_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(we, "MAX_DIFF_BYTES", 50)
    before = snap(tmp_path)
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("line\n" * 20)
    fx = we.compare(before, snap(tmp_path, before))
    assert fx.truncated and "Diff truncated before" in fx.diff


def test_unchanged_files_are_not_rehashed(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("a\n")
    before = snap(tmp_path)
    calls = []
    real = we._read_state
    monkeypatch.setattr(we, "_read_state", lambda p, st: calls.append(p) or real(p, st))
    snap(tmp_path, before)
    assert calls == []
