# Citation-bundle refinement (answer-audit-v2.3)

This evaluation-only postpass consumes completed v2.2 artifacts. It never invokes financial research or the answering model. The saved answers, task judgments, factual judgments, calculation checks, and answering resource measurements are preserved. v2.2 results and evaluator code are copied into the new output directory before processing.

Citation validity remains the fraction of reference IDs that exist. Citation correctness is evaluated per **cited factual segment's bundle**: all cited records and valid calculation/source lineage may jointly support the assertions. Citation completeness measures required factual segments with supporting citations, including uncited segments as failures. A missing or inappropriate citation never changes factual support into unsupported or contradicted. Nonfactual segments do not receive citation-correctness or completeness scores.

The correction addresses a v2.2 limitation: requiring each reference independently to prove an entire multi-source comparison unfairly penalizes jointly supporting sources. Individual-reference judgments remain in `prior_citation_jobs`, with their raw outputs and retry history. Final-method reliability counts reused factual/task jobs and the new citation jobs; it excludes superseded individual-reference jobs. This is not the total computational cost of all evaluator experiments.

Each model call uses a strict schema, exact claim IDs, and at most two attempts. Calibration checks joint support, missing evidence, unsupported causation, and historical-versus-projected values. A well-formed response may still be semantically wrong; the manual audit remains necessary. Deterministic tests validate contracts and failure handling rather than claiming to prove the local model's semantic accuracy.

From the repository root, with `PYTHONPATH=backend` and the project's Python environment:

```sh
python -m app.evaluation.v23.calibrate --output work/citation-calibration.json
python -m app.evaluation.v23.rejudge --source work/evaluation-corrected-v22 --output work/evaluation-corrected-v23 --dry-run
python -m app.evaluation.v23.rejudge --source work/evaluation-corrected-v22 --output work/evaluation-corrected-v23 --max-requests 166
```

The maximum of 166 applies to the current frozen 18-pair corpus; use the printed bound for other corpora. `--resume` skips checkpointed judgments, including recorded judge errors. It rejects source, model, or evaluator-code changes. It does not silently regenerate failed results. Source v2.2 must be complete. Historical output directories must not be overwritten.

The baseline inherited the agent's evidence and Python calculations. Its answer latency excludes retrieval, so the reported times are not an end-to-end speed comparison. The two cases in each category are descriptive examples, not statistically strong findings.
