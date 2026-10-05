# Efficiency and reliability work

The candidate is experimental. The normal application still uses its standard workflow, and MCP remains required for financial tools. No whole-agent performance improvement is established yet.

## Changes under evaluation

| Area | Candidate change | Guardrail retained |
| --- | --- | --- |
| Research | Select the first retrieval tool while making the plan | Tool schemas, tool budgets, subsequent investigation, and source verification |
| Comparisons | Compute revenue growth from retrieved adjacent annual figures | Decimal arithmetic, units, periods, scope checks, and input lineage |
| Research report | Assemble verified findings in Python | Claim validation, unsupported findings withheld, unresolved requirements retained |
| Investment | Use claim-specific source review with exact supporting excerpts | Every reason/risk and proposed action requires approval |
| Sentiment | Assemble a brief from reviewed arguments | Reading, quote checks, classification review, attribution, sample limitations |
| Education | Plan guide retrieval while routing when possible | Source review and checks that requested parts were answered |

## Results so far

The second broad development experiment used 9 questions across 9 categories, with standard and candidate agents each gathering their own frozen evidence. Its comparison case improved: both companies' growth and margins were included, using 6 model calls instead of 8. Its aggregate results regressed, however: average calls increased from 7.67 to 8.56 and latency from 90.32 to 101.59 seconds. Manual non-blinded review found task completion increased from 3/9 to 4/9, while fully source-supported responses fell from 7/9 to 5/9. **This candidate must not be promoted.**

The review identified wrong filing-section filters, ambiguous company selection, and analyst commentary attached to unrelated filing citations. The next candidate addresses these problems; passing unit tests alone does not prove answer quality.

- [Development v2 compact results](work/broad-development-v2/progress.md)
- [Development v2 answer-bound review labels](work/broad-development-v2/review-codex.json)
- [Development v6 run manifest](work/broad-development-v6/manifest.json)

The v3 run was stopped after a review-design gap was found: action suitability needed its own check alongside claim support. Partial results remain saved, with the interruption noted in its manifest. A later schema integration check caught another issue before rollout: the output schema needed the new finding IDs and tool argument schemas. Those checks are now covered by integration tests. The current candidate passed **400 backend tests** and the frontend TypeScript check. A live local-model smoke confirmed first-tool selection and rejection of the mis-cited analyst claim. Supported partial findings are retained without approving an incomplete investment assessment.

The v6 experiment applies an explicit frozen-data contract equally to both profiles. Fictional records remain labeled fictional; missing evidence and ambiguous companies remain gaps. This avoids repeated requests for live data that the offline test deliberately cannot provide. Because the contract changed, compare the profiles within v6 rather than mixing its timing with earlier versions.

## Before a resume claim

1. Finish development evaluation and inspect actual answers and citations.
2. Evaluate reserved questions without tuning on their outcomes.
3. Repeat timing runs to check hardware/load variance.
4. Report model calls, latency, task completion, and source support together.
5. Use percentage points for task-completion-rate changes. Do not present development-only or education-only improvements as whole-agent results.

Timing runs use a local Ollama model with frozen sources, not paid APIs. Live provider/network latency and retrieval failures require separate integration checks. Manual reviews here are not independent human evaluations.

## Latest checkpoint: development v7 and candidate v8

V7 finished all 18 runs (nine paired development questions). Manual, non-blinded answer/source review found 4/9 completed questions for standard and 6/9 for efficient. Supported answers were 6/9 and 8/9 respectively. These labels are separate from the agent's self-reported completion flag.

Mean calls: 8.11 → 7.89 (2.7% fewer). Mean latency: 93.99 → 102.21 seconds (8.7% slower); median: 88.09 → 83.94 seconds; p95: 194.80 → 201.86 seconds. The candidate is not ready for promotion. Investment and sentiment remain incomplete, and both profiles guess the ambiguous issuer.

Artifacts: `work/broad-development-v7/progress.md`, `review-codex.json`, `source.zip`, and `reproducibility.json`. One run per question, local inference, fictional frozen data; no whole-agent resume percentage is established.

V8 is merged into this isolated Documents project, not the original Desktop/GitHub app. It adds original-company-reference validation, conservative SEC-name resolution, duplicate-call recovery, calculation source context, clarification-bound review hashes, and actual Ollama token accounting. The two-question local integration smoke completed in `work/schema-smoke-v8`: ambiguous Mercury triggers clarification in two calls; the comparison returns both growth rates and margins in five calls without the false missing-source gap. These are integration checks, not a paired performance experiment. All 415 backend tests pass. Standard remains the application default.

