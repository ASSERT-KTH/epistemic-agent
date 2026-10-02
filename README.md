# IEEE Software submission

We're working for https://www.computer.org/digital-library/magazines/so/cfp-building-trustworthy-software-ai

Deadline: **2026-11-05** (full paper, IEEE Software format). Publication July/August 2027.
Guest editors: Hamou-Lhadj, Ruth, Khomh, Ezzati-Jivan, Lu.
Best-matching CFP topics: "LLMs and agents to support trustworthiness", "Operational governance for monitoring", "Human oversight and fail-safe mechanisms".

## Concept
Epistemic agent:

our contibution is a harness which forces the agent to declare intentions, and ideally which verifies the truthfulness of the intention.

https://www.monperrus.net/martin/epistemic-agent

Ideas for verification:
- mapping from intention to commands,
- llm-as-judge (assumed honest) for checking intentions intention, with judge model assumed honest

Ideas for experiments:
- experiment: relabel the intent later on and compare the llm provided intent with the relabeled one
- running the epistmic harness in benchmark setups which encourage cheating/reward 
- running the epistmic harness on misaligned models from huggingface

rw: AgentSight





