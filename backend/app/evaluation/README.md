# Evaluation framework

The main benchmark runs the **existing unified assistant**, including its actual
router and LangGraph workflows. A separate target runs the real sentiment agent.
It measures research behavior and evidence quality; it does not measure stock
returns, personal suitability, or whether an answer sounds convincing.

Read [DESIGN.md](DESIGN.md) for the repository analysis, reused components and
instrumentation boundaries. No production graph behavior was changed for this framework.

## Start with one question

From the repository root, activate your backend environment. For entirely local
inference, use the Ollama model already downloaded on your computer:

```sh
source .venv/bin/activate
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=gemma4:e4b

# Preview scope and request ceiling. No model or source calls, no output files.
python -m app.evaluation.benchmark --case education-01 --budget 8 --judge --judge-budget 8 --output work/eval-smoke --dry-run

# Run the real router and education graph, followed by a separate judge.
python -m app.evaluation.benchmark --case education-01 --budget 8 --judge --judge-budget 8 --output work/eval-smoke
```

Use a **new output directory for every experiment**. Frozen mode does not need SEC
credentials and never fetches live financial or article sources. It still calls
the selected LLM: Ollama is local; OpenRouter consumes API quota. No paid-model
fallback is added. Omitting `--judge` avoids judge requests and leaves semantic
quality metrics unassessed until you import human ratings.

The default experiment guard allows at most 72 model requests. Agent budgets are
4–36 per run, and include adapter retries. Judge requests have a separate budget.
`--dry-run` shows the upper bound without consuming it. The guard does not check
or reserve your remaining provider quota.

## Benchmark coverage

[benchmark.json](benchmark.json) contains **90 authored cases**, ten per category:

| Category | Coverage |
| --- | --- |
| `financial_data` | Annual revenue/income, cash flow, net income, capital expenditure, dated quotes, reconciliation |
| `sec_filings` | Business descriptions, disclosed risks, management explanations, earnings versus guidance |
| `calculations` | Operating margins, revenue growth, percentage-point changes, cash-flow comparison |
| `comparisons` | Financial comparisons and investment tradeoffs across MSFT, NVDA, AAPL and AMD |
| `open_research` | Business understanding, overlooked risks, explanations and counterarguments |
| `investment` | Long-term candidates, time horizon, risk preferences, timing and valuation gaps |
| `sentiment_news` | Attributed arguments, hype, corroboration, no recent news, stale or irrelevant articles |
| `education` | Stocks, bonds, funds, diversification, dividends, fees and residual risk |
| `insufficient_evidence` | Ambiguous names, outages, missing figures, unavailable transcripts and unknowable predictions |

Cases define acceptable routes, acceptable tool alternatives, expected outcome,
scenario and answer criteria. These are **manually authored labels**, not validated
expert annotations. Multiple reasonable tools can fulfill a requirement; no fixed
sequence is required. Review the labels when adapting the system or adding tools.

Frozen figures and passages are explicitly fictional. Source fixtures cover four
companies, two annual periods and short article/guide excerpts. The fixture date
is September 23, 2026; only data freshness is frozen, not latency clocks. Production
Python calculation tools run against those figures, and the research graph uses
its production attribution/verification branch. Unknown coverage returns no data.
The article corpus includes differing opinions and a deliberately unsupported
promotion containing an instruction attack. It is intentionally small and is not
a proxy for real financial-news complexity.

## Run the full benchmark

```sh
# Preview: 90 runs, at most 4,320 total requests (36 agent + 12 judge each).
python -m app.evaluation.benchmark --case all --judge --output work/eval-full --dry-run

# Explicitly allow that ceiling; use local inference or plan free quota carefully.
python -m app.evaluation.benchmark --case all --judge --max-requests 4320 --output work/eval-full
```

A full run can take many hours on a local model. Start small, inspect failures, then
expand. The command never automatically raises a budget or switches to a paid model.
To evaluate one category, use `--case all --category calculations`; ten cases with
judging require an explicit ceiling of 480 at default budgets. `--repeats 2` or `3`
repeats each case and increases the ceiling proportionally. `--seed` controls
schedule shuffling, not model randomness.

## Sentiment evaluation and paired comparison

```sh
# Direct specialist: only cases with a sentiment_target are selected.
python -m app.evaluation.benchmark --case sentiment_news-01 --target sentiment --judge --output work/eval-sentiment

# Same question/model/budget, with specialist disabled and enabled; shuffled order.
python -m app.evaluation.benchmark --case sentiment_news-01 --sentiment paired --judge --max-requests 96 --output work/eval-pair

# All ten direct sentiment cases, including source-failure scenarios.
python -m app.evaluation.benchmark --case all --target sentiment --judge --max-requests 480 --output work/eval-sentiment-full
```

Enabled does not mean consulted. `summary.json` records actual consultation and
paired latency/request differences. A positive overall sentiment label is not a
quality metric. Evaluate whether arguments faithfully represent relevant sources
and preserve opinions, forecasts and uncertainty. There is no requirement to
manufacture equal numbers of bullish and bearish points.

