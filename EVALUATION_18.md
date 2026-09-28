# 18-question comparison

Each question runs once for the full agent and once for the single-pass baseline. Each launch starts fresh; prior answers are not reused. Separate judge calls assess answers and are not additional question repetitions.

Start Ollama with `gemma4:e4b` downloaded, then run from the project folder:

```bash
./scripts/run-evaluation-18.command
```

Keep this Terminal window open. Ctrl+C stops the evaluation. Results are saved to a new `work/evaluation-18-...` folder. Open `comparison/comparison.md` inside it when finished.

To preview the scope without model calls: `./scripts/run-evaluation-18.command --dry-run`.

The source data is frozen benchmark data, not current market information. The baseline inherits the agent’s collected evidence; its answering latency excludes evidence collection.

## Questions

1. **financial_data** — Show Microsoft’s annual operating cash flow history for the last two reported years.
2. **financial_data** — What is the latest available Microsoft share price, and when was it recorded?
3. **sec_filings** — What growth risks does NVIDIA disclose in its annual filing?
4. **sec_filings** — What did NVIDIA report in its recent earnings announcement, and what was only guidance?
5. **calculations** — How much did NVIDIA’s revenue grow from fiscal 2024 to 2025?
6. **calculations** — How many percentage points did Microsoft’s operating margin change between fiscal 2024 and 2025?
7. **comparisons** — Compare Apple and Microsoft on annual revenue growth and operating margins.
8. **comparisons** — What are the most important differences between AMD and NVIDIA as long-term investments?
9. **open_research** — I am interested in Apple. What should I understand about the business?
10. **open_research** — What evidence would challenge an optimistic view of NVIDIA’s growth?
11. **investment** — I need my money next year. What should I consider before buying Microsoft?
12. **investment** — Is Microsoft cheap based on its current earnings?
13. **sentiment_news** — What are analysts saying about NVIDIA, and what is speculation?
14. **sentiment_news** — Is recent optimism about Microsoft supported by its cash flow?
15. **education** — What is diversification?
16. **education** — Can bonds lose money when interest rates rise?
17. **insufficient_evidence** — Should I buy Mercury?
18. **insufficient_evidence** — What is Apple’s operating margin when operating income is missing?
