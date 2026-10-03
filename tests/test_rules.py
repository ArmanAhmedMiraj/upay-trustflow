import rules


def row(**kw):
    base = {"claim_mismatch_on_recipient": 0, "is_first_time_recipient": 0, "report_count": 0}
    base.update(kw)
    return base


def test_story_mismatch_rule_fires_for_fake_credit_sms_to_new_recipient():
    hits = rules.rule_hits(row(claim_mismatch_on_recipient=1, is_first_time_recipient=1))
    assert [h["id"] for h in hits] == ["story_mismatch"]


def test_story_mismatch_rule_stays_quiet_otherwise():
    assert rules.rule_hits(row()) == []
    assert rules.rule_hits(row(claim_mismatch_on_recipient=1, is_first_time_recipient=0)) == []
