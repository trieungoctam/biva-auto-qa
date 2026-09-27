/* auto-qa UI v1 — Chạy / Lịch sử (review) / Dashboard / Bot / Admin. Không framework. */

const KEY = localStorage.getItem('autoqa_key') || '';
document.getElementById('apikey').value = KEY;
let ME = {name: '', role: ''};

function api(path, opts = {}) {
  const headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
  if (KEY) headers['X-API-Key'] = KEY;
  return fetch(path, Object.assign({}, opts, {headers})).then(async r => {
    if (r.status === 401) { toast('Sai/thiếu API key — lưu key rồi thử lại'); throw new Error('401'); }
    if (!r.ok) { toast((await r.json().catch(() => ({}))).detail || ('Lỗi ' + r.status)); throw new Error(r.status); }
    return r.status === 204 ? null : r.json();
  });
}
document.getElementById('setkey').onclick = () => {
  localStorage.setItem('autoqa_key', document.getElementById('apikey').value.trim());
  location.reload();
};

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(msg){ let t = document.createElement('div'); t.className='toast'; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), 5000); }
const dot = s => ({PASS:'pass',FAIL:'fail',BLOCKED:'block'}[s] || 'block');
const $ = id => document.getElementById(id);

const TABS = ['run','history','dash','bot','admin'];
function go(tab){
  TABS.forEach(t => { const el = $('tab-'+t); if (el) el.classList.toggle('on', t===tab); });
  ({run: renderRun, history: renderHistory, dash: renderDash, bot: renderBot, admin: renderAdmin})[tab]();
}
TABS.forEach(t => { const el = $('tab-'+t); if (el) el.onclick = () => go(t); });

(async function init(){
  try { ME = await api('/api/me'); } catch { return; }
  $('who').textContent = `${ME.name} (${ME.role})`;
  if (ME.role === 'admin') $('tab-admin').style.display = '';
  go('run');
})();

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
        <label>Song song <input id="conc" type="number" min="1" max="4" value="1" style="width:56px"></label>
        <label>Calls/kịch bản <input id="calls" type="number" min="1" max="20" value="1" style="width:70px" title="mỗi call một conversation — bắt lỗi lúc được lúc không"></label>
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
  const [list, know] = await Promise.all([
    api(`/api/bots/${bot}/scenarios`),
    api(`/api/bots/${bot}/knowledge`).catch(() => ({has_run_warning:false})),
  ]);
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
      target: $('sel-target').value || undefined, concurrency: +$('conc').value || 1, calls: +$('calls').value || 1,
    })});
    pollRun(r.run_id, r.total);
  } catch { $('btn-run').disabled = false; $('run-state').textContent = ''; }
}

function pollRun(runId, total){
  $('run-state').textContent = `đang chạy ${runId}…`;
  const timer = setInterval(async () => {
    const s = await api(`/api/runs/${runId}/status`).catch(() => null);
    if (!s) return;
    let prog = s.status === 'queued' && s.queue_position ? `hàng đợi #${s.queue_position}` : `${s.done ?? '?'}/${total}`;
    $('run-state').textContent = `đang chạy ${runId}… ${prog}`;
    if (s.status === 'queued' || s.status === 'running') return;
    clearInterval(timer);
    $('btn-run').disabled = false;
    $('run-state').textContent = '';
    const box = $('run-result'); box.style.display = '';
    box.innerHTML = `<h2>Kết quả run ${esc(runId)} — chạy bởi ${esc(ME.name)}</h2>` + (s.status === 'error'
      ? `<p class="warn">Lỗi: ${esc(s.error)}</p>`
      : `<table><tr><th></th><th>Trạng thái</th><th>Kịch bản</th><th>Conversation</th></tr>${
          s.results.map(r => `<tr><td><span class="dot ${dot(r.status)}"></span></td><td><b>${r.status}</b></td>
            <td><code>${esc(r.id)}</code>${r.call ? ` <span class="mut">(${esc(r.call)})</span>` : ''}</td>
            <td><code>${esc(r.conversation_id || '—')}</code></td></tr>`).join('')}</table>
          <p class="hint">Review transcript ở tab <b>Lịch sử</b> (run ${esc(runId)}).</p>`);
  }, 1000);
}

// ================= LỊCH SỬ + REVIEW =================
let HIST = [];

