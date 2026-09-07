from llm_matgen.adsorption.proposals import ProposalStreamAudit, bounded_proposal_stream


def test_bounded_stream_reports_attempts_and_truncation():
    values = iter(["a", "b", "c"])
    selected, audit = bounded_proposal_stream(values, max_attempts=2)
    assert selected == ["a", "b"]
    assert audit == ProposalStreamAudit(attempted=2, accepted=2, rejected=0, truncated=True)

