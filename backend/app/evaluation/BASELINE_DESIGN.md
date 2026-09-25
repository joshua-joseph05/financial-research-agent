# Same-evidence single-pass baseline

## Question being tested

Given the same question, underlying LLM and collected source material, does the
full agent produce a better supported and more complete answer than one model call?

The baseline receives all observed source evidence (including unused observations),
raw article bodies, source metadata and deterministic calculation results from the
matched agent run. It does not receive the agent's report, findings, interpretations,
sentiment synthesis, plan, verification verdicts, benchmark labels or judge scores.
One structured answering call produces cited answer sections and limitations.
No LangGraph, delegation, retrieval decisions, correction loop or self-verification
runs in the baseline. This is intentionally a strong, evidence-assisted baseline,
not a question-only model denied access to financial information.

## Fairness controls

- Every pair uses the exact same benchmark question and agent model identifier.
- The source bundle is frozen and hashed for replay. No label-based evidence filtering.
- No context truncation is silently applied. Model/context failures are recorded.
- The same judge model, schema, criteria and answer-only instructions assess both
  answers; agent self-review and system identity are not provided. Assessment order
  is seeded and randomized per pair. Previously saved agent quality scores are not
  mixed with the new answer-only comparison rubric.
- Reuse full agent runs to avoid concurrent workloads distorting the active benchmark.
  The comparison can wait on the benchmark's actual process lock before model calls.
- Baseline and judge budgets are explicit and independently metered. Missing or
  partial assessments do not become wins, ties, or zeros.
- Compare mean per-question scores on matched assessed pairs; also retain raw
  numerators/denominators, per-category counts, exceptions and assessment coverage.
- Calculate accuracy for calculation records actually referenced by final answers,
  rather than awarding credit for unused supplied calculations. Baseline may cite
  supplied Python results or provide its own structured arithmetic with input lineage.
  This tests use of calculations, not an isolated model-arithmetic competition.

## Resource accounting

The full agent's latency/calls include evidence gathering and verification. Baseline
latency/calls cover answering from a prepared bundle. Its direct tool calls are zero;
the inherited evidence-preparation tool calls and full-agent duration are reported
separately. These resource numbers are NOT equivalent end-to-end system costs and
must not be presented as a deployment speedup. They quantify the extra answering
work once evidence is available. The design does not measure retrieval superiority.

## Reports

Preserve per-pair baseline output, agent snapshot, source hash, both fresh judge
results, deterministic calculation checks and resource costs. Generate aggregate
and per-category tables, paired deltas and examples with improved, worse, mixed,
equal or unassessed outcomes. Rank no system with a hand-picked composite score.
Report missing cases and incomplete judging explicitly. A complete 90-case report
requires all 90 source runs and both answer assessments; partial reports stay marked
partial. These synthetic cases and LLM judges are not investment-performance evidence.
