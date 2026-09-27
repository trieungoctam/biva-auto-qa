/* auto-qa UI — Chạy / Lịch sử (panel review) / Dashboard / Bot (editor) / Admin. */

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
const $ = id => document.getElementById(id);
function toast(msg, ok){ const t = document.createElement('div'); t.className = 'toast';
  t.innerHTML = (ok ? '<span class="ok">✓</span> ' : '') + esc(msg);
  document.body.appendChild(t); setTimeout(() => t.remove(), 4200); }
const dot = s => ({PASS:'pass',FAIL:'fail',BLOCKED:'block'}[s] || 'block');
const fmtRun = id => id.length >= 15 ? `${id.slice(6,8)}/${id.slice(4,6)} ${id.slice(9,11)}:${id.slice(11,13)}` : id;
function copyText(t){ navigator.clipboard.writeText(t).then(() => toast('Đã copy: ' + t.slice(0, 42), true)); }

/* ---------- slide-over panel ---------- */
function openPanel(html){
  $('panel-body').innerHTML = html;
  $('backdrop').hidden = false;
  setTimeout(() => $('panel').classList.add('open'), 10);
  $('panel').setAttribute('aria-hidden', 'false');
  const x = $('panel-body').querySelector('.x');
  if (x) x.onclick = closePanel;
}
function closePanel(){
  $('panel').classList.remove('open');
  $('panel').setAttribute('aria-hidden', 'true');
  setTimeout(() => { $('backdrop').hidden = true; }, 250);
}
$('backdrop').onclick = closePanel;
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

const TABS = ['run', 'history', 'dash', 'bot', 'admin'];
function go(tab){
  TABS.forEach(t => { const el = $('tab-' + t); if (el) el.classList.toggle('on', t === tab); });
  ({run: renderRun, history: renderHistory, dash: renderDash, bot: renderBot, admin: renderAdmin})[tab]();
}
TABS.forEach(t => { const el = $('tab-'+t); if (el) el.onclick = () => go(t); });

(async function init(){
  try { ME = await api('/api/me'); } catch { return; }
  $('who').textContent = `${ME.name} · ${ME.role}`;
  if (ME.role === 'admin') $('tab-admin').style.display = '';
  go('run');
})();

/* ================= CHẠY TEST ================= */
let BOTS = [], TARGETS = [];

async function renderRun(){
  $('main').innerHTML = '<div class="loading"></div>';
  [BOTS, TARGETS] = await Promise.all([api('/api/bots'), api('/api/targets')]);
  if (!BOTS.length) { $('main').innerHTML = emptyChưaBot(); return; }
  $('main').innerHTML = `
    <section class="card">
      <div class="row">
        <label>Bot <select id="sel-bot">${BOTS.map(b =>
          `<option value="${esc(b.bot)}">${esc(b.display_name)} · ${b.n_scenarios} kịch bản</option>`).join('')}</select></label>
        <label>Target đè <select id="sel-target"><option value="">— theo kịch bản —</option>${
          TARGETS.map(t => `<option value="${esc(t.name)}">${esc(t.name)}</option>`).join('')}</select></label>
        <label>Song song <input id="conc" type="number" min="1" max="4" value="1" style="width:52px"></label>
        <label>Calls/kịch bản <input id="calls" type="number" min="1" max="20" value="1" style="width:64px" title="mỗi call một conversation"></label>
      </div>
      <div class="row" style="gap:8px">
        <button class="btn" id="sel-all">Chọn tất cả</button>
        <button class="btn" id="sel-none">Bỏ hết</button>
        <button class="btn" id="sel-smoke">Chỉ smoke</button>
        <span id="est" class="hint"></span>
      </div>
      <div id="scn-list" class="scn-list"></div>
      <div class="row">
        <button class="go" id="btn-run">Chạy test</button>
        <div class="progress" id="prog" style="display:none"><i></i></div>
        <span id="run-state" class="hint"></span>
      </div>
    </section>
    <section id="run-result" class="card" style="display:none"></section>`;
  const load4 = async () => { await loadScenarios(); restoreSel(); updateEst(); };
  $('sel-bot').onchange = load4;
  ['sel-all','sel-none','sel-smoke'].forEach(id => $(id).onclick = () => {
    const only = id === 'sel-smoke';
    document.querySelectorAll('#scn-list input').forEach(i => i.checked = only ? /smoke/.test(i.value) : id === 'sel-all');
    saveSel(); updateEst();
  });
  $('scn-list').addEventListener('change', () => { saveSel(); updateEst(); });
  await load4();
  $('btn-run').onclick = startRun;
}

