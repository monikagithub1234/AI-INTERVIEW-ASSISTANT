const DEFAULT_BACKEND = "http://127.0.0.1:5000";

function getBackendUrl() {
  return localStorage.getItem("backend_url") || DEFAULT_BACKEND;
}

function getSessionIdFromUrl() {
  const u = new URL(window.location.href);
  return u.searchParams.get("session_id") || sessionStorage.getItem("session_id") || "";
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed: ${res.status}`);
  return data;
}

function scoreClass(score) {
  if (score >= 8) return "ok";
  if (score >= 5) return "mid";
  return "bad";
}

function escapeText(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

function render(report) {
  document.getElementById("meta").textContent = `${report.role} • answered ${report.answered}/${report.questions_total} • session ${report.session_id}`;

  document.getElementById("totalScore").textContent = `${report.total_score}/${report.max_score}`;
  document.getElementById("avgScore").textContent = String(report.average_score);
  document.getElementById("tabSwitchesKpi").textContent = String((report.proctoring && report.proctoring.tab_switches) || 0);

  const tabs = (report.proctoring && report.proctoring.tab_switches) || 0;
  const note =
    tabs > 3
      ? "Proctoring note: high tab switching detected. In a real interview, avoid leaving the tab."
      : "Proctoring note: tab switching looks within normal range.";
  document.getElementById("note").textContent = note;

  const list = document.getElementById("list");
  list.innerHTML = "";
  renderScoreGraph(report.responses || []);
  for (const r of report.responses || []) {
    const q = r.question || {};
    const evaln = r.evaluation || {};
    const score = Number(evaln.score || 0);
    const item = document.createElement("div");
    item.className = "item";
    let suggestionsHtml = "";
    if (evaln.suggestions && evaln.suggestions.length > 0) {
      suggestionsHtml = `<div class="muted small" style="margin-top:6px"><b>Suggestions:</b><ul>` + 
        evaln.suggestions.map((s) => `<li>${escapeText(s)}</li>`).join("") + 
        `</ul></div>`;
    }

    item.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:12px">
        <h3 style="margin:0">Q${(r.index ?? 0) + 1}. ${escapeText(q.question || "")}</h3>
        <span class="score ${scoreClass(score)}">${score}/10</span>
      </div>
      <div class="qmeta" style="margin-top:8px">
        <span class="tag">${escapeText((q.difficulty || "medium").toUpperCase())}</span>
        <span class="tag">${escapeText(q.category || "general")}</span>
      </div>
      <div class="divider"></div>
      <div class="muted small"><b>Answer:</b> ${escapeText(r.answer || "")}</div>
      <div class="divider"></div>
      <div class="muted small"><b>Feedback:</b> ${escapeText(evaln.feedback || "")}</div>
      <div class="muted small" style="margin-top:6px"><b>Communication:</b> ${escapeText(evaln.communication || "")}</div>
      <div class="muted small" style="margin-top:6px"><b>Emotion:</b> ${escapeText(evaln.emotion || "Neutral")}</div>
      ${suggestionsHtml}
      <div class="muted small" style="margin-top:6px"><b>Solution:</b><br />${escapeText(evaln.solution || "")}</div>
    `;
    list.appendChild(item);
  }
}

function renderScoreGraph(responses) {
  const canvas = document.getElementById("scoreGraph");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const scores = (responses || []).map((r) => Number((r.evaluation && r.evaluation.score) || 0));
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  const padL = 50;
  const padR = 20;
  const padT = 20;
  const padB = 35;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  // Grid lines for 0..10
  ctx.strokeStyle = "rgba(255,255,255,.08)";
  ctx.lineWidth = 1;
  for (let s = 0; s <= 10; s++) {
    const y = padT + (1 - s / 10) * plotH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
    ctx.stroke();
    if (s === 0 || s === 5 || s === 10) {
      ctx.fillStyle = "rgba(255,255,255,.65)";
      ctx.font = "14px ui-sans-serif, system-ui";
      ctx.fillText(String(s), 10, y + 5);
    }
  }

  if (scores.length === 0) return;

  const xStep = scores.length === 1 ? 0 : plotW / (scores.length - 1);
  const points = scores.map((score, i) => {
    const x = padL + i * xStep;
    const y = padT + (1 - score / 10) * plotH;
    return { x, y };
  });

  ctx.strokeStyle = "rgba(110,168,255,.95)";
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((p, i) => {
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  });
  ctx.stroke();

  points.forEach((p) => {
    ctx.fillStyle = "rgba(110,168,255,.95)";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fill();
  });
}

async function load() {
  const backend = getBackendUrl();
  const sessionId = getSessionIdFromUrl();
  if (!sessionId) {
    window.location.href = "./index.html";
    return;
  }
  const report = await fetchJson(`${backend}/api/session/${encodeURIComponent(sessionId)}/report`);
  render(report);
}

document.getElementById("newBtn").addEventListener("click", () => {
  sessionStorage.clear();
  window.location.href = "./index.html";
});

load().catch((e) => {
  document.getElementById("meta").textContent = e.message || "Failed to load report.";
});

