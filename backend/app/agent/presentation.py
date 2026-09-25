"""Beginner explanations derived from verified findings, without another factual LLM pass."""
from datetime import date
from decimal import Decimal

from app.schemas import BeginnerGuide, ExplainedFinding, GlossaryEntry, Evidence
from app.tools.calculations import calculate

TERMS = {
    'revenue': ('Revenue', 'Money earned from selling products or services, before expenses are deducted.'),
    'operating income': ('Operating income', 'Profit from running the business after operating costs. It is not the same as cash flow or final profit after interest and taxes.'),
    'operating margin': ('Operating margin', 'The share of revenue left as operating profit. It describes profitability relative to sales, not how expensive the stock is.'),
    'gross margin': ('Gross margin', 'The share of sales left after the direct cost of products or services, before other operating expenses.'),
    'percentage point': ('Percentage points', 'The difference between two percentages. A margin moving from 20% to 25% rises by 5 percentage points; that is different from 5% growth.'),
    'net income': ('Net income', 'Profit after expenses, including interest and taxes. This is often called the bottom line.'),
    'cash flow': ('Cash flow', 'Cash moving into or out of the business. Accounting profit and cash flow can differ because payments and expenses are recorded at different times.'),
    'capital expenditure': ('Capital expenditure', 'Money spent on long-lived assets, such as equipment and buildings, rather than everyday operating costs.'),
    'guidance': ('Guidance', 'Management’s expectations for future results. It is a forecast, not a result the company has already achieved.'),
    'fiscal': ('Fiscal year', 'The company’s financial reporting year. It may end in a different month from the calendar year or another company’s reporting year.'),
    'segment': ('Business segment', 'One part of a company, such as a product group. Its performance should not be treated as the performance of the whole company.'),
    'supply chain': ('Supply chain', 'The suppliers and steps needed to produce and deliver a product. A disruption at one step can affect the rest.'),
    'hyperscaler': ('Hyperscaler', 'A company that operates very large cloud-computing infrastructure.'),
    'valuation': ('Valuation', 'How much investors are paying for a business relative to measures such as earnings or cash flow. Strong business results alone do not establish whether a stock is attractively priced.'),
    'cloud mix': ('Cloud mix', 'How much of the business comes from cloud products and services. Different products can have different costs and profit margins.'),
    'expense discipline': ('Expense discipline', 'Keeping spending under control. The phrase alone does not quantify which costs changed or by how much.'),
    'depreciation': ('Depreciation', 'An accounting expense that spreads the cost of a long-lived asset over its useful life.'),
}


def number(value):
    return f'{Decimal(value):,.2f}'.rstrip('0').rstrip('.')


def period(value):
    try:
        return date.fromisoformat(value).strftime('%B %d, %Y').replace(' 0', ' ')
    except (ValueError, TypeError):
        return value or 'the reported period'


