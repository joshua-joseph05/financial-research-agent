"""45 unique frozen questions, saved baseline answers, and corrected local judging."""
import argparse
from collections import Counter
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import httpx
from .benchmark_data import CATEGORIES, load_cases
from .checks import answer_claims
from .v2.transport import OllamaJudge

ROOT = Path(__file__).resolve().parents[3]


def selected_cases():
    selection = json.loads(Path(__file__).with_name('benchmark45.json').read_text())
    ids = selection['case_ids']
    available = {c.id: c for c in load_cases()}
    cases = [available[key] for key in ids]
    if len(ids) != 45 or len(set(ids)) != 45 or len({c.question for c in cases}) != 45:
        raise ValueError('Expected 45 unique question IDs and texts')
    if Counter(c.category for c in cases) != Counter({c: 5 for c in CATEGORIES}):
        raise ValueError('Expected five questions per category')
    return cases


def request_bounds(pairs, cases):
    """Same upper bounds as the immutable evaluator CLIs, including two attempts."""
    criteria = {c.id: len(c.criteria) for c in cases}
    factual = sum(2 * (criteria[p['case_id']] + 2 * math.ceil(len(answer_claims(p[s])) / 2))
                  for p in pairs for s in ('agent', 'baseline'))
    citations = sum(2 * math.ceil(sum(bool(c['evidence_ids']) for c in answer_claims(p[s])) / 2)
                    for p in pairs for s in ('agent', 'baseline'))
    return factual, citations


def complete(path, kind):
    file = path / ('summary.json' if kind == 'agent' else 'manifest.json')
    if not file.exists():
        return False
    data = json.loads(file.read_text())
    return (data.get('recorded_runs') == data.get('planned_runs') == 45
            if kind == 'agent' else data.get('state') == 'complete')


def invoke(module, args):
    subprocess.run([sys.executable, '-u', '-m', module, *map(str, args)], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Show all questions; no model calls or output directories')
    parser.add_argument('--resume', type=Path, help='Resume the printed evaluation-45 directory')
    args = parser.parse_args()
    cases = selected_cases()
    model = os.environ.get('OLLAMA_MODEL', 'gemma4:e4b')
    if args.resume:
        run = args.resume.expanduser().resolve()
        config = json.loads((run / 'run45.json').read_text())
        model = config['model']
        if config['cases'] != [c.model_dump() for c in cases]:
            parser.error('Benchmark changed; preserve this run and start a new one.')
    OllamaJudge(model)  # Reject cloud-style names before any answering calls.
    print(f'45 unique questions; 5 per category; 1 agent + 1 baseline answer each. Local model: {model}', flush=True)
    print('Answering request ceilings: agent 1620, baseline 90. Judge ceilings depend on saved answer lengths, with at most 2 attempts per job.', flush=True)
    print('Stages: agent answers → baseline answers (no legacy judge) → v2.2 factual/task grading → v2.3 citation bundles.', flush=True)
    if args.dry_run:
        for i, c in enumerate(cases, 1):
            print(f'{i:2}. [{c.id}] {c.question}')
        return
    # Refuse cloud-backed Ollama models, even if their names do not contain "cloud".
    try:
        with httpx.Client(base_url='http://127.0.0.1:11434', trust_env=False, timeout=15) as client:
            response = client.post('/api/show', json={'model': model})
            response.raise_for_status()
            metadata = response.json()
            if metadata.get('remote_host') or metadata.get('remote_model'):
                parser.error('Use a downloaded local model; cloud models are not permitted.')
    except httpx.HTTPError as error:
        parser.error(f'Local Ollama/model unavailable. Start Ollama and download {model}. ({type(error).__name__})')
    os.environ.update(LLM_PROVIDER='ollama', OLLAMA_MODEL=model, OLLAMA_BASE_URL='http://127.0.0.1:11434')
    if not args.resume:
        (ROOT / 'work').mkdir(exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix='evaluation-45-', dir=ROOT / 'work'))
        (run / 'run45.json').write_text(json.dumps({'version': 1, 'model': model, 'cases': [c.model_dump() for c in cases]}, indent=2) + '\n')
    print(f'Results: {run}\nResume: ./scripts/run-evaluation-45.command --resume "{run}"', flush=True)
    with (run / '.pipeline.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('This evaluation is already running.')
        agent, baseline, grading, corrected = [run / name for name in ('agent', 'answers', 'grading-v22', 'corrected')]
        stages = [
            (agent, 'agent', 'app.evaluation.benchmark', ['--case', 'all', '--case-ids', ','.join(c.id for c in cases), '--repeats', '1', '--max-requests', '1620', '--output', agent]),
            (baseline, 'baseline', 'app.evaluation.baseline_compare', ['--agent-directory', agent, '--output', baseline, '--answers-only', '--max-requests', '90'])]
        for path, kind, module, command in stages:
            if not complete(path, kind):
                invoke(module, command + (['--resume'] if path.exists() else []))
        pairs = [json.loads(p.read_text()) for p in sorted(baseline.glob('*-comparison.json'))]
        if len(pairs) != 45:
            raise ValueError('Expected 45 saved pairs before grading')
        factual_bound, citation_bound = request_bounds(pairs, cases)
        print(f'Judge request ceilings for these saved answers: v2.2 {factual_bound}; citation refinement {citation_bound}.', flush=True)
        for path, module, source, bound in (
            (grading, 'app.evaluation.v2.rejudge', baseline, factual_bound),
            (corrected, 'app.evaluation.v23.rejudge', grading, citation_bound)):
            if not complete(path, 'judge'):
                invoke(module, ['--source', source, '--output', path, '--model', model, '--max-requests', bound] + (['--resume'] if path.exists() else []))
        report = corrected / 'comparison-v23.md'
        text = report.read_text().replace('Two questions per category:', 'Five questions per category:')
        text = text.replace('## Original versus corrected', '## Saved-answer diagnostics versus corrected grading')
        note = '\nThis new 45-question run skips legacy judging. Unassessed original quality columns are intentional, not failed legacy scores. The corrected columns are the applicable results.\n'
        if note not in text:
            text += note
        report.write_text(text)
        print(f'\nFinished: {corrected / "comparison-v23.md"}', flush=True)
        print('Scores remain provisional: the local judge requires spot checks. Baseline latency excludes evidence collection.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Saved checkpoints remain; use the printed --resume command.', flush=True)
        raise SystemExit(130)
    except subprocess.CalledProcessError as error:
        print(f'\nStage failed (exit {error.returncode}); saved checkpoints remain. Resume the same directory.', file=sys.stderr)
        raise SystemExit(error.returncode)
