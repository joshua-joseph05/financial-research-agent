# Corrected answer evaluator v2

This evaluator reads saved answer pairs. It does not call either answering workflow. The original evaluator and original artifacts remain unchanged. Output is written to a new directory with source hashes and the v2 rubric version.

Factual support is judged against the complete collected evidence, independently of the citations attached to an answer segment. Missing citations affect citation completeness. A contradiction requires a conflicting evidence witness. Unsupported means a definite extra assertion not established by relevant supplied evidence; unjudgeable means insufficient relevant evidence or ambiguity prevents assessment. This boundary still requires manual calibration. Neither rate is automatically a hallucination rate.

Citation validity is deterministic existence checking. Citation correctness is semantic support by the referenced evidence. Citation completeness asks whether each assessed factual segment requiring evidence has at least one appropriate citation. Invalid IDs remain validity failures even if the underlying claim is supported elsewhere. Procedural research notices do not require financial evidence.

Task grading sees the question, criteria and final answer segments, but no source bodies. Positive passes must quote answer text. Conditional company clarification is waived identically when the frozen case identifies the company. Source truth and calculation lineage remain separate checks.

Judge requests use strict Pydantic schemas, exact-ID checks, quotation witnesses and at most two attempts per task/claim batch, equally for both systems. Two claims per batch bound response length. Raw HTTP response bodies, raw model content, parsed judgments, explanations, attempts, time and failure reasons are retained. Exhausted retries yield judge_error, not answering-system failure. Failed claims are excluded from semantic quality denominators and coverage is reported. Unjudgeable claims are also reported separately, not scored as supported or false.

Retained calculation checks measure structured record/lineage correctness, not just the visible numerical answer. Historical answering latency and calls are reused unchanged. Baseline timing excludes collection of its inherited evidence and cannot support an end-to-end speedup claim.

Deterministic tests validate contracts, metric semantics and failure handling against handwritten fixtures. They do not prove that the LLM always makes correct semantic judgments. Live rejudgments require a documented manual audit of representative classifications.

## Independent support and citation calls

Factual-support calls have all answer citation IDs removed. They see the complete available source evidence, so missing or irrelevant answer citations cannot steer the truth classification. Separate citation calls receive only each claim's cited evidence and its lineage. The same two-attempt policy applies to both systems and both call types. A failed citation judgment does not erase a valid factual-support judgment. Headline semantic comparisons exclude pairs with incomplete relevant judgment coverage.

Run only saved-answer grading:

```bash
python -m app.evaluation.v2.rejudge \
  --source work/evaluation-18-20260925-153815-iu1ZE0/comparison \
  --output work/evaluation-corrected-v2 \
  --max-requests 640
```

Use `--dry-run` to calculate the request ceiling without model calls. Resume the exact same inputs and evaluator using `--resume`. Changed source hashes, model or evaluator code require a new directory. Every run copies historical artifacts and snapshots both rubric versions. No research or answer-generation entry point is called.

`comparison-v2.json` and `comparison-v2.md` include paired and category metrics, numerator/denominator coverage, mean/median latency, retry and error statistics, and the original aggregate metrics. Each pair JSON retains the unchanged original pair and all new judgments. Local raw output may contain the benchmark answers and sources; no API keys or provider headers are stored.

Live calibration artifacts are deliberately preserved even when failed. Early revisions showed invented citations, an unsupported causal clause being ignored, a vague assertion being misclassified, and a local JSON-schema compatibility error. The final calibration separates support and citations, validates exact quotation/ID contracts, and puts concise evidence comparison before the final label. A passed small calibration is not proof of general semantic reliability; inspect representative saved-answer judgments before using the scores to optimize the agent.
