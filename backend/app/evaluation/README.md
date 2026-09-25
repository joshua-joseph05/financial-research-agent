# Lead-only versus sentiment-enabled evaluation

The general delegation workflow has been removed. The harness now compares the lead with sentiment disabled or enabled. **The current frozen financial fixtures do not provide sentiment articles or an issuer resolver: sentiment consultations return insufficient evidence. This harness does not yet measure the quality of live sentiment research.** Add representative frozen article cases before drawing quality conclusions. The application uses one bounded sentiment worker, a shared model-call budget, and direct lead investigation.

## Reproducible comparison

These cases use **fictional frozen financial data**, never production sources. They isolate orchestration from changing markets and source outages; they do not test live data retrieval accuracy. Unsupported fixture tools return no data. Run paired cases on the same day, since production freshness checks still use the current clock. Each pair uses the same configured model, question, evidence, and request budget. Case order is deterministically shuffled. Education questions are a control: they bypass specialists.

From the repository root, with the virtual environment active and `.env` loaded:

```sh
python -m app.evaluation.compare --case risks --budget 8 --output work/eval-risks --dry-run
python -m app.evaluation.compare --case risks --budget 8 --output work/eval-risks
python -m app.evaluation.summarize work/eval-risks
```

Only the middle command calls your configured LLM API. A pair may consume up to 16 requests. Check remaining free allowance first; there is no automatic quota reservation or paid fallback. Use a fresh output directory per experiment. `--case all --repeats 2 --budget 8` permits up to 160 requests across 20 runs, so do not run that when your available quota is smaller. `--dry-run` prints the upper bound without making model calls.

First score `blind-review.json` without opening `results.json` or the full reports. Use the question-specific rubric and provided evidence. Rate coverage, citation support, numerical accuracy and beginner readability from 0 (fails) to 4 (fully meets the criterion); count unsupported material claims separately. Leave numerical accuracy null if there are no numerical claims. A valid citation ID does not prove that its source supports a claim. Then run the summarizer and compare both workflows' human scores, completion rates, request counts and latency. Null scores mean unassessed, not zero.

Start with one pair as a smoke test, then accumulate multiple paired cases and repetitions across quota resets. Review paired differences per question, not only averages. Keep failures in the results. Small samples are descriptive, not proof of superiority. Run the same cases with live sources separately before drawing production conclusions. Freeze the model/configuration and save its identity with your experiment notes; provider routing and model availability can change.

The goal is better supported, understandable answers per request. More specialists, longer reports, or model self-approval alone are not evidence of improvement. Keep delegation optional until measured quality gains justify its overhead.


## Live sentiment smoke check

With your backend virtual environment active and `.env` loaded:

```sh
python -m app.evaluation.sentiment_smoke --ticker MSFT --budget 20 --output work/sentiment-smoke
```

Use a new directory for each run. This uses real public search/article requests
and the configured LLM. Ollama runs locally; OpenRouter consumes its free quota.
The command writes `report.json` (arguments, original attribution, coverage,
failures, timings and model identity) and `lead-handoff.json` (the compact brief
actually intended for the lead). A reviewed sample is not a source accuracy audit.
Check that extracted points concern the company, preserve forecasts/opinions,
represent the cited text, avoid duplicate stories, and give useful financial
verification tasks. Review both sides without demanding artificial balance.

Automated tests cover blocked/stale/undated pages, provider failure isolation,
public-address validation and redirects, original-provider metadata, syndication,
unsupported quotes, missing review checks, incomplete prose, source diversity and
handoff to the lead. Live availability remains variable. The old frozen financial
comparison does not replace this source-coverage test or a human quality review.
