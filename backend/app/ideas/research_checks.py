"""Beginner research prompts, kept separate from verified company conclusions."""


def research_checks(ticker, observations, sources, reasons, risks):
    """Point to retained evidence without implying that a check is complete."""
    retained=list(dict.fromkeys(key for claim in [*reasons,*risks] for key in claim.evidence_ids))
    records={}
    pending=list(reversed(retained))
    while pending:
        key=pending.pop()
        if key in records:continue
        record=observations.get(key)
        if not record or record.get('ticker')!=ticker or record.get('source_id') not in sources:continue
        records[key]=record
        pending.extend(reversed(record.get('input_ids',[])))
    def evidence(*metrics):
        return [key for key,record in records.items() if record.get('metric') in metrics][:4]
    rows=[
        ('Understand the business',f'Can you explain how {ticker} earns money and what could change customer demand?',[]),
        ('Check sales and profitability','Compare sales and operating profit across periods. What explains the changes, and are those explanations supported by filings?',evidence('revenue','operating_income','operating_margin','margin_change','growth')),
        ('Check cash and obligations','Compare operating cash flow (cash from running the business), spending on long-lived assets, cash balances, and debt. What still needs investigating?',evidence('operating_cash_flow','capital_expenditure','cash','total_debt')),
        ('Investigate the risks','Read the disclosed risks and ask how they could affect the business. Which risks are absent from this report?', [key for claim in risks for key in claim.evidence_ids if key in records][:4]),
        ('Assess price and personal fit','What assumptions would justify the share price? How would this stock fit your other investments, time horizon, and ability to absorb losses?',[]),
    ]
    return [{'title':title,'question':question,'evidence_ids':ids,
             'coverage':'Starting evidence available; this check is not complete.' if ids else 'Not established by the retained findings.'}
            for title,question,ids in rows]


def checklist_outline():
    """Expose existing report structure without suggesting any check is completed."""
    return {'status':'Research prompts included in the final report; not completed due diligence.',
            'checks':[{k:row[k] for k in ('title','question')}
                      for row in research_checks('the company', {}, {}, [], [])]}