## V9 failure and V10 focused repair

V9 was stopped early when the sentiment case presented historical numbers as projections and its LLM reviewer approved the claims. This is a source-accuracy regression, so the interrupted experiment is not an aggregate performance result. Raw outputs and the exact source snapshot are retained in `work/broad-development-v9`.

V10 adds a deterministic check against reclassifying structured historical figures as forecasts. It also bounds repeat sentiment investigation by issuer at schema and runtime levels. 422 tests pass. The two affected development questions are being retested locally in `work/schema-smoke-v10` before another broad evaluation. No changes have been promoted to the original app or GitHub.

V10 focused checks completed: both retained financial statements with supporting citations; the sentiment question still lacks an explicit speculation answer. See `work/schema-smoke-v10/review.md`. All 423 backend tests pass. The new full development comparison is running under `work/broad-development-v10`, with its source snapshot preserved. No overall improvement claim or deployment yet.

## Current checkpoint: V10 complete, V12 focused checks

V10 completed nine paired development questions (18 runs). Mean calls fell 8.1111 → 6.7778 (16.4%); mean latency fell 97.0911 → 86.1703 seconds (11.25%). Median latency fell 93.4549 → 72.0174 seconds, but p95 increased 185.2244 → 201.7155 seconds. Manual, non-blinded review found completion 4/9 → 7/9 and source support 6/9 → 8/9. These development results do not establish resume-ready improvements: an unsupported demand interpretation remained, speculation coverage was incomplete, and the latency tail regressed.

V11 merged numerical statement rendering and explicit speculation labeling. Its focused smoke now covers speculation but the LLM reviewer discarded valid numerical facts without supporting excerpts, leaving empty investment cards. V12 separates exact, reproducible Python-verified numerical statements from passage claims; the model still reviews passage interpretations and proposed actions. Failed action review cannot approve an investment assessment, but supported numerical facts remain visible as partial findings. Altered arithmetic, missing/cyclic dependencies, missing sources, wrong issuers, and added qualitative claims cannot receive Python approval.

V12 focused local-model checks: `work/schema-smoke-v12`. The main suite passed 442 tests; a subsequent review-outage regression test also passed in the targeted 65-test run. Full paired evaluation and reserved validation remain outstanding. Changes are isolated to Documents, standard remains default, and nothing in this checkpoint has been pushed to GitHub. Future paired experiments share the speculation-voting correctness fix across both profiles; standard is the current reference profile, not an immutable historical build.

V12 focused smoke completed: sentiment 13 calls/197.26s, investment 13 calls/169.95s. Both retain supported numerical findings rather than empty cards, while leaving rejected investment assessments partial. Sentiment covers opinions versus speculation. The beginner investment answer still needs a useful checklist, and repeated investigation remains inefficient. No full paired or held-out gain claimed. Full suite now 443 passed; detailed audit in `work/schema-smoke-v12/review.md`.

## V13 candidate

Added an optional beginner research checklist to each efficient-profile card, displayed separately from verified findings. It links only to retained claim evidence (and source-backed same-issuer dependencies); missing evidence remains explicitly unestablished. The checklist does not turn missing research into completed work. It adds no LLM call. Efficient investigation now stops on an exact repeated tool call, recording `duplicate_skipped` and an unresolved-gap limitation instead of spending the remaining decision budget repeating the failure. Different tool arguments remain eligible for further investigation.

445 backend tests and frontend TypeScript checks pass. Focused local-model smoke is in `work/schema-smoke-v13`; it is not a paired performance evaluation. Standard remains default; Documents changes are not deployed or pushed.

V13 smoke finished: sentiment12calls169.4025s; investment13calls188.5766s. The sentiment duplicate was skipped with supported content retained. Investment is not faster and still re-fetches initial financials; initial collection must enter duplicate detection. Checklist improves next-step guidance, but does not establish completion of company research. See `work/schema-smoke-v13/review.md`. A post-smoke deterministic checklist-order fix passed targeted tests; source snapshot predates that display-only ordering change. No active evaluation or validated aggregate performance gain from V13.

## V14 development complete; reserved validation started

