import pytest
from neo4j.exceptions import ServiceUnavailable
from test_graph_api import graph_environment as graph_environment
from test_graph_api import run_graph, source_doc
from test_import_api import import_environment as import_environment
from test_indexing_jobs import indexed_environment as indexed_environment

from app.graph.service import GraphService
from app.retrieval.search import SearchService

pytestmark = pytest.mark.integration


@pytest.fixture
def two_hop_sources(graph_environment):
    client, settings, _ = graph_environment
    handbook = source_doc(
        client, settings, "# 员工手册\n\n请假应按《考勤制度》提交申请。", "员工手册.md"
    )
    attendance = source_doc(client, settings)
    for job in client.post("/api/graph/build", json={}).json()["jobs"]:
        assert run_graph(client, settings, job["id"])["status"] == "ready"
    service = SearchService(client.app.state.db_engine, settings)
    snapshot, sources = service.capture(None)
    seed = next(
        source["id"]
        for source in sources
        if source["document_id"] == handbook["document_id"] and "《考勤制度》" in source["content"]
    )
    return client, settings, service, snapshot, sources, seed, handbook, attendance


def test_two_hop_expansion_returns_exact_target_evidence_and_real_path(two_hop_sources):
    from app.retrieval.graph_expansion import expand_graph_sources

    client, settings, _, snapshot, sources, seed, _, attendance = two_hop_sources
    result = expand_graph_sources(
        client.app.state.db_engine,
        settings,
        "超过3个工作日请假由谁审批？",
        snapshot,
        sources,
        [seed],
    )
    assert result["status"] == "completed" and result["candidate_ids"]
    path = result["paths"][0]
    assert path["relations"] == ["引用制度", "包含规则"]
    assert path["from"]["source"]["id"] == seed
    assert path["to"]["source"]["document_id"] == attendance["document_id"]
    assert "人力资源部仅备案" in path["to"]["quote"]
    assert path["to"]["quote"] in path["to"]["source"]["content"]


def test_graph_expansion_cannot_leave_explicit_document_scope(two_hop_sources):
    from uuid import UUID

    from app.retrieval.graph_expansion import expand_graph_sources

    client, settings, service, _, _, seed, handbook, _ = two_hop_sources
    snapshot, sources = service.capture([UUID(handbook["document_id"])])
    result = expand_graph_sources(
        client.app.state.db_engine, settings, "请假由谁审批？", snapshot, sources, [seed]
    )
    assert result["candidate_ids"] == [] and result["paths"] == []


def test_graph_failure_preserves_normal_search_and_reports_degradation(
    two_hop_sources, monkeypatch
):
    from app.model_clients import ModelClient, RankedItem, Ranking

    _, _, service, *_ = two_hop_sources

    def unavailable(*_):
        raise ServiceUnavailable("test graph outage")

    monkeypatch.setattr(GraphService, "read", unavailable)
    monkeypatch.setattr(
        ModelClient,
        "rerank",
        lambda self, q, candidates, top_n: Ranking(
            [RankedItem(i, 0.8) for i in range(len(candidates))], self.settings.qwen_rerank_model
        ),
    )
    result = service.retrieve("请假审批", use_graph=True)
    assert result["items"] and result["trace"]["graph"]["status"] == "failed"
    assert "graph_unavailable" in {warning["code"] for warning in result["warnings"]}


def test_modified_graph_quote_is_excluded_even_when_chunk_identity_exists(
    two_hop_sources, monkeypatch
):
    from app.retrieval.graph_expansion import expand_graph_sources

    client, settings, _, snapshot, sources, seed, *_ = two_hop_sources
    graph = GraphService(client.app.state.db_engine, settings).read()
    for evidence in graph["sources"].values():
        evidence["quote"] = "伪造的审批结论"
    monkeypatch.setattr(GraphService, "read", lambda *_: graph)
    result = expand_graph_sources(
        client.app.state.db_engine, settings, "请假审批", snapshot, sources, [seed]
    )
    assert result["candidate_ids"] == [] and result["paths"] == []


def test_graph_conditions_cannot_omit_original_duration(two_hop_sources, monkeypatch):
    from app.retrieval.graph_expansion import expand_graph_sources

    client, settings, _, snapshot, sources, seed, *_ = two_hop_sources
    graph = GraphService(client.app.state.db_engine, settings).read()
    for evidence in graph["sources"].values():
        evidence["conditions"] = []
    monkeypatch.setattr(GraphService, "read", lambda *_: graph)
    result = expand_graph_sources(
        client.app.state.db_engine, settings, "超过3个工作日请假审批", snapshot, sources, [seed]
    )
    assert result["candidate_ids"] == [] and result["paths"] == []


def test_updated_import_cannot_expand_through_the_previous_graph(two_hop_sources):
    from test_indexing_jobs import finish

    from app.retrieval.graph_expansion import expand_graph_sources

    client, settings, _, snapshot, sources, seed, _, attendance = two_hop_sources
    uploaded = client.post(
        f"/api/documents/{attendance['document_id']}/versions",
        files={"file": ("考勤制度.md", "# 新考勤\n\n请假必须提交新申请。".encode())},
    ).json()
    assert finish(client, settings, uploaded["job_id"])["status"] == "ready"
    result = expand_graph_sources(
        client.app.state.db_engine, settings, "超过3个工作日请假审批", snapshot, sources, [seed]
    )
    assert result["candidate_ids"] == [] and result["paths"] == []
