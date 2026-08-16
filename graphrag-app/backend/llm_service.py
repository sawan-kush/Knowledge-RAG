import json
import re
from groq import Groq

from . import config

_client = Groq(api_key=config.GROQ_API_KEY)

CYPHER_SYSTEM_PROMPT = """You are a Neo4j Cypher expert. You translate a user's natural-language \
question into a single READ-ONLY Cypher query against the graph described below.

{schema}

RULES:
- Output ONLY valid JSON: {{"cypher": "<query>"}}. No prose, no markdown fences.
- The query MUST be read-only: never use CREATE, MERGE, DELETE, DETACH, SET, REMOVE, or DROP.
- Always RETURN full nodes and relationships (not just properties) so the caller can render \
a subgraph, e.g. `RETURN n, r, m` or `RETURN p` for a path — never `RETURN n.name`.
- Prefer returning whole paths (e.g. `MATCH p = (a)-[r]->(b) WHERE ... RETURN p`) when the \
question involves a relationship between things, since that keeps nodes and edges together.
- NEVER match names/titles/labels with exact equality (e.g. `{{name: 'Gandhi'}}` or \
`n.name = 'Gandhi'`). The user's wording rarely matches the stored value exactly (they may \
type a partial name, a nickname, wrong case, or extra/missing words). Instead, ALWAYS use \
case-insensitive partial matching, e.g.:
  `WHERE toLower(n.name) CONTAINS toLower('gandhi')`
  This applies to every property used to identify an entity by name — people, places, \
organizations, titles, etc. Only use exact equality for things that are genuinely exact \
identifiers by nature (numeric ids, codes, enums, dates).
- Add a reasonable `LIMIT` (e.g. 50) to avoid pulling back the entire graph.
- Only use labels, relationship types, and properties that appear in the schema above. \
Never invent them.
- If the question truly cannot be answered from this schema, return \
{{"cypher": "", "reason": "<short explanation>"}}.
"""

ANSWER_SYSTEM_PROMPT = """You answer the user's question using ONLY the graph data provided below \
(nodes and relationships retrieved from Neo4j). This is your sole source of truth.

- Be concise and direct.
- Ground every claim in the provided data; do not use outside knowledge.
- If the data is empty or doesn't actually answer the question, say so plainly and suggest \
rephrasing rather than guessing.
- Do not mention Cypher, JSON, or implementation details — just answer naturally, as if you \
already knew this from the knowledge graph.
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def generate_cypher(
    question: str,
    schema: str,
    prior_error: str | None = None,
    prior_empty_cypher: str | None = None,
) -> dict:
    """Returns {"cypher": str} or {"cypher": "", "reason": str}."""
    messages = [
        {"role": "system", "content": CYPHER_SYSTEM_PROMPT.format(schema=schema)},
        {"role": "user", "content": question},
    ]
    if prior_error:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Your previous query failed with this Neo4j error:\n{prior_error}\n"
                    "Fix the query and try again. Output JSON only."
                ),
            }
        )
    if prior_empty_cypher:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"This query ran successfully but returned zero results:\n{prior_empty_cypher}\n"
                    "Broaden it: double-check you used case-insensitive CONTAINS matching (not "
                    "exact equality) on any name/title property, consider alternate labels or "
                    "relationship directions from the schema, and try again. Output JSON only."
                ),
            }
        )

    resp = _client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=messages,
        temperature=0,
        max_tokens=500,
    )
    content = resp.choices[0].message.content
    try:
        return _extract_json(content)
    except Exception:
        return {"cypher": "", "reason": f"Could not parse model output: {content[:300]}"}


def generate_answer(question: str, rows: list, subgraph: dict) -> str:
    compact = {
        "nodes": [
            {"labels": n["labels"], "properties": n["properties"]} for n in subgraph["nodes"]
        ],
        "relationships": [
            {"type": e["type"], "properties": e["properties"]} for e in subgraph["edges"]
        ],
        "additional_rows": rows,
    }

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Question: {question}\n\nGraph data:\n{json.dumps(compact, default=str, indent=2)[:12000]}",
        },
    ]

    resp = _client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=700,
    )
    return resp.choices[0].message.content.strip()