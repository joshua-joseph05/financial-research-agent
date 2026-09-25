"""Paired, frozen-source evaluation. Only model inference can use a network API."""
import argparse
import hashlib
import json
import os
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from app.evaluation.fixtures import FixtureRegistry, snapshot, guide
from app.evaluation.frozen_sources import frozen_environment, AS_OF
from app.evaluation.metrics import audit, review_item
from app.ideas.graph import run_ideas, SYSTEM
from app.ideas.models import IdeasRequest
from app.ideas.telemetry import MeteredModel
from app.providers.openrouter import create_model


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)


def manifest(cases, budget, repeats, seed):
    root = Path(__file__).parent
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in ('fixtures.py', 'frozen_sources.py', 'cases.json')}
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    return {'created_at': datetime.now(timezone.utc).isoformat(), 'fixture_date': AS_OF,
            'fixture_sha256': hashes, 'git_revision': revision, 'seed': seed,
            'cases': cases, 'budget_per_run': budget, 'repeats': repeats,
            'provider': os.getenv('LLM_PROVIDER', 'ollama'),
            'scope': 'Investment graph only; not unified routing or live retrieval quality. Fictional data.'}


def run_experiment(cases, output, budget=20, repeats=1, seed=42, model_factory=None, runner=run_ideas):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    tasks = [(c, r, w) for c in cases for r in range(repeats) for w in ('single', 'sentiment')]
    random.Random(seed).shuffle(tasks)
    write_json(output / 'manifest.json', manifest(cases, budget, repeats, seed))
    results, reviews = [], []
    factory = model_factory or (lambda: create_model(system_prompt=SYSTEM))
    for index, (case, repeat, workflow) in enumerate(tasks):
        label = f'report-{index+1:03d}'
        result = {'label': label, 'case': case['id'], 'repeat': repeat, 'workflow': workflow,
                  'complete': False, 'status': 'error'}
        model = None
        try:
            base = factory()
            model = MeteredModel(base, budget)
            result['model'] = getattr(base, 'model', type(base).__name__)
            request = IdeasRequest(question=case['question'], tickers=case['tickers'],
                                   sentiment_enabled=workflow == 'sentiment', max_model_requests=budget,
                                   research_size=3)
            with frozen_environment():
                report = runner(request, model, FixtureRegistry(), snapshot_fn=snapshot, guide_fn=guide)
            result.update(audit(report), complete=bool(report.get('complete')), status='returned')
            reviews.append(review_item(label, case, report))
            write_json(output / (label + '.json'), report)
        except Exception as error:
            # Exception messages may contain provider response text; retain type only.
            result['error'] = type(error).__name__
        result['telemetry'] = model.report() if model else {'request_budget_used': 0, 'elapsed_seconds': 0}
        results.append(result)
        write_json(output / 'results.json', results)
        write_json(output / 'blind-review.json', reviews)
        print(label, 'recorded; requests:', result['telemetry']['request_budget_used'], flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', default='risks')
    parser.add_argument('--budget', type=int, default=20)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max-requests', type=int, default=40, help='Experiment-wide upper-bound guard')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not 4 <= args.budget <= 48 or not 1 <= args.repeats <= 3:
        parser.error('budget must be 4–48; repeats must be 1–3')
    cases = json.loads(Path(__file__).with_name('cases.json').read_text())
    cases = [c for c in cases if args.case == 'all' or c['id'] == args.case]
    if not cases:
        parser.error('Unknown case')
    runs = len(cases) * args.repeats * 2
    upper = runs * args.budget
    print(f'{runs} runs; at most {upper} model requests including adapter retries. Fictional evidence.')
    if args.dry_run:
        return
    if upper > args.max_requests:
        parser.error(f'Upper bound exceeds --max-requests {args.max_requests}; select fewer cases or explicitly raise it')
    if args.output.exists():
        parser.error('Use a new output directory; previous evaluations are never overwritten')
    run_experiment(cases, args.output, args.budget, args.repeats, args.seed)
    print('Score blind-review.json before inspecting results.json. Resolvable citations do not establish accuracy.')


if __name__ == '__main__':
    main()
