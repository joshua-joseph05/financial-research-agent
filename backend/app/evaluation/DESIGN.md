# Evaluation design

The benchmark measures the real unified assistant, not an alternative agent built
for a test. Production behavior and graph edges remain unchanged.

## Repository findings and instrumentation

| Available today | Evaluation use | Gap addressed |
| --- | --- | --- |
| `run_assistant` routes with `Route`, then calls existing graphs | Capture actual route and clarification | Evaluation model wrapper records typed route output, even on later failure |
| ResearchState stores observations, sources, calls, iterations, checks, errors | Retain complete state alongside final report | Evaluation wrapper captures returned state; final report alone discards unused evidence |
| Investment report includes evidence, calculations and tool telemetry | Capture reports and baseline/follow-up calls | Registry wrapper records full tool arguments/results; model wrapper counts investigation decisions, including failed calls |
| MeteredModel records requests, retries, timings and available token usage | Resource measurements | Separate outer evaluation meter enforces experiment configuration and preserves failed-run accounting |
| Sentiment consult accepts search/read dependencies and returns review diagnostics | Dedicated specialist evaluation | Frozen article bodies, issuer resolution, failure scenarios and source-level checks |
| Existing verification uses numeric/reference checks plus model self-review | System behavior to evaluate | Independent calculation oracle and separate judge; self-approval is not evaluation ground truth |
| Partial paired harness compares sentiment enabled/disabled | Keep compatibility and paired analysis | Fix fixture web isolation; new unified benchmark is the main evaluation entry point |

## Planned artifacts

- 90 versioned cases with category, expected routes, tool alternatives, answer
  criteria, scenario and expected outcome. Labels are authored expectations,
  not machine-proven truth; no mandatory hardcoded tool sequence.
- Frozen synthetic source adapter using production tool schemas and Python
  calculation executor. Date fixed for source freshness, not for runtime clocks.
  Unknown coverage returns no data. No public data requests in frozen mode.
- Evaluation-only recording around actual `run_assistant`, `run_research`,
  `run_ideas` and `consult`; no new production workflow or persisted production state.
- Per-question report, trace, model identity, source material and metric records;
  aggregate JSON/Markdown with numerators, denominators, missing assessments,
  failures and per-category results. Existing artifacts cannot be overwritten.
- Separate strict-schema judge. It receives the question, labeled criteria,
  final output and cited evidence, but no production verification verdicts.
  Missing/invalid judge results remain unassessed. Judge calls have a separate
  budget. Optional manual score override has explicit provenance.

## Metric classification

Deterministic: route matches labeled acceptable routes; tool precision/coverage
against authored alternatives; independent Decimal recalculation of emitted
calculation records; citation and recursive provenance integrity; source dates;
exact sentiment quote and attribution presence; budgets, failures and latency.

LLM-judged or manual: task fulfillment, factual entailment of each claim,
unsupported-claim rate, tool appropriateness in context, source relevance,
sentiment stance/attribution fidelity. These require strict item coverage and
reason/evidence references, with no model self-certification counted as a score.

Agent behavior: controlled graph regression tests plus trace diagnostics for
follow-up after missing evidence, continued investigation after a gap, stopping
on sufficient evidence, and refusing unsupported answers. Scripted tests prove
orchestration; live model decisions require actual benchmark runs and judgment.

Frozen mode tests agent reasoning over known synthetic evidence; live mode tests
provider integration but is not stable across dates. Sentiment is evaluated both
as an optional lead tool and directly with the real specialist. Model randomness,
source sampling, judge bias, incomplete benchmarks and small samples limit claims
of superiority. No metric measures investment returns or personal suitability.