async function renderHistory(){
  HIST = await api('/api/runs');
  $('main').innerHTML = `
    <section class="card">
      <div class="row">
        <input id="filter" placeholder="lọc: bot / conv / run / người…" style="flex:1">
        <select id="f-status"><option value="">mọi trạng thái</option><option value="chưa review">chưa review</option><option value="issue">có issue</option></select>
        <span class="hint">${HIST.length} dòng · ${new Set(HIST.map(r => r.run)).size} run</span>
      </div>
      <table id="hist-table"></table>
    </section>
    <section id="run-detail" class="card" style="display:none"></section>`;
  const draw = () => {
    const fl = $('filter').value.toLowerCase(), st = $('f-status').value;
    $('hist-table').innerHTML = '<tr><th></th><th>Run</th><th>Target</th><th>Kịch bản</th><th>Conversation</th><th>Người chạy</th></tr>' +
      HIST.filter(r => (!fl || (r.run + r.target + r.scenario + r.conversation + r.user).toLowerCase().includes(fl)))
        .map(r => `<tr class="hrow" data-run="${esc(r.run)}">
          <td><span class="dot ${dot(r.status)}"></span></td><td>${esc(r.run)}</td><td>${esc(r.target)}</td>
          <td><code>${esc(r.scenario)}</code></td><td><code>${esc(r.conversation)}</code></td><td>${esc(r.user)}</td></tr>`).join('');
    document.querySelectorAll('.hrow').forEach(el => el.onclick = () => openRun(el.dataset.run));
  };
  $('filter').oninput = draw;
  $('f-status').onchange = async () => { await markReviewStatus(); draw(); };
  await markReviewStatus();
  draw();
}

async function markReviewStatus(){
  // gắn trạng thái review vào HIST để filter "chưa review / issue" dùng được
  const runs = [...new Set(HIST.map(r => r.run))].slice(0, 60); // các run gần nhất
  const map = {};
  await Promise.all(runs.map(async rid => {
    try { map[rid] = await api(`/api/runs/${rid}/review`); } catch { map[rid] = []; }
  }));
  for (const r of HIST) {
    const rv = (map[r.run] || []).find(v => v.scenario === r.scenario.replace(/ \(\d+\/\d+\)$/, ''));
    r._rv = rv ? rv.verdict : '';
  }
  applyStatusFilter();
}

function applyStatusFilter(){
  const st = $('f-status') ? $('f-status').value : '';
  if (!st) { HIST.forEach(r => delete r._hide); return; }
  HIST.forEach(r => {
    r._hide = st === 'chưa review' ? !!r._rv : !(r._rv === 'issue');
  });
}

async function openRun(runId){
  const d = await api(`/api/runs/${runId}`);
  const box = $('run-detail'); box.style.display = '';
  const rvOf = (scn, call) => (d.reviews || []).find(v => v.scenario === scn && (!v.call || v.call === call)) || null;
  box.innerHTML = `<div class="row"><h2 style="margin:0">Run ${esc(runId)}</h2>
    <a class="btn" href="/api/runs/${esc(runId)}/export" target="_blank">Xuất MD</a>
    <a class="btn" href="/api/runs/${esc(runId)}/export?format=csv" target="_blank">Xuất CSV</a></div>` +
    d.scenarios.map(sc => {
      const scn = `${sc.suite}/${sc.scenario}`, call = sc.call || '1/1';
      const rv = rvOf(scn, call);
      return `<details class="tr" ${d.scenarios.length === 1 ? 'open' : ''}>
      <summary><span class="dot ${dot(sc.status)}"></span> <code>${esc(scn)}</code>${call !== '1/1' ? ` <span class="mut">(${esc(call)})</span>` : ''}
        — ${sc.status} ${sc.conversation_id ? `· conv <code>${esc(sc.conversation_id)}</code>` : ''}
        ${rv ? `· <span class="badge ${rv.verdict === 'issue' ? 'llm' : ''}">review: ${esc(rv.verdict)} (${esc(rv.reviewer)}${rv.anchor ? ' · ' + esc(rv.anchor) : ''})</span>` : '· <span class="mut">chưa review</span>'}</summary>
      ${sc.error ? `<p class="warn">Lỗi: ${esc(sc.error)}</p>` : ''}
      ${(sc.checks || []).filter(c => c.status !== 'PASS').map(c => `<div class="det">✕ ${esc(c.name)}: ${esc(c.detail)}</div>`).join('')}
      <div class="msgs" data-scn="${esc(scn)}" data-call="${esc(call)}">
      ${(sc.transcript || []).map(t => `
        <div class="msg u"><b>Khách:</b> ${esc(t.user || '(im lặng)')}</div>
        <div class="msg a"><b>Bot:</b> ${esc(t.assistant || '(rỗng)')}${t.tag ? ` <code>|${esc(t.tag)}</code>` : ''}${
          t.caller_note ? `<div class="mut note">caller: ${esc(t.caller_note)}</div>` : ''}
          <button class="pin" data-anchor="T${t.turn}" title="neo finding vào lượt này">⌖ T${t.turn}</button></div>`).join('')}
      </div>
      ${reviewForm(scn, call, rv)}
    </details>`;
    }).join('') +
    `<p class="hint">Báo cáo: runs/${esc(runId)}.md — JSONL: runs/${esc(runId)}.jsonl</p>`;

  box.querySelectorAll('.msgs').forEach(m => {
    m.querySelectorAll('.pin').forEach(b => b.onclick = () => {
      m.querySelectorAll('.pin').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      m.dataset.anchor = b.dataset.anchor;
    });
  });
  box.querySelectorAll('form.rv').forEach(f => f.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(f);
    try {
      await api(`/api/runs/${runId}/review`, {method: 'POST', body: JSON.stringify({
        scenario: f.dataset.scn, call: f.dataset.call, verdict: fd.get('verdict'),
        anchor: f.closest('.tr').querySelector('.msgs').dataset.anchor || '',
        note: fd.get('note'),
      })});
      toast('Đã lưu review');
      openRun(runId);
    } catch {}
  });
  box.scrollIntoView({behavior:'smooth'});
}

