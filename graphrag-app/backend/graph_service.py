import re
from neo4j import GraphDatabase
from neo4j.graph import Node, Relationship

from . import config

# Clauses that would mutate the database. We only ever want READ access.
_WRITE_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+dbms\.|"
    r"CALL\s+apoc\.periodic\.|CALL\s+apoc\.create\.|CALL\s+apoc\.merge\.)\b",
    re.IGNORECASE,
)


class CypherSafetyError(Exception):
    pass


class GraphService:
    def __init__(self):
        self._driver = GraphDatabase.driver(
            config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )
        self._schema_cache = None

    def close(self):
        self._driver.close()

    def verify_connectivity(self):
        self._driver.verify_connectivity()

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------
    def get_schema_text(self, force_refresh: bool = False) -> str:
        if self._schema_cache is not None and not force_refresh:
            return self._schema_cache

        with self._driver.session(database=config.NEO4J_DATABASE) as session:
            labels = [r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label")]
            rel_types = [
                r["relationshipType"]
                for r in session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
                )
            ]

            # Sample property keys per node label
            label_props = {}
            for label in labels:
                q = f"MATCH (n:`{label}`) WITH n LIMIT 25 UNWIND keys(n) AS k RETURN DISTINCT k"
                keys = [r["k"] for r in session.run(q)]
                label_props[label] = keys

            # Sample property keys per relationship type
            rel_props = {}
            for rtype in rel_types:
                q = f"MATCH ()-[r:`{rtype}`]->() WITH r LIMIT 25 UNWIND keys(r) AS k RETURN DISTINCT k"
                keys = [r["k"] for r in session.run(q)]
                rel_props[rtype] = keys

            # Connectivity pattern: which labels does each rel type connect?
            connectivity = []
            try:
                result = session.run("CALL db.schema.visualization()")
                schema_nodes = {}
                for record in result:
                    for n in record.get("nodes", []):
                        schema_nodes[n.element_id] = list(n.labels)
                    for r in record.get("relationships", []):
                        start_labels = schema_nodes.get(r.start_node.element_id, ["?"])
                        end_labels = schema_nodes.get(r.end_node.element_id, ["?"])
                        connectivity.append(
                            f"(:{'|'.join(start_labels)})-[:{r.type}]->(:{'|'.join(end_labels)})"
                        )
            except Exception:
                pass  # db.schema.visualization() not available on this deployment; skip

        lines = ["NODE LABELS (with sample properties):"]
        for label in labels:
            props = ", ".join(label_props.get(label, [])) or "(no properties found)"
            lines.append(f"  (:{label}) {{{props}}}")

        lines.append("")
        lines.append("RELATIONSHIP TYPES (with sample properties):")
        for rtype in rel_types:
            props = ", ".join(rel_props.get(rtype, [])) or "(no properties)"
            lines.append(f"  [:{rtype}] {{{props}}}")

        if connectivity:
            lines.append("")
            lines.append("KNOWN CONNECTIVITY PATTERNS (label)-[relationship]->(label):")
            for c in sorted(set(connectivity)):
                lines.append(f"  {c}")

        schema_text = "\n".join(lines)
        self._schema_cache = schema_text
        return schema_text

    # ------------------------------------------------------------------
    # Safe query execution
    # ------------------------------------------------------------------
    @staticmethod
    def validate_read_only(cypher: str):
        if _WRITE_CLAUSES.search(cypher):
            raise CypherSafetyError(
                "Generated Cypher contains a write/mutating clause and was blocked. "
                "This tool only runs read queries."
            )
        if not re.search(r"\bRETURN\b", cypher, re.IGNORECASE):
            raise CypherSafetyError("Generated Cypher has no RETURN clause; nothing to retrieve.")

    def run_read_query(self, cypher: str, params: dict | None = None):
        """Executes a read-only cypher query and returns (rows, subgraph)."""
        self.validate_read_only(cypher)
        params = params or {}

        with self._driver.session(database=config.NEO4J_DATABASE) as session:
            result = session.run(cypher, params, timeout=config.QUERY_TIMEOUT_SECONDS)
            records = list(result)
            graph = result.graph()

        nodes = []
        for n in graph.nodes:
            nodes.append(
                {
                    "id": n.element_id,
                    "labels": list(n.labels),
                    "properties": dict(n.items()),
                }
            )

        edges = []
        for r in graph.relationships:
            edges.append(
                {
                    "id": r.element_id,
                    "type": r.type,
                    "source": r.start_node.element_id,
                    "target": r.end_node.element_id,
                    "properties": dict(r.items()),
                }
            )

        # Plain scalar rows (for values that aren't nodes/relationships, e.g. counts)
        rows = []
        for rec in records[: config.MAX_ROWS]:
            row = {}
            for key, value in rec.items():
                if isinstance(value, (Node, Relationship)):
                    continue  # already captured in the subgraph
                row[key] = _jsonable(value)
            if row:
                rows.append(row)

        return rows, {"nodes": nodes, "edges": edges}


def _jsonable(value):
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