function selKey(){ return 'autoqa_sel_' + $('sel-bot').value; }
function saveSel(){ localStorage.setItem(selKey(), JSON.stringify([...document.querySelectorAll('#scn-list input:checked')].map(i => i.value))); }
function restoreSel(){
  const saved = new Set(JSON.parse(localStorage.getItem(selKey()) || '[]'));
  document.querySelectorAll('#scn-list input').forEach(i => i.checked = saved.has(i.value));
}
function updateEst(){
  const n = document.querySelectorAll('#scn-list input:checked').length;
  const calls = +$('calls').value || 1;
  $('est').textContent = n ? `${n} kịch bản × ${calls} call = ${n * calls} cuộc gọi bot` : 'chưa chọn kịch bản nào';
}
$('main') && null;
document.addEventListener('change', e => { if (e.target.id === 'calls') updateEst && $('est') && updateEst(); });

async function loadScenarios(){
  const bot = $('sel-bot').value;
  const [list, know] = await Promise.all([
    api(`/api/bots/${bot}/scenarios`), api(`/api/bots/${bot}/knowledge`).catch(() => ({})),
  ]);
  if (!list.length) { $('scn-list').innerHTML = '<div class="empty" style="padding:18px"><b>Chưa có kịch bản</b>thêm ở tab Bot</div>'; return; }
  $('scn-list').innerHTML =
    (know.has_run_warning ? `<div class="warn">⚠️ Bot có cảnh báo chạy test trong knowledge (có thể tạo vé thật trên DEV khi khách đồng ý) — đọc kỹ trước khi chạy llm.</div>` : '') +
    list.map(s => s.error
      ? `<div class="scn err"><code>${esc(s.id)}</code> — lỗi: ${esc(s.error)}</div>`
      : `<label class="scn"><input type="checkbox" value="${esc(s.id)}">
           <code>${esc(s.id.split('/').pop())}</code> <span class="badge ${s.mode}">${s.mode}</span>
           <span class="mut">${s.turns} lượt${s.mix.length ? ' · mix ' + esc(s.mix.join('+')) : ''}</span></label>`
    ).join('');
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
  $('prog').style.display = ''; $('prog').querySelector('i').style.width = '0';
  const timer = setInterval(async () => {
    const s = await api(`/api/runs/${runId}/status`).catch(() => null);
    if (!s) return;
    const label = s.status === 'queued' ? `hàng đợi #${s.queue_position}` : `${s.done ?? 0}/${total}`;
    $('run-state').textContent = `${runId} · ${label}`;
    $('prog').querySelector('i').style.width = `${Math.round(100 * (s.done ?? 0) / total)}%`;
    if (s.status === 'queued' || s.status === 'running') return;
    clearInterval(timer);
    $('btn-run').disabled = false; $('prog').style.display = 'none';
    const box = $('run-result'); box.style.display = '';
    box.innerHTML = `<h2>Run ${esc(fmtRun(runId))} — chạy bởi ${esc(ME.name)}</h2>` +
      (s.status === 'error' ? `<p class="warn">Lỗi: ${esc(s.error)}</p>`
      : `<table><tr><th></th><th>Kết quả</th><th>Kịch bản</th><th>Conversation</th></tr>${
        s.results.map(r => `<tr><td><span class="dot ${dot(r.status)}"></span></td><td><b>${r.status}</b></td>
          <td><code>${esc(r.id.split('/').pop())}</code>${r.call ? ` <span class="mut">${esc(r.call)}</span>` : ''}</td>
          <td>${r.conversation_id ? `<code>${esc(r.conversation_id)}</code> <button class="copy" data-c="${esc(r.conversation_id)}">copy</button>` : '—'}</td></tr>`).join('')}</table>
        <p class="row" style="margin-top:10px"><button class="btn" onclick="openRunPanel('${esc(runId)}')">Review transcript →</button>
        <span class="hint">runs/${esc(runId)}.{jsonl,md}</span></p>`);
    box.querySelectorAll('.copy').forEach(b => b.onclick = () => copyText(b.dataset.c));
  }, 1000);
}

