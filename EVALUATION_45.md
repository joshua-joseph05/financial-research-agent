# 45-question evaluation

45 unique questions, five per category, including the previous 18 questions. Each question is answered once by the full agent and once by the same-model single-pass baseline. Judge calls are separate and may retry; they are not repeated research questions.

Start Ollama with `gemma4:e4b` downloaded. From the project folder:

```bash
./scripts/run-evaluation-45.command
```

Preview the questions without model calls:

```bash
./scripts/run-evaluation-45.command --dry-run
```

Keep Terminal open. The launcher keeps a Mac awake while it runs. Ctrl+C stops it. Copy the resume command printed at startup to continue the same run:

```bash
./scripts/run-evaluation-45.command --resume "/full/path/to/work/evaluation-45-RUN_ID"
```

The saved run chooses its original model when resumed. Completed stages and saved answer/judgment checkpoints are reused. Changing evaluator code or benchmark cases during an unfinished run can prevent resuming; finish a run before changing those files.

## What runs

1. The agent answers 45 questions using fictional frozen sources (at most 1,620 answering requests).
2. The baseline answers the same questions using the agent's collected evidence and calculations (at most 90 requests including retries). No legacy judge runs.
3. The corrected v2.2 evaluator grades answer content and factual support.
4. The v2.3 citation pass assesses citations collectively and produces the final report.

This uses downloaded local Ollama models, not paid model APIs. The model defaults to `gemma4:e4b`; `OLLAMA_MODEL` can select another downloaded local model for a new run. Judge request ceilings depend on the lengths of saved answers and are printed after answering completes. Each judging job has at most two attempts. Allow several hours on a laptop; actual duration depends on hardware and answer lengths.

## Results

Every new launch creates a fresh `work/evaluation-45-...` directory. The final results are:

- `corrected/comparison-v23.md` — readable comparison, categories, coverage, resources and judge errors.
- `corrected/comparison-v23.json` — machine-readable results.
- Individual pair JSON files — original answers, traces and raw judge responses.

The intermediate `answers/comparison.md` is intentionally ungraded. In the final report, legacy quality columns are unassessed because the old judge was skipped. Use the corrected columns.

The local judge still makes semantic mistakes, so spot-check results before drawing conclusions. The earlier 18-question manual audit does not automatically apply to these newly generated answers. Five examples per category remain descriptive, not statistical proof. Baseline latency excludes collecting inherited evidence and cannot establish an end-to-end speedup.

## Questions

1. **financial_data** — What were Microsoft’s revenue and operating income in fiscal 2025?
2. **financial_data** — Show Microsoft’s annual operating cash flow history for the last two reported years.
3. **financial_data** — Show Apple’s annual capital expenditure history for the last two reported years.
4. **financial_data** — What is the latest available Microsoft share price, and when was it recorded?
5. **financial_data** — Cross-check NVIDIA’s fiscal 2025 revenue against its filing.
6. **sec_filings** — How does Microsoft describe its business in its annual filing?
7. **sec_filings** — What growth risks does NVIDIA disclose in its annual filing?
8. **sec_filings** — What growth risks does AMD disclose in its annual filing?
9. **sec_filings** — What did Microsoft management say caused its fiscal 2025 margin change?
10. **sec_filings** — What did NVIDIA report in its recent earnings announcement, and what was only guidance?
11. **calculations** — Calculate Microsoft’s fiscal 2025 operating margin.
12. **calculations** — How much did NVIDIA’s revenue grow from fiscal 2024 to 2025?
13. **calculations** — Calculate AMD’s fiscal 2025 operating margin.
14. **calculations** — How many percentage points did Microsoft’s operating margin change between fiscal 2024 and 2025?
15. **calculations** — Did Microsoft’s operating cash flow grow at the same rate as revenue in fiscal 2025?
16. **comparisons** — Compare Microsoft and NVIDIA on annual revenue growth and operating margins.
17. **comparisons** — Compare Apple and Microsoft on annual revenue growth and operating margins.
18. **comparisons** — What are the most important differences between AMD and NVIDIA as long-term investments?
19. **comparisons** — Compare Apple and AMD on annual revenue growth and operating margins.
20. **comparisons** — What are the most important differences between Microsoft and AMD as long-term investments?
21. **open_research** — What might I be overlooking about Microsoft?
22. **open_research** — I am interested in Apple. What should I understand about the business?
23. **open_research** — I am interested in AMD. What should I understand about the business?
24. **open_research** — Why have Microsoft’s operating margins changed?
25. **open_research** — What evidence would challenge an optimistic view of NVIDIA’s growth?
26. **investment** — What should a beginner check before investing in NVIDIA?
27. **investment** — What technology stocks could I research for long-term investing?
28. **investment** — I need my money next year. What should I consider before buying Microsoft?
29. **investment** — I have low tolerance for losses. Would concentrating in NVIDIA fit that goal?
30. **investment** — Is Microsoft cheap based on its current earnings?
31. **sentiment_news** — What are analysts saying about NVIDIA, and what is speculation?
32. **sentiment_news** — Is recent optimism about Microsoft supported by its cash flow?
33. **sentiment_news** — Summarize recent news about Apple and identify what needs corroboration.
34. **sentiment_news** — What do recent sources say about Microsoft as an investment if no current articles are available?
35. **sentiment_news** — What do recent sources say about NVIDIA as an investment?
36. **education** — What is diversification?
37. **education** — What does owning a stock mean?
38. **education** — Can bonds lose money when interest rates rise?
39. **education** — What is an ETF?
40. **education** — Why do investment fees matter?
41. **insufficient_evidence** — Should I buy Mercury?
42. **insufficient_evidence** — Which stock is guaranteed to double next month?
43. **insufficient_evidence** — What was Microsoft’s latest revenue if the financial feed is unavailable?
44. **insufficient_evidence** — What is Apple’s operating margin when operating income is missing?
45. **insufficient_evidence** — Give me AMD’s most recent earnings-call transcript.
