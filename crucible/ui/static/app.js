"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const AGENTS = [
  ["architect", "Architect", '<path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6"/>'],
  ["adversary", "Adversary", '<path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/>'],
  ["implementer", "Implementer", '<path d="M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12"/>'],
  ["surgeon", "Surgeon", '<path d="M6 3v6a6 6 0 0012 0V3M9 21a3 3 0 100-6 3 3 0 000 6zM12 15v-3"/>'],
  ["arbiter", "Arbiter", '<path d="M12 3v18M5 7h14M7 7l-3 6h6zM17 7l3 6h-6z"/>'],
];
const MODES = {
  code: { prompt: "merge overlapping booking intervals", baseTitle: "Gemma 4 31B · Google AI Studio", tag: "5 agents · oracle gauntlet", gpLab: "GPU baseline (AI Studio)" },
  app:  { prompt: "a calculator app with a display and buttons for digits and + - * / =", tag: "build · render · vision QA", gpLab: "—" },
  repo: { prompt: "add a 'split the bill between N people' feature", tag: "fix · verify-in-container · vision QA", gpLab: "—", repo: "webrepo" },
};
function setLayout(m) { els.split.className = "split mode-" + m; }

let es = null, runId = null, mode = "code", curGauntlet = null, hasCE = false, baseTimer = null;

const els = {
  prompt: $("prompt"), runBtn: $("run-btn"), split: $("split"),
  tps: $("tps-value"), gpTps: $("gp-tps"), gpLab: $("gp-lab"), cbWho: $("cb-who"),
  vCode: $("vanilla-code"), vStats: $("vanilla-stats"), vVerdict: $("vanilla-verdict"),
  baseName: $("base-name"), baseTimer: $("base-timer"),
  process: $("process"), cruTag: $("cru-tag"),
  seal: $("deliver-badge"), verdict: $("verdict"),
  compareBtn: $("compare-btn"), compare: $("compare"),
  appFrame: $("appFrame"), prevEmpty: $("prev-empty"), prevTag: $("prev-tag"),
};

/* ---- agents rail ---- */
(function buildAgents() {
  const rail = $("agents");
  AGENTS.forEach((a, i) => {
    const el = document.createElement("div");
    el.className = "agent"; el.dataset.role = a[0];
    el.innerHTML = `<div class="ring"><svg viewBox="0 0 24 24">${a[2]}</svg></div><b>${a[1]}</b>`
      + (i < AGENTS.length - 1 ? '<div class="conn"></div>' : "");
    rail.appendChild(el);
  });
})();
function setChip(role, cls) { const el = document.querySelector(`.agent[data-role="${role}"]`); if (el) el.className = "agent " + cls; }

/* ---- theme + tabs ---- */
$("themeBtn").onclick = () => { const h = document.documentElement; h.dataset.theme = h.dataset.theme === "dark" ? "light" : "dark"; };
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  if (es) return; // don't switch mid-run
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("on"));
  t.classList.add("on");
  mode = t.dataset.mode;
  const m = MODES[mode];
  els.prompt.value = m.prompt;
  setLayout(mode);
  els.cruTag.textContent = m.tag;
  els.gpLab.textContent = m.gpLab;
  if (m.baseTitle) els.baseName.textContent = m.baseTitle;
}));

function resetUI() {
  if (es) { es.close(); es = null; }
  runId = null; curGauntlet = null; hasCE = false;
  clearInterval(baseTimer);
  els.process.innerHTML = '<div class="placeholder">running…</div>';
  els.vCode.innerHTML = '<span class="dim">// the GPU baseline writes one confident answer…</span>';
  els.vStats.textContent = "unverified"; els.vVerdict.classList.remove("show");
  els.baseTimer.textContent = "GPU · 0.0s";
  els.seal.textContent = "verifying…"; els.verdict.className = "verdict";
  els.tps.textContent = "0"; els.gpTps.textContent = "0";
  els.compareBtn.disabled = true; els.compare.className = "compare hide"; els.compare.innerHTML = "";
  document.querySelectorAll(".agent").forEach(a => a.className = "agent");
  els.appFrame.classList.remove("live"); els.appFrame.removeAttribute("srcdoc");
  els.prevEmpty.style.display = ""; els.prevTag.textContent = "renders as it builds"; els.prevTag.classList.remove("prev-tag-verified");
}

function card(cls, html) {
  if (els.process.querySelector(".placeholder")) els.process.innerHTML = "";
  const d = document.createElement("div"); d.className = "card " + cls; d.innerHTML = html;
  els.process.appendChild(d); els.process.scrollTop = els.process.scrollHeight;
  return d;
}
function ensureRow(stage) {
  if (!curGauntlet) {
    if (els.process.querySelector(".placeholder")) els.process.innerHTML = "";
    const wrap = document.createElement("div"); wrap.className = "card gauntlet-card";
    wrap.innerHTML = '<div class="gauntlet"></div>';
    els.process.appendChild(wrap);
    curGauntlet = { el: wrap, box: wrap.querySelector(".gauntlet"), rows: {} };
  }
  if (!curGauntlet.rows[stage]) {
    const r = document.createElement("div"); r.className = "stage running"; r.dataset.stage = stage;
    r.innerHTML = `<span class="mark">◐</span><span class="sname">${esc(stage)}</span><span class="sdetail"></span>`;
    curGauntlet.box.appendChild(r); curGauntlet.rows[stage] = r;
    els.process.scrollTop = els.process.scrollHeight;
  }
  return curGauntlet.rows[stage];
}

