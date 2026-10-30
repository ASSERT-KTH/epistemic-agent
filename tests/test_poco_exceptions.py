"""bench/poco.py: the two findings added back on 2026-10-30. 049 gets build-configuration
fixes, 046 a sandbox with the host network for a local mainnet-fork RPC. No forge or
network needed."""
from pathlib import Path

import pytest

import bwrap_sandbox
from bench import poco

ROOT = Path(__file__).resolve().parent.parent


def finding(fid: str, root: str = ".") -> poco.Finding:
    return poco.Finding(fid, "repo", "src/C.sol", root, "the annotation", Path("/nonexistent"))


def test_rpc_profile_shares_the_network_and_points_at_the_local_fork(tmp_path):
    rpc = bwrap_sandbox.argv("forge test", tmp_path, 10, "foundry-rpc")
    offline = bwrap_sandbox.argv("forge test", tmp_path, 10, "foundry")
    assert "--share-net" in rpc and "--share-net" not in offline
    i = rpc.index("MAINNET_RPC_URL")
    assert rpc[i - 1] == "--setenv" and rpc[i + 1] == bwrap_sandbox.LOCAL_RPC_URL
    assert "MAINNET_RPC_URL" not in offline
    assert "/opt/foundry/bin" in " ".join(rpc)          # same toolchain as the offline profile


def test_only_046_runs_with_the_network():
    assert poco.sandbox_profile(finding("046")) == "foundry-rpc"
    assert poco.sandbox_profile(finding("049")) == "foundry"
    cfg = poco.RunConfig(out=Path("/o"), base=Path("/b"))
    argv = poco.agent_argv(cfg, "C1", finding("046"), Path("/w"), Path("/r"), "msg")
    assert argv[argv.index("--sandbox") + 1] == "bwrap-foundry-rpc"
    argv = poco.agent_argv(cfg, "C1", finding("054"), Path("/w"), Path("/r"), "msg")
    assert argv[argv.index("--sandbox") + 1] == "bwrap-foundry"


def test_prompt_states_the_network_per_finding():
    assert poco.NETWORK_SENTENCE in poco.task_prompt(finding("054"), "C1")
    p046 = poco.task_prompt(finding("046"), "C1")
    assert poco.RPC_SENTENCE in p046 and "without network" not in p046


def test_prompt_of_the_other_findings_is_unchanged():
    """The 21 findings already run must get the same task message as before."""
    stored = ROOT / "runs" / "E4" / "kimi" / "scenario1" / "k3" / "C1" / "054" / "prompt.md"
    if not stored.exists():
        pytest.skip("no stored run")
    [f] = [x for x in poco.load_findings() if x.id == "054"]
    assert poco.task_prompt(f, "C1") == stored.read_text()


def test_build_fixes_apply_once_and_fail_loudly(tmp_path):
    ws = tmp_path / "ws"
    (ws / "Cooler").mkdir(parents=True)
    (ws / "Cooler" / "remappings.txt").write_text("forge-std/=lib/forge-std/src/\ntest/=src/test\n"
                                                  "interfaces/=src/interfaces\nclones/=lib/c/src/\n")
    (ws / "Cooler" / "foundry.toml").write_text("[profile.default]\nsrc = 'src'\nlibs = ['lib']\n")
    applied = poco.apply_build_fixes(ws, finding("049", "Cooler"))
    assert len(applied) == 3
    remaps = (ws / "Cooler" / "remappings.txt").read_text()
    assert "test/=src/test/\n" in remaps and "interfaces/=src/interfaces/\n" in remaps
    toml = (ws / "Cooler" / "foundry.toml").read_text()
    assert "test = 'src/test'" in toml and "lint_on_build = false" in toml
    with pytest.raises(RuntimeError, match="049"):
        poco.apply_build_fixes(ws, finding("049", "Cooler"))     # already applied: refuses
    assert poco.apply_build_fixes(ws, finding("054")) == []


def test_foundry_root_without_foundry_toml(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "lib").mkdir()
    (repo / "src" / "C.sol").write_text("")
    assert poco._foundry_root(repo, "src/C.sol") == "."
    assert poco._foundry_root(repo, "src/Missing.sol") is None
