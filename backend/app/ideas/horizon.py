"""Conservative interpretation of typed horizons; ambiguous dates stay unresolved."""
import re
from datetime import date


def interpret_horizon(text, today=None):
    today=today or date.today()
    text=text.lower().strip().replace('–','-').replace('—','-')
    for word,value in {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'twelve':12,'fifteen':15,'twenty':20}.items():
        text=re.sub(r'\b'+word+r'\b',str(value),text)
    if re.search(r'\b(?:less than|under|within|before|not sure|unsure|whenever|maybe|possibly)\b',text):
        return 'custom'  # No reliable earliest need date.
    candidates=[]
    if re.search(r'\b(next year|a year)\b',text): candidates.append(1.0)
    if re.search(r'\b(next month|a month|soon|next week)\b',text): candidates.append(1/12)
    compound=re.search(r'(\d+(?:\.\d+)?)\s*years?\s*(?:and\s*)?(\d+(?:\.\d+)?)\s*months?',text)
    if compound:
        candidates.append(float(compound[1])+float(compound[2])/12)
        text=text[:compound.start()]+text[compound.end():]
    for match in re.finditer(r'(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?\s*(years?|months?|weeks?|days?)\b',text):
        value=float(match[1]);unit=match[2]
        candidates.append(value if unit.startswith('year') else value/12 if unit.startswith('month') else value/52 if unit.startswith('week') else value/365.25)
    iso=re.search(r'\b(20\d{2}-\d{2}-\d{2})\b',text)
    if iso:
        try: candidates.append((date.fromisoformat(iso[1])-today).days/365.25)
        except ValueError: return 'custom'
        text=text.replace(iso[1],'')
    for year in re.findall(r'\b(20\d{2})\b',text):
        # A year without a month means the earliest date within that year.
        candidates.append((date(int(year),1,1)-today).days/365.25)
    if not candidates: return 'custom'
    years=min(candidates)
    if years<0: return 'custom'
    return 'under_3_years' if years<3 else '3_to_5_years' if years<5 else '5_plus_years'
