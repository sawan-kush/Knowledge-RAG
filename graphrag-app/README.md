# Knowledge Graph RAG (vectorless / GraphRAG)

Ask a question → an LLM (Groq) writes a read-only Cypher query against your Neo4j AuraDB
knowledge graph → the retrieved subgraph is fed back to the LLM to write a grounded answer →
the UI shows the answer with a **source chip** you can click to open and explore the exact
subgraph that produced it.

No embeddings, no vector index — retrieval is done entirely through graph traversal (text-to-Cypher).

## How it works

```
question → [Groq: NL → Cypher] → Neo4j (read-only) → subgraph (nodes+edges)
                                                         │
                                                         ▼
                                        [Groq: subgraph → grounded answer]
                                                         │
                                                         ▼
                                    UI: answer + clickable "subgraph" source chip
                                                         │
                                                         ▼
                                   modal: vis-network graph, click any node/edge for its properties
```

On startup, the backend introspects your Neo4j schema (labels, relationship types, sample
properties, and known connectivity patterns) and includes it in every Cypher-generation prompt,
so the LLM only ever references labels/types/properties that actually exist in your graph.

Every generated query is checked against a denylist of write clauses (`CREATE`, `MERGE`,
`DELETE`, `SET`, `REMOVE`, `DROP`, `LOAD CSV`, etc.) before it's run — this app never
writes to your database. If a query errors or returns nothing usable, it's retried
(up to 3 attempts) with the error fed back to the model.

## Setup

```bash
cd graphrag-app
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env with your Neo4j Aura URI/password and your Groq API key
```

## Run

```bash
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000**. The status dot in the header shows whether it connected to
Neo4j — click it any time to force a schema refresh (useful after you add new
labels/relationships to the graph).

## Notes / tuning

- **Model**: default is `openai/gpt-oss-120b` on Groq (fast, strong at structured output).
  Change `GROQ_MODEL` in `.env` to try others (e.g. `qwen/qwen3.6-27b`, `moonshotai/kimi-k2-instruct`).
- **Row limits**: `MAX_ROWS` and query `LIMIT`s cap how much comes back per question, both for
  answer quality and so the subgraph view stays readable. Raise `MAX_ROWS` in `.env` if you need
  bigger result sets.
- **Node labels in the graph view**: the viewer labels each node using the first of
  `name` / `title` / `id` / `label` it finds on that node's properties, falling back to
  `<Label> (<short id>)`. If your nodes use a different key for their display name, add it
  to the `candidates` list in `frontend/app.js` (`labelFor`).
- **Multiple databases**: if your Aura instance has more than one database, set
  `NEO4J_DATABASE` accordingly.
- **Why text-to-Cypher instead of embeddings**: this keeps retrieval fully symbolic — every
  answer traces back to an actual, inspectable Cypher query and a real subgraph, rather than
  approximate nearest-neighbor chunks. Trade-off: it depends on the LLM writing correct Cypher
  for your schema, which is why schema introspection + the retry loop matter.

## Project layout

```
graphrag-app/
  backend/
    main.py            # FastAPI app, /api/ask, /api/schema, /api/subgraph/{id}
    graph_service.py    # Neo4j driver, schema introspection, safe query execution
    llm_service.py       # Groq calls: question->Cypher, subgraph->answer
    config.py             # env loading
  frontend/
    index.html
    style.css
    app.js               # chat UI + vis-network subgraph modal
  requirements.txt
  .env.example
```
