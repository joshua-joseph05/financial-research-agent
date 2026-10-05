"""Summarize a reviewed paired audit without hiding costly or incomplete categories.

Usage: python scripts/report-category-efficiency.py path/to/paired-audit.json
No inference, source mutation, or automatic promotion.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path


def summarize(audit):
    groups = defaultdict(list)
    for case in audit['cases']:
        groups[case['category']].append(case)
    result = {}
    for category, cases in sorted(groups.items()):
        reductions = {}
        for metric in ('calls', 'seconds', 'tokens'):
            values = {profile: [c['profiles'][profile][metric] for c in cases]
                      for profile in ('standard', 'efficient')}
            if any(v is None for values_ in values.values() for v in values_):
                reductions[metric] = None
                continue
            old, new = (sum(values[p]) for p in ('standard', 'efficient'))
            reductions[metric] = 100 * (old - new) / old if old else None
        successful = sum(c['profiles']['efficient']['success'] for c in cases)
        quality_ok = not any(c['quality_regressions'] for c in cases)
        measured = successful == len(cases) and quality_ok and all(
            x is not None and x > 0 for x in reductions.values())
        result[category] = dict(pairs=len(cases), candidate_successes=successful,
                                reductions_percent=reductions,
                                observed_all_metrics_improved=measured)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit', type=Path)
    args = parser.parse_args()
    rows = summarize(json.loads(args.audit.read_text()))
    print('# Category efficiency check\n')
    print('Positive percentages mean reductions. Success requires completion and source support. One observed pass is not evidence of generalization.\n')
    print('| Category | Complete + supported | Calls | Time | Tokens | All observed checks |')
    print('|---|---:|---:|---:|---:|---|')
    for name, row in rows.items():
        values = ['unknown' if v is None else f'{v:+.1f}%' for v in row['reductions_percent'].values()]
        print(f"| {name} | {row['candidate_successes']}/{row['pairs']} | {' | '.join(values)} | {'pass' if row['observed_all_metrics_improved'] else 'needs work'} |")
