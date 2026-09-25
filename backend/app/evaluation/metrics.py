"""Structural diagnostics, explicitly separate from semantic answer quality."""
def claims_from(report):
    return [claim for idea in report.get('ideas', [])
            for claim in idea.get('reasons', []) + idea.get('risks', [])] + report.get('answer_sections', [])


def audit(report):
    claims = claims_from(report)
    known = {e['id'] for e in report.get('evidence', [])}
    resolved = sum(bool(c.get('evidence_ids')) and all(i in known for i in c['evidence_ids']) for c in claims)
    consultations = report.get('sentiment_results', [])
    return {
        'claims': len(claims), 'claims_with_resolvable_citations': resolved,
        'citation_resolution_rate': resolved / len(claims) if claims else None,
        'sentiment_consultations': len(consultations),
        'sentiment_reviewed_samples': sum(c.get('status') == 'reviewed_sample' for c in consultations),
        'sentiment_arguments': sum(len(c.get('arguments', [])) for c in consultations),
    }


SCORE_KEYS = ('coverage_0_to_4', 'citation_support_0_to_4', 'numerical_accuracy_0_to_4',
              'readability_0_to_4', 'sentiment_usefulness_0_to_4', 'unsupported_claim_count')


def review_item(label, case, report):
    return {
        'label': label, 'question': case['question'], 'rubric': case['rubric'],
        'answer': claims_from(report),
        'decisions': [{k: idea.get(k) for k in ('ticker', 'action', 'gate')} for idea in report.get('ideas', [])],
        'evidence': report.get('evidence', []), 'sources': report.get('sources', []),
        'sentiment': [{k: item.get(k) for k in ('ticker', 'synthesis', 'arguments', 'limitations')}
                      for item in report.get('sentiment_results', [])],
        'limitations': report.get('limitations', []),
        'scores': {key: None for key in SCORE_KEYS}, 'notes': '',
    }