function emptyChưaBot(){
  return `<div class="card"><div class="empty"><b>Chưa có bot nào</b>thêm bot theo bots/TEMPLATE-bot.md rồi khởi động lại</div></div>`;
}

/* ================= LỊCH SỬ — nhóm theo run ================= */
let HIST = [];

async function renderHistory(){
  $('main').innerHTML = '<div class="loading"></div>';
  HIST = await api('/api/runs');
  if (!HIST.length) { $('main').innerHTML = `<div class="card"><div class="empty"><b>Chưa có run nào</b>bắt đầu ở tab Chạy test</div></div>`; return; }
  $('main').innerHTML = `
    <section class="card">
      <div class="row">
        <input id="filter" placeholder="lọc: kịch bản / conv / người…" style="flex:1; min-width:220px">
        <select id="f-status"><option value="">mọi dòng</option><option value="unreviewed">chưa review</option><option value="issue">có issue</option></select>
        <span class="hint" id="hist-sum"></span>
      </div>
      <div id="run-list"></div>
    </section>`;
  const draw = async () => { await markReviewStatus(); renderGroups(); };
  $('filter').oninput = () => renderGroups();
  $('f-status').onchange = draw;
  await draw();
}

async function markReviewStatus(){
  const runs = [...new Set(HIST.map(r => r.run))].slice(0, 80);
  const map = {};
  await Promise.all(runs.map(async rid => {
    try { map[rid] = await api(`/api/runs/${rid}/review`); } catch { map[rid] = []; }
  }));
  for (const r of HIST) {
    const base = r.scenario.replace(/ \(\d+\/\d+\)$/, '');
    r._rv = (map[r.run] || []).find(v => v.scenario === base) || null;
  }
}

function renderGroups(){
  const fl = $('filter').value.toLowerCase(), st = $('f-status').value;
  const groups = new Map();
  for (const r of HIST) {
    if (fl && !(r.run + r.target + r.scenario + r.conversation + r.user).toLowerCase().includes(fl)) continue;
    if (st === 'unreviewed' && r._rv) continue;
    if (st === 'issue' && (!r._rv || r._rv.verdict !== 'issue')) continue;
    if (!groups.has(r.run)) groups.set(r.run, []);
    groups.get(r.run).push(r);
  }
  $('hist-sum').textContent = `${groups.size} run · ${HIST.length} dòng`;
  if (!groups.size) { $('run-list').innerHTML = '<div class="empty"><b>Không có gì khớp bộ lọc</b></div>'; return; }
  $('run-list').innerHTML = [...groups.entries()].map(([run, rows]) => {
    const nPass = rows.filter(r => r.status === 'PASS').length;
    const users = [...new Set(rows.map(r => r.user))].join(', ');
    const targets = [...new Set(rows.map(r => r.target))].join(', ');
    const scns = [...new Set(rows.map(r => r.scenario.replace(/ \(\d+\/\d+\)$/, '')))];
    return `<div class="rungroup" data-run="${esc(run)}">
      <div class="when"><b>${esc(fmtRun(run))}</b><span class="mut">${esc(run.slice(0,8))}</span></div>
      <div class="meta">
        <span class="chip"><b>${esc(targets)}</b></span>
        <span class="chip"><span class="dot ${nPass === rows.length ? 'pass' : 'fail'}"></span> ${nPass}/${rows.length}</span>
        <span class="chip">${scns.length} kịch bản${scns.length <= 3 ? ` · ${scns.map(s => '<b>' + esc(s.split('/').pop()) + '</b>').join(' ')}` : ''}</span>
        ${users ? `<span class="chip">bởi <b>${esc(users)}</b></span>` : ''}
      </div>
      <span class="mut">mở →</span>
    </div>`;
  }).join('');
  document.querySelectorAll('.rungroup').forEach(el => el.onclick = () => openRunPanel(el.dataset.run));
}

