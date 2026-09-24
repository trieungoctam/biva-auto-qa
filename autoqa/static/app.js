/* auto-qa UI — 3 màn: Chạy / Lịch sử / Bot. Không framework, không build. */

const KEY = localStorage.getItem('autoqa_key') || '';
document.getElementById('apikey').value = KEY;

function api(path, opts = {}) {
  const headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
  if (KEY) headers['X-API-Key'] = KEY;
  return fetch(path, Object.assign({}, opts, {headers})).then(async r => {
    if (r.status === 401) { toast('Sai/thiếu API key — lưu key rồi thử lại'); throw new Error('401'); }
    if (!r.ok) { toast((await r.json().catch(() => ({}))).detail || ('Lỗi ' + r.status)); throw new Error(r.status); }
    return r.json();
  });
}
document.getElementById('setkey').onclick = () => {
  localStorage.setItem('autoqa_key', document.getElementById('apikey').value.trim());
  location.reload();
};

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(msg){ let t = document.createElement('div'); t.className='toast'; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), 4000); }
const dot = s => ({PASS:'pass',FAIL:'fail',BLOCKED:'block'}[s] || 'block');
const $ = id => document.getElementById(id);

function go(tab){
  ['run','history','bot'].forEach(t => $('tab-'+t).classList.toggle('on', t===tab));
  ({run: renderRun, history: renderHistory, bot: renderBot})[tab]();
}
$('tab-run').onclick = () => go('run');
$('tab-history').onclick = () => go('history');
$('tab-bot').onclick = () => go('bot');

// ================= CHẠY TEST =================
let BOTS = [], TARGETS = [];

async function renderRun(){
  const main = $('main');
  [BOTS, TARGETS] = await Promise.all([api('/api/bots'), api('/api/targets')]);
  main.innerHTML = `
    <section class="card">
      <div class="row">
        <label>Bot <select id="sel-bot">${BOTS.map(b =>
          `<option value="${esc(b.bot)}">${esc(b.display_name)} (${b.n_scenarios} kịch bản${b.n_llm ? `, ${b.n_llm} llm` : ''})</option>`).join('')}</select></label>
        <label>Target đè <select id="sel-target"><option value="">— theo kịch bản —</option>${
          TARGETS.map(t => `<option value="${esc(t.name)}">${esc(t.name)} (${esc(t.kind)})</option>`).join('')}</select></label>
        <label>Song song <input id="conc" type="number" min="1" max="4" value="1" style="width:60px"></label>
      </div>
      <div id="scn-list" class="scn-list"><p class="hint">chọn bot…</p></div>
      <div class="row">
        <button class="go" id="btn-run">Chạy test</button>
        <span id="run-state" class="hint"></span>
      </div>
    </section>
    <section id="run-result" class="card" style="display:none"></section>`;
  $('sel-bot').onchange = loadScenarios;
  await loadScenarios();
  $('btn-run').onclick = startRun;
}

async function loadScenarios(){
  const bot = $('sel-bot').value;
  const list = await api(`/api/bots/${bot}/scenarios`);
  const know = await api(`/api/bots/${bot}/knowledge`).catch(() => ({has_run_warning:false}));
  $('scn-list').innerHTML =
    (know.has_run_warning ? `<p class="warn">⚠️ Bot này có cảnh báo chạy test trong knowledge/business.md (ví dụ: có thể tạo vé thật trên DEV khi khách đồng ý bản xác nhận) — đọc kỹ trước khi chạy kịch bản llm.</p>` : '') +
    (list.length ? list.map(s => s.error
      ? `<label class="scn err"><input type="checkbox" disabled> <code>${esc(s.id)}</code> — lỗi: ${esc(s.error)}</label>`
      : `<label class="scn"><input type="checkbox" value="${esc(s.id)}">
           <code>${esc(s.id)}</code> <span class="badge ${s.mode}">${s.mode}</span>
           <span class="mut">${s.turns} lượt${s.mix.length ? ' · mix: ' + esc(s.mix.join(', ')) : ''}</span></label>`
    ).join('') : '<p class="hint">bot chưa có kịch bản nào</p>');
}

async function startRun(){
  const chosen = [...document.querySelectorAll('#scn-list input:checked')].map(i => i.value);
  if (!chosen.length) return toast('Chọn ít nhất một kịch bản');
  $('btn-run').disabled = true;
  $('run-state').textContent = 'đang gửi…';
  try {
    const r = await api('/api/runs', {method:'POST', body: JSON.stringify({
      bot: $('sel-bot').value, scenarios: chosen,
      target: $('sel-target').value || undefined, concurrency: +$('conc').value || 1,
    })});
    pollRun(r.run_id, r.total);
  } catch { $('btn-run').disabled = false; $('run-state').textContent = ''; }
}

