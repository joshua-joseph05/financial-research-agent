"""Refine only citation bundles after v2.2 completes; reuse factual/task judgments."""
import argparse
import json
import fcntl
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from copy import deepcopy
from . import VERSION
from .citations import BundleJudge, refine
from app.evaluation.v2.rejudge import digest, write
from app.evaluation.v2.report import summary, render
from app.evaluation.checks import answer_claims


def invariant(before, after):
    """Citation refinement must never alter answers, task grading or factual support."""
    assert before['original'] == after['original']
    for system in ('agent', 'baseline'):
        a, b = before['corrected'][system], after['corrected'][system]
        assert a['task'] == b['task']
        assert a['claim_jobs'] == b['claim_jobs']
        assert a['metrics']['calculation_accuracy'] == b['metrics']['calculation_accuracy']
        assert [(c['claim_id'], c.get('support')) for c in a['claims']] == [(c['claim_id'], c.get('support')) for c in b['claims']]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model', default='gemma4:e4b')
    p.add_argument('--max-requests', type=int, default=0)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    manifest = json.loads((args.source / 'manifest.json').read_text())
    if manifest['state'] != 'complete':
        p.error('Source evaluation is not complete; keep its existing process running.')
    files = sorted(args.source.glob('*-comparison-v2.json'))
    if len(files) != manifest['planned_pairs']:
        p.error('Source pair count does not match its completed manifest.')
    pairs = [json.loads(f.read_text()) for f in files]
    bound = sum(2 * math.ceil(sum(bool(c['evidence_ids']) for c in answer_claims(pair['original'][s])) / 2)
                for pair in pairs for s in ('agent', 'baseline'))
    print(f'{len(pairs)} saved pairs; 0 new answers; citation-only upper bound {bound} requests.', flush=True)
    if args.dry_run:
        return
    if args.max_requests < bound:
        p.error('Explicit --max-requests must cover the bound.')
    if args.output.resolve() == args.source.resolve():
        p.error('Choose a separate output directory.')
    if args.output.exists() and not args.resume:
        p.error('Output exists; choose another directory or --resume.')
    args.output.mkdir(parents=True, exist_ok=args.resume)
    with (args.output / '.run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hashes = {f.name: digest(f) for f in files + [args.source / 'manifest.json', args.source / 'comparison-v2.json']}
        code = {str(f.relative_to(Path(__file__).parents[1])): digest(f)
                for folder in ('v2', 'v23') for f in (Path(__file__).parents[1] / folder).glob('*.py')}
        settings = dict(version=VERSION, model=args.model, source=str(args.source.resolve()), source_hashes=hashes, evaluator_code=code, max_attempts=2)
        path = args.output / 'manifest.json'
        if path.exists():
            run = json.loads(path.read_text())
            if run['settings'] != settings:
                p.error('Source/model/code changed; use a new output directory.')
        else:
            run = dict(settings=settings, state='running', planned_pairs=len(pairs), request_upper_bound=bound, created_at=datetime.now(timezone.utc).isoformat())
            shutil.copytree(args.source, args.output / 'prior_v22', ignore=shutil.ignore_patterns('.run.lock'))
            for folder in ('v2', 'v23'):
                shutil.copytree(Path(__file__).parents[1] / folder, args.output / 'evaluator_snapshot' / folder, ignore=shutil.ignore_patterns('__pycache__'))
            write(path, run)
        cases = {c['id']: c for c in json.loads((args.source / 'original' / 'manifest.json').read_text())['source_manifest']['cases']}
        old = json.loads((args.source / 'original' / 'comparison.json').read_text())
        transport = BundleJudge(args.model)
        completed = []
        for i, (file, pair) in enumerate(zip(files, pairs)):
            out = args.output / file.name
            result = json.loads(out.read_text()) if out.exists() else deepcopy(pair)
            for system in ('agent', 'baseline'):
                cached = result['corrected'][system]
                if cached.get('bundle_complete'):
                    continue
                print(f'[{i+1}/{len(pairs)}] {pair["original"]["case_id"]}: citations {system}', flush=True)
                def save(value):
                    result['corrected'][system] = value
                    write(out, result)
                refine(pair, system, cases[pair['original']['case_id']], transport, save,
                       cached if 'bundle_completed_ids' in cached else None)
            invariant(pair, result)
            completed.append(result)
            report = summary(completed, old, len(pairs))
            report['version'] = VERSION
            report['citation_correctness_unit'] = 'cited claim bundle; validity remains per reference'
            report['superseded_citation_jobs'] = {s: sum(len(x['corrected'][s].get('prior_citation_jobs', [])) for x in completed) for s in ('agent', 'baseline')}
            write(args.output / 'comparison-v23.json', report)
            text = render(report).replace('# Corrected evaluator v2 comparison', '# Corrected evaluator v2.3 comparison')
            text += '\nCitation correctness uses jointly cited claim bundles, not isolated references. Citation validity remains per reference. Task and factual judgments are reused unchanged from v2.2. Superseded individual-reference jobs are preserved in prior_citation_jobs and excluded from final-method reliability rates.\n'
            (args.output / 'comparison-v23.md').write_text(text)
        if any(digest(args.source / name) != value for name, value in hashes.items()):
            raise ValueError('Source artifacts changed.')
        run.update(state='complete', finished_at=datetime.now(timezone.utc).isoformat())
        write(path, run)
        print('Citation refinement complete.', flush=True)


if __name__ == '__main__':
    main()