Nine paired development questions: mean calls8.1111→6.5556 (-19.2%); mean latency99.9575→82.5794s (-17.4%), median89.8274→67.4669s, p95231.135→168.4786s. Manual non-blinded rubric review: completion4/9→9/9; source support6/9→9/9. These are small development-set scores, not independent validation. Investment and open_research regress on latency/calls despite aggregate gains; investment changes routing between profiles. The beginner checklist satisfies the request for checks, not completion of those checks; open research meets only the narrow disclosed-risk/data-gap rubric.

447 tests pass. Initial collection now informs efficient duplicate detection. Development artifacts and exact source archived in `work/broad-development-v14`. Reserved validation running in `work/broad-validation-v14`, same frozen code/model, no retuning during run. Default remains standard; changes are Documents-only and not pushed.

## V14 reserved validation failed the quality gate

All18 reserved runs completed unchanged. Mean calls9.8889→8.2222 (-16.9%), mean latency137.8421→115.9590s (-15.9%); median125.2411→102.1146s, p95261.9963→230.3793s. Strict manual non-blinded review: completion3/9→4/9, fully supported5/9→4/9. The all-claims support rule includes unsupported qualifiers (e.g. infrastructure investment called necessary); details are explicit in `work/broad-validation-v14/review-codex.json`. Development9/9 did NOT generalize. Do not promote or use development-only quality percentages as a whole-agent claim.

Failures: missing business comparison; attributed analyst opinion excluded as speculation; research business claim cited a risks-only passage; unspecified comparison company invented; unsupported qualitative necessity modifier. v15 begins repairs: shared route missing-context field/check and attribution-aware sentiment counting that keeps uncertainty labels.455tests passed before a subsequent bounded-display text guard; targeted sentiment suite also checked. Sentiment correction applies to both profiles. Any replay of these formerly reserved cases is now a regression check, not fresh held-out validation. Original Desktop/GitHub/default remain unchanged.

## V16 regression checkpoint

The shared missing-context route check now asks for the unnamed comparison target before either graph, using the existing routing call. V15 mistakenly treated the local model's N/A placeholder as a reference; V16 ignores explicit empty placeholders only if absent from the question. Full suite460passed. Targeted local checks: missing company clarified in1call; named-company sentiment continued normally in11calls and preserved attributed bullish/bearish coverage while excluding anonymous speculation from the opinion tally. These are regression checks on already-examined cases, not new validation. Qualitative source support (necessary-investment modifier), research citation mismatch, and business coverage remain unresolved. Detailed results: `work/schema-smoke-v16/review.md`. No active evaluation, promotion, or push.

## V17 reliability repairs

Efficient-profile deterministic guards reject unsupported necessity wording and clear business-topic/citation mismatches. Passing these narrow guards is not semantic entailment; model review and provenance checks remain.471tests passed before local regression checks. The business-research case now retrieves/cites its business passage instead of attaching the claim to risk text; the investment case retains the risk without unsupported necessity. Archived runs:10calls188.1868s and6calls85.234s respectively, candidate only, no paired gain claim. Details in `work/schema-smoke-v17/review.md`.

Post-smoke presentation repairs distinguish supported findings from rejected actions and suppress historical-comparison warnings on descriptive reports.473fulltests passed before a narrow wording-condition follow-up, followed by targeted tests. No new held-out score; general business-comparison completeness remains outstanding. No model run active, no promotion or push.

## V18–V19 comparison repairs

V18 routed explanatory investment comparisons into research but failed to retain a useful answer (12 calls, about181seconds). The trace exposed repeated claim IDs overwriting unrelated findings and confusion over the incremental evidence batch. V19 preserves unrelated findings under unique IDs while permitting same-source wording corrections and explicit rejected-claim replacement. It also supplies an inventory of already collected evidence to assessment.477backend tests pass. A candidate-only local replay is in progress in `work/schema-smoke-v19`; no new quality or speed claim is established. Source snapshot archived; original Desktop/GitHub app and default profile remain unchanged.

V19 replay completed:12calls218.65s, still fails comparison completion and source support. Prior Microsoft findings survive, but the reviewer accepts a Microsoft business statement citing NVIDIA and an evidence-absence claim citing one Microsoft value. Narrow topic checks are insufficient when companies share generic vocabulary. Audit: `work/schema-smoke-v19/review.md`. Next priorities: issuer-aware claim checks, exclusion of retrieval-coverage assertions from sourced facts, and comparison coverage. No run active; no promotion.

