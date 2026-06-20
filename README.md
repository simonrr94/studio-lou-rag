# Studio Lou RAG — Knowledge Base System

A custom retrieval-augmented generation (RAG) system built for [Studio Lou Interiors](https://www.studiolouinteriors.com), a Phoenix-based virtual interior design and marketing consultancy.

This system allows Studio Lou to query its own brand rules, content standards, audience strategy, and production history using natural language — retrieving semantically relevant context from a vector database before generating answers via Claude.

---

## What It Does

Instead of manually re-explaining brand voice, blog structure, and content operations at the start of every AI session, this RAG encodes that knowledge into a queryable vector store. Ask it anything about Studio Lou — it retrieves the most relevant context and generates a grounded, accurate response.

**Example queries:**
- "What are the hard voice rules for Studio Lou?"
- "How does the At a Glance table work in blog posts?"
- "Who is the primary audience for Month 3 content?"
- "What is the Pinterest pin description formula?"

---

## Architecture
**Stack:**
- **Vector database:** Pinecone (serverless, AWS us-east-1)
- **Embedding model:** OpenAI text-embedding-3-small (1536 dimensions, cosine similarity)
- **Generation model:** Anthropic Claude (claude-sonnet-4-6)
- **Backend:** Python + Flask
- **Frontend:** Vanilla JS + CSS, served via Flask static files

**Knowledge base:** 31 chunks across 5 layers:
- Brand & Voice (7 chunks) — tone rules, voice brief, visual system, platform registers
- Content Operations (6 chunks) — sprint model, posting cadence, scheduling tools, growth strategy
- Blog Standards (7 chunks) — post skeleton, At a Glance table, word counts, CTA format, linking rules
- Audience Personas (4 chunks) — homeowner, design firm, hidden hiring manager, startup founder
- Content Archive (7 chunks) — Lauren and Gavin's setup, Months 1–4 content history, tech infrastructure

---

## Setup

### Prerequisites
- Python 3.9+
- Pinecone account (free tier works)
- Anthropic API key
- OpenAI API key

### Install dependencies
```bash
pip install anthropic pinecone openai python-dotenv flask
```

### Environment variables
Create a `.env` file in the project root:
### Index the knowledge base
```bash
python3 setup_pinecone.py
```
This embeds all 31 chunks and upserts them to Pinecone. Only needs to run once (or when the knowledge base is updated).

### Run the web UI
```bash
python3 app.py
```
Open `http://127.0.0.1:5000` in your browser.

### Run in terminal mode
```bash
python3 query.py
```

---

## Project Structure
---

## Design Decisions

**Why RAG instead of full-document injection?** Injecting all Studio Lou docs into every prompt consumes the full context window and adds latency. Semantic retrieval pulls only the 5 most relevant chunks per query, keeping responses fast and cost-efficient.

**Why OpenAI embeddings + Anthropic generation?** OpenAI's text-embedding-3-small is the industry standard for RAG pipelines — high quality, low cost (~$0.00002/1K tokens). Claude handles generation because it produces more nuanced, on-brand responses for content strategy work.

**Why Flask?** Lightweight, no build step, runs locally without infrastructure. The goal was a working internal tool, not a production deployment.

---

## Built By

Lauren — founder of Studio Lou Interiors. Dual background in interior design and marketing; previously at West Elm, Visual Comfort, and Havenly.

[studiolouinteriors.com](https://www.studiolouinteriors.com) · [LinkedIn](https://www.linkedin.com/company/studio-lou-interiors/)