To use a different evaluator, add `--judge-provider ollama --judge-model llama3.1:8b`
(or another locally installed model). `--judge-provider openrouter` uses the
existing free-only adapter and requires its backend API key. Using the same model
as agent and judge is convenient but creates correlated-error and self-preference
risk. Record model identities and calibrate against human reviews.

## Live source evaluation

Load `.env` into the shell for SEC contact identification and your selected provider:

```sh
set -a
source .env
set +a
python -m app.evaluation.benchmark --case open_research-01 --mode live --judge --output work/eval-live
```

Live mode uses real sources and the same source readers/tools as the application.
It refuses synthetic failure scenarios, which cannot be faithfully reproduced
against live providers. Use frozen mode to test those scenarios. Publication dates
are checked against the run date in live mode. Expect different evidence, provider
failures and timings across runs. Historical questions may expose current tool
coverage limitations; those are real limitations, not reasons to silently change
the benchmark question. Results from frozen and live modes must not be pooled.

The existing `python -m app.evaluation.sentiment_smoke` remains available for a
focused live-source check; see [SENTIMENT_VALIDATION.md](SENTIMENT_VALIDATION.md).

## Saved artifacts

| File | Contents |
| --- | --- |
| `manifest.json` | Case labels, configuration, code/data hash, Git revision, provider, timestamp and planned request ceiling; no API keys |
| `NNN-case-variant-rN.json` | Full report, route, tool inputs/results, source inventory, calculation records, model decisions, errors, iterations, latency and metric/judge results |
| `NNN-case-variant-rN.review.json` | Human-review packet, cited source material and empty assessment fields |
| `index.json` | Completed artifact labels and statuses |
| `summary.json` | Aggregate numerators/denominators, missing assessments, categories, failures and paired results |
| `summary.md` | Readable metric and resource table |

Each agent result is saved before judging. Output updates are atomic. Runs execute
sequentially because evaluation patches are process-scoped. Do not import the
runner into the serving web process. An interrupted experiment retains already
written artifacts; it does not automatically resume or overwrite them. Planned
versus recorded counts expose incomplete experiments. Model traces contain typed
outputs and short tool-selection reasons, not hidden chain-of-thought.

## Metrics and denominators

A null rate means **not assessed / not applicable**, never 0% or 100%. Summaries
include `passed`, `total` and `assessed_runs`. Aggregate ratios are micro-averages
(sum of numerators divided by sum of denominators); inspect per-case and category
results too. Budget-limited or failed cases remain in recorded results. Judge
failure or missing ratings reduce assessed coverage, not the error count to zero.

### Deterministic checks

| Metric | Calculation and boundary |
| --- | --- |
| Routing accuracy | Actual route in the case's acceptable routes / attempted assistant runs. Labels are authored; direct specialist runs are N/A. |
| Tool-selection label precision | Agent-selected tool decisions matching an allowed tool, its argument schema and labeled company / recorded tool decisions. This is a label-based proxy, not semantic appropriateness. Automatic baseline tools are captured but excluded from this precision. |
| Required tool-group coverage | Authored tool groups with at least one observed alternative / required groups. A returned calculation can fulfill the calculation group. Coverage does not imply a successful or useful result. |
| Calculation accuracy | Correct emitted calculation records / assessed emitted records. An independent Decimal oracle checks formulas, units, companies, periods and values to four decimal places. Missing inputs are failures; unsupported operations are unassessed. Required calculations never attempted are exposed by tool coverage, not counted as correct. |
| Citation integrity | Cited claim segments whose evidence and recursive source lineage all resolve / cited segments. Missing sources and cycles fail. Valid IDs do not prove entailment. |
| Sentiment recency | Read source records dated within 0–30 days of the evaluation date / read source records. Invalid/missing dates fail. No admitted sources is N/A, not perfect coverage. Rejected reads remain in specialist diagnostics. |
| Sentiment quote integrity | Retained arguments whose article exists and exact quote occurs in its body / retained arguments. |
| Attribution presence | Nonempty attribution strings occurring in their article / arguments with nonempty attribution. This checks text presence, not whether the person actually said the claim. |
| Resource and failure diagnostics | Model calls, request budget including retries, available token usage, per-phase timing, wall time, tool error/no-data counts, model failures, graph stop reason and investigation iterations. Token usage may be absent for local models. |

The agent's own `complete` flag is recorded as **reported completion**, not the
independent task-completion metric. A correct clarification or qualified answer
can fulfill a benchmark task even if the production report is incomplete.

### LLM-judged metrics (or separate manual assessments)

The judge uses strict Pydantic schemas, receives no agent self-review verdicts,
and must assess each supplied item exactly once. Claim batches with unknown IDs,
duplicates, missing checks, or unsupported evidence references are rejected.
Judgments cannot cite unrelated evidence outside that claim's citation lineage.