## V20–V21 source and coverage checks

V20 adds efficient-profile issuer checks using known issuer names/tickers and cited metadata, plus a guard excluding retrieval-absence statements from sourced company findings. Assessments receive all collected observations instead of only the latest batch. The focused replay retained both business descriptions with correct citations, but remained incomplete and slower (15calls326.92s). NVIDIA risks and the financial comparison were missing; the source review also leaves unsupported spending-size modifiers. No fully supported completion or efficiency improvement is claimed.

V21 adds model-selected per-company coverage targets. Python reports which requested filing sections, financial measures and calculations have been retrieved for each company; another company's evidence cannot fill the gap. Missing targets block completion, while the agent continues to choose tools. Coverage is not entailment.488tests pass; local regression replay in `work/schema-smoke-v21` is running. Original Desktop/GitHub unchanged; standard remains default.

V21 replay completed:12calls260.21s. Final retained claims match inspected fictional sources, but the comparison is incomplete. The checklist reports missing per-company requirements; the agent still repeats searches rather than retrieving both companies' risks and NVIDIA financials. Model plan also put tool-call JSON inside free-text questions. This remains a failed completion case, not a speed/quality promotion. Details: `work/schema-smoke-v21/review.md`. No evaluation running.

## V23–V25 combined assessment and numerical fast path

Efficient research assessment now proposes the next tool in the same response, with actual argument schemas, prior calls, and unchanged final verification. V23 comparison finally covered both businesses, risks, margins and growth in10calls, but317.60seconds and56183tokens: lower call count alone did not imply lower cost. Its simple financial question still omitted a retrieved metric.

V24 adds canonical Python rendering of annual company financial values, preserving exact amounts, units, periods and source links. Eligible declared numerical-only questions can skip drafting once every company target is retrieved; final question-coverage review still runs. V25 removes exact empty markers such as unresolved=['None'] so they do not trigger redundant investigation.507backend tests pass.

Focused financial_data02 regression v24→v25:5→4calls,16792→12004total tokens (28.5%reduction), correct requested figures retained and no false missing-data gap. Local time95.26→25.11seconds is cache/load-sensitive, not a generalized performance claim. No broader new cost/completion result. Latest source is archived under schema-smoke-v25; another-company/missing-data checks are running under schema-smoke-v25-safety. Standard remains default; original Desktop/GitHub unchanged; no OpenRouter testing.

Additional V25 checks completed: Microsoft financial answer complete and source-supported in4calls11972tokens; unavailable NVIDIA financial data correctly produces no factual findings and remains incomplete (5calls12783tokens). Missing-data run still repeats requests. Reviews under `work/schema-smoke-v25-safety/review.md`. No evaluation running; broad paired/repeated testing remains before rollout.

## V25 full paired development results

All18answers reviewed (nine pairs): calls8.11→5.11 (-37.0%), mean latency97.84→82.15s (-16.0%), mean tokens18602.78→16138 (-13.25%). Manual non-blinded completion4/9→7/9 and supported answers6/9→7/9. Including failed attempts, tokens per supported completed answer41856→20749 (-50.4%); this is a small development-set token ratio, not billed cost or validation evidence. Comparison/calculation/open-research tokens and latency regress. Candidate business-description answer fails from next-action/tool contradiction; beginner investment question still incomplete. Full review and cost report: `work/broad-development-v25/review-notes.md` and `token-cost.json`. No promotion.

V26 strengthens generated assessment schemas to require tool/action consistency and keeps validated findings if a provider still returns a malformed action. Exact empty open-question markers are normalized.513tests pass. Focused local filing/calculation regression running in `work/schema-smoke-v26`; no OpenRouter or deployment.

V27 focused regressions complete and source-supported: filing description4calls10157tokens; calculation3calls8000tokens; financial comparison3calls10749tokens. Calculation/comparison use62.8%/64.3%fewer tokens than the V25 candidate on those specific familiar questions. These are follow-up regressions, not new broad paired scores; timing is load/cache-sensitive.515tests pass. V28 is testing a routing correction for the remaining beginner due-diligence failure, using the existing company checklist workflow. No default rollout or OpenRouter testing.

## Token-aware evaluation gate

