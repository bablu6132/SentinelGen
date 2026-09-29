"""
SentinelGen MVP backend — PS 26154 (Gen AI Platform for Automated Content Transformation)

Scope for this prototype:
  - Input: pasted English text (articles, reports, documents, advisories, etc.)
  - Outputs: LinkedIn Post, Twitter/X Post
  - Parameters: audience, tone, language, level of detail
  - Provenance: every generated output is hashed (source + params + output) and logged

Run:
  pip install -r requirements.txt --break-system-packages
  python main.py
  open http://localhost:8000
"""

import hashlib
import io
import json
import os
import sqlite3
import time
import uuid
from typing import List, Optional

import requests
import pdfplumber
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

DB_PATH = os.path.join(os.path.dirname(__file__), "provenance.db")

app = FastAPI(title="SentinelGen MVP")

MAX_UPLOAD_SIZE = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Storage: a tiny append-only provenance log (SQLite)
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS provenance (
            id TEXT PRIMARY KEY,
            output_type TEXT,
            source_hash TEXT,
            params TEXT,
            output_hash TEXT,
            combined_hash TEXT,
            created_at REAL
        )"""
    )
    conn.commit()
    conn.close()


init_db()


def seal(output_type: str, source_text: str, params: dict, output_text: str) -> dict:
    """Hash source + params + output, log it, return the provenance record."""
    source_hash = hashlib.sha256(source_text.encode()).hexdigest()
    output_hash = hashlib.sha256(output_text.encode()).hexdigest()
    payload = json.dumps(
        {"source_hash": source_hash, "params": params, "output_hash": output_hash},
        sort_keys=True,
    )
    combined_hash = hashlib.sha256(payload.encode()).hexdigest()
    record_id = str(uuid.uuid4())
    created_at = time.time()

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO provenance VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            record_id,
            output_type,
            source_hash,
            json.dumps(params),
            output_hash,
            combined_hash,
            created_at,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "id": record_id,
        "combined_hash": combined_hash,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# LLM call (Groq, OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------
def call_llm(prompt: str, temperature: float = 0.6) -> str:
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not set. Add it to your .env file.")

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"LLM call failed: {resp.text}")

    return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Normalization — understand the source once, before generating anything
# ---------------------------------------------------------------------------
def normalize(source_text: str) -> dict:
    prompt = f"""Read the following content and extract a structured summary.
Return ONLY valid JSON, no markdown fences, no commentary, with these keys:
- "facts": a list of the key factual points (3-6 items)
- "entities": a list of key people/organizations/places mentioned
- "tone": the dominant tone of the source (one or two words)
- "source_type": what kind of document this looks like (e.g. news article, report, advisory)
- "intent": one sentence on what the source is trying to communicate

Content:
\"\"\"{source_text}\"\"\"
"""
    raw = call_llm(prompt, temperature=0.2)
    # Be forgiving in case the model wraps JSON in a code fence anyway
    raw = raw.strip().strip("`")
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to a minimal structure rather than crashing the demo
        return {
            "facts": [source_text[:200]],
            "entities": [],
            "tone": "unknown",
            "source_type": "unspecified",
            "intent": "unspecified",
        }


# ---------------------------------------------------------------------------
# Custom prompt builder — every parameter combination gets its own prompt,
# built dynamically rather than hardcoded per combination.
# ---------------------------------------------------------------------------
FORMAT_RULES = {
    "linkedin": (
        "Write a single professional LinkedIn post. Use short paragraphs, "
        "a strong opening line, and end with a light call-to-reflection or "
        "call-to-action. No hashtag spam — at most 3 relevant hashtags at the end."
    ),
    "twitter": (
        "Write it as a tweet, or a numbered tweet thread (2-5 tweets) if the "
        "level of detail requires it. Each tweet must stay under 280 characters. "
        "Number tweets like 1/, 2/, 3/ if it's a thread."
    ),
    "advisory": (
        "Write it as a formal structured advisory document with these exact section headers, each on its own line: 'SUBJECT:', 'SITUATION:', "
        "'RECOMMENDED ACTIONS:', and 'URGENCY LEVEL:'. Under RECOMMENDED ACTIONS, "
        "use a short numbered list of concrete, actionable steps — no vague advice. "
        "Under URGENCY LEVEL, state one word (Low / Medium / High / Critical) plus "
        "one sentence justifying it based on the source content. Keep the whole "
        "advisory tight and scannable — this will be read under time pressure."
    ),
}


def build_prompt(output_type: str, normalized: dict, params: dict) -> str:
    audience = params.get("audience", "general public")
    tone = params.get("tone", "neutral")
    language = params.get("language", "English")
    detail = params.get("detail_level", "medium")

    facts = "; ".join(normalized.get("facts", []))
    entities = ", ".join(normalized.get("entities", []))

    return f"""You are generating a {output_type.upper()} post from the source content below.

SOURCE UNDERSTANDING:
- Key facts: {facts}
- Entities: {entities}
- Original tone: {normalized.get('tone')}
- Intent: {normalized.get('intent')}

GENERATION PARAMETERS (apply all of these):
- Target audience: {audience}
- Desired tone: {tone}
- Language: {language}
- Level of detail: {detail} (low = one punchy idea only, medium = 2-3 supporting points, high = full context and nuance)

FORMAT RULES:
{FORMAT_RULES[output_type]}

Write ONLY the final post text, ready to publish. No preamble, no explanation, no markdown headers.
"""


# ---------------------------------------------------------------------------
# API schema
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    source_text: str
    output_types: List[str]  # subset of ["linkedin", "twitter"]
    audience: Optional[str] = "general public"
    tone: Optional[str] = "neutral"
    language: Optional[str] = "English"
    detail_level: Optional[str] = "medium"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.post("/api/extract-text")
async def extract_text(file: UploadFile = File(...)):
    filename = file.filename or ""
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {".txt", ".pdf"}:
        raise HTTPException(400, "Unsupported file type. Please upload a .txt or .pdf file.")

    file_bytes = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "File is too large. Maximum accepted size is 5 MB.")

    if extension == ".txt":
        try:
            source_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "Could not decode the uploaded text file as UTF-8.") from exc
    else:
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                source_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as exc:
            raise HTTPException(400, "Could not read the uploaded PDF file.") from exc

    return {"source_text": source_text}


@app.post("/api/generate")
def generate(req: GenerateRequest):
    if not req.source_text.strip():
        raise HTTPException(400, "source_text is empty")
    if not req.output_types:
        raise HTTPException(400, "select at least one output type")

    normalized = normalize(req.source_text)
    params = {
        "audience": req.audience,
        "tone": req.tone,
        "language": req.language,
        "detail_level": req.detail_level,
    }

    results = []
    for output_type in req.output_types:
        if output_type not in FORMAT_RULES:
            continue
        prompt = build_prompt(output_type, normalized, params)
        output_text = call_llm(prompt)
        provenance = seal(output_type, req.source_text, params, output_text)
        results.append(
            {
                "output_type": output_type,
                "content": output_text,
                "provenance": provenance,
            }
        )

    return {"normalized": normalized, "results": results}


@app.get("/api/verify/{record_id}")
def verify(record_id: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT * FROM provenance WHERE id = ?", (record_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "No provenance record found for that id")
    keys = ["id", "output_type", "source_hash", "params", "output_hash", "combined_hash", "created_at"]
    return dict(zip(keys, row))


# ---------------------------------------------------------------------------
# Serve the frontend
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
