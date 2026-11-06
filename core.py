import os, re, json, hashlib, fitz, requests
import database
import time
from google.genai import errors
from dotenv import load_dotenv
from neo4j import GraphDatabase
load_dotenv()
E = os.getenv
driver = GraphDatabase.driver(E("NEO4J_URI"), auth=(E("NEO4J_USER"), E("NEO4J_PASSWORD")))
_embedder = None


class FastEmbedAdapter:
    def __init__(self):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

    def embed_query(self, text):
        vector = next(
            self.model.embed(
                [text],
                batch_size=1,
                parallel=None
            )
        )
        return vector.tolist()


def get_embedder():
    global _embedder

    if _embedder is None:
        _embedder = FastEmbedAdapter()

    return _embedder
DIM = 384  # all-MiniLM-L6-v2
IDX = "chunk_index"

def setup():
    from neo4j_graphrag.indexes import create_vector_index

    driver.execute_query("CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE")
    driver.execute_query("CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")
    create_vector_index(
        driver,
        IDX,
        label="Chunk",
        embedding_property="embedding",
        dimensions=DIM,
        similarity_fn="cosine"
    )

# ---------- LLM (Google Gemini API) ----------

from google import genai
from google.genai import types

def llm(system, user):
    api_key = E("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from your .env file")

    client = genai.Client(api_key=api_key)

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=E("LLM_MODEL", "gemini-flash-lite-latest"),
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.2,
                ),
            )

            if not response.text:
                raise RuntimeError("Gemini returned an empty response.")

            return response.text

        except errors.ServerError:
            if attempt == 2:
                raise

            time.sleep(2 ** (attempt + 1))


# ---------- PDF -> chunks (PyMuPDF) ----------
def pdf_chunks(path, size=900, overlap=150):
    doc, chunks = fitz.open(path), []
    title = (doc.metadata.get("title") or "").strip()
    for pno, page in enumerate(doc, 1):
        t = re.sub(r"\s+", " ", page.get_text())
        for i in range(0, len(t), size - overlap):
            if len(t[i:i + size]) > 80: chunks.append((pno, t[i:i + size]))
    first = chunks[0][1] if chunks else ""
    return (title or first[:80]), chunks

def extract_concepts(text):
    out = llm(
        "Return ONLY a JSON list of 8-12 short, lowercase technical concepts "
        "(methods, tasks, techniques, datasets) central to this paper. Use canonical names.",
        text[:3500]
    )

    try:
        match = re.search(r"\[.*\]", out, re.S)

        if not match:
            return []

        return [
            c.strip().lower()
            for c in json.loads(match.group())
        ][:12]

    except (json.JSONDecodeError, AttributeError):
        return []

def ingest(path, name, user_id):
    import uuid

    pid = str(uuid.uuid4())
    print("[INGEST] Starting PDF extraction", flush=True)

    title, chunks = pdf_chunks(path)
    print(f"[INGEST] PDF extracted: {len(chunks)} chunks", flush=True)
    print("[INGEST] Starting Gemini concept extraction", flush=True)

    concepts = extract_concepts(
        " ".join(c for _, c in chunks[:4])
    )
    print(f"[INGEST] Concepts extracted: {len(concepts)}", flush=True)
    print("[INGEST] Starting embedding generation", flush=True)
    driver.execute_query(
        "MERGE (p:Paper {id:$id}) "
        "SET p.title=$t, p.file=$f, p.user_id=$uid",
        id=pid,
        t=title,
        f=name,
        uid=user_id
    )

    for n, (page, text) in enumerate(chunks):
        if n == 0 or (n + 1) % 10 == 0:
            print(f"[INGEST] Processing chunk {n + 1}/{len(chunks)}", flush=True)
        driver.execute_query(
            "MATCH (p:Paper {id:$pid, user_id:$uid}) "
            "MERGE (c:Chunk {id:$cid}) "
            "SET c.text=$text, c.page=$page, "
            "c.embedding=$emb, c.user_id=$uid "
            "MERGE (p)-[:HAS_CHUNK]->(c)",
            pid=pid,
            uid=user_id,
            cid=f"{pid}-{n}",
            text=text,
            page=page,
            emb=get_embedder().embed_query(text)
        )

        print("[INGEST] All embeddings stored", flush=True)


    for c in concepts:
        driver.execute_query(
            "MATCH (p:Paper {id:$pid, user_id:$uid}) "
            "MERGE (k:Concept {name:$c}) "
            "MERGE (p)-[:DISCUSSES]->(k) "
            "WITH k, p "
            "MATCH (p)-[:HAS_CHUNK]->(ch) "
            "WHERE toLower(ch.text) CONTAINS k.name "
            "MERGE (ch)-[:MENTIONS]->(k)",
            pid=pid,
            uid=user_id,
            c=c
        )

    return {
        "id": pid,
        "title": title,
        "concepts": concepts,
        "chunks": len(chunks)
    }

def fmt(rec):
    from neo4j_graphrag.types import RetrieverResultItem

    return RetrieverResultItem(
        content=rec["text"],
        metadata=dict(rec)
    )


RQ = """
MATCH (c:Chunk)
MATCH (p:Paper)-[:HAS_CHUNK]->(c)
WHERE c.embedding IS NOT NULL
  AND p.user_id = $user_id
  AND ($ids = [] OR p.id IN $ids)
RETURN
    c.text AS text,
    c.page AS page,
    p.title AS paper,
    p.id AS paper_id,
    [(p)-[:DISCUSSES]->(k:Concept) | k.name] AS concepts
"""


