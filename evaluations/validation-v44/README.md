# V44 predeclared validation

One paired pass: nine newly authored questions, two current profiles, 18 answers, local gemma4:e4b with fixed fictional sources and existing counterbalanced order/limits. Questions/rubrics fixed before inference. No runtime changes during the validation. This round checks generalization after development regressions; it is not another two-repetition stability study. Familiar issuers/fixtures and categories limit external validity.

Review A/B answer content before opening profile mappings. Hide nested runtime metrics in the review display. Same developer/rubric author is reviewing: partial blinding, not independent validation. Count completion and source support separately, including failures. Release gate: no per-question completion/support regression, nondecreasing aggregate quality, and lower calls/time/tokens with known telemetry. Otherwise do not promote. Even a relative gate pass is not broad readiness proof. Preserve original results and report the subset successful in both versions separately.


## V44 validation completed — 2026-10-02

18 answers reviewed against predeclared criteria. Complete: 2/9 → 6/9; jointly complete/source-supported: 1/9 → 6/9. Calls fell 21.1%, but average latency increased 20.4% and tokens increased 22.8%. Gate: do_not_promote; standard remains default. Remaining failures: education explanation, prospective-risk interpretation, sentiment routing. Partial manual blinding, familiar fixtures, one pass; not independent or generalizable proof. Source/model/archive and score/audit integrity verified. Full report: `work/validation-v44-final/comparison.md`. V44 is now inspected evidence, not an unseen validation set.
