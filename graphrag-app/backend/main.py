import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config
from .graph_service import GraphService, CypherSafetyError
from . import llm_service

app = FastAPI(title="Vectorless GraphRAG")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

graph_service: GraphService | None = None

# In-memory store so a subgraph can be re-fetched by id when the user clicks
# "view subgraph" (avoids re-sending the whole graph payload on every message).
_subgraph_store: dict[str, dict] = {}

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.on_event("startup")
def startup():
    global graph_service
    graph_service = GraphService()
    try:
        graph_service.verify_connectivity()
        print("[startup] Connected to Neo4j.")
    except Exception as e:
        print(f"[startup] WARNING: could not connect to Neo4j: {e}")


@app.on_event("shutdown")
def shutdown():
    if graph_service:
        graph_service.close()


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    cypher: str
    subgraph_id: str
    node_count: int
    edge_count: int
    row_count: int


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/schema")
def get_schema(refresh: bool = False):
    try:
        schema = graph_service.get_schema_text(force_refresh=refresh)
        return {"schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schema introspection failed: {e}")


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    schema = graph_service.get_schema_text()

    cypher = ""
    rows, subgraph = [], {"nodes": [], "edges": []}
    last_error = None
    last_empty_cypher = None
    MAX_ATTEMPTS = 3

    for attempt in range(MAX_ATTEMPTS):
        gen = llm_service.generate_cypher(
            req.question, schema, prior_error=last_error, prior_empty_cypher=last_empty_cypher
        )
        cypher = gen.get("cypher", "")

        if not cypher:
            reason = gen.get("reason", "The question could not be mapped to the graph schema.")
            return AskResponse(
                answer=f"I can't answer that from the knowledge graph: {reason}",
                cypher="",
                subgraph_id="",
                node_count=0,
                edge_count=0,
                row_count=0,
            )

        try:
            rows, subgraph = graph_service.run_read_query(cypher)
        except CypherSafetyError as e:
            # Don't retry safety violations — surface immediately.
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            last_error, last_empty_cypher = str(e), None
            continue

        last_error = None
        if not subgraph["nodes"] and not rows:
            last_empty_cypher = cypher
            continue  # try a broader query
        last_empty_cypher = None
        break

    if last_error:
        raise HTTPException(
            status_code=502,
            detail=f"Query failed after {MAX_ATTEMPTS} attempts. Last error: {last_error}",
        )

    if not subgraph["nodes"] and not rows:
        answer = (
            "I tried a few different queries but couldn't find anything in the graph matching "
            "that question. Try rephrasing it, or check the exact names/terms used in your data."
        )
    else:
        answer = llm_service.generate_answer(req.question, rows, subgraph)

    subgraph_id = str(uuid.uuid4())
    _subgraph_store[subgraph_id] = {
        "cypher": cypher,
        "question": req.question,
        "subgraph": subgraph,
        "rows": rows,
    }

    return AskResponse(
        answer=answer,
        cypher=cypher,
        subgraph_id=subgraph_id,
        node_count=len(subgraph["nodes"]),
        edge_count=len(subgraph["edges"]),
        row_count=len(rows),
    )


@app.get("/api/subgraph/{subgraph_id}")
def get_subgraph(subgraph_id: str):
    data = _subgraph_store.get(subgraph_id)
    if not data:
        raise HTTPException(status_code=404, detail="Subgraph not found (server may have restarted).")
    return data


# --- Static frontend ---
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))