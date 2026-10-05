#!/usr/bin/env python3
"""Archive source and dependency versions for an evaluation; exclude .env and run data."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    app=root/'backend/app'
    files=sorted(p for p in app.rglob('*') if p.is_file() and p.suffix in ('.py','.json'))
    code_hash=hashlib.sha256(b''.join(str(p.relative_to(app)).encode()+p.read_bytes() for p in files)).hexdigest()
    manifest=json.loads((args.run_directory/'manifest.json').read_text())
    recorded=manifest.get('settings',{}).get('code_sha256')
    if recorded != code_hash:raise SystemExit('Source does not match the run manifest; refusing a misleading snapshot.')
    extra=[root/'backend/pyproject.toml',root/'BROAD_EFFICIENCY.md',Path(__file__).resolve(),root/'scripts/render-efficiency-progress.py']
    extra += sorted((root/'backend/tests').glob('*.py'))
    extra += [root/'frontend/app/investment-results.tsx']
    archive=args.run_directory/'source.zip'
    with ZipFile(archive,'x',ZIP_DEFLATED) as z:
        for file in files+extra:z.write(file,file.relative_to(root))
    metadata={'code_sha256':code_hash,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
              'python':sys.version,'system':platform.system(),'system_release':platform.release(),'machine':platform.machine(),
              'dependencies':{name:importlib.metadata.version(name) for name in ('langgraph','langchain-core','mcp','httpx','pydantic','fastapi','pytest')},
              'excluded':['.env','credentials','virtual environments','research runs','node_modules'],
              'note':'Source snapshot, not a deployment or quality endorsement. Model name, question set, and rubric are in manifest.json.'}
    (args.run_directory/'reproducibility.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(archive)


if __name__=='__main__':main()
