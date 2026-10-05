# Reviewing paired agent evaluations

Keep quality review separate from model-call, time and token comparisons. No commands in this guide invoke an LLM or retrieve external financial data: they read completed, saved evaluation files.

## 1. Prepare the experiment

Declare questions, criteria and development/validation membership before inference. Freeze source code, model and source fixtures for the whole paired run. Use the same questions for both profiles, retain failed answers, and counterbalance execution order. The efficiency runner records these settings and supports custom case/split files.

New wording over familiar fixtures is a regression pilot, not independent real-world validation. Once a question has informed a fix, treat it as development material. One run per question does not establish stable latency; repeat timing separately before a broad performance claim.

## 2. Review without version names or performance metrics

From the project root:

```sh
PYTHONPATH=backend work/mcp-venv/bin/python -m app.evaluation.paired_audit work/fresh-validation-v34 --packet --output work/new-review-packet
```

Use a new output directory. The command writes:

- `review-packet.json`: questions, predeclared criteria, reports and their sources under randomized A/B labels. Model calls, timing telemetry and version names are omitted.
- `scores-template.json`: fill in the reviewer/method, completion, support and a short evidence-specific explanation for every answer. Leave nothing unreviewed before importing.
- `private-mapping.json`: maps A/B labels back to profiles and binds each answer to its saved hash. Keep this closed until scoring is finished; do not send it to a reviewer with the packet.

Formatting may reveal which implementation produced an answer, so describe this as version-hidden or partially blinded review, not guaranteed double-blind evaluation. Existing V34 reviews were non-blinded; generating a packet later does not change that history.

Review the original question and the predeclared criteria. Check each factual assertion against its own cited source, including extra assertions and claimed source limitations. Do not score from the agent's `complete` or `verified` flags. Those are behavior under test.

Completion and source support are separate:

- Correct figures without the requested explanation can fail completion.
- Answering the requested parts while adding an unsupported claim fails support.
- A clear, justified limitation can satisfy a qualified-answer rubric; an empty failure does not automatically count as a supported success.
- In notes, identify the failed criterion or claim and its evidence ID. Do not reinterpret criteria after seeing results to favor either profile.

For meaningful claims, use a second reviewer on disagreements and unsupported-claim cases. Keep each original review and document adjudication instead of overwriting it.

## 3. Import completed scores

```sh
PYTHONPATH=backend work/mcp-venv/bin/python -m app.evaluation.paired_audit work/fresh-validation-v34 --scores work/new-review-packet/scores-template.json --mapping work/new-review-packet/private-mapping.json --output work/imported-review
```

The importer rejects unreviewed placeholders, duplicate or missing slots, answer-hash mismatches, and changes to the experiment settings or rubric. The resulting `review.json` is compatible with the efficiency summary and token-cost report. Preserve the packet and mapping alongside the scores.

## 4. Inspect every question, not only averages

```sh
PYTHONPATH=backend work/mcp-venv/bin/python -m app.evaluation.paired_audit work/fresh-validation-v34 --review work/imported-review/review.json --output work/new-paired-audit
```

`paired-audit.md` and `paired-audit.json` report:

- Completion, support and joint success counts.
- Calls, time and tokens across **all attempts**, including failures.
- A separate comparison on questions successful in **both** versions.
- Per-question quality and efficiency regressions, missing usage and reviewer notes.

The audit refuses incomplete experiment pairs rather than silently dropping them. Zero jointly successful pairs means successful-task speed comparison is unavailable, not zero cost. Missing usage is unknown, not free. Token counts are a model-specific cost proxy, not dollars.

The historical V34 audit is in `work/evaluation-audit-v39-final`. It shows overall efficiency gains but no questions satisfying both completion and support in both versions under the strict review. Consequently, it cannot establish faster successful research on a matched-success subset. Its release decision remains **do not promote**.


A fresh repeated validation is complete: `work/validation-v40-final/comparison.md` (nine new questions, two repetitions, 36 answers). The experimental profile has aggregate efficiency/quality gains but fails promotion due to a repeated education completion regression. Its reviews were only partially blinded; see the report for exact limitations. The reviewed questions are now development material.


## V44 validation completed — 2026-10-02

18 answers reviewed against predeclared criteria. Complete: 2/9 → 6/9; jointly complete/source-supported: 1/9 → 6/9. Calls fell 21.1%, but average latency increased 20.4% and tokens increased 22.8%. Gate: do_not_promote; standard remains default. Remaining failures: education explanation, prospective-risk interpretation, sentiment routing. Partial manual blinding, familiar fixtures, one pass; not independent or generalizable proof. Source/model/archive and score/audit integrity verified. Full report: `work/validation-v44-final/comparison.md`. V44 is now inspected evidence, not an unseen validation set.


## V51 completed — 2026-10-03

18 answers reviewed before unblinding. Calls 86→57 (-33.7%); average seconds 154.85→104.70 (-32.4%); recorded tokens 206,636→173,888 (-15.8%). Complete 1/9→8/9, source-supported 5/9→7/9, jointly successful 0/9→6/9. No matched successful pairs; standard timeout makes recorded token usage incomplete for any unreturned computation. Two categories meet all observed quality/resource checks; whole-agent goal unfinished. Gate do_not_promote; no second timing pass per predeclared rule. Source/model/archive/review integrity verified. Remaining issues: education coverage, mixed/interpretive citation support, and unnecessary research. Report: `work/validation-v51-final/comparison.md`. V51 is now inspected evidence, not unseen validation.