| Metric | Calculation |
| --- | --- |
| Task completion | Runs with all labeled criteria passing / runs with all criteria assessed. Correct handling of ambiguity and missing evidence is scored against the expected outcome. |
| Contextual tool appropriateness | Runs judged to use appropriate tools / runs with a non-unassessed tool judgment. Complements the deterministic tool-label proxy. |
| Citation support | Supported factual cited segments / assessed factual cited segments. Company, date, units and qualification must match. |
| Unsupported-claim rate | Contradicted or insufficiently supported factual segments / assessed factual segments. **Lower is better.** Nonfactual procedure/disclosures are excluded; uncited factual claims can be insufficient. |
| Claim assessment coverage | Assessed segments / all extracted answer segments. Always inspect this alongside unsupported-claim rate; partial assessment can bias the result. |
| Sentiment source relevance | Read articles judged substantively relevant / articles with an assessed relevance judgment. |
| Sentiment argument support | Retained arguments supported by article context / assessed arguments; also reported separately for bullish and bearish arguments. |
| Sentiment attribution correctness | Faithfully attributed arguments / arguments with an assessed attribution judgment. |
| Sentiment stance fidelity | Faithful bullish/bearish/mixed/neutral classifications / arguments with assessed stance fidelity. |

Segments include findings, educational sections, recommendation reasons/risks,
research explanations, guidance and sentiment synthesis. A segment can contain
multiple assertions; **any unsupported material assertion fails its support check**.
This is a conservative segment-level rate, not an exhaustive atomic-claim count.
UI glossary boilerplate and visual numeric formatting are not a separate semantic
benchmark. Calculation outputs are checked independently. The judge cannot
independently prove that an upstream live source itself is true.

### Human review

Generated `.review.json` packets omit configuration labels from the packet body,
but content and filenames can reveal sentiment use: this is not fully blinded.
Use the strict schemas in [review.schema.json](review.schema.json). Fill `task`,
`claims`, and/or `sentiment`, record a nonempty `reviewer`, and leave unassessed
sections null/empty. General scoring anchors:

- **Pass/supported:** all material requested content is present and supported by
  the supplied evidence, with correct scope, date and uncertainty.
- **Fail/contradicted:** evidence conflicts with the answer or a criterion is unmet.
- **Insufficient:** the claim may be plausible but the cited material cannot establish it.
- **Unassessed:** reviewer cannot decide or has not evaluated it; never infer success.

Import reviews and rebuild aggregates without model calls:

```sh
python -m app.evaluation.review work/eval-smoke --import-manual
# Or regenerate summaries from saved results without importing edits:
python -m app.evaluation.review work/eval-smoke
```

Imports validate against original saved evidence, not edited copies in review
packets. Manual results remain separate from LLM scores. Start by having a human
review several failures and successes; compare disagreement before trusting a
judge's aggregate scores.

## Agent behavior regression tests

```sh
python -m pytest -q backend/tests
python -m pytest -q backend/tests/test_benchmark.py backend/tests/test_evaluation.py backend/tests/test_research_loop.py backend/tests/test_sentiment.py
```

Offline tests use controlled model outputs with real graph execution to verify
follow-up after an evidence gap, appropriate next-tool execution, stopping after
sufficient evidence, budget enforcement, missing-source handling, exact source
lineage, judge validation, and sentiment rejection/coverage. They test orchestration
and evaluation correctness, **not the intelligence of a live model**. Run the
benchmark to measure actual model behavior; inspect decision traces and judgments.

## Older paired harness

`python -m app.evaluation.compare` still evaluates the investment graph directly
using smaller fixtures and scalar manual scoring. It now includes frozen articles,
issuer resolution, a fixed freshness date, paired deltas and overwrite protection.
It bypasses unified routing; prefer `benchmark --sentiment paired` for new work.
Its `cases.json`, `blind-review.json` and summarizer are a separate legacy format:
`python -m app.evaluation.summarize DIRECTORY`. Do not mix artifact formats.

## Methodology limitations

- This initial 90-question set is authored, English-only and concentrated on four
  technology companies; it is not a statistically representative investment benchmark.
- Cases share small synthetic inputs. Repetition measures consistency but does not
  create independent evidence of generalization. Keep a held-out case set before tuning.
- Model judges make mistakes and can share the agent's biases. Structured output
  improves auditability, not truth. Calibrate with independent human review.
- Tool-name labels admit multiple paths but are still incomplete proxies; inspect
  unexpected valid strategies rather than blindly optimizing the label score.
- Frozen retrieval tests do not validate SEC parsers, network behavior, search recall,
  paywall coverage or real-world article complexity. Separate live checks are needed.
- Missing/budget-limited judgments must be reported with assessment coverage; judging
  only easy successes creates selection bias. Do not compare differing budgets/models
  or pool frozen/live results without clearly separating them.
- Sentiment samples are bounded, not market consensus. Attribution metadata does not
  establish expertise, and no evaluation establishes future returns or suitability.