The evaluation now reports total tokens and tokens per manually reviewed, source-supported completed answer. The numerator includes unsuccessful attempts. A promising-small-sample result requires complete usage data and non-increasing total tokens and tokens per supported completion, alongside the existing quality, calls, and timing checks. Missing usage or zero supported completions cannot pass; no validation cases leaves the gate awaiting review. Tokens remain a usage proxy, not dollar savings. This change adds no model calls and does not change runtime agent behavior.

V29 explicit sentiment regression retained the specialist and source-attributed opinions/speculation (12 calls, 31,688 tokens). It still over-researches and displays unsolicited timing language. No new broad or held-out improvement is claimed; V25 remains the latest paired development measurement.

## Informational results (V31)

Efficient drafting explicitly classifies informational questions versus investment decisions in the existing model call. Informational cards omit buy/watch/avoid and timing instructions; source verification and incomplete status remain. The interface hides the purchase-instructions section when all cards are informational. Company batches preserve the answer type.

526 backend tests and the frontend type check passed. A two-call local drafting/source-review check with replayed research evidence confirmed the informational format. The preceding full V30 sentiment run did not improve calls or tokens and still repeated a search; no new end-to-end efficiency gain is claimed.

## Informational completion and stopping (V33)

Informational reports now review source support and question coverage independently of investment-action approval, within the existing review call. The reviewer sees the displayed sentiment summary and checklist and must explicitly identify unanswered requirements. Correct facts alone cannot establish completion. The investigation step similarly declares whether the question is covered; a covered question without remaining requirements proceeds to final review instead of dispatching an optional tool.

A local V32 run exposed exact N/A strings being mistaken for unresolved requirements. V33 reuses the existing empty-marker normalizer; real gap sentences remain. Replaying the saved model decisions confirms complete informational output and removal of the duplicate attempt. This replay used no inference and is not evidence of speed/token savings. The earlier optional web search remains unresolved. 536 backend tests pass. No broad validation or promotion yet.

## Fresh-question pilot started (V34)

Added a separate nine-question validation set with predeclared criteria, including cash-flow direction comparison, industry-focused ETF concentration, and unavailable financial figures. The runner accepts external case/split files and rejects duplicated, overlapping, missing or unknown assignments. Its manifest records split membership, full case content and source-code fingerprint.

542 tests pass. The local paired run is in `work/fresh-validation-v34`, with progress in `work/fresh-validation-v34.log`. No results or promotion decision are asserted until all answers are saved and audited. The new questions reuse familiar fictional fixtures; disclose this limit.

# V34 completed new-question comparison

All 18 answers manually audited against predeclared question criteria and each claim's own sources. Non-blinded Codex review, one run per profile/question, nine new questions using familiar fictional data. Timing depends on local load/cache. These questions have now been inspected and used to diagnose fixes, so they are development material for future iterations.

| Measure | Standard | Efficient |
|---|---:|---:|
| Mean model calls | 9.78 | 6.89 |
| Mean response seconds | 130.10 | 96.93 |
| Mean tokens | 24041 | 19341 |
| Reviewed completion | 2/9 | 5/9 |
| Fully supported answers | 4/9 | 6/9 |
| Both complete and fully supported | 0/9 | 4/9 |

Measured reductions: calls 29.5%, mean time 25.5%, tokens 19.5%. Completion rose by 3 of 9 questions (33.3 percentage points), not a broadly validated accuracy claim.

Decision: **do not promote**. Three candidate answers fail strict source support, and only four meet both completion and support. Correct facts do not excuse missing requested conclusions or additional unsupported claims. Costs per successful baseline answer cannot be calculated because the strict joint-success denominator is zero; no relative cost-per-success percentage is defined. Usage tokens themselves are present for all answers. The gate field token_usage_complete currently conflates that ratio availability with token availability; see the actual per-profile token_coverage=9 values.

The financial-figure, operating-profit-input and beginner-checklist results improved. The sentiment answer retained attributed opinions with speculation labels and eliminated unsolicited timing. Cash-flow direction synthesis, ETF own-citation support, missing-data explanations and open-risk recovery remain weak. The filing answer also added an unsupported regulatory-risk claim. Detailed decisions are in review-codex.json and diagnoses in review-notes.md.

V35's filing-section schema correction was made only after this complete run and audit. It is not represented in the above paired figures. No original Desktop checkout/GitHub update or default-profile promotion occurred.


## Filing contract correction (V35)

