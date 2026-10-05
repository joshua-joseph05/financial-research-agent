from app.tools.registry import ToolRegistry
from app.schemas import Evidence


def test_calculation_choices_preserve_company_currency_and_order():
    observations={}
    for ticker,unit in [('X','USD'),('Y','EUR')]:
        for year in (2024,2025):
            key=f'{ticker}:{year}'
            observations[key]=Evidence(id=key,source_id='s',text='Reported revenue',
                ticker=ticker,unit=unit,metric='revenue',value='100',period=f'{year}-12-31').model_dump()
    registry=ToolRegistry()
    choices=next(t for t in registry.descriptions(observations,[]) if t['name']=='calculate_financial_metrics')['input_schema']['anyOf']
    arguments=[{'operation':c['properties']['operation']['const'],
                'evidence_ids':[i['const'] for i in c['properties']['evidence_ids']['prefixItems']]} for c in choices]
    assert arguments==[{'operation':'growth','evidence_ids':['X:2025','X:2024']},
                       {'operation':'growth','evidence_ids':['Y:2025','Y:2024']}]
    calls=[{'name':'calculate_financial_metrics','arguments':arguments[0],'result':{'status':'ok'}}]
    remaining=next(t for t in registry.descriptions(observations,calls) if t['name']=='calculate_financial_metrics')['input_schema']['anyOf']
    assert remaining==choices[1:]
