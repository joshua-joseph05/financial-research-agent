"""Summarize recorded runs and optional blind human scores without model calls."""
import argparse
import json
from pathlib import Path
from statistics import mean


def summarize(results, reviews):
    scores = {item['label']: item.get('scores', {}) for item in reviews}
    summary = {}
    for workflow in ('single', 'sentiment'):
        runs = [r for r in results if r['workflow'] == workflow]
        if not runs:
            continue
        scored = [scores.get(r['label'], {}) for r in runs]
        human = {}
        for key in ('coverage_0_to_4', 'citation_support_0_to_4', 'numerical_accuracy_0_to_4', 'readability_0_to_4', 'unsupported_claim_count'):
            values = [s[key] for s in scored if isinstance(s.get(key), (int, float))]
            human[key] = {'mean': mean(values) if values else None, 'rated_runs': len(values)}
        summary[workflow] = {
            'runs': len(runs),
            'completion_rate': mean(bool(r['complete']) for r in runs),
            'mean_requests': mean(r['telemetry']['request_budget_used'] for r in runs),
            'mean_seconds': mean(r['telemetry']['elapsed_seconds'] for r in runs),
            'human_scores': human,
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    results = json.loads((args.directory / 'results.json').read_text())
    reviews = json.loads((args.directory / 'blind-review.json').read_text())
    result = summarize(results, reviews)
    (args.directory / 'summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print('Missing ratings are unassessed. Completion and citation IDs do not establish answer quality.')


if __name__ == '__main__':
    main()
