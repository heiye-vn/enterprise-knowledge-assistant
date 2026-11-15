"""Immutable Neo4j projections; PostgreSQL decides which projections are published."""

import re
from collections import defaultdict

from neo4j import GraphDatabase

from app.graph.extraction import RELATIONS, identity


def document_name(value):
    return re.sub(r"^\d+[_\s-]+", "", value).strip().strip("*《》")


def projection_data(projection_id, rules, catalog):
    names = defaultdict(list)
    for item in catalog:
        for name in {
            document_name(item["title"]),
            document_name(item["filename"].rsplit(".", 1)[0]),
        }:
            names[name].append(item["document_id"])
    nodes, edges = {}, {}

    def entity(kind, title, document_id=None):
        key = (
            ("document:" + document_id)
            if document_id
            else kind + ":" + identity([kind, title])[:24]
        )
        nodes[key] = {
            "id": key,
            "kind": kind,
            "title": title,
            "detail": title,
            **({"document_id": document_id} if document_id else {}),
        }
        return key

    def edge(source, target, predicate, evidence_id):
        label = {"contains": "包含规则", "governs": "适用规则"}.get(predicate)
        label = label or RELATIONS[predicate][1]
        key = identity([projection_id, source, predicate, target, evidence_id])
        edges[key] = {
            "id": key,
            "source": source,
            "target": target,
            "label": label,
            "predicate": predicate,
            "evidence_id": evidence_id,
        }

    catalog_by_id = {item["document_id"]: item for item in catalog}
    for rule in rules:
        source = rule["source"]
        doc = catalog_by_id[source["document_id"]]
        root = entity("document", document_name(doc["title"]), source["document_id"])
        rid = "rule:" + identity([projection_id, rule["unit_id"]])[:32]
        eid = identity([projection_id, rule["unit_id"]])
        nodes[rid] = {
            "id": rid,
            "kind": "rule",
            "title": rule["title"],
            "detail": rule["quote"],
            "scope": rule["scope"],
            "projection_id": projection_id,
        }
        edge(root, rid, "contains", eid)
        mid = "matter:" + identity([source["document_id"], rule["matter"]])[:24]
        nodes[mid] = {
            "id": mid,
            "kind": "matter",
            "title": rule["matter"],
            "detail": rule["matter"],
        }
        edge(mid, rid, "governs", eid)
        for relation in rule["relations"]:
            title = relation["target"]
            target_doc = None
            if relation["target_kind"] == "document":
                title = document_name(title)
                matches = set(names.get(title, []))
                target_doc = next(iter(matches)) if len(matches) == 1 else None
            target = entity(relation["target_kind"], title, target_doc)
            edge(rid, target, relation["type"], eid)
    return list(nodes.values()), list(edges.values())


class GraphStore:
    def __init__(self, settings):
        self.settings = settings

    def driver(self):
        return GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password.get_secret_value()),
            connection_timeout=self.settings.dependency_timeout,
            connection_acquisition_timeout=self.settings.dependency_timeout,
        )

    def project(self, projection_id, rules, catalog):
        nodes, edges = projection_data(projection_id, rules, catalog)
        with self.driver() as driver, driver.session() as session:
            session.run(
                "CREATE CONSTRAINT eka_knowledge_node_key IF NOT EXISTS "
                "FOR (n:KnowledgeNode) REQUIRE (n.namespace,n.id) IS UNIQUE"
            ).consume()

            def write(tx):
                tx.run(
                    "UNWIND $nodes AS row "
                    "MERGE (n:KnowledgeNode {namespace:$namespace,id:row.id}) SET n += row",
                    namespace=self.settings.graph_namespace,
                    nodes=nodes,
                ).consume()
                tx.run(
                    "UNWIND $edges AS row "
                    "MATCH (a:KnowledgeNode {namespace:$namespace,id:row.source}) "
                    "MATCH (b:KnowledgeNode {namespace:$namespace,id:row.target}) "
                    "MERGE (a)-[r:KnowledgeLink {namespace:$namespace,id:row.id}]->(b) "
                    "SET r += row, r.projection_id=$projection",
                    namespace=self.settings.graph_namespace,
                    projection=projection_id,
                    edges=edges,
                ).consume()

            session.execute_write(write)
        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "business_relations": sum(e["predicate"] not in {"contains", "governs"} for e in edges),
        }

    def read(self, projection_ids, *, max_nodes=1000):
        if not projection_ids:
            return [], [], False
        with self.driver() as driver, driver.session() as session:
            rows = list(
                session.run(
                    "MATCH (a:KnowledgeNode)-[r:KnowledgeLink]->(b:KnowledgeNode) "
                    "WHERE a.namespace=$namespace AND b.namespace=$namespace "
                    "AND r.namespace=$namespace AND r.projection_id IN $projections "
                    "RETURN properties(a) AS a,properties(r) AS edge,properties(b) AS b "
                    "ORDER BY r.id LIMIT $limit",
                    namespace=self.settings.graph_namespace,
                    projections=projection_ids,
                    limit=5001,
                )
            )
        nodes, edges = {}, []
        truncated = len(rows) > 5000
        for row in rows[:5000]:
            values = [row["a"], row["b"]]
            additions = {value["id"] for value in values} - nodes.keys()
            if len(nodes) + len(additions) > max_nodes:
                truncated = True
                continue
            for value in values:
                nodes[value["id"]] = {key: value[key] for key in ["id", "kind", "title", "detail"]}
            edges.append(
                {
                    key: row["edge"][key]
                    for key in ["id", "source", "target", "label", "predicate", "evidence_id"]
                }
            )
        return sorted(nodes.values(), key=lambda value: value["id"]), edges, truncated
