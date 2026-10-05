import jsonschema
import pytest
from app.agent.graph import EfficientPlan
from app.schemas import Verification
from app.providers.llm import response_schema
from app.evaluation.sources import BenchmarkRegistry


def test_initial_tool_uses_actual_tool_argument_schema():
    context={'available_tools':BenchmarkRegistry().descriptions({})}
    schema=response_schema('plan',context,EfficientPlan)
    valid={'coverage_targets':[], 'companies':['NVDA'],'questions':['Growth risks?'],'answer_type':'descriptive','evidence_requirements':['filing_passages'],'initial_tool':{'name':'get_sec_filings','arguments':{'ticker':'NVDA','section':'risks'}}}
    jsonschema.validate(valid,schema)
    for tool in [{'name':'not_a_tool','arguments':{}},{'name':'get_sec_filings','arguments':{}},{'name':'calculate_financial_metrics','arguments':{'operation':'growth','evidence_ids':['invented','made_up']}}]:
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**valid,'initial_tool':tool},schema)


def test_claim_scoped_research_review_requires_every_nonderived_finding():
    context={'data_mode':'SEC filings','claims_to_review':[{'finding':{'id':'risk'},'cited_evidence':{}},{'finding':{'id':'derived:calc'},'cited_evidence':{}}]}
    schema=response_schema('verify',context,Verification)
    valid={'coverage':'sufficient','unresolved_requirements':[],'checks':[{'finding_id':'risk','status':'supported','explanation':'Matches its cited text.'}]}
    jsonschema.validate(valid,schema)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**valid,'checks':[]},schema)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**valid,'checks':[{'finding_id':'other','status':'supported','explanation':'Wrong finding.'}]},schema)


def test_investment_review_schema_requires_actions_and_scoped_citations():
    from app.ideas.claim_review import ClaimReview
    context={'claims':[{'claim_id':'NVDA:risks:0','evidence':{'risk':{}}}],'actions':[{'ticker':'NVDA','action':'watch'}]}
    schema=response_schema('ideas_claim_review',context,ClaimReview)
    valid={'checks':[{'claim_id':'NVDA:risks:0','supported':True,'quotes':[{'evidence_id':'risk','quote':'Exact excerpt.'}]}],'actions':[{'ticker':'NVDA','supported':True}]}
    jsonschema.validate(valid,schema)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**valid,'actions':[]},schema)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({**valid,'checks':[]},schema)
    valid['checks'][0]['quotes'][0]['evidence_id']='unrelated'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(valid,schema)


def test_descriptive_plan_cannot_require_causal_filing_explanation():
    context={'available_tools':BenchmarkRegistry().descriptions({})}
    schema=response_schema('plan',context,EfficientPlan)
    response={'coverage_targets':[], 'companies':['AMD'],'questions':['Compute profit growth'],
              'answer_type':'descriptive','evidence_requirements':['financial_values','calculated_metrics','filing_explanations'],
              'initial_tool':{'name':'get_financials','arguments':{'ticker':'AMD'}}}
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)
    response['answer_type']='historical_explanation'
    jsonschema.validate(response,schema)
    response.update(answer_type='descriptive',evidence_requirements=['filing_passages'])
    jsonschema.validate(response,schema)


def test_education_review_indices_are_limited_to_supplied_parts_and_sections():
    from app.providers.llm import response_schema
    from app.ideas.models import EducationalCoverageReview
    schema = response_schema('ideas_education_review', {
        'requested_parts': ['Explain one concept', 'Contrast another'],
        'draft': {'sections': [{'text': 'One'}, {'text': 'Two'}, {'text': 'Comparison'}]},
    }, EducationalCoverageReview)
    props = schema['$defs']['EducationalPartCheck']['properties']
    assert schema['properties']['covered_parts']['maxItems'] == 2
    assert schema['properties']['missing_parts']['maxItems'] == 2
    assert props['part_index']['enum'] == [0, 1]
    assert props['answer_section_index']['enum'] == [0, 1, 2]
    assert schema['properties']['missing_parts']['items']['enum'] == [0, 1]
    # Other phases and generic schema consumers keep the unconstrained schema.
    assert 'enum' not in EducationalCoverageReview.model_json_schema()['$defs']['EducationalPartCheck']['properties']['part_index']


def test_financial_coverage_requires_named_metrics_in_schema_and_runtime():
    from app.agent.coverage import CoverageTarget
    from pydantic import ValidationError
    context={'available_tools':BenchmarkRegistry().descriptions({})}
    schema=response_schema('plan',context,EfficientPlan)
    target={'ticker':'MSFT','needs':['business','financial_values'],'financial_metrics':[],'minimum_periods':1}
    response={'coverage_targets':[target], 'companies':['MSFT'],'questions':['Revenue?'],'answer_type':'descriptive','evidence_requirements':['financial_values'],'initial_tool':{'name':'get_financials','arguments':{'ticker':'MSFT'}}}
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)
    with pytest.raises(ValidationError):CoverageTarget.model_validate(target)
    target['financial_metrics']=['revenue']
    jsonschema.validate(response,schema)
    target.update(needs=['business','risks'],financial_metrics=[])
    jsonschema.validate(response,schema)
