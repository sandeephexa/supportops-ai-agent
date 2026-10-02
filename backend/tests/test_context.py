from supportops.retrieval import chunk_markdown, pack_context


def test_compression_respects_budget_and_keeps_warnings():
    content = (
        " ".join(["A long unrelated background sentence."] * 50)
        + " Never transmit credential secrets. Missing sync:write causes 403 errors."
    )
    evidence = [{"id": "runbook:1", "source": "runbook", "content": content}]
    packed = pack_context(evidence, 700, "403 sync:write")
    assert packed
    assert "Never transmit credential secrets." in packed[0]["content"]
    assert len(packed[0]["content"].encode()) + 200 <= 700


def test_tool_json_is_not_truncated_into_invalid_evidence():
    evidence = [{"id": "tool:1", "source": "tool", "content": '{"value":"' + "x" * 2000 + '"}'}]
    assert pack_context(evidence, 700) == []


def test_chunking_keeps_headings_and_parent_provenance():
    sections = list(chunk_markdown("# Product\n## Authentication\nUse scopes.\n## Failures\nCheck the code."))
    assert len(sections) == 2
    assert sections[0] == ("Product", "Authentication", "Use scopes.", "Use scopes.")