/* ---------- panel: chi tiết run + review sticky ---------- */
async function openRunPanel(runId){
  let d;
  try { d = await api(`/api/runs/${runId}`); } catch { return; }
  const rvOf = (scn, call) => (d.reviews || []).find(v => v.scenario === scn && (!v.call || v.call === call || call === '1/1' && v.call === '1/1')) || null;
  const calls = d.scenarios.map((sc, i) => {
    const scn = `${sc.suite}/${sc.scenario}`, call = sc.call || '1/1', rv = rvOf(scn, call);
    return `<details class="call" data-scn="${esc(scn)}" data-call="${esc(call)}" ${i === 0 ? 'open' : ''}>
      <summary><span class="dot ${dot(sc.status)}"></span> <code>${esc(scn.split('/').pop())}</code>
        ${call !== '1/1' ? `<span class="mut">${esc(call)}</span>` : ''}
        ${sc.conversation_id ? `<button class="copy" data-c="${esc(sc.conversation_id)}" title="copy conv ID">⧉ ${esc(sc.conversation_id.slice(-6))}</button>` : ''}
        ${rv ? `<span class="badge ${rv.verdict === 'issue' ? 'llm' : ''}">${esc(rv.verdict)}${rv.anchor ? ' · ' + esc(rv.anchor) : ''}</span>` : '<span class="badge">chưa review</span>'}
      </summary>
      ${sc.error ? `<p class="warn">${esc(sc.error)}</p>` : ''}
      ${(sc.checks || []).filter(c => c.status !== 'PASS').map(c => `<div class="det">${esc(c.name)}: ${esc(c.detail)}</div>`).join('')}
      <div class="msgs">${(sc.transcript || []).map(t => `
        <div class="msg u"><b>Khách</b> <span class="dim">T${t.turn}</span><br>${esc(t.user || '(im lặng)')}</div>
        <div class="msg a"><b>Bot</b>${t.tag ? ` <code>${esc(t.tag)}</code>` : ''}<br>${esc(t.assistant || '(rỗng)')}
          ${t.caller_note ? `<div class="mut note">caller: ${esc(t.caller_note)}</div>` : ''}
          <button class="pin" data-anchor="T${t.turn}">⌖ neo T${t.turn}</button></div>`).join('')}
      </div>
    </details>`;
  }).join('');

  openPanel(`
    <div class="phead"><h2>Run ${esc(fmtRun(runId))}</h2>
      <a class="btn" href="/api/runs/${esc(runId)}/export" target="_blank">MD</a>
      <a class="btn" href="/api/runs/${esc(runId)}/export?format=csv" target="_blank">CSV</a>
      <button class="x" title="đóng (Esc)">✕</button></div>
    ${calls}
    <div class="pfoot"><form class="rv" id="rv-form">
      <div class="row">
        <b style="font-size:12.5px">Review <span class="mut">(${esc(ME.name)})</span>:</b>
        <label><input type="radio" name="verdict" value="ok" checked> ok</label>
        <label><input type="radio" name="verdict" value="issue"> issue</label>
        <label><input type="radio" name="verdict" value="warn"> warn</label>
        <input name="note" placeholder="ghi chú — bấm ⌖ trên lượt chat để neo" style="flex:1; min-width:160px">
        <button class="go" type="submit">Lưu</button>
      </div></form></div>`);

  // form review gắn với call đang mở (call mở cuối cùng)
  const panel = $('panel-body');
  panel.querySelectorAll('.copy').forEach(b => b.onclick = () => copyText(b.dataset.c));
  let current = panel.querySelector('details.call[open]');
  const track = () => { current = panel.querySelector('details.call[open]') || current; };
  panel.querySelectorAll('details.call').forEach(dt => {
    dt.ontoggle = track;
    dt.querySelectorAll('.pin').forEach(p => p.onclick = () => {
      dt.querySelectorAll('.pin').forEach(x => x.classList.remove('on'));
      p.classList.add('on'); dt.dataset.anchor = p.dataset.anchor;
      dt.querySelector('summary').scrollIntoView({block: 'nearest', behavior: 'smooth'});
    });
  });
  $('rv-form').onsubmit = async e => {
    e.preventDefault();
    if (!current) return;
    const fd = new FormData(e.target);
    try {
      const rv = await api(`/api/runs/${runId}/review`, {method: 'POST', body: JSON.stringify({
        scenario: current.dataset.scn, call: current.dataset.call, verdict: fd.get('verdict'),
        anchor: current.dataset.anchor || '', note: fd.get('note'),
      })});
      toast(`Đã lưu review ${rv.verdict}${rv.anchor ? ' · ' + rv.anchor : ''}`, true);
      openRunPanel(runId);
    } catch {}
  };
}