_retriever = None

def get_retriever():
    global _retriever

    if _retriever is None:
        from neo4j_graphrag.retrievers import VectorCypherRetriever

        _retriever = VectorCypherRetriever(
            driver,
            IDX,
            RQ,
            embedder=get_embedder(),
            result_formatter=fmt
        )

    return _retriever


def retrieve(q, user_id, ids=(), k=6):
    retriever = get_retriever()

    res = retriever.search(
        query_text=q,
        top_k=k * 4 if ids else k,
        query_params={
            "user_id": user_id,
            "ids": list(ids)
        }
    )

    return [dict(i.metadata) for i in res.items][:k]


def ctx(rows):
    return "\n\n".join(f"[{r['paper']}, p.{r['page']}] (concepts: {', '.join(r['concepts'])})\n{r['text']}" for r in rows)

SYS = {
 "extract": "Extract the exact information requested (numbers, datasets, hyperparameters, definitions). Quote briefly, cite [paper, page]. If absent say 'Not found in the papers'.",
 "qa": "Answer using ONLY the context. Cite as [paper, page]. If the context is insufficient, say so.",
 "summarize": "Summarize the paper: problem, method, key results, limitations. Use short sections.",
}
def answer(q, user_id, mode="qa", ids=()):
    rows = retrieve(q, user_id, ids)

    return {
        "answer": llm(
            SYS[mode],
            f"Context:\n{ctx(rows)}\n\nQuestion: {q}"
        ),
        "sources": [
            {"paper": r["paper"], "page": r["page"]}
            for r in rows
        ]
    }
def summarize(pid, user_id):
    rows = driver.execute_query(
        """
        MATCH (p:Paper {id:$i, user_id:$uid})-[:HAS_CHUNK]->(c:Chunk)
        RETURN c.text AS t
        ORDER BY c.page, c.id
        LIMIT 12
        """,
        i=pid,
        uid=user_id
    ).records

    if not rows:
        return "Paper not found in your research library."

    return llm(
        SYS["summarize"],
        "\n".join(r["t"] for r in rows)[:9000]
    )
def delete_paper(pid, user_id):
    # Delete only the selected user's paper and its chunks.
    driver.execute_query(
        """
        MATCH (p:Paper {id:$pid, user_id:$uid})
        OPTIONAL MATCH (p)-[:HAS_CHUNK]->(c:Chunk)
        DETACH DELETE p, c
        """,
        pid=pid,
        uid=user_id
    )

    # Remove concepts only when no relationships remain.
    driver.execute_query(
        """
        MATCH (k:Concept)
        WHERE NOT (k)--()
        DELETE k
        """
    )
def compare(a, b, user_id, aspect="main methods and findings"):

    # Verify that both papers belong to this user
    records = driver.execute_query(
        """
        MATCH (p:Paper)
        WHERE p.id IN $ids AND p.user_id = $uid
        RETURN p.id AS id
        """,
        ids=[a, b],
        uid=user_id
    ).records

    owned_ids = {r["id"] for r in records}

    if a not in owned_ids or b not in owned_ids:
        return {
            "shared_concepts": [],
            "comparison": "One or both papers were not found in your library."
        }

    shared = [
        r["n"] for r in driver.execute_query(
            """
            MATCH (pa:Paper {id:$a, user_id:$uid})-[:DISCUSSES]->(k:Concept)
                  <-[:DISCUSSES]-(pb:Paper {id:$b, user_id:$uid})
            RETURN k.name AS n
            """,
            a=a,
            b=b,
            uid=user_id
        ).records
    ]

    ra = retrieve(aspect, user_id, [a], 4)
    rb = retrieve(aspect, user_id, [b], 4)

    prompt = (
        f"Shared concepts found in the knowledge graph: {shared or 'none'}\n\n"
        f"PAPER A context:\n{ctx(ra)}\n\n"
        f"PAPER B context:\n{ctx(rb)}\n\n"
        f"Aspect: {aspect}"
    )

    return {
        "shared_concepts": shared,
        "comparison": llm(
            "Compare Paper A and Paper B. Explain similarities, differences, "
            "strengths and weaknesses. Cite [paper, page].",
            prompt
        )
    }
def graph(user_id, limit=400):
    recs = driver.execute_query(
        """
        MATCH (p:Paper {user_id: $uid})-[:DISCUSSES]->(k:Concept)
        RETURN p.id AS pid, p.title AS pt, k.name AS k
        LIMIT $l
        """,
        uid=user_id,
        l=limit
    ).records

    nodes, edges = {}, []

    for r in recs:
        nodes[r["pid"]] = {
            "data": {
                "id": r["pid"],
                "label": r["pt"][:40],
                "type": "paper"
            }
        }

        nodes["c:" + r["k"]] = {
            "data": {
                "id": "c:" + r["k"],
                "label": r["k"],
                "type": "concept"
            }
        }

        edges.append({
            "data": {
                "source": r["pid"],
                "target": "c:" + r["k"]
            }
        })

    return list(nodes.values()) + edges
def papers(user_id):
    db = database.get_db()

    rows = db.execute(
        """
        SELECT
            neo4j_id AS id,
            title,
            filename,
            uploaded_at
        FROM papers
        WHERE user_id = ?
        ORDER BY uploaded_at DESC
        """,
        (user_id,)
    ).fetchall()

    return [dict(row) for row in rows]

