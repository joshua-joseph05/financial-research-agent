"""The shorter education path retains source checks and explicit answer coverage."""
import pytest
from app.evaluation.benchmark_data import load_cases
from app.evaluation.recording import run_case

class Educator:
    model='offline-test'
    def __init__(self,missing=False,bad_section=False,unsupported=False,empty_plan=False,duplicate_part=False):
        self.missing=missing;self.bad_section=bad_section;self.unsupported=unsupported;self.empty_plan=empty_plan;self.duplicate_part=duplicate_part
    def respond(self,phase,context,schema,timeout):
        if phase=='assistant_route':
            out={'workflow':'education','reason':'General concept'}
            if 'education_plan' in schema.model_fields:
                out['education_plan']=None if self.empty_plan else {'topics':['diversification'],'parts':['Explain spreading investments','Explain remaining loss risk']}
        elif phase=='ideas_select':out={'kind':'education','topics':['diversification']}
        elif phase=='ideas_education':
            key=next(iter(context['observations']))
            out={'sections':[{'title':'Explanation','text':'Diversification spreads investments across different assets. It does not guarantee protection from losses.','evidence_ids':[key]}]}
        elif phase=='ideas_education_review':
            out={'supported':not self.unsupported,'explanation':'Source reviewed.'}
            if 'covered_parts' in schema.model_fields:
                out['covered_parts']=[{'part_index':0,'answer_section_index':4 if self.bad_section else 0}]
                if self.missing:out['missing_parts']=[1]
                else:
                    out['covered_parts'].append({'part_index':1,'answer_section_index':0})
                    out['missing_parts']=[]
                if self.duplicate_part:out['covered_parts'].append(dict(out['covered_parts'][0]))
        else:raise AssertionError(phase)
        return schema.model_validate(out)


def education():return next(c for c in load_cases() if c.id=='education-01')


def test_one_less_call_without_removing_evidence_or_review():
    standard=run_case(education(),Educator())
    candidate=run_case(education(),Educator(),execution_profile='efficient')
    assert standard['status']==candidate['status']=='returned'
    assert standard['telemetry']['model_calls']==4
    assert candidate['telemetry']['model_calls']==3
    assert standard['report']['answer_sections']==candidate['report']['answer_sections']
    assert candidate['report']['complete']
    assert [t['name'] for t in candidate['trace']['tool_calls']]==['get_investing_guide']
    assert [d['phase'] for d in candidate['trace']['model_decisions']]==['assistant_route','ideas_education','ideas_education_review']


@pytest.mark.parametrize('options',[{'bad_section':True},{'unsupported':True},{'missing':True},{'duplicate_part':True}])
def test_failed_source_or_coverage_checks_cannot_claim_completion(options):
    result=run_case(education(),Educator(**options),execution_profile='efficient')
    assert result['status']=='returned' and not result['report']['complete']
    if options.get('missing'):assert result['report']['follow_up_questions']==['Explain remaining loss risk']
    else:assert not result['report']['answer_sections']


def test_uncertain_route_falls_back_to_existing_selection():
    result=run_case(education(),Educator(empty_plan=True),execution_profile='efficient')
    assert result['telemetry']['model_calls']==4 and result['report']['complete']


def test_performance_report_does_not_treat_self_completion_as_review(tmp_path):
    from app.evaluation.efficiency import summarize
    import json
    runs=[run_case(education(),Educator(),execution_profile=p) for p in ('standard','efficient')]
    summarize(tmp_path,runs)
    result=json.loads((tmp_path/'summary.json').read_text())
    assert result['metrics']['all']['paired_questions']==1
    assert result['metrics']['all']['reviewed_pairs']==0
    assert result['gate']['status']=='awaiting_validation_review'


def test_review_must_match_exact_answer(tmp_path):
    import json
    from app.evaluation.efficiency import summarize
    run=run_case(education(),Educator())
    review=tmp_path/'review.json'
    review.write_text(json.dumps({'runs':[{'case_id':run['case_id'],'profile':'standard','answer_sha256':'wrong','complete':True,'supported':True}]}))
    with pytest.raises(ValueError,match='does not match'):
        summarize(tmp_path,[run],review)