def beginner_guide(findings, evidence, complete, synthetic=False, stop_reason=None, has_observations=False):
    """Only consume report-selected, verified evidence; do not infer missing company facts."""
    observations = {e['id']: e for e in evidence}
    cards, covered, summaries = [], set(), []
    margins = {}
    # Calculation inputs were recursively reproduced during verification too.
    reachable = set()
    def include(key):
        if key in reachable or key not in observations:
            return
        reachable.add(key)
        for dependency in observations[key].get('input_ids', []):
            include(dependency)
    for finding in findings:
        for key in finding['evidence_ids']:
            include(key)
    for key in sorted(reachable):
        record = observations[key]
        if record.get('operation') == 'operating_margin':
            margins.setdefault(record['ticker'], {})[key] = record
    for ticker, records in margins.items():
        rows = sorted(records.values(), key=lambda row: row.get('period') or '')
        latest = rows[-1]
        value = number(latest['value'])
        per_sales = (f'about ${number(abs(Decimal(latest["value"])))} was lost at the operating level' if Decimal(latest['value']) < 0 else f'about ${value} remained as operating profit after operating costs')
        explanation = (f"For the year ending {period(latest['period'])}, {ticker} had an operating margin of about {value}%. "
                       f"Think of it this way: for every $100 of sales, {per_sales}. "
                       "This is before interest and taxes; it is not the amount of cash the company kept.")
        takeaway = f"{ticker}: for every $100 of sales, {per_sales}."
        if len(rows) >= 2:
            previous = rows[-2]
            try:
                delta, _ = calculate('margin_change', [Evidence.model_validate(latest), Evidence.model_validate(previous)])
                change = Decimal(delta)
                verb = 'rose' if change > 0 else 'fell' if change < 0 else 'was unchanged'
                movement = f"{ticker}’s operating margin {verb}"
                if change:
                    movement += f" by about {number(abs(change))} percentage points"
                movement += f" between the years ending {period(previous['period'])} and {period(latest['period'])}."
                explanation += ' ' + movement
                takeaway = movement
            except (ValueError, ArithmeticError):
                pass
        ids = [row['id'] for row in rows]
        covered.update(ids)
        cards.append(ExplainedFinding(title=f'{ticker}: how much profit is left from sales', explanation=explanation,
            why_it_matters='A higher operating margin means more operating profit from each dollar of sales. It does not by itself explain the cause, prove future growth, or tell you whether the stock is worth its price.',
            evidence_ids=ids, figures=[{'period': period(row['period']), 'value': number(row['value']) + '%'} for row in rows]))
        summaries.append(takeaway)
    for finding in findings:
        if all(key in covered for key in finding['evidence_ids']):
            continue
        # A separately verified margin change is already explained by the paired margins.
        if all(observations.get(key, {}).get('operation') == 'margin_change' and
               set(observations[key].get('input_ids', [])) <= covered for key in finding['evidence_ids']):
            continue
        cited = [observations[key] for key in finding['evidence_ids'] if key in observations]
        title, meaning = 'What the evidence says', 'Consider this finding alongside the other evidence. It describes part of the business, not a conclusion about whether to buy or sell the stock.'
        if finding.get('kind') == 'risk':
            title, meaning = 'A risk to understand', 'This describes something that could go wrong, not something certain to happen. The next question is how exposed the company is and what evidence would show the risk increasing or decreasing.'
        elif finding.get('explains_change'):
            title, meaning = 'What may help explain the change', 'This is a reported explanation or an interpretation of the evidence. It can explain part of the change without measuring how much each factor contributed.'
        elif cited and all(e['id'].startswith('news:') for e in cited):
            title, meaning = 'A headline to investigate', 'A headline is a starting point. The full article and primary sources still need checking before treating its claims as established facts.'
        elif cited and all(e.get('metric') == 'market_close' for e in cited):
            title, meaning = 'A dated share price', 'This is a price from a previous trading session, not a live quote. A share price alone does not show whether a business is cheap or expensive.'
        explanation = finding['text']
        if len(cited) == 1:
            record = cited[0]
            definitions = {
                'revenue': ('sales', 'Revenue measures the size of the business’s sales. Rising sales do not automatically mean rising profit, because costs can rise too.'),
                'operating_income': ('operating profit', 'Operating profit shows what is left from running the business after operating costs, before interest and taxes. Comparing it with sales helps put the amount in context.'),
                'net_income': ('net profit', 'Net profit includes expenses such as interest and taxes. It can include unusual items, so one year alone may not represent ongoing performance.'),
                'operating_cash_flow': ('cash generated by operating activities', 'This tracks cash from running the business. It can differ from accounting profit and does not deduct spending on long-lived assets.'),
                'capital_expenditure': ('spending on long-lived assets', 'This is money invested in assets such as buildings and equipment. It uses cash today and may support future operations; the figure alone does not establish the return on that spending.'),
            }
            if not record.get('operation') and record.get('metric') in definitions and record.get('unit') in ('USD', 'USD_millions') and record.get('value') is not None:
                label, meaning = definitions[record['metric']]
                amount = Decimal(record['value']) * (1000000 if record['unit'] == 'USD_millions' else 1)
                divisor, suffix = (Decimal(1000000000), ' billion') if abs(amount) >= 1000000000 else (Decimal(1000000), ' million') if abs(amount) >= 1000000 else (Decimal(1), '')
                title = f"{record['ticker']}: {label}"
                explanation = f"For the year ending {period(record.get('period_end') or record.get('period'))}, {record['ticker']} reported {label} of about ${number(amount / divisor)}{suffix}."
        labels = []
        if finding.get('scope') == 'segment':
            labels.append('This applies only to ' + (finding.get('segment') or 'one business segment') + ', not the whole company.')
        if finding.get('fiscal_years'):
            labels.append('Financial years discussed: ' + ' and '.join(map(str, finding['fiscal_years'])) + '.')
        cards.append(ExplainedFinding(title=title, explanation=explanation + (' ' + ' '.join(labels) if labels else ''), why_it_matters=meaning, evidence_ids=finding['evidence_ids']))
    if len(margins) > 1:
        windows = {tuple(sorted((r.get('period_start'), r.get('period_end')) for r in records.values())) for records in margins.values()}
        if len(windows) > 1:
            summaries.append('These companies report different financial-year dates, so this is not a comparison of identical calendar periods.')
    if not summaries:
        summaries = [card.explanation for card in cards[:2]]
    text = ' '.join([f['text'] for f in findings] + [c.explanation for c in cards]).lower().replace('_', ' ')
    glossary = [GlossaryEntry(term=term, definition=definition) for key, (term, definition) in TERMS.items() if key in text]
    status = ('These findings address the question using the available evidence. They are research support, not an investment recommendation.' if complete else
              'This is a partial answer. The supported findings below are useful starting points, but the evidence does not yet answer every part of your question.')
    if not findings:
        if stop_reason in ('model_error', 'assessment_error', 'verification_error', 'synthesis_error'):
            summaries = ['The local AI could not finish processing or checking the research.']
            status = 'This is a research-system failure, not evidence that the company has no relevant information. Retry the run with Ollama running; technical details are available below.'
        elif stop_reason in ('no_new_evidence', 'repeated_tool_call') and not has_observations:
            summaries = ['The search did not retrieve usable evidence with the filters it tried.']
            status = 'This run failed to investigate the question successfully. It does not establish that the company has no disclosed risks or relevant information. The tool results below explain where retrieval stopped.'
        elif stop_reason in ('time_budget', 'tool_budget', 'iteration_budget', 'verification_budget'):
            summaries = ['The research run reached its limit before it could produce a verified answer.']
            status = 'This is an incomplete run, not a conclusion about the company. No unsupported findings are shown.'
        else:
            status = 'The run did not produce verified findings. This does not establish that relevant information is unavailable. Review the research limitations below.'
    if synthetic:
        status = 'Practice report: all company information here is fictional. ' + status
    return BeginnerGuide(overview=' '.join(summaries), status=status, explanations=cards, glossary=glossary,
        next_steps=['What explains the change, and is that explanation supported by the same reporting period?', 'What evidence could change this interpretation?'] if margins else ['Which parts are established facts, and which are management expectations or possible risks?', 'What additional evidence would make this finding more useful?'])
