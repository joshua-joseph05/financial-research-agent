# V40 predeclared validation

Nine newly authored questions across nine categories, two full paired repetitions (36 answers). Both profiles run the same current code snapshot, local gemma4:e4b, frozen fictional sources, limits and warm-up. No runtime tuning during validation. Existing runner counterbalances profile order across questions; repetitions use the same fixed order. Two repetitions give a preliminary variability check, not precise statistical confidence.

Score completion and full source support separately using version-hidden A/B packets before opening mappings. The reviewing Codex also authored rubrics and implementation; this is not independent validation and style may reveal a profile. No model self-reported completion labels are used as ground truth. Preserve all failures, missing usage and run durations. Report each repetition and aggregate counts, plus per-question consistency. Familiar fixtures limit generalization to real sources and unseen companies.

Release requires no completion/support regression, known usage, and lower calls/time/tokens. Otherwise do not promote. Both profiles must succeed for matched-success speed comparisons. Do not change rubrics after inspecting results.

## Completed run

Both repetitions finished. See `../../work/validation-v40-final/comparison.md` for results and review limitations. No promotion: the education question regressed. Questions/rubrics above were preserved throughout; these cases are now inspected development material.