Constrained filing section arguments to the actual provider topics and aligned invalid-input handling across production and frozen tools. A local regression retrieved and correctly cited customer/packaging risks that V34 had missed. It still drifted into an unrelated historical margin explanation, so full question coverage remains unresolved. Five calls, 15,062 tokens; no new efficiency gain claimed.

Separately corrected the evaluation gate's reporting distinction: complete token telemetry and a comparable cost-per-success ratio are now separate flags. Zero successful baseline answers makes the ratio unavailable, not the usage data missing. The archived V34 summary keeps its original gate field; audited-comparison.md explains this limitation.

## Requested-metric coverage (V36)

The planner now declares raw financial metrics and a minimum count of comparable annual periods. A profit-growth request can be covered by operating income; a cash-flow request by operating cash flow. Coverage rejects mismatched issuers, currencies, periods, segment/quarterly records, duplicate dates, calculations masquerading as raw values and nonfinite numbers. Final review still checks exact requested years and answer completeness; retrieval coverage is not final approval.

557 tests passed before the final field-description wording cleanup. Two local regressions correctly removed unrelated revenue requirements but still took seven calls each. One added an unnecessary filing requirement; the other failed to calculate the second company's change and state the comparison. No additional end-to-end efficiency gain is claimed.

## Planning consistency and remaining calculations (V37–V38)

Efficient plan schemas now disallow filing_explanations for descriptive questions while preserving historical causal research. When a declared company calculation is missing, the decision context surfaces bounded, valid, not-yet-executed calculation options from the existing tool schema. The agent still chooses among all tools and results still require verification.

The familiar cash-flow comparison selected Apple's missing calculation and completed with six model calls versus seven, and 24,919 versus 29,066 tokens (14.3% lower on that one replay). The profit-growth case remained at seven calls: the model substituted an unnecessary generic filing requirement. This is not a broad efficiency result.

V38 adds increase/decrease/no-change-at-displayed-precision wording to Python-derived growth and margin changes, with signed values and provenance retained. A no-inference replay confirms both companies' directions are explicit. 562 backend tests pass. No release/default switch/GitHub push; V34 comparison remains immutable.


## Evaluation audit and review workflow (V39)

Prioritized evaluation tooling over additional runtime tuning. Added an offline paired audit separating all-attempt efficiency from efficiency on questions completed and source-supported by both profiles. Reports expose per-question quality and efficiency regressions, preserve missing usage as unknown, and reject incomplete or duplicate experiment pairs.

Added randomized A/B review packets with profile labels and telemetry removed, separate completion/support scores, and an importer binding scores to answer hashes and experiment settings/rubrics. This is partial blinding: answer style can reveal a profile. The existing V34 review remains non-blinded, and its questions are now development material. No new inference, independent review, or performance gain is claimed.

574 backend tests passed. Final artifacts: work/evaluation-audit-v39-final/paired-audit.md and work/evaluation-review-packet-v39-final/. Review instructions: evaluations/REVIEW_WORKFLOW.md. The strict V34 joint-success counts remain 0/9 standard and 4/9 efficient; no matched-success speed comparison is available. Do not promote. No GitHub push or default switch.


## Repeated fresh-question validation (V40, completed)

Ran nine predeclared new questions across nine categories, two full repetitions, both current standard/efficient profiles: 36 answers using local gemma4:e4b and familiar frozen fictional fixtures. No runtime tuning during the run. All answer-bound/rubric-bound reviews, source archive hashes, code fingerprints and local model digests verified. Both repetitions completed; no evaluation job remains active.

Across 18 attempts per profile: standard 175 calls, 457316 tokens, 2575.9003 seconds; efficient 110 calls, 343358 tokens, 2067.1613 seconds. Reductions: 37.1% calls, 24.9% tokens, 19.7% time. Completion 6/18 to 8/18 (+11.1 percentage points); full support 10/18 to 16/18; joint success 2/18 to 8/18. All-attempt savings include failures. Only one unique question succeeded under both profiles, so matched-success speed results are narrow.

Do not promote: education completion regressed in both repetitions. Remaining weaknesses include missing formula/working, missing explicit comparison conclusions, sales/cash-flow synthesis, and missing-data explanations. Timing reductions varied from 24.6% in repetition 1 to 15.4% in repetition 2. Two repeated observations per question do not establish broad statistical confidence.

