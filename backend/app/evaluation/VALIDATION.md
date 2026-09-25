# Evaluation framework validation

This record describes framework validation, not a full benchmark quality result.

## Checks performed

- All 290 backend tests passed after adding the framework.
- The benchmark loader validates 90 unique cases: ten in each of nine categories.
- Offline tests execute real research graph loops for missing evidence, follow-up
  retrieval, sufficient-evidence stopping, clarification and request exhaustion.
- Frozen numerical inputs are checked against independent labeled values for all
  four companies; corruption, mismatched fiscal windows, missing inputs and
  cyclic citation lineage are rejected by evaluation checks.
- The direct sentiment target runs the actual consultation loop using controlled
  model outputs and frozen articles; article reads, arguments, dates, exact quotes,
  attribution and empty-source behavior are captured and checked.
- Judge tests reject omitted/duplicate items and uncited evidence. Missing results
  stay unassessed. CLI tests cover no-request dry runs, budget guards, artifact
  persistence, summary generation and validated manual review import.
- Frozen news tools are isolated from public network calls. Live-source parser
  behavior is covered by the repository's existing provider tests, not by synthetic
  article fixtures.

## Local-model smoke run

Ran the benchmark CLI for `education-01` ("What is diversification?") with real
local `gemma4:e4b` inference and frozen education evidence:

- Correct education route; sourced answer returned.
- Four agent model calls; approximately 35 seconds for the agent run.
- Two additional judge calls using the same local model.
- Judge task/claim output passed schema and evidence-ID validation; no judge errors.
- The single claim segment was judged supported and both case criteria passed.

This one easy case validates command integration and artifact generation. It is
**not** an estimate of overall accuracy. The same model acted as agent and judge;
there was no independent human adjudication. No 90-case live-model benchmark or
real-source quality study has been completed by this implementation run.

Full traces are written to ignored `work/` output directories when running the
commands. Use a fresh directory and report configuration and denominators with
any résumé or project-quality claims.
