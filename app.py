import os
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
import anthropic
from flask import Flask, request, jsonify, render_template_string, send_from_directory

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))

app = Flask(__name__, static_folder="static")

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOU. — Knowledge Base</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,700;1,400&family=Crimson+Pro:ital,wght@0,400;0,600;1,400;1,600&display=swap');

:root {
  --burgundy: #6B2737;
  --burgundy-hover: #7D3042;
  --burgundy-pale: rgba(107,39,55,0.07);
  --linen: #F7F2EA;
  --linen-dark: #EDE6D6;
  --cream: #FDFAF5;
  --sage: #7A8C6E;
  --sage-light: #A8B89A;
  --sage-pale: rgba(122,140,110,0.1);
  --sage-green: #D7E8BC;
  --warm-brown: #8B7355;
  --warm-brown-pale: rgba(139,115,85,0.08);
  --slate: #4A5568;
  --slate-light: #718096;
  --ink: #1C1C1C;
  --border: #E0D8CA;
  --border-light: #EDE6D6;
  --cat-brand: #6B2737;
  --cat-ops: #7A8C6E;
  --cat-blog: #8B7355;
  --cat-persona: #4A5568;
  --cat-archive: #C4956A;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'DM Sans', sans-serif;
  background-color: #F7F2EA;
  background-image: url('/static/kraft.jpg');
  background-repeat: repeat;
  background-size: 600px 600px;
  color: var(--ink);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100vh;
}

body::before {
  content: '';
  position: fixed;
  inset: 0;
  background: rgba(247,242,234,0.80);
  pointer-events: none;
  z-index: 0;
}

nav {
  background: rgba(253,250,245,0.96);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 58px;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
}

.nav-left { display: flex; align-items: center; gap: 14px; }

.nav-logo {
  height: 28px;
  width: auto;
  object-fit: contain;
}

.nav-divider { width: 1px; height: 16px; background: var(--border); }

.nav-title {
  font-family: 'Crimson Pro', serif;
  font-style: italic;
  font-size: 15px;
  color: var(--slate-light);
}

.nav-badge {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--sage);
  background: var(--sage-green);
  border: 1px solid rgba(122,140,110,0.3);
  padding: 4px 12px;
  border-radius: 20px;
}

.layout {
  display: grid;
  grid-template-columns: 284px 1fr;
  flex: 1;
  min-height: 0;
  position: relative;
  z-index: 1;
}

.sidebar {
  background-color: #6B2737;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.sidebar::before { display: none; }

.sidebar > * { position: relative; z-index: 1; }

.sidebar-top {
  padding: 22px 20px 18px;
  border-bottom: 1px solid rgba(224,216,202,0.8);
}

.sidebar-eyebrow {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(215,232,188,0.8);
  margin-bottom: 8px;
}

.sidebar-headline {
  font-family: 'Crimson Pro', serif;
  font-size: 19px;
  font-weight: 600;
  color: #F7F2EA;
  line-height: 1.25;
  margin-bottom: 8px;
}

.sidebar-desc {
  font-size: 11.5px;
  color: rgba(247,242,234,0.6);
  line-height: 1.65;
}

.layers-section {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(224,216,202,0.8);
}

.section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--slate-light);
  margin-bottom: 10px;
}

.layer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 8px;
  margin-bottom: 3px;
  transition: background 0.2s;
}

.layer.active { background: rgba(255,255,255,0.12); }

.layer-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  opacity: 0.3;
  transition: opacity 0.3s, transform 0.3s;
}

.layer.active .layer-dot { opacity: 1; transform: scale(1.3); }
.layer-name { font-size: 12px; font-weight: 500; color: rgba(247,242,234,0.85); flex: 1; }
.layer-count { font-size: 10px; color: rgba(247,242,234,0.45); font-weight: 600; }

