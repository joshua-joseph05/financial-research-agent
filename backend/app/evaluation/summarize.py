"""Summarize recorded runs and paired human scores without model calls."""
import argparse
import json
from pathlib import Path
from statistics import mean, median
from app.evaluation.metrics import SCORE_KEYS


def validated_scores(results, reviews):
    labels = [r['label'] for r in results]
    if len(set(labels)) != len(labels):
        raise ValueError('Duplicate result labels')
    scores = {}
    for item in reviews:
        label = item['label']
        if label not in labels or label in scores:
            raise ValueError('Unknown or duplicate review label: ' + label)
        values = item.get('scores', {})
        for key, value in values.items():
            if key not in SCORE_KEYS:
                raise ValueError('Unknown score: ' + key)
            if value is not None and (type(value) is not int or value < 0 or
                                      (key != 'unsupported_claim_count' and value > 4)):
                raise ValueError('Scores must be integers 0–4, nonnegative counts, or null: ' + key)
        scores[label] = values
    return scores


def summarize(results, reviews):
    scores = validated_scores(results, reviews)
    summary = {}
    for workflow in ('single', 'sentiment'):
        runs = [r for r in results if r['workflow'] == workflow]
        if not runs:
            continue
        human = {}
        for key in SCORE_KEYS:
            values = [scores.get(r['label'], {}).get(key) for r in runs]
            values = [v for v in values if v is not None]
            human[key] = {'mean': mean(values) if values else None, 'rated_runs': len(values)}
        claims = sum(r.get('claims', 0) for r in runs)
        timings = [r['telemetry']['elapsed_seconds'] for r in runs]
        summary[workflow] = {
            'runs': len(runs), 'completion_rate': mean(bool(r['complete']) for r in runs),
            'exception_rate': mean('error' in r for r in runs),
            'mean_requests': mean(r['telemetry']['request_budget_used'] for r in runs),
            'mean_seconds': mean(timings), 'median_seconds': median(timings),
            'citation_resolution_rate': sum(r.get('claims_with_resolvable_citations', 0) for r in runs) / claims if claims else None,
            'sentiment_consulted_runs': sum(r.get('sentiment_consultations', 0) > 0 for r in runs),
            'human_scores': human,
        }
    return summary


def paired_comparison(results, reviews):
    scores = validated_scores(results, reviews)
    groups = {}
    for run in results:
        key = (run['case'], run['repeat'])
        group = groups.setdefault(key, {})
        if run['workflow'] in group:
            raise ValueError('Duplicate workflow in case/repeat pair')
        group[run['workflow']] = run
    pairs = []
    for (case, repeat), group in groups.items():
        if not {'single', 'sentiment'} <= group.keys():
            continue
        single, sentiment = group['single'], group['sentiment']
        deltas = {}
        for key in SCORE_KEYS:
            a, b = scores.get(single['label'], {}).get(key), scores.get(sentiment['label'], {}).get(key)
            deltas[key] = b - a if a is not None and b is not None else None
        pairs.append({'case': case, 'repeat': repeat,
                      'both_complete': bool(single['complete'] and sentiment['complete']),
                      'sentiment_consulted': sentiment.get('sentiment_consultations', 0) > 0,
                      'extra_requests': sentiment['telemetry']['request_budget_used'] - single['telemetry']['request_budget_used'],
                      'extra_seconds': sentiment['telemetry']['elapsed_seconds'] - single['telemetry']['elapsed_seconds'],
                      'score_deltas': deltas})
    means = {}
    for key in SCORE_KEYS:
        values = [p['score_deltas'][key] for p in pairs if p['score_deltas'][key] is not None]
        means[key] = {'mean_delta': mean(values) if values else None, 'rated_pairs': len(values)}
    return {'direction': 'sentiment minus single; lower unsupported_claim_count is better',
            'matched_pairs': len(pairs), 'unmatched_groups': len(groups) - len(pairs),
            'mean_score_deltas': means, 'pairs': pairs}


def markdown_summary(summary, paired):
    lines = ['# Evaluation results', '',
             'Fictional frozen evidence. Human ratings are required to assess answer quality.', '',
             '| Configuration | Runs | Complete | Exceptions | Mean requests | Median seconds |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name, item in summary.items():
        lines.append(f"| {name} | {item['runs']} | {item['completion_rate']:.0%} | {item['exception_rate']:.0%} | {item['mean_requests']:.1f} | {item['median_seconds']:.1f} |")
    lines += ['', f"Matched pairs: {paired['matched_pairs']}. Unmatched groups: {paired['unmatched_groups']}.", '',
              '| Human criterion | Mean paired change | Rated pairs |', '| --- | ---: | ---: |']
    for name, item in paired['mean_score_deltas'].items():
        value = 'Unassessed' if item['mean_delta'] is None else f"{item['mean_delta']:+.2f}"
        lines.append(f"| {name} | {value} | {item['rated_pairs']} |")
    lines += ['', 'Changes are sentiment minus single. Lower unsupported-claim counts are better.',
              'Sentiment enabled does not mean consulted. Inspect paired.json for actual use.',
              'Citation resolution checks IDs, not entailment. Small samples do not establish superiority.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    results = json.loads((args.directory / 'results.json').read_text())
    reviews = json.loads((args.directory / 'blind-review.json').read_text())
    result, paired = summarize(results, reviews), paired_comparison(results, reviews)
    (args.directory / 'summary.json').write_text(json.dumps(result, indent=2))
    (args.directory / 'paired.json').write_text(json.dumps(paired, indent=2))
    text = markdown_summary(result, paired)
    (args.directory / 'summary.md').write_text(text)
    print(text)


if __name__ == '__main__':
    main()
