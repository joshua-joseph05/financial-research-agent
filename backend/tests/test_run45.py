"""Launcher scope and restart contracts, without model calls."""
import json
from collections import Counter
from pathlib import Path
import sys
import pytest
from app.evaluation import run45


def test_45_balanced_distinct_and_contains_previous_18():
    cases=run45.selected_cases()
    prior=json.loads(Path(run45.__file__).with_name('benchmark18.json').read_text())['case_ids']
    assert len(cases)==len({c.question for c in cases})==45
    assert set(prior)<={c.id for c in cases}
    assert set(Counter(c.category for c in cases).values())=={5}


def test_dry_run_never_contacts_models_or_creates_output(monkeypatch,tmp_path,capsys):
    monkeypatch.setattr(run45,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['run45','--dry-run'])
    monkeypatch.setenv('OLLAMA_MODEL','gemma4:e4b')
    def forbidden(*args,**kwargs):raise AssertionError('Dry run must be offline')
    monkeypatch.setattr(run45.httpx,'Client',forbidden)
    run45.main()
    assert '45 unique questions' in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_pipeline_uses_corrected_judges_and_resume_skips_completed_stages(monkeypatch,tmp_path):
    monkeypatch.setattr(run45,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['run45'])
    monkeypatch.setenv('OLLAMA_MODEL','gemma4:e4b')
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):return self
        def raise_for_status(self):pass
        def json(self):return {}
    monkeypatch.setattr(run45.httpx,'Client',Client)
    calls=[]
    def invoke(module,args):
        calls.append((module,args))
        output=Path(args[args.index('--output')+1]);output.mkdir()
        if module.endswith('.benchmark'):
            (output/'summary.json').write_text(json.dumps({'recorded_runs':45,'planned_runs':45}))
        else:
            (output/'manifest.json').write_text(json.dumps({'state':'complete'}))
        if module.endswith('.baseline_compare'):
            assert '--answers-only' in args
            for i in range(45):(output/f'{i:03}-comparison.json').write_text('{}')
        if module.endswith('.v23.rejudge'):
            (output/'comparison-v23.md').write_text('Two questions per category: descriptive examples.\n## Original versus corrected\n')
    monkeypatch.setattr(run45,'invoke',invoke)
    monkeypatch.setattr(run45,'request_bounds',lambda pairs,cases:(500,150))
    run45.main()
    assert [c[0] for c in calls]==['app.evaluation.benchmark','app.evaluation.baseline_compare','app.evaluation.v2.rejudge','app.evaluation.v23.rejudge']
    assert '--judge' not in calls[0][1]
    run=next((tmp_path/'work').iterdir())
    original=(run/'run45.json').read_bytes()
    monkeypatch.setattr(sys,'argv',['run45','--resume',str(run)])
    run45.main()
    assert len(calls)==4 and (run/'run45.json').read_bytes()==original


def test_incomplete_checkpoint_not_skipped(tmp_path):
    (tmp_path/'summary.json').write_text(json.dumps({'recorded_runs':44,'planned_runs':45}))
    assert not run45.complete(tmp_path,'agent')
    (tmp_path/'manifest.json').write_text(json.dumps({'state':'running'}))
    assert not run45.complete(tmp_path,'judge')