Review method: Codex manually scored A/B packets before opening profile mappings, with same developer/rubric author (not independent review). First packet exposed nested sentiment timing; the second display hid it. Formatting could reveal profile; partial blinding only. Second scores checked exact content differences against the first reviewed answers. The V40 questions are now inspected development material. Future tuning requires a separate fresh validation set for new generalization claims.

Final report: work/validation-v40-final/comparison.md and comparison.json. Raw runs/audits: work/validation-v40-r1 and work/validation-v40-r2. Predeclared dataset: evaluations/validation-v40. No paid API calls, default switch, original Desktop checkout edits or GitHub push.


## Targeted completion fixes (V41–V42)

Fixed the efficient education route when its education_plan is null: explicitly plan relevant guide topics and requested parts instead of silently using diversification. Valid route plans retain the shorter path. Direct efficient education selections also receive explicit coverage planning. Regression retrieves stocks and bonds for the ownership/lending/dividend question and retains both source and part-coverage review.

Shared Python-derived financial findings now display source-input arithmetic for growth, operating margin and margin changes. Numeric reproduction and citation checks remain mandatory. Efficient research adds comparisons only from reproduced company-wide annual growth calculations with the same metric, currency and fiscal boundaries. It rejects altered/missing/ambiguous inputs and incompatible scopes, and explicitly states faster growth, different directions or equal displayed changes. It does not rank investment suitability.

586 backend tests passed. Three local development regressions (previously inspected V40 questions) now contain the missing content: education (4 calls, 3902 tokens, 24.9767 s), capital-spending calculation (5 calls, 16657 tokens, 102.5429 s), cash-flow comparison (7 calls, 30780 tokens, 153.9298 s). These are targeted quality checks, not new aggregate validation or additional proven efficiency gains.

Artifacts: work/development-smoke-v41/review.md and work/development-smoke-v42/review.md, original answers, manifests and source archives. Both jobs completed. V40 remains immutable; its failed promotion gate is not superseded. Remaining work includes open-research synthesis, useful missing-data explanations, residual citation reliability, and a separate fresh validation after fixes. No default switch, original Desktop edits or GitHub push.


## V44 validation completed — 2026-10-02

18 answers reviewed against predeclared criteria. Complete: 2/9 → 6/9; jointly complete/source-supported: 1/9 → 6/9. Calls fell 21.1%, but average latency increased 20.4% and tokens increased 22.8%. Gate: do_not_promote; standard remains default. Remaining failures: education explanation, prospective-risk interpretation, sentiment routing. Partial manual blinding, familiar fixtures, one pass; not independent or generalizable proof. Source/model/archive and score/audit integrity verified. Full report: `work/validation-v44-final/comparison.md`. V44 is now inspected evidence, not an unseen validation set.


## V48 checkpoint — 2026-10-03

Whole-agent reductions are not established. Fixed two-stage sentiment routing and preserved source-approved education content despite invalid coverage metadata, without declaring it complete. Removed redundant research inventory. 590 tests pass; targeted model jobs and offline replay finished. Filing example uses fewer calls/tokens but remains incomplete and no faster; sentiment now actually answers at higher cost than the earlier empty result. Remaining work: consistent question-scoped plans, sentiment-only path, fresh broad repeated validation. Details: `work/development-checkpoint-v48/progress.md`. No default promotion, paid APIs or push.


## V50 implementation; V51 validation in progress — 2026-10-03

Added a dedicated commentary LangGraph branch for efficient-profile, named-company, opinion-only questions. It preserves specialist extraction/source review, adds compact question-coverage review, skips financial collection and purchase drafting, and renders a dedicated frontend heading. Mixed/discovery/purchase requests keep the full path. Disabled sentiment and failed coverage remain incomplete; long questions are passed intact. Planning now rejects financial_values with no metrics, uses compatible structured-schema branches, and permits one repair before tool execution. Repeated invalid plans stop incomplete. 600 backend tests and frontend type-check pass.

V49 sentiment development case: complete/supported by manual author review, 8 calls/58.4363s/8,796 tokens versus V46 same-question full path 11/127.6636s/25,212. Not a controlled repeated comparison. V49 plan schema failed; V50 repaired it and returned filing facts, but over-investigation and incomplete warning interpretation remain. V50 filing 9 calls/204.4611s/41,374 tokens; no successful-task gain claim.

