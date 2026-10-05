#!/usr/bin/env python3
"""Record the selected local model's identity without prompts or credentials."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if args.output.exists():parser.error('Output already exists; refusing to overwrite runtime provenance')
with httpx.Client(base_url='http://127.0.0.1:11434',trust_env=False,follow_redirects=False,timeout=10) as client:
    response=client.get('/api/tags');response.raise_for_status()
    models=response.json().get('models',[])
    matches=[m for m in models if args.model in (m.get('name'),m.get('model'))]
    if len(matches)!=1:raise SystemExit('Selected model was not uniquely found in the local runtime')
    row=matches[0]
    response=client.get('/api/version');response.raise_for_status()
    result={'captured_at':datetime.now(timezone.utc).isoformat(),
        'model':{k:row.get(k) for k in ('name','model','digest','modified_at','size','details')},
        'runtime_version':response.json().get('version'),
        'note':'Read-only snapshot of the local runtime at capture time, not a guarantee about prior model state. No inference request was made.'}
with args.output.open('x') as handle:json.dump(result,handle,indent=2);handle.write('\n')
print(args.output)
