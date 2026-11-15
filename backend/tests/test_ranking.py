from app.retrieval.ranking import keyword_ranking, reciprocal_rank_fusion, tokenize


def test_rrf_deduplicates_per_list_and_across_both_routes():
    result = reciprocal_rank_fusion([["a", "a", "b"], ["b", "c", "a"]])
    assert len(result) == 3 and len({identity for identity, _ in result}) == 3
    scores = dict(result)
    assert abs(scores["a"] - (1 / 61 + 1 / 63)) < 1e-10
    assert scores["b"] > scores["c"]


def test_chinese_terms_and_thousands_amounts_are_retrievable():
    corpus = ["费用报销：超过5,000元由财务经理审批。", "人事考勤：事假需要部门负责人审批。"]
    result = keyword_ranking("报销5000元 财务经理", corpus, limit=2)
    assert result[0][0] == 0
    assert "5000" in tokenize(corpus[0])


def test_nonmatching_keywords_do_not_enter_keyword_candidates():
    assert keyword_ranking("火星航天", ["员工请假审批", "费用发票"], limit=5) == []


def test_one_document_corpus_is_not_lost_when_bm25_idf_is_negative():
    assert keyword_ranking("报销发票", ["报销须提供发票"], limit=1)[0][0] == 0


def test_graph_promoted_candidate_keeps_actual_fusion_rank_and_unknown_score_stays_missing():
    from app.retrieval.trace import retrieval_trace

    sources = {key: {"id": key, "content": "原文"} for key in ["first", "promoted", "graph-only"]}
    trace = retrieval_trace(
        "问题",
        sources,
        [("first", 0.03), ("promoted", 0.01), ("graph-only", None)],
        {},
        {},
        {},
        set(),
        [],
        {},
        fusion_order=[("first", 0.03), ("omitted", 0.02), ("promoted", 0.01)],
    )
    by_id = {candidate["source"]["id"]: candidate for candidate in trace["candidates"]}
    assert by_id["promoted"]["ranks"]["fusion"] == 3
    assert by_id["promoted"]["scores"]["rrf"] == 0.01
    assert by_id["graph-only"]["ranks"]["fusion"] is None
    assert by_id["graph-only"]["scores"]["rrf"] is None
