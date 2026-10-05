from app.agent.graph import merge_finding_updates


def claim(key, evidence, text):
    return {'id': key, 'evidence_ids': [evidence], 'text': text}


def test_disjoint_id_collision_retains_both_companies_and_deduplicates_replay():
    old = claim('claim_1', 'msft_business', 'Microsoft business')
    new = claim('claim_1', 'nvda_business', 'NVIDIA business')
    merged = merge_finding_updates([old], [new])
    assert merged == [old, {**new, 'id': 'claim_1_2'}]
    assert merge_finding_updates(merged, [new]) == merged
    assert new['id'] == 'claim_1'


def test_same_evidence_wording_correction_replaces_claim():
    old = claim('claim_1', 'msft_business', 'Wrong wording')
    new = claim('claim_1', 'msft_business', 'Correct wording')
    assert merge_finding_updates([old], [new]) == [new]


def test_rejected_claim_can_be_corrected_with_different_source():
    old = claim('claim_1', 'msft_risks', 'Business description')
    new = claim('claim_1', 'msft_business', 'Correct business description')
    assert merge_finding_updates([old], [new], {'claim_1'}) == [new]


def test_collision_does_not_overwrite_existing_suffixed_id():
    old = claim('claim_1', 'a', 'A')
    second = claim('claim_1_2', 'b', 'B')
    new = claim('claim_1', 'c', 'C')
    assert merge_finding_updates([old, second], [new])[-1]['id'] == 'claim_1_3'
