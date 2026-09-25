# Sentiment integration validation — 24 September 2026

The implementation now uses multi-index public discovery, article extraction,
information-type classification, source review, and a compact lead-agent handoff.
This is a prototype validation record, not an investment-performance benchmark.

## Automated and browser checks

- 244 backend tests passed.
- Next.js production build passed.
- Browser replay of a collected report passed: sentiment toggle and API payload,
  overall assessment, bullish/bearish sections, expandable source citations, and
  mobile layout without horizontal overflow.
- Coverage tests include non-public destinations and redirects, pinned TLS host
  verification, response-size bounds, provider failure isolation, stale/missing
  dates, inaccessible bodies, original-provider attribution, duplicate articles
  and quotations, irrelevant discovery results, unsupported excerpts, incomplete
  review, truncated synthesis, and sentiment handoff to the lead.

## Live local-model checks

Model: local Ollama `gemma4:e4b`. No hosted-model requests were used.
Question scope: Microsoft's current investment arguments and financial claims
requiring corroboration. All sources are a bounded 30-day sample.

| Measure | First development run | Second validation run |
| --- | ---: | ---: |
| Discovered candidates | 36 | 24 |
| Article attempts | 10 | 10 |
| Articles read | 6 | 6 |
| Articles contributing reviewed points | 5 | 6 |
| Attributed publishers contributing points | 4 | 5 |
| LLM calls | 9 | 10 |
| Elapsed seconds | 337 | 310 |

Both produced mixed-sentiment sample assessments. Yahoo Finance RSS, Bing News,
and Bing web returned candidates. DuckDuckGo was unavailable during these runs;
that failure did not suppress the other discovery results. Some publisher pages
were blocked or lacked accessible dated article bodies; four attempts failed in
each run. Results retained those gaps rather than manufacturing conclusions.

The first run exposed a truncated summary sentence that model review accepted.
A deterministic completeness check and conservative fallback were added. In the
second run the free-form synthesis was withheld; individually reviewed points
formed the final brief with bullish/bearish arguments and corroboration tasks.
Later refinements keep publisher diversity, deduplicate near-identical quotes,
and ensure a mixed fallback summary cites both sides. Tests cover those refinements.

The lead handoff includes the assessment, cited arguments, information types,
source provenance, coverage and useful verification tasks. Full article bodies,
retrieval logs and redundant quote text are excluded from the lead context; the
user-facing report retains supporting excerpts. The validated handoff was about
6 KB of JSON. The API/graph integration tests verify that the lead receives it on
its next investigation decision and during final drafting.

A live lead-agent handoff check selected `get_financial_metric_history` for MSFT
operating cash flow over five years, using the sentiment brief to choose a useful
financial follow-up. Its arguments passed the production tool schema. The check
did not execute that financial retrieval. It exposed and fixed a missing-input
tool decision: investment tool choices now use the actual available-tool schemas
and reject a tool action with null input.

## Limits on these conclusions

These are two development smoke runs for one company, not a controlled A/B test.
Publisher variety is not proof of independent reporting: outlets may describe
the same underlying analyst note. Exact/near-copy deduplication does not detect
all shared narratives. Source metadata does not establish credentials, and
same-model review can miss semantic errors. Reported facts must still be checked
against financial/filing tools. No representative social-media or paywalled
research coverage is claimed.

Repeat using `python -m app.evaluation.sentiment_smoke` with a new output directory.
Use multiple companies and a human-reviewed rubric before claiming better
investment answers than the lead-only workflow.
