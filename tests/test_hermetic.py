"""The system prompt must not depend on the machine running the agent."""
import pytest

CLAUDE_MARK = "MARKER-FROM-HOME-CLAUDE-MD"
AGENTS_MARK = "MARKER-FROM-CWD-AGENTS-MD"


@pytest.fixture
def contaminated_env(harness, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text(CLAUDE_MARK)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "work" / "AGENTS.md").write_text(AGENTS_MARK)
    return harness


def _system_prompt(ea, tmp_path, hermetic):
    import agentknit._core as core
    seen = []
    schema = ea._build_schema("test-model", "https://example.invalid/v1", "UNSET_KEY_ENV")
    with ea._agentknit_sessions(hermetic, on_session=seen.append):
        core.init_session(schema, non_interactive=True,
                          system_prompt_supplement=ea._system_supplement(hermetic),
                          session_dir=tmp_path / f"session-{hermetic}")
    [session] = seen
    return session["messages"][0]["content"]


def test_hermetic_prompt_excludes_personal_context(contaminated_env, tmp_path):
    prompt = _system_prompt(contaminated_env, tmp_path, hermetic=True)
    assert CLAUDE_MARK not in prompt
    assert AGENTS_MARK not in prompt
    assert "## Environment" not in prompt
    assert "Attribution" not in prompt


def test_hermetic_prompt_keeps_harness_instructions(contaminated_env, tmp_path):
    ea = contaminated_env
    prompt = _system_prompt(ea, tmp_path, hermetic=True)
    assert prompt.startswith(ea._AGENTKNIT_DEFAULT_INSTRUCTION)
    assert ea._SYSTEM_SUPPLEMENT in prompt


def test_hermetic_prompt_is_identical_across_machines(harness, tmp_path, monkeypatch):
    ea = harness
    prompts = []
    for name in ("alice", "bob"):
        home = tmp_path / name
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "CLAUDE.md").write_text(f"I am {name}")
        monkeypatch.setenv("HOME", str(home))
        prompts.append(_system_prompt(ea, tmp_path / name, hermetic=True))
    assert prompts[0] == prompts[1]


def test_non_hermetic_prompt_documents_the_contamination(contaminated_env, tmp_path):
    prompt = _system_prompt(contaminated_env, tmp_path, hermetic=False)
    assert CLAUDE_MARK in prompt
    assert AGENTS_MARK in prompt


def test_session_wrapper_is_removed_after_the_block(harness):
    import agentknit._core as core
    before = core.init_session
    with harness._agentknit_sessions(True):
        assert core.init_session is not before
    assert core.init_session is before


def test_hermetic_is_the_cli_default(monkeypatch):
    import sys
    import epistemic_agent as ea
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "task words"])
    assert ea.parse_args().hermetic is True
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--no-hermetic", "task words"])
    assert ea.parse_args().hermetic is False
