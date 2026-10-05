# Whole-assistant efficiency experiments

Status: experimental and opt-in. The standard profile remains the default. The current work is an isolated copy of the original Desktop project, prepared inside the writable workspace; it has not been installed into the original running project.

## Scope

The pilot covers nine existing benchmark categories: financial data, SEC filings, calculations, comparisons, open research, investing, sentiment/news, education and insufficient evidence. One development case and one reserved validation case per category provide an initial diagnostic, not statistically strong category-level claims. Expand the sample and repeat timings before rollout. The questions come from the existing benchmark, not a wholly unseen corpus.

Both profiles use the same model and frozen source availability and collect their own evidence. No one-call baseline inherits the other agent's evidence. Each saved run includes answer, trace, model-call count, latency and source provenance. Model tokens remain unavailable when the provider does not report them.

## Candidate changes

- Retain educational planning/review work from the prior experiment.
- Choose the first research tool while planning, constrained by its real argument schema.
- Reuse unchanged verification results and recover from duplicate retrieval before doing an unnecessary intermediate review; keep stop limits and unresolved gaps.
- Verify original company references against issuer identities before named-company investment research. Ask for clarification on ambiguous names rather than investigate a guessed symbol.
- Preserve calculation input/source lineage in compact review context. Record actual local-model prompt/output token counts, including rejected truncated replies.
- Enrich company comparisons with Python revenue-growth calculations from compatible annual inputs.
- Review investment claims against their own cited evidence and exact supporting excerpts, separately checking the proposed action. Preserve supported partial findings without marking the overall assessment complete.
- Assemble sentiment briefs from reviewed source arguments while retaining source review.
- Assemble live research reports in Python from verified findings, preserving unresolved requirements and running final structural validation. Skip the redundant synthesis selection call. Synthetic demo behavior is unchanged.
- Build the investment graph's fixed five-category evidence checklist in Python. Additional investigation still chooses tools dynamically; recommendation and source review remain model steps.
- Explicitly preserve sector restrictions in investment discovery. Start with three candidates for unspecified breadth, rather than filling the eight-company cap. Honor explicit breadth and named companies within existing limits. A smaller sample is disclosed, not called a market-wide search.

These are hypotheses until the paired experiments and answer review show gains. Fewer calls do not automatically imply faster or better answers.

## Run

From this project with its Python dependencies installed:

```bash
PYTHONPATH=backend python -m app.evaluation.efficiency --suite broad --split development --output work/broad-development-NEW --max-requests 649
```

Use `--dry-run` first to see the nine questions and retry-inclusive request bound without making requests. Only after development succeeds, run `--split validation` in a fresh output directory with the same frozen code. Use `--resume` for interrupted runs without code/model/rubric changes. Existing answers are not overwritten.

Fill the generated review template after inspecting actual answers and sources, leaving unknown labels null. Review completion separately from source support; never use the agent's own complete flag as ground truth. Preserve answer hashes.

```bash
PYTHONPATH=backend python -m app.evaluation.efficiency --suite broad --output work/broad-development-NEW --review work/broad-development-NEW/review.json
python scripts/profile-evaluation.py work/broad-development-NEW
```

The summary includes category-specific results. The validation gate requires no completion regression overall or within a category, all candidate answers source-supported, no candidate errors, fewer mean calls, lower median latency and no p95 increase. It does not deploy anything automatically. A stricter whole-agent claim also needs broader category samples, repeated runs, and demonstrated completion gains rather than merely nonregression.