.dot-brand { background: var(--cat-brand); }
.dot-ops { background: var(--cat-ops); }
.dot-blog { background: var(--cat-blog); }
.dot-persona { background: var(--cat-persona); }
.dot-archive { background: var(--cat-archive); }

.retrieval-section {
  padding: 16px 20px;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.retrieval-empty {
  font-size: 12px;
  color: var(--slate-light);
  font-style: italic;
  line-height: 1.65;
}

.chunk-card {
  background: rgba(255,255,255,0.12);
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  animation: slideIn 0.2s ease;
  backdrop-filter: blur(4px);
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}

.chunk-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
}

.chunk-id {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.chunk-score {
  font-size: 10px;
  font-weight: 700;
  color: #5A7A4E;
  background: var(--sage-green);
  padding: 2px 7px;
  border-radius: 10px;
}

.chunk-preview {
  font-size: 11px;
  color: var(--slate);
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.stats-section {
  padding: 14px 20px;
  border-top: 1px solid rgba(224,216,202,0.8);
  display: flex;
  gap: 20px;
}

.stat { display: flex; flex-direction: column; gap: 2px; }
.stat-value { font-size: 18px; font-weight: 700; color: #F7F2EA; }
.stat-label { font-size: 10px; color: var(--slate-light); letter-spacing: 0.06em; text-transform: uppercase; }

.main { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  scroll-behavior: smooth;
}

.welcome-state { max-width: 580px; }

.accent-bar {
  width: 36px;
  height: 3px;
  background: var(--sage-green);
  border-radius: 2px;
  margin-bottom: 16px;
}

.welcome-state h2 {
  font-family: 'Crimson Pro', serif;
  font-size: 30px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 12px;
  line-height: 1.2;
}

.welcome-state p {
  font-size: 13.5px;
  color: var(--slate);
  line-height: 1.75;
  margin-bottom: 24px;
}

.chips-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--slate-light);
  margin-bottom: 10px;
}

.chips { display: flex; flex-wrap: wrap; gap: 8px; }

.chip {
  font-family: 'DM Sans', sans-serif;
  font-size: 12px;
  color: var(--slate);
  background: rgba(253,250,245,0.88);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 7px 15px;
  cursor: pointer;
  transition: all 0.15s;
  backdrop-filter: blur(4px);
}

.chip:hover {
  border-color: var(--burgundy);
  color: var(--burgundy);
  background: var(--burgundy-pale);
}

.msg { display: flex; flex-direction: column; gap: 5px; }
.msg.user { align-items: flex-end; }
.msg.assistant { align-items: flex-start; }

.msg-role {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--slate-light);
  padding: 0 6px;
}

.msg-bubble {
  border-radius: 14px;
  padding: 14px 20px;
  font-size: 13.5px;
  line-height: 1.8;
  max-width: 620px;
}

.msg.user .msg-bubble {
  background: var(--burgundy);
  color: #F7F2EA;
  border-radius: 14px 4px 14px 14px;
}

.msg.assistant .msg-bubble {
  background: rgba(253,250,245,0.93);
  color: var(--ink);
  border: 1px solid var(--border);
  border-radius: 4px 14px 14px 14px;
  backdrop-filter: blur(10px);
}

.msg-bubble p { margin-bottom: 10px; }
.msg-bubble p:last-child { margin-bottom: 0; }
.msg-bubble strong { color: var(--burgundy); font-weight: 700; }
.msg-bubble ul { margin: 8px 0 10px 18px; }
.msg-bubble li { margin-bottom: 5px; font-size: 13px; line-height: 1.6; }

.msg-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.src-tag {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 20px;
  border: 1px solid;
}

.src-brand { color: var(--cat-brand); border-color: var(--cat-brand); background: var(--burgundy-pale); }
.src-ops { color: var(--cat-ops); border-color: var(--cat-ops); background: var(--sage-pale); }
.src-blog { color: var(--cat-blog); border-color: var(--cat-blog); background: var(--warm-brown-pale); }
.src-persona { color: var(--cat-persona); border-color: var(--cat-persona); background: rgba(74,85,104,0.06); }
.src-archive { color: var(--cat-archive); border-color: var(--cat-archive); background: rgba(196,149,106,0.06); }

