"""Question-specific source planning; never substitute an unrelated default guide."""

def planning_context(question):
    return {'question':question, 'guide_topics':{
        'stocks':'Company ownership, share value, dividends and their uncertainty.',
        'bonds':'Lending to an issuer, credit risk and interest-rate risk.',
        'funds':'Pooled holdings, ETFs, fees and fund concentration.',
        'diversification':'Spreading investments, concentration and remaining loss risk.'},
        'instruction':'Plan evidence retrieval, do not answer. Select every guide topic needed for the actual question, with no unrelated defaults. A comparison needs sources for both concepts. List only the distinct requested parts as self-contained questions, at most four. Preserve qualifications such as whether a payment is guaranteed. Questions about concentration, diversification or protection from losses need the diversification guide even when they also concern funds; retrieve both guides when fund structure or fees are requested. Do not add companies or invent facts.'}