function pollRun(runId, total){
  $('run-state').textContent = `đang chạy ${runId}…`;
  const timer = setInterval(async () => {
    const s = await api(`/api/runs/${runId}/status`).catch(() => null);
    if (!s) return;
    $('run-state').textContent = `đang chạy ${runId}… ${s.done ?? '?'}/${total}`;
    if (s.status === 'running') return;
    clearInterval(timer);
    $('btn-run').disabled = false;
    $('run-state').textContent = '';
    const box = $('run-result'); box.style.display = '';
    box.innerHTML = `<h2>Kết quả run ${esc(runId)}</h2>` + (s.status === 'error'
      ? `<p class="warn">Lỗi: ${esc(s.error)}</p>`
      : `<table><tr><th></th><th>Trạng thái</th><th>Kịch bản</th><th>Conversation</th></tr>${
          s.results.map(r => `<tr><td><span class="dot ${dot(r.status)}"></span></td><td><b>${r.status}</b></td>
            <td><code>${esc(r.id)}</code></td><td><code>${esc(r.conversation_id || '—')}</code></td></tr>`).join('')}</table>
          <p class="hint">Chi tiết transcript ở tab <b>Lịch sử</b> (run ${esc(runId)}).</p>`);
  }, 1000);
}

// ================= LỊCH SỬ =================
async function renderHistory(){
  const rows = await api('/api/runs');
  const q = new URLSearchParams(location.search).get('q') || '';
  $('main').innerHTML = `
    <section class="card">
      <div class="row"><input id="filter" placeholder="lọc theo bot / conv / run…" value="${esc(q)}" style="flex:1">
      <span class="hint">${rows.length} dòng từ runs/INDEX.md</span></div>
      <table id="hist-table"><tr><th></th><th>Run</th><th>Target</th><th>Kịch bản</th><th>Conversation</th></tr></table>
    </section>
    <section id="run-detail" class="card" style="display:none"></section>`;
  const draw = f => {
    const fl = f.toLowerCase();
    $('hist-table').innerHTML = '<tr><th></th><th>Run</th><th>Target</th><th>Kịch bản</th><th>Conversation</th></tr>' +
      rows.filter(r => !fl || (r.run + r.target + r.scenario + r.conversation).toLowerCase().includes(fl))
        .map(r => `<tr class="hrow" data-run="${esc(r.run)}" data-scn="${esc(r.scenario)}">
          <td><span class="dot ${dot(r.status)}"></span></td><td>${esc(r.run)}</td><td>${esc(r.target)}</td>
          <td><code>${esc(r.scenario)}</code></td><td><code>${esc(r.conversation)}</code></td></tr>`).join('');
    document.querySelectorAll('.hrow').forEach(el => el.onclick = () => openRun(el.dataset.run));
  };
  $('filter').oninput = e => draw(e.target.value);
  draw(q);
}

async function openRun(runId){
  const d = await api(`/api/runs/${runId}`);
  const box = $('run-detail'); box.style.display = '';
  box.innerHTML = `<h2>Run ${esc(runId)}</h2>` + d.scenarios.map(sc => `
    <details class="tr" ${d.scenarios.length === 1 ? 'open' : ''}>
      <summary><span class="dot ${dot(sc.status)}"></span> <code>${esc(sc.suite)}/${esc(sc.scenario)}</code>
        — ${sc.status} ${sc.conversation_id ? `· conv <code>${esc(sc.conversation_id)}</code>` : ''}</summary>
      ${sc.error ? `<p class="warn">Lỗi: ${esc(sc.error)}</p>` : ''}
      ${(sc.checks || []).filter(c => c.status !== 'PASS')
        .map(c => `<div class="det">✕ ${esc(c.name)}: ${esc(c.detail)}</div>`).join('')}
      ${(sc.transcript || []).map(t => `
        <div class="msg u"><b>Khách:</b> ${esc(t.user || '(im lặng)')}</div>
        <div class="msg a"><b>Bot:</b> ${esc(t.assistant || '(rỗng)')}${t.tag ? ` <code>|${esc(t.tag)}</code>` : ''}${
          t.caller_note ? `<div class="mut note">caller: ${esc(t.caller_note)}</div>` : ''}</div>`).join('')}
    </details>`).join('') +
    `<p class="hint">Báo cáo: runs/${esc(runId)}.md — JSONL: runs/${esc(runId)}.jsonl</p>`;
  box.scrollIntoView({behavior:'smooth'});
}

// ================= BOT (đọc) =================
async function renderBot(){
  const bots = await api('/api/bots');
  $('main').innerHTML = `
    <section class="card">
      <div class="row"><label>Bot <select id="bsel">${bots.map(b =>
        `<option value="${esc(b.bot)}">${esc(b.display_name)}</option>`).join('')}</select></label>
      <span class="hint">knowledge/business.md — rubric để review transcript (read-only)</span></div>
      <pre id="know" class="know">đang tải…</pre>
    </section>`;
  const load = async () => {
    const k = await api(`/api/bots/${$('bsel').value}/knowledge`);
    $('know').textContent = k.business || '(bot này chưa có knowledge/business.md)';
  };
  $('bsel').onchange = load;
  await load();
}

go('run');
