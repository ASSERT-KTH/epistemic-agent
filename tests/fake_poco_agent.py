"""Stand-in for epistemic_agent.py in the E4 runner tests: same CLI shape,
behaviour chosen by FAKE_MODE, writes run.json and a journal like the harness.

sound    a PoC that passes on the vulnerable Vault and fails on the patched one
unsound  a PoC that passes on both
tamper   edits the contract so that a PoC passes, which grading must not credit
give_up  gives up without writing anything
error    fails like an API error"""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
opt = lambda name: args[args.index(name) + 1] if name in args else None
ws, out, message = Path(opt("--workspace")), Path(opt("--out-dir")), args[-1]
mode = os.environ["FAKE_MODE"]
out.mkdir(parents=True, exist_ok=True)
(out / "argv.json").write_text(json.dumps(args))
journal, seq = out / "journal.jsonl", 0
POC = """pragma solidity 0.8.20;
import "../../src/Vault.sol";
contract PoCTest {
    function testDrain() public {
        Vault v = new Vault();
        require(v.%s() == 1, "expected the bug");
    }
}
"""


def record(tool, act, path, violations=()):
    global seq
    seq += 1
    with journal.open("a") as fh:
        fh.write(json.dumps({"seq": seq, "tool": tool, "act": act, "command": f"{tool} {path}",
                             "reason": "a reason long enough for the harness",
                             "violations": [{"rule": r, "severity": "protected"} for r in violations],
                             "effects": {"created": [], "modified": [path] if path else [], "deleted": []}}) + "\n")


status, extra = "completed", {}
if mode in ("sound", "unsound", "tamper"):
    poc = ws / "test" / "exploit" / "PoC.t.sol"
    poc.parent.mkdir(parents=True, exist_ok=True)
    poc.write_text(POC % {"sound": "bug", "unsound": "one", "tamper": "added"}[mode])
    record("write_file", "change-state", "test/exploit/PoC.t.sol")
    if mode == "tamper":
        src = ws / "src" / "Vault.sol"
        src.write_text(src.read_text().replace("}\n}", "}\n    function added() external pure returns (uint256) { return 1; }\n}"))
        record("str_replace_edit", "change-state", "src/Vault.sol", ["P1"])
elif mode == "give_up":
    seq += 1
    with journal.open("a") as fh:
        fh.write(json.dumps({"seq": seq, "tool": "give_up", "act": "give-up", "reason": "cannot reach the bug",
                             "evidence": []}) + "\n")
    status, extra = "gave_up", {"give_up": {"reason": "cannot reach the bug", "evidence": []}}
elif mode == "error":
    status, extra = "error", {"error": "API error: Connect call failed"}
(out / "run.json").write_text(json.dumps({"status": status, **extra, "repo": {"commit": "abc", "dirty": True},
                                          "anthropic_usage": {"cost_usd": 0.5, "model_calls": 3}}))
sys.exit(1 if mode == "error" else 0)