/* ================= DASHBOARD ================= */
async function renderDash(){
  $('main').innerHTML = '<div class="loading"></div>';
  const days = new URLSearchParams(location.search).get('days') || 14;
  const s = await api(`/api/stats?days=${days}`);
  $('main').innerHTML = `
    <section class="card">
      <div class="row"><h2 style="margin:0">Xu hướng ${s.days} ngày</h2>
        <span class="hint">${s.runs} run · ${s.rows} call · ${s.reviewed} đã review</span>
        <select id="days-sel" style="margin-left:auto">${[7,14,30].map(d => `<option value="${d}" ${d == days ? 'selected' : ''}>${d} ngày</option>`).join('')}</select></div>
      ${s.scenarios.length ? `<table><tr><th>Kịch bản</th><th style="width:130px">Pass-rate</th><th>Fail/Blk</th><th>Issue</th><th>Review</th></tr>
      ${s.scenarios.map(x => {
        const rate = x.total ? Math.round(100 * x.pass / x.total) : 0;
        return `<tr><td><code>${esc(x.scenario.split('/').pop())}</code> <span class="mut">${esc(x.target)}</span></td>
          <td><div class="bar"><i style="width:${rate}%; background:${rate === 100 ? 'var(--pass)' : rate >= 60 ? 'var(--warn)' : 'var(--fail)'}"></i></div> <span class="mut">${rate}%</span></td>
          <td><b class="${x.fail + x.blocked ? 'bad' : 'mut'}">${x.fail}/${x.blocked}</b></td>
          <td><b class="${x.issues ? 'bad' : 'mut'}">${x.issues}</b></td>
          <td class="mut">${x.reviewed}/${x.total}</td></tr>`;
      }).join('')}</table>` : '<div class="empty"><b>Chưa có dữ liệu</b>chạy test trước rồi quay lại đây</div>'}
      <p class="hint" style="margin-top:10px">Sắp theo nhiều vấn đề nhất · issue mở/đóng quản ngoài tool</p>
    </section>`;
  $('days-sel').onchange = e => { history.replaceState(null, '', `?days=${e.target.value}`); renderDash(); };
}