.loading-bubble {
  background: rgba(253,250,245,0.92);
  border: 1px solid var(--border);
  border-radius: 4px 14px 14px 14px;
  padding: 16px 20px;
  display: flex;
  gap: 6px;
  align-items: center;
  backdrop-filter: blur(8px);
}

.loading-bubble span {
  width: 7px; height: 7px;
  background: var(--sage-light);
  border-radius: 50%;
  animation: bounce 1.2s infinite;
}
.loading-bubble span:nth-child(2) { animation-delay: 0.2s; }
.loading-bubble span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%,80%,100% { transform: translateY(0); }
  40% { transform: translateY(-7px); }
}

.input-area {
  border-top: 1px solid var(--border);
  background: rgba(253,250,245,0.95);
  backdrop-filter: blur(12px);
  padding: 14px 40px 20px;
  flex-shrink: 0;
}

.input-row { display: flex; gap: 10px; align-items: flex-end; }

textarea {
  flex: 1;
  font-family: 'DM Sans', sans-serif;
  font-size: 13.5px;
  padding: 12px 16px;
  border: 1.5px solid var(--border);
  border-radius: 12px;
  background: rgba(247,242,234,0.85);
  color: var(--ink);
  resize: none;
  min-height: 48px;
  max-height: 130px;
  outline: none;
  line-height: 1.5;
  transition: border-color 0.15s;
}

textarea:focus { border-color: var(--burgundy); }
textarea::placeholder { color: var(--slate-light); }