function reviewForm(scn, call, rv){
  return `<form class="rv" data-scn="${esc(scn)}" data-call="${esc(call)}">
    <div class="row">
      <b>Review (${esc(ME.name)}):</b>
      <label><input type="radio" name="verdict" value="ok" ${!rv || rv.verdict === 'ok' ? 'checked' : ''}> ok</label>
      <label><input type="radio" name="verdict" value="issue" ${rv && rv.verdict === 'issue' ? 'checked' : ''}> issue</label>
      <label><input type="radio" name="verdict" value="warn" ${rv && rv.verdict === 'warn' ? 'checked' : ''}> warn</label>
      <input name="note" placeholder="ghi chú (kèm lượt đã neo)" style="flex:1" value="${esc(rv ? rv.note : '')}">
      <button class="go" type="submit">Lưu</button>
    </div></form>`;
}

// ================= DASHBOARD =================
async function renderDash(){
  const days = new URLSearchParams(location.search).get('days') || 14;
  const s = await api(`/api/stats?days=${days}`);
  $('main').innerHTML = `
    <section class="card">
      <div class="row"><h2 style="margin:0">Xu hướng ${s.days} ngày</h2>
        <span class="hint">${s.runs} run · ${s.rows} call · ${s.reviewed} đã review</span>
        <select id="days-sel">${[7,14,30].map(d => `<option value="${d}" ${d == days ? 'selected' : ''}>${d} ngày</option>`).join('')}</select></div>
      <table><tr><th>Kịch bản</th><th>Pass</th><th>Fail/Block</th><th>Issue review</th><th>Đã review</th><th>total</th></tr>
      ${s.scenarios.map(x => `<tr>
        <td><code>${esc(x.scenario)}</code> <span class="mut">${esc(x.target)}</span></td>
        <td><b class="ok">${x.pass}</b></td>
        <td><b class="${x.fail + x.blocked ? 'bad' : 'mut'}">${x.fail}/${x.blocked}</b></td>
        <td><b class="${x.issues ? 'bad' : 'mut'}">${x.issues}</b></td>
        <td>${x.reviewed}</td><td class="mut">${x.total}</td></tr>`).join('')}</table>
      <p class="hint">Sắp theo nhiều vấn đề nhất. Issue mở/đóng quản lý ngoài tool (Linear/sheet).</p>
    </section>`;
  $('days-sel').onchange = e => { history.replaceState(null, '', `?days=${e.target.value}`); renderDash(); };
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

// ================= ADMIN =================
async function renderAdmin(){
  if (ME.role !== 'admin') { $('main').innerHTML = '<p class="hint">chỉ admin</p>'; return; }
  const users = await api('/api/users');
  $('main').innerHTML = `
    <section class="card">
      <h2>Người dùng</h2>
      <table><tr><th>Tên</th><th>Vai trò</th><th></th></tr>
        ${users.map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.role)}</td>
          <td><button class="btn" data-rot="${esc(u.name)}">Xoay key</button>
              <button class="btn" data-del="${esc(u.name)}">Xoá</button></td></tr>`).join('')}</table>
      <form id="add-user" class="row" style="margin-top:12px">
        <input name="name" placeholder="tên (a-z0-9)" required>
        <select name="role"><option value="member">member</option><option value="admin">admin</option></select>
        <button class="go" type="submit">Thêm người</button>
      </form>
      <p class="hint">Key chỉ hiện MỘT lần khi thêm/xoay — gửi ngay cho người dùng. users.yaml chỉ lưu hash.</p>
    </section>
    <section id="new-key" class="card" style="display:none"></section>`;
  $('add-user').onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await api('/api/users', {method:'POST', body: JSON.stringify({name: fd.get('name'), role: fd.get('role')})});
      showKeyOnce(`${r.name} (${r.role})`, r.key); renderAdmin();
    } catch {}
  };
  document.querySelectorAll('[data-rot]').forEach(b => b.onclick = async () => {
    try { const r = await api(`/api/users/${b.dataset.rot}/rotate`, {method:'POST'}); showKeyOnce(r.name, r.key); } catch {}
  });
  document.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm(`Xoá ${b.dataset.del}?`)) return;
    try { await api(`/api/users/${b.dataset.del}`, {method:'DELETE'}); renderAdmin(); } catch {}
  });
}

function showKeyOnce(who, key){
  const box = $('new-key'); box.style.display = '';
  box.innerHTML = `<p class="warn">Key của <b>${esc(who)}</b> (chỉ hiện lần này — copy ngay):</p>
    <pre class="know">${esc(key)}</pre>`;
  box.scrollIntoView({behavior:'smooth'});
}
