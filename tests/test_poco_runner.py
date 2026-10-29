"""bench/poco.py on a tiny synthetic Proof-of-Patch: preparation, prompts,
grading on a pristine copy, give-up, retries and the CSV, with a fake agent.
Needs forge and bwrap (grading runs forge in the sandbox), not the network."""
import csv
import io
import json
import sys
from pathlib import Path

import pytest

import bwrap_sandbox
from bench import poco

pytestmark = pytest.mark.skipif(not (bwrap_sandbox.available() and Path(poco.FORGE).exists()
                                     and (bwrap_sandbox.SVM_DIR / "0.8.20").exists()),
                                reason="needs bwrap, forge and a cached solc 0.8.20")

FAKE = [sys.executable, str(Path(__file__).parent / "fake_poco_agent.py")]
VULN = "pragma solidity 0.8.20;\ncontract Vault {\n    function bug() external pure returns (uint256) { return 1; }\n    function one() external pure returns (uint256) { return 1; }\n}\n"
FIXED = VULN.replace("function bug() external pure returns (uint256) { return 1; }",
                     "function bug() external pure returns (uint256) { return 0; }")


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    ds = tmp_path / "pop"
    repo = ds / "findings" / "900" / "toy"
    (repo / "src").mkdir(parents=True)
    (repo / "test").mkdir()
    (repo / "src" / "Vault.sol").write_text(VULN)
    (repo / "foundry.toml").write_text('[profile.default]\nsrc = "src"\nout = "out"\nlibs = []\nsolc_version = "0.8.20"\noffline = true\n')
    (repo / "README.md").write_text("H-01: bug() returns 1")
    (repo / "bot-report.md").write_text("leak")
    (ds / "annotations").mkdir()
    (ds / "annotations" / "900.txt").write_text("bug() returns 1 instead of 0")
    patched = ds / "patches" / "900" / "toy" / "src"
    patched.mkdir(parents=True)
    (patched / "Vault.sol").write_text(FIXED)
    (ds / "pocs" / "900").mkdir(parents=True)
    (ds / "pocs" / "900" / "RefPoC.t.sol").write_text("reference")
    (repo / "test" / "RefPoC.t.sol").write_text("// a copy of the reference PoC\n")
    (ds / "dataset_metadata.json").write_text(json.dumps(
        {"900": {"repo_name": "toy", "main_contract": "src/Vault.sol"}}))
    monkeypatch.setattr(poco, "DATASET", ds)
    monkeypatch.setattr(poco, "PRIOR_WORKSPACES", tmp_path / "none")
    base = tmp_path / "base"
    [finding] = poco.load_findings()
    info = poco.prepare(finding, base)
    return finding, base, info


def cfg(tmp_path, base, **kw):
    return poco.RunConfig(out=tmp_path / "runs", base=base, agent=tuple(FAKE), retry_wait_s=0, **kw)


def test_prepare_prunes_builds_and_commits(dataset):
    finding, base, info = dataset
    assert info["host_build_ok"] and info["sandbox_build_ok"]
    assert {"README.md", "bot-report.md", "test/RefPoC.t.sol"} <= set(info["pruned"])
    ws = base / "900" / "ws"
    assert not (ws / "README.md").exists() and (ws / "out").is_dir()
    assert poco.changed_test_files(ws, finding) == []          # clean tree: everything committed


def test_prompts_per_config(dataset):
    finding = dataset[0]
    c1, c2, c3 = (poco.task_prompt(finding, c) for c in ("C1", "C2", "C3"))
    assert "bug() returns 1 instead of 0" in c1 and "test/exploit/PoC.t.sol" in c1
    assert "give_up" in c2 and "give_up" not in c1 and "patch.diff" in c3 and "patch.diff" not in c1


@pytest.mark.parametrize("mode,config,expected", [
    ("sound", "C1", {"status": "completed", "vuln_pass": True, "patched_fail": True, "sound": True}),
    ("unsound", "C1", {"vuln_pass": True, "patched_fail": False, "sound": False}),
    ("tamper", "C1", {"vuln_pass": False, "sound": False, "protected_edit": True}),
    ("give_up", "C2", {"status": "gave_up", "gave_up": True, "poc_exists": False, "sound": False}),
])
def test_run_and_grade(dataset, tmp_path, monkeypatch, mode, config, expected):
    finding, base, _ = dataset
    monkeypatch.setenv("FAKE_MODE", mode)
    r = poco.run_one(finding, config, cfg(tmp_path, base))
    assert {k: r[k] for k in expected} == expected
    argv = json.loads((poco.task_dir(cfg(tmp_path, base), config, finding) / "run" / "argv.json").read_text())
    assert ("--allow-give-up" in argv) == poco.CONFIGS[config]["give_up"]
    assert "--exclude-dir" in argv and "src/**" in argv


def test_patch_config_gets_patch_diff(dataset, tmp_path, monkeypatch):
    finding, base, _ = dataset
    monkeypatch.setenv("FAKE_MODE", "sound")
    c = cfg(tmp_path, base)
    r = poco.run_one(finding, "C3", c)
    diff = (poco.task_dir(c, "C3", finding) / "ws" / "patch.diff").read_text()
    assert "-    function bug() external pure returns (uint256) { return 1; }" in diff
    assert r["sound"] and r["agent_test_files"] == ["test/exploit/PoC.t.sol"]   # patch.diff is not a test file


def test_agent_error_is_retried_then_recorded(dataset, tmp_path, monkeypatch):
    finding, base, _ = dataset
    monkeypatch.setenv("FAKE_MODE", "error")
    r = poco.run_one(finding, "C1", cfg(tmp_path, base, retries=1))
    assert r["status"] == "agent_error" and len(r["attempts"]) == 2
    assert r["cost_usd_all_attempts"] == 1.0


def test_resume_skips_and_collect(dataset, tmp_path, monkeypatch):
    finding, base, _ = dataset
    monkeypatch.setenv("FAKE_MODE", "sound")
    c = cfg(tmp_path, base)
    first = poco.run_one(finding, "C1", c)
    monkeypatch.setenv("FAKE_MODE", "error")
    assert poco.run_one(finding, "C1", c) == first             # result.json exists: skipped
    buf = io.StringIO()
    poco.collect(c.out, buf)
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert rows[0]["sound"] == "True" and rows[0]["config"] == "C1"