const handlers = {
  run_id: (e) => { runId = e.id; },

  /* LEFT baseline pane */
  vanilla_start: (e) => {
    els.vCode.textContent = ""; els.vStats.textContent = "writing…";
    if (e.provider) els.baseName.textContent = `${e.model || "Gemma 4 31B"} · ${e.provider}`;
    let t0 = performance.now();
    clearInterval(baseTimer);
    baseTimer = setInterval(() => { els.baseTimer.textContent = "GPU · " + ((performance.now() - t0) / 1000).toFixed(1) + "s"; }, 80);
  },
  vanilla_token: (e) => { els.vCode.textContent += e.text; els.vCode.scrollTop = els.vCode.scrollHeight; },
  vanilla_done: (e) => {
    clearInterval(baseTimer);
    els.gpTps.textContent = Math.round(e.tokens_per_sec || 0).toLocaleString();
    els.vStats.textContent = `${(e.elapsed || 0).toFixed(2)}s · unverified`;
    els.baseTimer.textContent = "GPU · " + (e.elapsed || 0).toFixed(1) + "s";
    els.vVerdict.classList.add("show");
  },
  vanilla_error: (e) => { clearInterval(baseTimer); els.vCode.textContent = "// baseline error: " + e.message; },

  /* RIGHT Crucible */
  run_start: () => { if (els.process.querySelector(".placeholder")) els.process.innerHTML = ""; },
  agent_start: (e) => setChip(e.role, "active"),
  agent_done: (e) => setChip(e.role, "done"),

  spec_ready: (e) => {
    const s = e.spec, d = (s.explicit_decisions || [])[0];
    let html = `<h4>Architect · frozen spec</h4><div class="fn">${esc(s.signature || s.function_name || "")}</div>`;
    if (s.description) html += `<div style="color:var(--dim);font-size:12px">${esc(s.description)}</div>`;
    if (d) html += `<div class="decision"><span class="amb">ambiguity:</span> ${esc(d.ambiguity)} → ${esc(d.decision)}</div>`;
    card("spec", html);
  },
  oracle_ready: (e) => {
    const tags = (e.boundary_categories || []).map(c => `<span class="tag">${esc(c)}</span>`).join("");
    const props = (e.property_names || []).map(p => `<span class="tag prop">∀ ${esc(p)}</span>`).join("");
    const diff = e.has_reference ? `<span class="tag diff">differential ref</span>` : "";
    card("oracle", `<h4>Adversary · blind oracle (never sees the code)</h4>
      <div style="font-size:12px;color:var(--dim);margin-bottom:4px">${e.example_count} example tests · ${(e.property_names || []).length} properties</div>
      <div class="tags">${tags}</div><div class="tags">${props}${diff}</div>`);
  },
  candidate_proposed: () => {},

  iteration: (e) => {
    const h = document.createElement("div"); h.className = "iter-head"; h.textContent = "iteration " + e.n;
    if (els.process.querySelector(".placeholder")) els.process.innerHTML = "";
    els.process.appendChild(h);
    curGauntlet = null; // next stage_* starts a fresh gauntlet card
  },
  stage_start: (e) => { const r = ensureRow(e.stage); r.className = "stage running"; r.querySelector(".mark").textContent = "◐"; },
  stage_result: (e) => {
    const r = e.result, row = ensureRow(r.stage);
    const skipped = r.status === "pass" && /^skipped/.test(r.detail || "");
    row.className = "stage " + (skipped ? "skip" : r.status);
    row.querySelector(".mark").textContent = skipped ? "–" : r.status === "pass" ? "✓" : r.status === "fail" ? "✕" : "!";
    row.querySelector(".sdetail").textContent = r.detail || "";
    if (r.counterexample) {
      hasCE = true;
      const c = r.counterexample;
      card("ce", `<h4>⚠ Counterexample — caught at ${esc(c.failing_stage || r.stage)}</h4>
        <div class="row"><span class="k">input</span><span class="v">${esc(c.input_repr)}</span></div>
        <div class="row"><span class="k">got</span><span class="v bad">${esc(c.actual_repr)}</span></div>
        <div class="row"><span class="k">expected</span><span class="v good">${esc(c.expected_repr)}</span></div>`);
    }
  },
  surgeon_patch: (e) => card("surgeon-card", `<h4>✎ Surgeon · targeted fix</h4><div class="why">${esc(e.diff_explanation)}</div>`),
  arbiter_verdict: (e) => {
    const v = e.verdict;
    card("arbiter-card", `<h4>⚖ Arbiter · ruling</h4>
      <div>verdict: <span class="v-verdict ${esc(v.verdict)}">${esc(v.verdict)}</span></div>
      <div style="font-size:12px;color:var(--dim);margin-top:4px">${esc(v.recommended_action)}</div>`);
  },
  note: (e) => {
    if (els.process.querySelector(".placeholder")) els.process.innerHTML = "";
    const d = document.createElement("div"); d.className = "note-line"; d.textContent = "› " + e.text;
    els.process.appendChild(d); els.process.scrollTop = els.process.scrollHeight;
  },
  metrics: (e) => { els.tps.textContent = Math.round(e.tokens_per_sec || 0).toLocaleString(); },

  app_ready: (e) => {
    els.appFrame.srcdoc = e.html || "";
    els.appFrame.classList.add("live");
    els.prevEmpty.style.display = "none";
    els.prevTag.textContent = e.verified ? "✓ verified · live & clickable" : "live · verifying…";
    els.prevTag.classList.toggle("prev-tag-verified", !!e.verified);
  },

  candidate_delivered: (e) => {
    els.seal.textContent = "✅ VERIFIED · shipped"; els.verdict.className = "verdict win";
    card("spec", `<h4 style="color:var(--green)">✅ Verified deliverable</h4><pre style="font-family:var(--mono);font-size:11.5px;white-space:pre-wrap;color:var(--ink);max-height:220px;overflow:auto">${esc(e.code)}</pre>`);
  },
  floor_reached: (e) => {
    els.seal.textContent = "⚠ floor · " + (e.unverified_property || "unverified"); els.verdict.className = "verdict floor";
    card("surgeon-card", `<h4>⚠ Honest floor</h4><div class="why">Could not fully verify: ${esc(e.unverified_property || "")}. Shipping the best partial, clearly labeled.</div><pre style="font-family:var(--mono);font-size:11.5px;white-space:pre-wrap;color:var(--ink);max-height:200px;overflow:auto">${esc(e.code || "")}</pre>`);
  },
  run_done: () => {},
  run_error: (e) => { els.seal.textContent = "error"; els.verdict.className = "verdict err"; card("surgeon-card", `<h4 style="color:var(--red)">error</h4><div class="why">${esc(e.message)}</div>`); },

  all_done: () => {
    els.runBtn.disabled = false; els.runBtn.textContent = "Run ▶";
    if (hasCE && runId && mode === "code") els.compareBtn.disabled = false;
    if (es) { es.close(); es = null; }
  },
};

