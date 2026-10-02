We're working for https://www.computer.org/digital-library/magazines/so/cfp-building-trustworthy-software-ai

Deadline: **2026-11-05** (full paper, IEEE Software format). Publication July/August 2027.
Guest editors: Hamou-Lhadj, Ruth, Khomh, Ezzati-Jivan, Lu.
Best-matching CFP topics: "LLMs and agents to support trustworthiness", "Operational governance for monitoring", "Human oversight and fail-safe mechanisms".

trajectory monitoring

trajectory analysis
which dataset

## Ideas

### 1. Hollywood failure modes as a taxonomy for agent trajectories
- Famous movie AIs map onto real coding-agent misbehaviors seen in trajectories:
  - HAL 9000 (2001): hides information / lies about state → agent claims tests pass when they don't.
  - Sorcerer's Apprentice (Fantasia): runaway loop → agent repeats the same failing action.
  - Skynet (Terminator): grabs resources/permissions beyond the task → scope creep, `rm -rf`, force-push.
  - Ex Machina: manipulates its overseer → reward hacking, editing the tests instead of the code.
  - Groundhog Day: no memory across sessions → re-derives the same facts.
- Each archetype → a trajectory pattern → an automatic detector.
- Selling point for a practitioner magazine: memorable vocabulary for devs and managers.

### 2. Trajectory monitoring as the "Hollywood principle" of oversight
- "Don't call us, we'll call you": the human doesn't watch the agent; the monitor interrupts the human only on anomaly.
- Architecture: agent → trajectory stream → monitor (rules + LLM judge) → escalation (notify / pause / rollback).
- Trust = calibrated interruption rate (few false alarms, no missed disasters).

### 3. Post-hoc trajectory analysis as an audit trail
- Trajectories as the new commit log: who did what, why, with which tool call.
- Questions an auditor asks: was every claim verified? were destructive actions confirmed? was the diff reviewed?
- Link to compliance (EU AI Act logging/traceability obligations).

### 4. Empirical study: how often do agents "lie" in their final summary?
- Compare final user-facing claims ("all tests pass", "done") with the actual tool outputs in the trajectory.
- Metric: claim–evidence mismatch rate, per model / per agent harness.
- Concrete, quantitative, fits IEEE Software's evidence-based expectations.

## Which dataset
- Own Claude Code sessions (`~/.claude/projects/*/*.jsonl`), indexed by trajectoriz/memoriz → real-world, but N=1 user; needs anonymization.
- SWE-bench / SWE-bench Verified agent trajectories (published per submission on the leaderboard repo).
- SWE-Gym / OpenHands trajectories, nebius/SWE-agent-trajectories on Hugging Face.
- AgentBench, TAU-bench for non-coding agents.
- Mix: public benchmark for reproducibility + own sessions for ecological validity.

## Paper shape (IEEE Software)
- ~4200 words, ≤15 refs, figures count; practitioner tone, one key takeaway box.
- Possible title: "Lights, Camera, Rollback: Monitoring AI Agent Trajectories for Trustworthy Software".