V51: nine predeclared new question texts and rubrics, familiar fixtures, 18 paired answers. Runtime code frozen. Runner work/run-validation-v51.py; log work/validation-v51.log; output work/validation-v51. Finish answer review before opening the private mapping; evaluate each category and successful matched subset. No paid API, profile promotion or GitHub push. Second timing repetition only if initial quality/efficiency gates pass.


## V51 completed — 2026-10-03

18 answers reviewed before unblinding. Calls 86→57 (-33.7%); average seconds 154.85→104.70 (-32.4%); recorded tokens 206,636→173,888 (-15.8%). Complete 1/9→8/9, source-supported 5/9→7/9, jointly successful 0/9→6/9. No matched successful pairs; standard timeout makes recorded token usage incomplete for any unreturned computation. Two categories meet all observed quality/resource checks; whole-agent goal unfinished. Gate do_not_promote; no second timing pass per predeclared rule. Source/model/archive/review integrity verified. Remaining issues: education coverage, mixed/interpretive citation support, and unnecessary research. Report: `work/validation-v51-final/comparison.md`. V51 is now inspected evidence, not unseen validation.


## V52 reviewer-feedback boundary — 2026-10-03

Removed unverified coverage-review prose from investment report limitations. Reviewer feedback still determines incompleteness internally; the report displays a fixed missing-information notice and retains source-approved findings. This closes the path observed in V51 where feedback introduced an unsupported causal explanation into an otherwise reviewed answer. Tradeoff: free-text missing-question detail is no longer displayed on this path until it has a safe, verified representation. Two regression cases cover both a reviewer claiming completion and a reviewer admitting a gap; neither can publish the injected factual allegation or mark the report complete. No extra model calls, no inference benchmark rerun, no revised V51 scores, and no new measured efficiency claim. Citation completeness and education coverage remain outstanding.


## V53 financial-trend citation boundary — 2026-10-03

Added a shared deterministic guard to efficient research structural checks and investment claim checks. Explicit financial-trend statements now reject a missing metric topic in their own cited records; uncited observations cannot supply that topic. Covers revenue, net income, operating income/cash flow, capital spending and operating margins. Unknown-metric contrasts remain allowed. This narrow guard supplements semantic review: it does not prove trend direction, period completeness or causal interpretation, and does not automatically attach citations. Existing correction and incomplete-answer behavior remains in force. Five regression cases cover multi-metric claims, cited passages, unknown-metric contrasts and unrelated observations. No inference benchmark rerun or new latency/token/completion improvement claim.


## V54 focused evaluation — 2026-10-03

Two inspected V51 cases rerun on local gemma4:e4b. Calls and tokens unchanged (19 calls; 67,724 recorded tokens). NVIDIA reviewer-prose leak removed with retained rubric coverage; Apple reported-metric citation omission persists because its wording asserts no explicit trend. Unblinded author review: jointly complete/supported 0/2→1/2 against historical V51, not independent or broad validation. No efficiency gain or promotion. Source/archive hashes verified. Details: `work/development-smoke-v54/comparison.md`.


## V55–V56 broad check and scope experiment — 2026-10-04

V55 nine-category inspected-question run: 57 calls, 173,913 tokens; no new overall efficiency gain. Manual review 7/9 jointly complete/source-supported vs V51 6/9, attributable to the reviewer-prose fix. V56 three-case scope experiment improved education completion by selecting both requested guides in the actual routing path, retaining three calls but increasing tokens. Research changes did not establish quality-preserving efficiency gains and were reverted to archived V55 graph. Education router improvement retained; 609 tests passed before inference, regression rerun after restore. Artifacts: work/development-broad-v55/comparison.md and work/development-smoke-v56/comparison.md. No promotion or paid API use.


## V57–V59 optimization experiments — 2026-10-04

V57 schema-title trimming: paired identical answers in financial data, sentiment and education; financial tokens -3.25%, others unchanged, mixed timing. V58 expanded test failed filings efficiency (more tokens/time), stopped early and remains disabled. V59 retained a deterministic calculation-choice optimization: index same-company/unit candidates before validating pairs. Exact output and order matched the previous implementation; 12 alternating timings each show median preparation-time reductions of 42.4%/64.3%/86.5% at 4/8/25 companies; single-company essentially unchanged. These are backend microbenchmark gains, not model usage or end-to-end latency. Consistent whole-agent efficiency goal remains unmet. Artifacts: work/schema-pilot-v57/review.md, work/schema-broad-v58/review.md, work/registry-performance-v59.md.
