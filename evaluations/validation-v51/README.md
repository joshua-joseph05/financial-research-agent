# V51 predeclared validation

Nine newly worded questions covering all nine categories, including a mixed sentiment/financial purchase question that must retain the full workflow. Familiar fictional source fixtures and previously studied task families; this is not independent external validation.

Run one counterbalanced paired pass (18 answers) using local gemma4:e4b. Freeze runtime source throughout the pass. Review answer content against the rubrics before inspecting the private profile mapping. The developer is the reviewer, and formatting can reveal the implementation, so blinding is partial. Strip nested timing/call telemetry when displaying review packets.

Report all attempts, complete/source-supported successes, the matched-success subset, and each category's calls/time/tokens. Faster empty answers never establish successful-task improvement. Use the existing promotion gate without changing thresholds. Additionally, a whole-agent reduction claim requires successful candidate answers and measured reductions in all three resource metrics across every category. One question per category is insufficient evidence of generalization even if all checks pass. A second paired timing pass is appropriate only after the first pass meets quality and efficiency gates; otherwise diagnose failures before spending more model requests.

The standard reference is the current source snapshot and includes shared correctness fixes. Do not compare aggregate percentages to V44 as if the question sets were identical. No automatic promotion or paid API use.


## V51 completed — 2026-10-03

18 answers reviewed before unblinding. Calls 86→57 (-33.7%); average seconds 154.85→104.70 (-32.4%); recorded tokens 206,636→173,888 (-15.8%). Complete 1/9→8/9, source-supported 5/9→7/9, jointly successful 0/9→6/9. No matched successful pairs; standard timeout makes recorded token usage incomplete for any unreturned computation. Two categories meet all observed quality/resource checks; whole-agent goal unfinished. Gate do_not_promote; no second timing pass per predeclared rule. Source/model/archive/review integrity verified. Remaining issues: education coverage, mixed/interpretive citation support, and unnecessary research. Report: `work/validation-v51-final/comparison.md`. V51 is now inspected evidence, not unseen validation.