/* ================= BOT — xem + sửa nghiệp vụ ================= */
async function renderBot(){
  $('main').innerHTML = '<div class="loading"></div>';
  const bots = await api('/api/bots');
  const canEdit = ME.role === 'admin';
  $('main').innerHTML = `
    <section class="card">
      <div class="row">
        <label>Bot <select id="bsel">${bots.map(b => `<option value="${esc(b.bot)}">${esc(b.display_name)}</option>`).join('')}</select></label>
        <span class="hint">knowledge = rubric chấm${canEdit ? ' · admin có thể sửa trực tiếp, mọi thay đổi commit git' : ' (chỉ admin sửa)'}</span>
        ${canEdit ? '<button class="btn" id="edit-know" style="margin-left:auto">✎ Sửa business.md</button>' : ''}
      </div>
      <pre id="know" class="know">đang tải…</pre>
    </section>
    <section class="card">
      <div class="row"><h2 style="margin:0">Kịch bản & tình huống</h2>
        ${canEdit ? '<button class="btn" id="add-scn" style="margin-left:auto">+ Kịch bản</button><button class="btn" id="add-sit">+ Tình huống</button>' : ''}</div>
      <div id="src-list" class="row" style="gap:7px"></div>
    </section>`;
  const load = async () => {
    const k = await api(`/api/bots/${$('bsel').value}/knowledge`);
    $('know').textContent = k.business || '(chưa có knowledge/business.md)';
    await loadSources();
  };
  async function loadSources(){
    const bot = $('bsel').value;
    const scns = await api(`/api/bots/${bot}/scenarios`);
    const el = $('src-list');
    el.innerHTML = scns.filter(s => !s.error).map(s =>
      `<span class="chip">${canEdit ? `<button class="link" data-edit-scn="${esc(s.id.split('/').pop())}">✎</button> ` : ''}<b>${esc(s.id.split('/').pop())}</b> <span class="badge ${s.mode}">${s.mode}</span></span>`
    ).join('') + (canEdit ? `<span class="hint">tình huống: ${esc(bot)} — nút + ở trên</span>` : '');
    el.querySelectorAll('[data-edit-scn]').forEach(b => b.onclick = () => editSource(bot, 'scenarios', b.dataset.editScn));
  }
  $('bsel').onchange = load;
  if (canEdit) {
    $('edit-know').onclick = async () => editKnowledge($('bsel').value);
    $('add-scn').onclick = () => editSource($('bsel').value, 'scenarios', null);
    $('add-sit').onclick = () => editSource($('bsel').value, 'situations', null);
  }
  await load();
}

async function editKnowledge(bot){
  const k = await api(`/api/bots/${bot}/knowledge`);
  openPanel(`
    <div class="phead"><h2>Sửa nghiệp vụ — ${esc(bot)}</h2><button class="x">✕</button></div>
    <p class="hint">Nguồn trust cho QA và push lên cloud bot. Mỗi lần lưu = 1 commit git mang tên bạn.</p>
    <textarea id="k-edit" class="know" style="width:100%; min-height:52vh">${esc(k.business)}</textarea>
    <div class="row" style="margin-top:10px">
      <button class="go" id="k-save">Lưu</button>
      <span class="hint">bắt buộc không để trống</span></div>`);
  $('k-save').onclick = async () => {
    try {
      const r = await api(`/api/bots/${bot}/knowledge`, {method: 'PUT', body: JSON.stringify({business: $('k-edit').value})});
      toast('Đã lưu' + (r.commit ? ` · commit ${r.commit}` : ''), true);
      closePanel(); renderBot();
    } catch {}
  };
}

