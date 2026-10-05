#!/usr/bin/env python3
"""Profile saved evaluation runs without model calls or external requests."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory',type=Path)
args=parser.parse_args()
runs=[]
for path in sorted(args.directory.glob('*.json')):
    row=json.loads(path.read_text())
    if isinstance(row,dict) and all(key in row for key in ('case_id','trace','telemetry','latency_seconds')):
        runs.append(row)
if not runs:parser.error('No saved answering runs found')
print('# Saved-run performance profile\n')
print('No new model calls. Counts include all saved profiles/repeats; these are diagnostics, not quality judgments.\n')
print('| Category / profile | Runs | Mean calls | Mean seconds | Tool errors | Empty tool results | Blocked duplicate events |')
print('| --- | ---: | ---: | ---: | ---: | ---: | ---: |')
groups=defaultdict(list)
for row in runs:groups[(row['category'],row.get('execution_profile','original'))].append(row)
for (category,profile),rows in sorted(groups.items()):
    calls=[c for r in rows for c in r['trace']['tool_calls']]
    events=[event for r in rows for event in (r['trace'].get('research_state') or {}).get('events',[])]
    print(f'| {category} / {profile} | {len(rows)} | {mean(r["telemetry"]["model_calls"] for r in rows):.2f} | {mean(r["latency_seconds"] for r in rows):.2f} | {sum(c["status"]=="error" for c in calls)} | {sum(c["status"]=="no_data" for c in calls)} | {sum(isinstance(e,str) and e.startswith("Blocked duplicate") for e in events)} |')
print('\n## Model phase costs\n')
print('| Profile / phase | Calls | Total seconds | Mean seconds | Errors |')
print('| --- | ---: | ---: | ---: | ---: |')
phases=defaultdict(list)
for row in runs:
    for call in row['telemetry']['calls']:phases[(row.get('execution_profile','original'),call['phase'])].append(call)
for (profile,phase),calls in sorted(phases.items(),key=lambda item:-sum(c['seconds'] for c in item[1])):
    print(f'| {profile} / {phase} | {len(calls)} | {sum(c["seconds"] for c in calls):.2f} | {mean(c["seconds"] for c in calls):.2f} | {sum(c["status"]=="error" for c in calls)} |')
print('\n## Stop reasons\n')
for (profile,reason),count in sorted(Counter((r.get('execution_profile','original'),(r.get('report') or {}).get('stop_reason',r['status'])) for r in runs).items()):
    print(f'- {profile}: {reason}: {count}')

print('\n## Reported token usage\n')
print('Counts come from provider responses. Missing usage stays unknown; do not interpret an empty field as zero.\n')
print('| Category / profile | Runs with usage / runs | Mean input tokens | Mean output tokens | Mean total tokens |')
print('| --- | ---: | ---: | ---: | ---: |')
for (category,profile),rows in sorted(groups.items()):
    values=[r['telemetry'].get('tokens',{}) for r in rows]
    def average(key):
        known=[v[key] for v in values if type(v.get(key)) is int]
        return f'{mean(known):.1f}' if known else 'unknown'
    known=sum(type(v.get('total_tokens')) is int for v in values)
    print(f"| {category} / {profile} | {known}/{len(rows)} | {average('prompt_tokens')} | {average('completion_tokens')} | {average('total_tokens')} |")
