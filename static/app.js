let queryCount = 0;
const CAT_CLASS = { brand:'src-brand', ops:'src-ops', blog:'src-blog', persona:'src-persona', archive:'src-archive' };
const CAT_LABEL = { brand:'Brand & Voice', ops:'Content Operations', blog:'Blog Standards', persona:'Audience Personas', archive:'Content Archive' };
const CHUNK_COLORS = { brand:'#6B2737', ops:'#7A8C6E', blog:'#8B7355', persona:'#4A5568', archive:'#C4956A' };

function resize(el) { el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,130)+'px'; }
function handleKey(e) { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();} }
function esc(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function fmt(text) {
  return text.split('\n\n').map(p => {
    p = p.trim();
    if (!p) return '';
    p = p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const lines = p.split('\n').filter(l => l.trim());
    if (lines.length > 1 && lines[0].match(/^[\d\-\*]/)) {
      return '<ul>' + lines.map(l => `<li>${l.replace(/^\d+\.\s*/,'').replace(/^[\-\*]\s*/,'')}</li>`).join('') + '</ul>';
    }
    return `<p>${p.replace(/\n/g,'<br>')}</p>`;
  }).join('');
}

function activateLayers(categories) {
  ['brand','ops','blog','persona','archive'].forEach(cat => {
    const el = document.getElementById(`layer-${cat}`);
    if (categories.includes(cat)) el.classList.add('active');
    else el.classList.remove('active');
  });
}

function showChunks(chunks, scores) {
  document.getElementById('retrieval-empty').style.display = 'none';
  const container = document.getElementById('chunk-cards');
  container.innerHTML = '';
  chunks.forEach((id, i) => {
    const cat = id.split('-')[0];
    const score = scores[i] ? (scores[i]*100).toFixed(0)+'%' : '';
    const color = CHUNK_COLORS[cat] || '#4A5568';
    const card = document.createElement('div');
    card.className = 'chunk-card';
    card.style.borderLeftColor = 'rgba(247,242,234,0.3)';
    card.innerHTML = `
      <div class="chunk-header">
        <span class="chunk-id" style="color:rgba(247,242,234,0.9)">${id}</span>
        ${score ? `<span class="chunk-score">${score}</span>` : ''}
      </div>
      <div class="chunk-preview" style="color:rgba(247,242,234,0.8)" id="preview-${id}">Loading...</div>
    `;
    container.appendChild(card);
  });
}

function updatePreviews(chunks_data) {
  chunks_data.forEach(c => {
    const el = document.getElementById(`preview-${c.id}`);
    if (el) el.textContent = c.preview;
  });
}

function addMsg(role, text, categories) {
  document.getElementById('welcome-state').style.display = 'none';
  const chat = document.getElementById('chat');
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  const label = role==='user' ? 'You' : 'Studio Lou KB';
  let inner = role==='user' ? `<p>${esc(text)}</p>` : fmt(text);
  if (role==='assistant' && categories && categories.length) {
    const tags = categories.map(c => `<span class="src-tag ${CAT_CLASS[c]||''}">${CAT_LABEL[c]||c}</span>`).join('');
    inner += `<div class="msg-sources">${tags}</div>`;
  }
  wrap.innerHTML = `<div class="msg-role">${label}</div><div class="msg-bubble">${inner}</div>`;
  chat.appendChild(wrap);
  document.getElementById('chat-scroll').scrollTop = 99999;
}

function addLoading() {
  const chat = document.getElementById('chat');
  const wrap = document.createElement('div');
  wrap.className = 'msg assistant';
  wrap.id = 'loading-msg';
  wrap.innerHTML = '<div class="msg-role">Studio Lou KB</div><div class="loading-bubble"><span></span><span></span><span></span></div>';
  chat.appendChild(wrap);
  document.getElementById('chat-scroll').scrollTop = 99999;
}

async function send() {
  const input = document.getElementById('input');
  const btn = document.getElementById('btn');
  const query = input.value.trim();
  if (!query) return;
  input.value = ''; input.style.height = 'auto'; btn.disabled = true;
  addMsg('user', query);
  addLoading();
  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    const data = await res.json();
    document.getElementById('loading-msg')?.remove();
    queryCount++;
    document.getElementById('stat-queries').textContent = queryCount;
    activateLayers(data.categories);
    showChunks(data.chunks, data.scores);
    updatePreviews(data.chunks_data);
    addMsg('assistant', data.answer, data.categories);
  } catch(e) {
    document.getElementById('loading-msg')?.remove();
    addMsg('assistant', 'Error connecting to the server. Make sure app.py is running.');
  }
  btn.disabled = false; input.focus();
}

function prefill(btn) {
  const input = document.getElementById('input');
  input.value = btn.textContent;
  input.focus(); resize(input);
}