async function editSource(bot, kind, name){
  const label = kind === 'scenarios' ? 'kịch bản' : 'tình huống';
  let yaml = '', title = name ? `Sửa ${label}: ${name}` : `Thêm ${label}`;
  if (name) yaml = (await api(`/api/bots/${bot}/${kind}/${name}/source`)).yaml;
  else yaml = kind === 'scenarios'
    ? `mode: llm\nsuite: ${esc(bot)}\nname: ten-kich-ban\ntarget: ${esc(bot)}\ngoal: >-\n  ...\nmax_turns: 10\n`
    : `name: ten-tinh-huong\ngoal: |\n  ...\nextra_turns: 2\n`;
  openPanel(`
    <div class="phead"><h2>${esc(title)}</h2>${name ? `<button class="btn danger" id="src-del">Xoá</button>` : ''}<button class="x">✕</button></div>
    ${!name ? `<div class="row"><label>Tên file <input id="src-name" placeholder="ten-khong-dau" style="width:200px"></label></div>` : ''}
    <textarea id="src-edit" class="know" style="width:100%; min-height:52vh" spellcheck="false">${esc(yaml)}</textarea>
    <div class="row" style="margin-top:10px">
      <button class="go" id="src-save">Lưu (validate)</button>
      <span class="hint">server kiểm tra bằng chính loader — sai cú pháp sẽ chặn, file nguyên vẹn</span></div>`);
  $('src-save').onclick = async () => {
    const finalName = name || $('src-name').value.trim();
    if (!finalName) return toast('Đặt tên file trước');
    try {
      const r = name
        ? await api(`/api/bots/${bot}/${kind}/${name}/source`, {method: 'PUT', body: JSON.stringify({yaml: $('src-edit').value})})
        : await api(`/api/bots/${bot}/${kind}`, {method: 'POST', body: JSON.stringify({name: finalName, yaml: $('src-edit').value})});
      toast('Đã lưu' + (r.commit ? ` · commit ${r.commit}` : ''), true);
      closePanel(); renderBot();
    } catch {}
  };
  const del = $('src-del');
  if (del) del.onclick = async () => {
    if (!confirm(`Xoá ${label} ${name}?`)) return;
    try { await api(`/api/bots/${bot}/${kind}/${name}`, {method: 'DELETE'}); toast('Đã xoá', true); closePanel(); renderBot(); } catch {}
  };
}

/* ================= ADMIN ================= */
async function renderAdmin(){
  if (ME.role !== 'admin') { $('main').innerHTML = '<p class="hint">chỉ admin</p>'; return; }
  const users = await api('/api/users');
  $('main').innerHTML = `
    <section class="card">
      <h2>Người dùng</h2>
      <table><tr><th>Tên</th><th>Vai trò</th><th style="width:170px"></th></tr>
        ${users.map(u => `<tr><td><b>${esc(u.name)}</b></td><td>${esc(u.role)}</td>
          <td><button class="btn" data-rot="${esc(u.name)}">Xoay key</button>
              <button class="btn danger" data-del="${esc(u.name)}">Xoá</button></td></tr>`).join('')}</table>
      <form id="add-user" class="row" style="margin-top:12px">
        <input name="name" placeholder="tên (a-z0-9)" required>
        <select name="role"><option value="member">member</option><option value="admin">admin — được sửa nghiệp vụ</option></select>
        <button class="go" type="submit">Thêm người</button>
      </form>
      <p class="hint">Key chỉ hiện MỘT lần — gửi ngay. admin = chạy được + sửa nghiệp vụ/kịch bản (có git audit).</p>
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
    try { const r = await api(`/api/users/${b.dataset.rot}/rotate`, {method: 'POST'}); showKeyOnce(r.name, r.key); } catch {}
  });
  document.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm(`Xoá ${b.dataset.del}?`)) return;
    try { await api(`/api/users/${b.dataset.del}`, {method: 'DELETE'}); renderAdmin(); } catch {}
  });
}

function showKeyOnce(who, key){
  const box = $('new-key'); box.style.display = '';
  box.innerHTML = `<p class="warn">Key của <b>${esc(who)}</b> (chỉ hiện lần này):</p>
    <div class="row"><code class="know" style="flex:1">${esc(key)}</code><button class="btn" onclick="copyText('${esc(key)}')">Copy</button></div>`;
}
