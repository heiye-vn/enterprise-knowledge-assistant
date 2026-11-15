"""Expand only explicit, source-validated rule → document → rule paths."""

import re
import unicodedata
from uuid import UUID

from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.graph.extraction import Candidate, build_units, identity, validate_candidate
from app.graph.service import GraphProblem, GraphService
from app.graph.store import document_name
from app.models import DocumentContent
from app.retrieval.ranking import keyword_ranking


def scope_matches(question, scope):
    """Check explicit amounts/workdays; keep unknown units and ambiguous quantities unresolved."""
    query = unicodedata.normalize("NFKC", question).replace(",", "")
    scope = unicodedata.normalize("NFKC", scope).replace(",", "")
    if re.search(r"(?:不超过|超过|不少于|至少|不低于|至多|[<>≤≥])\s*\d", query) or re.search(
        r"\d+(?:\.\d+)?(?:个)?(?:工作日|元)(?:以下|以内|以上|及以上)", query
    ):
        return None
    if "工作日" in scope:
        values = re.findall(r"(\d+(?:\.\d+)?)\s*(?:个)?工作日", query)
        if "半天" in query and not values:
            values = ["0.5"]
    elif "元" in scope:
        values = re.findall(r"(\d+(?:\.\d+)?)\s*元", query)
    else:
        return None
    if len(values) != 1:
        return None
    bounds = re.findall(r"(不超过|超过|不低于|至少|<=|>=|≤|≥|<|>)(\d+(?:\.\d+)?)", scope)
    if not bounds:
        return None
    amount = float(values[0])
    checks = {
        "不超过": lambda value: amount <= value,
        "<=": lambda value: amount <= value,
        "≤": lambda value: amount <= value,
        "超过": lambda value: amount > value,
        ">": lambda value: amount > value,
        "<": lambda value: amount < value,
        "不低于": lambda value: amount >= value,
        "至少": lambda value: amount >= value,
        ">=": lambda value: amount >= value,
        "≥": lambda value: amount >= value,
    }
    return all(checks[operator](float(value)) for operator, value in bounds)


def expand_graph_sources(engine, settings, question, snapshot, sources, seeds):
    try:
        return _expand(engine, settings, question, snapshot, sources, seeds)
    except (GraphProblem, SQLAlchemyError, DriverError, Neo4jError, ValueError, KeyError):
        return {"status": "failed", "reason": "graph_unavailable", "candidate_ids": [], "paths": []}


def _expand(engine, settings, question, snapshot, sources, seeds):
    result = {"status": "completed", "reason": None, "candidate_ids": [], "paths": []}
    try:
        graph = GraphService(engine, settings).read()
    except (GraphProblem, SQLAlchemyError, DriverError, Neo4jError):
        return {**result, "status": "failed", "reason": "graph_unavailable"}
    if not graph["available"]:
        return {**result, "status": "failed", "reason": "graph_unavailable"}
    if not graph["edges"]:
        return {**result, "status": "skipped", "reason": "no_published_graph"}
    allowed_jobs = {doc["job_id"] for doc in snapshot["documents"]}
    by_source = {source["id"]: source for source in sources if source["job_id"] in allowed_jobs}
    nodes = {node["id"]: node for node in graph["nodes"]}
    verified, unit_cache = {}, {}

    def evidence(eid, db):
        if eid in verified:
            return verified[eid]
        verified[eid] = None
        record = graph["sources"].get(eid)
        if not record:
            return None
        saved = record["source"]
        source = by_source.get(saved["id"])
        if not source or any(
            saved[key] != source[key] for key in ("job_id", "version_id", "document_id")
        ):
            return None
        if source["id"] not in unit_cache:
            content = db.get(DocumentContent, UUID(source["job_id"]))
            unit_cache[source["id"]] = (
                {
                    identity(unit.source["locators"]): unit
                    for unit in build_units(content.blocks, [source])
                }
                if content
                else {}
            )
        unit = unit_cache[source["id"]].get(identity(saved["locators"]))
        if not unit or unit.text != record["quote"] or unit.scope != record["scope"]:
            return None
        if any(
            condition != unit.scope and condition not in unit.text
            for condition in record["conditions"]
        ):
            return None
        try:
            validate_candidate(
                Candidate(
                    unit_id=unit.id,
                    title="原文依据",
                    conditions=[value for value in record["conditions"] if value != unit.scope],
                    relations=[],
                ),
                unit,
            )
        except ValueError:
            return None
        verified[eid] = {
            "source": unit.source,
            "quote": unit.text,
            "conditions": record["conditions"],
        }
        return verified[eid]

    contains = {}
    for edge in graph["edges"]:
        if edge["predicate"] == "contains":
            contains.setdefault(edge["source"], []).append(edge)
    candidates, seen = [], set()
    with Session(engine) as db:
        references = []
        for reference in graph["edges"]:
            if reference["predicate"] != "references":
                continue
            origin = evidence(reference["sources"][0], db)
            if not origin or origin["source"]["id"] not in seeds:
                continue
            if reference["target"] == "document:" + origin["source"]["document_id"]:
                continue
            references.append((reference, origin))
        named_origins = [
            item
            for item in references
            if document_name(item[1]["source"]["document_title"]) in question
        ]
        references = named_origins or references
        named_targets = [
            item for item in references if nodes[item[0]["target"]]["title"] in question
        ]
        references = named_targets or references
        focus = question
        for node in graph["nodes"]:
            if node["kind"] == "document":
                focus = focus.replace(node["title"], "")
        reference_rank = keyword_ranking(focus, [item[1]["quote"] for item in references], limit=2)
        for ref_index, _ in reference_rank:
            reference, origin = references[ref_index]
            targets = []
            for edge in contains.get(reference["target"], []):
                destination = evidence(edge["sources"][0], db)
                if (
                    destination
                    and destination["source"]["document_id"] != origin["source"]["document_id"]
                ):
                    matched = scope_matches(question, graph["sources"][edge["sources"][0]]["scope"])
                    if matched is not False:
                        targets.append((edge, destination, matched))
            matching_scope = [item for item in targets if item[2] is True]
            targets = matching_scope or targets
            ranking = keyword_ranking(
                focus,
                [
                    nodes[value[0]["target"]]["title"] + "\n" + value[1]["quote"]
                    for value in targets
                ],
                limit=2,
            )
            for index, _ in ranking:
                edge, destination, _ = targets[index]
                key = (origin["source"]["id"], destination["source"]["id"])
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(destination["source"]["id"])
                result["paths"].append(
                    {
                        "from": origin,
                        "to": destination,
                        "nodes": [
                            origin["source"]["document_title"],
                            nodes[reference["target"]]["title"],
                            nodes[edge["target"]]["title"],
                        ],
                        "relations": [reference["label"], edge["label"]],
                    }
                )
                if len(result["paths"]) >= 4:
                    break
            if len(result["paths"]) >= 4:
                break
    result["candidate_ids"] = list(dict.fromkeys(candidates))[:6]
    if not result["paths"]:
        result["reason"] = "no_matching_path"
    return result