function start() {
  const prompt = els.prompt.value.trim();
  if (!prompt) return;
  resetUI();
  els.runBtn.disabled = true; els.runBtn.textContent = "running…";
  let url = "/run_stream?prompt=" + encodeURIComponent(prompt) + "&mode=" + mode;
  if (mode === "code") url += "&baseline=gemini";
  if (mode === "repo") url += "&repo=" + (MODES.repo.repo || "webrepo");
  es = new EventSource(url);
  es.onmessage = (msg) => { let ev; try { ev = JSON.parse(msg.data); } catch { return; } const h = handlers[ev.type]; if (h) h(ev); };
  es.onerror = () => { if (es) { es.close(); es = null; } els.runBtn.disabled = false; els.runBtn.textContent = "Run ▶"; clearInterval(baseTimer); };
}

async function compare() {
  if (!runId) return;
  els.compareBtn.disabled = true;
  const res = await fetch("/compare/" + runId, { method: "POST" });
  const data = await res.json();
  if (!data.available) { els.compareBtn.disabled = false; return; }
  const same = (o) => o && o.ok && o.output != null;
  const vWrong = !(same(data.vanilla) && String(data.vanilla.output) === String(data.expected));
  const cRight = same(data.crucible) && String(data.crucible.output) === String(data.expected);
  els.compare.className = "compare";
  els.compare.innerHTML = `
    <div class="col"><h5>GPU baseline on the counterexample</h5>
      <div class="io"><span class="lbl">input</span>${esc(data.input)}</div>
      <div class="io"><span class="lbl">output</span><span class="res ${vWrong ? "bad" : "good"}">${esc(data.vanilla.output)}</span></div></div>
    <div class="col"><h5>Crucible on the counterexample</h5>
      <div class="io"><span class="lbl">input</span>${esc(data.input)}</div>
      <div class="io"><span class="lbl">output</span><span class="res ${cRight ? "good" : "bad"}">${esc(data.crucible.output)}</span></div></div>
    <div class="caption">expected <b>${esc(data.expected)}</b> — the model shipped a facade; Crucible caught it before the user did.</div>`;
}

els.runBtn.addEventListener("click", start);
els.prompt.addEventListener("keydown", (e) => { if (e.key === "Enter") start(); });
els.compareBtn.addEventListener("click", compare);

setLayout(mode); // initial layout (code)

// Offline replay hook (used for headless verification / a scripted recording fallback):
// feed a captured array of real events straight through the live handlers.
window.__replay = (events) => { for (const e of (events || [])) { const h = handlers[e.type]; if (h) { try { h(e); } catch (_) {} } } };
