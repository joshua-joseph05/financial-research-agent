# New-question validation pilot

Nine new questions and criteria authored before model runs, one in each benchmark category. Both standard and efficient agents retrieve their own evidence from the same existing fictional source fixtures, with the same local model and counterbalanced order. These fixtures and underlying task types are familiar; this is not independent real-world validation or a blinded study.

Freeze application code, questions, and criteria during the run. Review every answer against its own sources and the predeclared criteria; do not score from the agent's complete flag. Record failures as well as successes. Once inspected for tuning, these cases become development material. Repeat timing on further reserved questions before a resume-level efficiency claim or default rollout.

Run from the project root:

```sh
PYTHONPATH=backend work/mcp-venv/bin/python -m app.evaluation.efficiency --cases-file evaluations/validation-v34/cases.json --splits-file evaluations/validation-v34/splits.json --split validation --output work/fresh-validation-v34 --max-requests 649
```

This starts 18 answers, not 649 mandatory calls. 649 is the conservative request cap including warm-up. Only local Ollama gemma4:e4b is used; source calls are replayed locally. Use --dry-run to inspect without inference. Resume only unchanged code/model/rubrics with --resume. Do not run two jobs against the same model for timing comparisons.

After completion, fill review-template.json with hash-bound completion and source-support decisions, then use the same cases/splits flags with --review PATH to render reviewed metrics without inference. Original development/validation scripts still work. The manifest records the exact questions, rubrics and split membership.
