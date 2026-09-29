# SentinelGen

**A traceable GenAI pipeline for transforming one source into audience-ready content.**

## Live Demo

[Open SentinelGen](https://sentinelgen.onrender.com/)

## Problem Statement

> **PS 26154 — Gen AI Platform for Automated Content Transformation**  
> **Organization:** National Technical Research Organisation (NTRO)  
> **Category:** Software  
> **Theme:** Blockchain & Cybersecurity

Organizations such as NTRO routinely need to turn reports, articles, advisories, and other source material into multiple communication formats for different audiences. This work is often manual and time-consuming, can produce inconsistent results between formats, and does not provide a reliable way to verify which source and settings produced a published output.

## What This Solves

SentinelGen uses one structured understanding of the source to generate several configured outputs, rather than asking for each format independently. Each output is sealed with a SHA-256 provenance hash and stored in SQLite, making the transformation traceable and allowing the record to be verified after generation.

## Features

- Paste source text directly into the web interface.
- Upload a `.txt` or `.pdf` file and extract its text. Uploads are limited to 5 MB.
- Normalize the source with an LLM into key facts, entities, source tone, source type, and intent.
- Generate one or more of the following output types:
  - LinkedIn Post
  - Twitter / X Post
  - Advisory with `SUBJECT`, `SITUATION`, `RECOMMENDED ACTIONS`, and `URGENCY LEVEL` sections
- Configure the target audience, tone, language, and level of detail.
- Seal every generated output with hashes derived from the source, generation parameters, and output.
- Store provenance records in a local SQLite database.
- Verify a provenance record by its returned ID through the API.

## Architecture

The application follows this pipeline:

`Input → Normalization → Output Router → Format Generators → Provenance Log`

The browser accepts pasted or uploaded source content and sends it to the FastAPI backend. The backend calls the configured Groq-compatible LLM endpoint once to normalize the source, then routes the normalized understanding and selected parameters to a format-specific prompt for each requested output. Each result is hashed and appended to `provenance.db` before it is returned to the browser.

### Technology Stack

- **Python** with **FastAPI** for the HTTP API
- **Uvicorn** for the local ASGI server
- **Groq OpenAI-compatible Chat Completions API** via `requests`
- **Pydantic** through FastAPI request models
- **pdfplumber** for PDF text extraction
- **python-multipart** for file uploads
- **python-dotenv** for loading `GROQ_API_KEY` from a `.env` file
- **SQLite** for the provenance log
- **HTML, CSS, and browser JavaScript** for the frontend

## Setup & Installation

### Prerequisites

- Python 3.10 or newer
- A Groq API key with access to the configured model

### Install and run locally

From the `prototype` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the API key in the current PowerShell session:

```powershell
$env:GROQ_API_KEY = "your-groq-api-key"
```

Alternatively, create a `.env` file in `prototype` with:

```text
GROQ_API_KEY=your-groq-api-key
```

Start the server:

```powershell
python main.py
```

Open [http://localhost:8001](http://localhost:8001) in a browser. The server binds to `0.0.0.0` on port `8001`.

The default model is `openai/gpt-oss-20b`. It can be overridden with the optional `GROQ_MODEL` environment variable.

## API Endpoints

### `POST /api/extract-text`

Accepts a multipart upload in the `file` field. Supports `.txt` and `.pdf` files up to 5 MB and returns the extracted text as `{ "source_text": "..." }`.

### `POST /api/generate`

Accepts JSON containing `source_text`, a non-empty `output_types` list, and optional `audience`, `tone`, `language`, and `detail_level` values. It normalizes the source, generates the selected formats, seals each result, and returns the normalized data and generated results.

Supported output type values are `linkedin`, `twitter`, and `advisory`.

### `GET /api/verify/{record_id}`

Looks up a provenance record by ID and returns its output type, source hash, stored parameters, output hash, combined hash, and creation timestamp. Returns `404` when the ID is not found.

### `GET /`

Serves the frontend from `static/index.html`.

The application also mounts `/static` for frontend static assets.

## Usage Example

1. Start the server and open `http://localhost:8001`.
2. Paste an article, report, advisory, or other document text into **Source content**, or upload a `.txt`/`.pdf` file.
3. Select one or more output types: LinkedIn Post, Twitter / X Post, or Advisory.
4. Choose the audience, tone, language, and level of detail.
5. Select **Generate**. SentinelGen normalizes the source and generates the selected outputs through the live LLM integration.
6. Review each result. The interface displays a provenance ID and combined SHA-256 hash for every generated output.

## Deployment

This FastAPI application is suitable for deployment on Python-compatible services such as Render or Azure App Service. Configure `GROQ_API_KEY` and, if needed, `GROQ_MODEL` as environment variables in the platform dashboard. Do not commit or deploy a `.env` file containing secrets. The application currently uses a local SQLite file for provenance storage, so production deployments should account for the hosting platform's filesystem persistence model.

## Team / Hackathon

**Team:** [Coddy Blinders]  
Built for **Smart India Hackathon 2026**.
