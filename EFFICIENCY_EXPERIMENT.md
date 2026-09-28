# Agent efficiency experiment

This compares the **standard agent with an opt-in efficient agent**, rather than giving a one-call baseline evidence collected by another system. Both profiles retrieve the same frozen sources themselves. Production requests still default to `standard`.

## First change

General education questions previously made four model calls: route, select education topics, draft, review. The efficient profile obtains guide topics and requested answer parts in the routing call, removing the redundant selection call. It keeps source retrieval, numeric/citation validation and a separate source review. Drafting and review must address each requested part. The reviewer selects zero-based answer-section indices; Python rejects missing/duplicate part indices and nonexistent or empty answer sections. Source-only information and headings cannot establish coverage; semantic relevance still depends on the model review and must be audited separately. No extra model call is added for this check.

If routing cannot supply an education plan, the existing selection workflow is used. Company research and investment workflows remain on their established paths. This first experiment does not yet optimize financial lookups or complex research.

The new profile is explicit in the API request:

```json
{"question":"How do stocks differ from bonds?","execution_profile":"efficient"}
```

The main frontend continues to use the standard profile. No automatic rollout or self-modification occurs.

## Run the experiment

Use the project's Python environment and start local Ollama with `gemma4:e4b` downloaded. From the repository root:

```bash
PYTHONPATH=backend python -m app.evaluation.efficiency --split development --output work/efficiency-development-NEW --max-requests 361
PYTHONPATH=backend python -m app.evaluation.efficiency --split validation --output work/efficiency-validation-NEW --max-requests 361
```

Add `--dry-run` to preview without model calls; use `--resume` with the same output directory to reuse completed answers. Source-code, model and rubric changes require a new experiment. The printed maximum includes retry budgets; normal education runs should use far fewer calls.

Development cases: education 01, 03, 05, 07, 09. Reserved validation: 02, 04, 06, 08, 10. These are reserved for this change, not wholly unseen questions: they come from the existing benchmark. Both profile orders occur to reduce order bias; the model is warmed before timing. Every saved run records the complete report, source/tool trace, model calls, usage tokens when supplied and end-to-end latency.

## Review before accepting a change

The generated `review-template.json` contains a predeclared content rubric and answer hashes. A separate reviewer should fill `complete`, `supported`, `notes` and `reviewer`, save as `review.json`, and run:

```bash
PYTHONPATH=backend python -m app.evaluation.efficiency --output work/efficiency-development-NEW --review work/efficiency-development-NEW/review.json
```

The report never substitutes the agent's self-reported completion for reviewed quality. Unknown token counts remain unavailable. It reports paired sample sizes, mean calls, mean/median/p95 latency, tokens, errors, reviewed completion and supported answers separately for development and validation.

The validation gate requires all five reserved pairs reviewed, no completion regression, all efficient answers source-supported, no candidate errors, fewer mean model calls, lower median latency and no p95 latency increase. Passing produces only `promising_small_sample`; it does not enable the profile. One run per question and a five-case validation set do not prove broad gains. Repeat timings and use broader independent cases before rollout.

## Development iterations

The first candidate reduced calls but increased latency. A second candidate shortened planning and review; development testing exposed copied source text instead of answer quotations and an incorrect guide choice for a fees question. These were quality failures, not speed wins. An intermediate third run was interrupted after identifying the routing problem; partial artifacts remain preserved.

The current opt-in candidate uses descriptions of the available guide topics, specific nonoverlapping question parts, concise drafting, and answer-section references instead of generated quotations. This avoids copying errors without removing source review. There is no claim that a valid section index alone proves semantic coverage. Standard prompts and the default profile remain unchanged.