.send-btn {
  background: var(--burgundy);
  color: #F7F2EA;
  border: none;
  border-radius: 12px;
  width: 48px;
  height: 48px;
  cursor: pointer;
  font-size: 18px;
  flex-shrink: 0;
  transition: background 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.send-btn:hover { background: var(--burgundy-hover); }
.send-btn:disabled { background: var(--border); cursor: not-allowed; }
.hint { font-size: 11px; color: var(--slate-light); text-align: center; margin-top: 8px; }
</style>
</head>
<body>

<nav>
  <div class="nav-left">
    <img src="/static/logo.png" alt="Studio Lou" class="nav-logo">
    <div class="nav-divider"></div>
    <span class="nav-title">Knowledge Base</span>
  </div>
  <span class="nav-badge">Internal Tool</span>
</nav>

<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="sidebar-eyebrow">Studio Lou Interiors</div>
      <div class="sidebar-headline">What do you need to know?</div>
      <div class="sidebar-desc">Semantic search across five knowledge layers. Powered by Pinecone + Claude.</div>
    </div>

    <div class="layers-section">
      <div class="section-label">Knowledge Layers</div>
      <div class="layer" id="layer-brand">
        <div class="layer-dot dot-brand"></div>
        <div class="layer-name">Brand &amp; Voice</div>
        <div class="layer-count">7</div>
      </div>
      <div class="layer" id="layer-ops">
        <div class="layer-dot dot-ops"></div>
        <div class="layer-name">Content Operations</div>
        <div class="layer-count">6</div>
      </div>
      <div class="layer" id="layer-blog">
        <div class="layer-dot dot-blog"></div>
        <div class="layer-name">Blog Standards</div>
        <div class="layer-count">7</div>
      </div>
      <div class="layer" id="layer-persona">
        <div class="layer-dot dot-persona"></div>
        <div class="layer-name">Audience Personas</div>
        <div class="layer-count">4</div>
      </div>
      <div class="layer" id="layer-archive">
        <div class="layer-dot dot-archive"></div>
        <div class="layer-name">Content Archive</div>
        <div class="layer-count">7</div>
      </div>
    </div>

    <div class="retrieval-section">
      <div class="section-label">Last Retrieved</div>
      <div class="retrieval-empty" id="retrieval-empty">Retrieved chunks will appear here after your first query.</div>
      <div id="chunk-cards"></div>
    </div>

    <div class="stats-section">
      <div class="stat">
        <div class="stat-value" id="stat-chunks">31</div>
        <div class="stat-label">Chunks</div>
      </div>
      <div class="stat">
        <div class="stat-value" id="stat-queries">0</div>
        <div class="stat-label">Queries</div>
      </div>
      <div class="stat">
        <div class="stat-value">5</div>
        <div class="stat-label">Layers</div>
      </div>
    </div>
  </aside>

  <main class="main">
    <div class="chat-scroll" id="chat-scroll">
      <div class="welcome-state" id="welcome-state">
        <div class="accent-bar"></div>
        <h2>Ask anything about Studio Lou.</h2>
        <p>This knowledge base retrieves the most relevant context from your Pinecone vector index before generating an answer — so every response is grounded in your actual brand rules, not generic advice.</p>
        <div class="chips-label">Try asking</div>
        <div class="chips">
          <button class="chip" onclick="prefill(this)">What are the hard voice rules?</button>
          <button class="chip" onclick="prefill(this)">How does the At a Glance table work?</button>
          <button class="chip" onclick="prefill(this)">What's the Pinterest pin formula?</button>
          <button class="chip" onclick="prefill(this)">Who is the Month 3 audience?</button>
          <button class="chip" onclick="prefill(this)">What is Gavin's work setup?</button>
          <button class="chip" onclick="prefill(this)">What carousel types does Studio Lou use?</button>
          <button class="chip" onclick="prefill(this)">What's the CTA format for blog posts?</button>
          <button class="chip" onclick="prefill(this)">Which platform drives the most traffic?</button>
        </div>
      </div>
      <div id="chat"></div>
    </div>

    <div class="input-area">
      <div class="input-row">
        <textarea id="input"
          placeholder="Ask about brand voice, blog structure, posting cadence, audience strategy…"
          rows="1"
          onkeydown="handleKey(event)"
          oninput="resize(this)"></textarea>
        <button class="send-btn" id="btn" onclick="send()">↑</button>
      </div>
      <div class="hint">Enter to send · Shift+Enter for new line</div>
    </div>
  </main>
</div>

<script src="/static/app.js"></script>
</body>
</html>
"""

def get_embedding(text):
    response = openai_client.embeddings.create(input=text, model="text-embedding-3-small")
    return response.data[0].embedding

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

@app.route("/ask", methods=["POST"])
def ask():
    query = request.json.get("query", "")
    embedding = get_embedding(query)
    results = index.query(vector=embedding, top_k=5, include_metadata=True)
    context = "\n\n---\n\n".join([m.metadata["text"] for m in results.matches])
    categories = list(set([m.metadata["category"] for m in results.matches]))
    chunk_ids = [m.id for m in results.matches]
    scores = [round(m.score, 3) for m in results.matches]
    chunks_data = [{"id": m.id, "preview": m.metadata["text"][:120] + "..."} for m in results.matches]
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system="""You are a Studio Lou Interiors knowledge assistant.
Answer questions using ONLY the retrieved context provided.
Be specific and actionable. If the context does not cover the question fully, say so.
Never invent facts not present in the context.""",
        messages=[{"role": "user", "content": f"Retrieved context:\n\n{context}\n\n---\n\nQuestion: {query}"}]
    )
    return jsonify({
        "answer": response.content[0].text,
        "categories": categories,
        "chunks": chunk_ids,
        "scores": scores,
        "chunks_data": chunks_data
    })

if __name__ == "__main__":
    print("Starting Studio Lou RAG server...")
    print("Open http://127.0.0.1:5000 in your browser")
    app.run(debug=True, port=5000)