import json
from pathlib import Path
import pytest
from app.evaluation.efficiency import experiment_cases
from app.evaluation.benchmark_data import CATEGORIES,load_cases

ROOT=Path(__file__).resolve().parents[2]
CASES=ROOT/'evaluations/validation-v34/cases.json'
SPLITS=ROOT/'evaluations/validation-v34/splits.json'


def test_new_suite_is_complete_disjoint_and_has_no_reused_exact_questions():
    cases,dev,val=experiment_cases(CASES,SPLITS)
    assert not dev and len(val)==9
    assert {c.category for c in cases}==set(CATEGORIES)
    old={c.question.casefold().strip() for c in load_cases()}
    assert not old & {c.question.casefold().strip() for c in cases}
    assert next(c for c in cases if c.category=='insufficient_evidence').scenario=='missing_financials'


@pytest.mark.parametrize('problem',['overlap','duplicate','unknown','unassigned','empty'])
def test_invalid_split_cannot_silently_drop_questions(tmp_path,problem):
    splits=json.loads(SPLITS.read_text())
    if problem=='overlap':splits['development']=[splits['validation'][0]]
    if problem=='duplicate':splits['validation'].append(splits['validation'][0])
    if problem=='unknown':splits['validation'].append('not-a-case')
    if problem=='unassigned':splits['validation'].pop()
    if problem=='empty':splits={'development':[],'validation':[]}
    path=tmp_path/'splits.json';path.write_text(json.dumps(splits))
    with pytest.raises(ValueError):experiment_cases(CASES,path)
