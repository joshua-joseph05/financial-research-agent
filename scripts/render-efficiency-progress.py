#!/usr/bin/env python3
"""Render a compact view of a saved paired experiment; never invokes a model."""
import argparse
import json
from pathlib import Path


def reduction(before, after):
    return '—' if before in (None,0) or after is None else f'{100*(before-after)/before:.1f}%'


def render(folder):
    data=json.loads((folder/'summary.json').read_text())
    lines=['# Paired agent evaluation','', 'Positive reductions mean fewer calls or faster responses. Negative reductions are regressions. Development results are not held-out validation.','',
           '| Split | Pairs | Calls (standard → candidate) | Call reduction | Mean seconds (standard → candidate) | Latency reduction | Completion (standard → candidate) | Fully supported (standard → candidate) |',
           '| --- | ---: | --- | ---: | --- | ---: | --- | --- |']
    def number(value):return '—' if value is None else f'{value:.2f}'
    for split,row in data['metrics'].items():
        if not row['paired_questions'] or split=='all':continue
        a,b=[row['profiles'][p] for p in ('standard','efficient')]
        n=row['reviewed_pairs']
        quality=lambda key:f"{a[key]}/{n} → {b[key]}/{n}" if n else 'Unreviewed'
        lines.append(f"| {split} | {row['paired_questions']} | {number(a['mean_model_calls'])} → {number(b['mean_model_calls'])} | {reduction(a['mean_model_calls'],b['mean_model_calls'])} | {number(a['mean_latency_seconds'])} → {number(b['mean_latency_seconds'])} | {reduction(a['mean_latency_seconds'],b['mean_latency_seconds'])} | {quality('reviewed_completion')} | {quality('reviewed_supported_answers')} |")
    lines += ['', '**Gate:** '+data['gate']['status'], '', data['gate']['reason'], '', 'Quality scores require review of the actual answer and cited evidence. A self-reported completion flag is not a score. Each pair uses the same model and frozen source collection; timing can vary with hardware load. See summary.md for medians, tail latency, and errors.']
    if data.get('reviewer'):lines += ['', '**Reviewer:** '+data['reviewer']]
    return '\n'.join(lines)+'\n'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    args=parser.parse_args()
    path=args.folder/'progress.md';path.write_text(render(args.folder));print(path)
