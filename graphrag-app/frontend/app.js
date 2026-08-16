const feed = document.getElementById('feed');
const emptyState = document.getElementById('emptyState');
const form = document.getElementById('askForm');
const input = document.getElementById('questionInput');
const askBtn = document.getElementById('askBtn');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const statusWrap = document.getElementById('status');

const modalBackdrop = document.getElementById('modalBackdrop');
const modalTitle = document.getElementById('modalTitle');
const modalClose = document.getElementById('modalClose');
const networkEl = document.getElementById('network');
const cypherBox = document.getElementById('cypherBox');
const detailBox = document.getElementById('detailBox');

let network = null;

// ---------- Status check ----------
async function checkStatus() {
  statusText.textContent = 'checking…';
  statusDot.className = 'dot';
  try {
    const res = await fetch('/api/schema');
    if (!res.ok) throw new Error('schema failed');
    statusDot.classList.add('ok');
    statusText.textContent = 'connected to Neo4j';
  } catch (e) {
    statusDot.classList.add('bad');
    statusText.textContent = 'not connected — check .env';
  }
}
statusWrap.addEventListener('click', () => fetch('/api/schema?refresh=true').then(checkStatus));
checkStatus();

// ---------- Chat ----------
function addUserMessage(text) {
  emptyState.style.display = 'none';
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `<div class="bubble"></div>`;
  div.querySelector('.bubble').textContent = text;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

function addThinking() {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.id = 'thinkingMsg';
  div.innerHTML = `<div class="thinking"><span></span><span></span><span></span></div>`;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
  return div;
}

function addAssistantMessage({ answer, isError, subgraph_id, node_count, edge_count, cypher, question }) {
  const thinking = document.getElementById('thinkingMsg');
  if (thinking) thinking.remove();

  const div = document.createElement('div');
  div.className = 'msg assistant';

  const bubble = document.createElement('div');
  bubble.className = 'bubble' + (isError ? ' error' : '');
  bubble.textContent = answer;
  div.appendChild(bubble);

  if (!isError && subgraph_id && node_count > 0) {
    const chip = document.createElement('div');
    chip.className = 'source-chip';
    chip.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none"><circle cx="5" cy="6" r="2" fill="currentColor"/><circle cx="19" cy="6" r="2" fill="currentColor"/><circle cx="12" cy="18" r="2" fill="currentColor"/><line x1="6" y1="7" x2="11" y2="16" stroke="currentColor" stroke-width="1.2"/><line x1="18" y1="7" x2="13" y2="16" stroke="currentColor" stroke-width="1.2"/><line x1="7" y1="6" x2="17" y2="6" stroke="currentColor" stroke-width="1.2"/></svg>
      subgraph · ${node_count} node${node_count === 1 ? '' : 's'} · ${edge_count} edge${edge_count === 1 ? '' : 's'}
    `;
    chip.addEventListener('click', () => openSubgraph(subgraph_id, question));
    div.appendChild(chip);
  }

  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;

  addUserMessage(question);
  input.value = '';
  askBtn.disabled = true;
  addThinking();

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    if (!res.ok) {
      addAssistantMessage({ answer: data.detail || 'Something went wrong.', isError: true });
    } else {
      addAssistantMessage({ ...data, question, isError: false });
    }
  } catch (err) {
    addAssistantMessage({ answer: `Request failed: ${err.message}`, isError: true });
  } finally {
    askBtn.disabled = false;
    input.focus();
  }
});

// ---------- Subgraph modal ----------
async function openSubgraph(subgraphId, question) {
  modalTitle.textContent = question ? `Subgraph — “${question}”` : 'Subgraph';
  detailBox.innerHTML = '<span class="hint">Click a node or edge to inspect its properties.</span>';
  modalBackdrop.style.display = 'flex';

  const res = await fetch(`/api/subgraph/${subgraphId}`);
  if (!res.ok) {
    cypherBox.textContent = '(subgraph unavailable)';
    return;
  }
  const data = await res.json();
  cypherBox.textContent = data.cypher || '(no cypher recorded)';
  renderGraph(data.subgraph);
}

function labelFor(node) {
  const p = node.properties || {};
  const candidates = ['name', 'title', 'id', 'label'];
  for (const c of candidates) {
    if (p[c]) return String(p[c]);
  }
  const firstLabel = (node.labels && node.labels[0]) || 'Node';
  return `${firstLabel} (${node.id.slice(0, 6)})`;
}

const PALETTE = ['#7c8b6f', '#b5654a', '#c99a3c', '#5c6b7a', '#7a5c6b', '#3c6e5c'];
function colorForLabel(label) {
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

function renderGraph(subgraph) {
  const nodeMap = new Map();
  const visNodes = subgraph.nodes.map((n) => {
    nodeMap.set(n.id, n);
    const label = (n.labels && n.labels[0]) || '';
    const color = colorForLabel(label);
    return {
      id: n.id,
      label: labelFor(n),
      shape: 'dot',
      size: 14,
      color: { background: color, border: color, highlight: { background: color, border: '#221f1a' } },
      font: { color: '#221f1a', size: 12, face: 'Inter' },
    };
  });

  const edgeMap = new Map();
  const visEdges = subgraph.edges.map((e) => {
    edgeMap.set(e.id, e);
    return {
      id: e.id,
      from: e.source,
      to: e.target,
      label: e.type,
      arrows: 'to',
      color: { color: '#d8cdb4', highlight: '#221f1a' },
      font: { color: '#8c8474', size: 9, strokeWidth: 0, align: 'middle' },
      smooth: { type: 'continuous' },
    };
  });

  if (network) network.destroy();
  network = new vis.Network(
    networkEl,
    { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) },
    {
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -4000, springLength: 120 } },
      interaction: { hover: true },
    }
  );

  network.on('click', (params) => {
    if (params.nodes.length) {
      showDetail(nodeMap.get(params.nodes[0]), 'node');
    } else if (params.edges.length) {
      showDetail(edgeMap.get(params.edges[0]), 'edge');
    }
  });
}

function showDetail(item, kind) {
  if (!item) return;
  const title = kind === 'node' ? (item.labels || []).join(', ') || 'Node' : item.type;
  const props = item.properties || {};
  const rows = Object.entries(props)
    .map(([k, v]) => `<div class="prop-row"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v))}</span></div>`)
    .join('') || '<span class="hint">No properties.</span>';
  detailBox.innerHTML = `<div class="node-detail-title">${escapeHtml(title)}</div>${rows}`;
}

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

modalClose.addEventListener('click', () => (modalBackdrop.style.display = 'none'));
modalBackdrop.addEventListener('click', (e) => {
  if (e.target === modalBackdrop) modalBackdrop.style.display = 'none';
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') modalBackdrop.style.display = 'none';
});
