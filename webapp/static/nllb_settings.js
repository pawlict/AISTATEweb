"use strict";

// NLLB Settings page JS
// - Task progress at the top
// - Install deps (transformers/sentencepiece)
// - Cache (predownload) selected NLLB models to HF cache

function qs(id){ return document.getElementById(id); }
function sleep(ms){ return new Promise(r=>setTimeout(r, ms)); }

let NLLB_STATUS = null;
let NLLB_MODELS_STATE = null;
let NLLB_CURRENT_TASK_ID = null;

function _tSafe(key, fallback){
  try{ if(typeof t === 'function') return t(key); }catch(e){}
  return fallback;
}

function setTaskLogsLink(taskId){
  const a = qs("nllb_task_open_logs");
  if(!a) return;
  if(!taskId){
    a.style.display = "none";
    a.href = "/logs";
    return;
  }
  a.href = `/logs?task_id=${encodeURIComponent(taskId)}`;
  a.style.display = "inline-flex";
}

function setBar(pct){
  const bar = qs("nllb_task_bar");
  if(!bar) return;
  const p = Math.max(0, Math.min(100, parseInt(pct || 0, 10)));
  bar.style.width = p + "%";
}

function setTaskUI(t){
  const st = qs("nllb_task_status");
  const pct = qs("nllb_task_pct");
  if(st) st.textContent = t ? (t.status || "—") : "—";
  if(pct) pct.textContent = (t ? (t.progress || 0) : 0) + "%";
  setBar(t ? t.progress : 0);
}

function _pkgLine(info){
  if(info && info.installed) return `✅ installed (${info.version || "unknown"})`;
  return "❌ not installed";
}

function depsInstalled(){
  if(!NLLB_STATUS) return false;
  const tf = (NLLB_STATUS.transformers || {}).installed;
  const sp = (NLLB_STATUS.sentencepiece || {}).installed;
  return !!(tf && sp);
}

async function refreshStatus(){
  try{
    NLLB_STATUS = await api("/api/nllb/status");
    const s = NLLB_STATUS || {};

    const deps = qs("nllb_deps_status");
    const fast = qs("nllb_fast_status");
    const acc = qs("nllb_accurate_status");

    const tf = _pkgLine(s.transformers);
    const sp = _pkgLine(s.sentencepiece);
    const tc = _pkgLine(s.torch);
    const sm = _pkgLine(s.sacremoses);

    if(deps) deps.textContent = `transformers: ${tf} • sentencepiece: ${sp} • torch: ${tc} • sacremoses: ${sm}`;

    const ok = depsInstalled();
    if(fast) fast.textContent = ok ? _tSafe('nllb.ready', '✅ gotowe') : _tSafe('nllb.needs_deps', '⚠️ zainstaluj zależności');
    if(acc) acc.textContent = ok ? _tSafe('nllb.ready', '✅ gotowe') : _tSafe('nllb.needs_deps', '⚠️ zainstaluj zależności');

    // deps button
    const btn = qs("nllb_deps_install_btn");
    if(btn) btn.style.display = ok ? "none" : "inline-flex";
    const inline = qs("nllb_deps_inline");
    if(inline) inline.textContent = ok ? _tSafe('nllb.deps_installed', '✅ zależności zainstalowane') : _tSafe('nllb.deps_hint', 'Kliknij „Instaluj”, aby doinstalować transformers/sentencepiece');

    return s;
  }catch(e){
    console.warn("NLLB status failed", e);
    return null;
  }
}

async function refreshModelStates(force){
  try{
    const url = force ? '/api/nllb/models_state?refresh=1' : '/api/nllb/models_state';
    NLLB_MODELS_STATE = await api(url);
    return NLLB_MODELS_STATE;
  }catch(e){
    console.warn('NLLB models_state failed', e);
    NLLB_MODELS_STATE = null;
    return null;
  }
}

function notInstalledSuffix(){
  return _tSafe('nllb.model_not_installed_suffix', ' (niezainstalowany)');
}

function modelCached(mode, id){
  if(!id) return false;
  const ms = NLLB_MODELS_STATE || {};
  const key = (String(mode||'').toLowerCase() === 'accurate') ? 'accurate' : 'fast';
  const d = ms[key] || {};
  return !!d[id];
}

function updateSelectLabels(mode){
  const selId = (String(mode||'') === 'accurate') ? 'nllb_accurate_select' : 'nllb_fast_select';
  const sel = qs(selId);
  if(!sel) return;
  const suff = notInstalledSuffix();
  for(const opt of Array.from(sel.options || [])){
    const v = opt.value || '';
    if(!v) continue;
    const ok = modelCached(mode, v);
    opt.textContent = v + (ok ? '' : suff);
  }
}

function updateAllSelectLabels(){
  updateSelectLabels('fast');
  updateSelectLabels('accurate');
}

function updateInstallButton(mode){
  const btnId = (String(mode||'') === 'accurate') ? 'nllb_accurate_install_btn' : 'nllb_fast_install_btn';
  const inlineId = (String(mode||'') === 'accurate') ? 'nllb_accurate_inline' : 'nllb_fast_inline';
  const btn = qs(btnId);
  const inline = qs(inlineId);
  if(!btn || !inline) return;

  const sel = (String(mode||'') === 'accurate') ? qs('nllb_accurate_select') : qs('nllb_fast_select');
  const id = sel ? (sel.value || '') : '';

  if(!id){
    btn.style.display = 'inline-flex';
    inline.textContent = _tSafe('nllb.select_model', 'Wybierz model…');
    return;
  }

  const okDeps = depsInstalled();
  const cached = modelCached(mode, id);

  if(cached){
    btn.style.display = 'none';
    inline.textContent = _tSafe('nllb.model_installed_inline', '✅ zainstalowany');
    return;
  }

  btn.style.display = 'inline-flex';
  inline.textContent = okDeps ? _tSafe('nllb.model_not_installed_inline', '❌ niezainstalowany') : _tSafe('nllb.needs_deps_inline', '⚠️ zainstaluj zależności');
}

function updateAllInstallButtons(){
  updateInstallButton('fast');
  updateInstallButton('accurate');
}

function esc(s){
  return String(s || "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#39;");
}

// Model info presets
const NLLB_INFO = {
  "facebook/nllb-200-distilled-600M": {
    tier: "fast",
    params: "~600M",
    langs_k: "nllb.value.langs.nllb200",
    offline_k: "nllb.value.offline_yes",
    vram_k: "nllb.value.vram.cpu_ok_gpu_4_6",
    ram_k: "nllb.value.ram.16_recommended",
    disk_k: "nllb.value.disk.cache_3_6",
    speed_k: "nllb.value.speed.fast",
    quality_k: "nllb.value.quality.balanced",
    use_ks: ["nllb.use.on_the_fly", "nllb.use.drafts", "nllb.use.bulk"],
    notes_k: "nllb.notes.distilled_600m"
  },
  "facebook/nllb-200-distilled-1.3B": {
    tier: "accurate",
    params: "~1.3B",
    langs_k: "nllb.value.langs.nllb200",
    offline_k: "nllb.value.offline_yes",
    vram_k: "nllb.value.vram.cpu_ok_gpu_6_10",
    ram_k: "nllb.value.ram.24_recommended",
    disk_k: "nllb.value.disk.cache_6_12",
    speed_k: "nllb.value.speed.medium",
    quality_k: "nllb.value.quality.very_good",
    use_ks: ["nllb.use.better_quality", "nllb.use.cyrillic", "nllb.use.balanced_daily"],
    notes_k: "nllb.notes.distilled_1_3b"
  },
  "facebook/nllb-200-3.3B": {
    tier: "accurate",
    params: "~3.3B",
    langs_k: "nllb.value.langs.nllb200",
    offline_k: "nllb.value.offline_yes",
    vram_k: "nllb.value.vram.cpu_ok_gpu_14_24",
    ram_k: "nllb.value.ram.32_recommended",
    disk_k: "nllb.value.disk.cache_12_25",
    speed_k: "nllb.value.speed.slow",
    quality_k: "nllb.value.quality.best",
    use_ks: ["nllb.use.highest_quality", "nllb.use.long_docs", "nllb.use.demanding_langs"],
    notes_k: "nllb.notes.base_3_3b"
  }
};

function infoFor(modelId){
  const id = String(modelId||'').trim();
  const base = NLLB_INFO[id] || null;

  const vOr = (key, fallback) => {
    if(!key) return fallback || '';
    return _tSafe(key, fallback || key);
  };

  if(base){
    const use = Array.isArray(base.use_ks) ? base.use_ks.map(k => _tSafe(k, k)).filter(Boolean) : [];
    return {
      name: id,
      params: base.params || '—',
      langs: vOr(base.langs_k, '—'),
      offline: vOr(base.offline_k, '—'),
      quality: vOr(base.quality_k, '—'),
      speed: vOr(base.speed_k, '—'),
      vram: vOr(base.vram_k, '—'),
      ram: vOr(base.ram_k, '—'),
      disk: vOr(base.disk_k, '—'),
      use,
      notes: vOr(base.notes_k, '')
    };
  }

  // Fallback for unknown model id
  return {
    name: id || "—",
    offline: vOr("nllb.value.offline_yes", "✅ Tak"),
    langs: vOr("nllb.value.langs.generic", "NLLB (wielojęzyczny)"),
    vram: vOr("nllb.value.vram.generic", "CPU OK • GPU: zależnie od rozmiaru"),
    ram: vOr("nllb.value.ram.generic", "16GB+"),
    disk: vOr("nllb.value.disk.generic", "Cache HF"),
    speed: "—",
    quality: "—",
    use: [],
    notes: ""
  };
}

function renderInfo(mode, modelId){
  const m = (String(mode||'') === 'accurate') ? 'accurate' : 'fast';
  const boxName = qs(m === 'accurate' ? 'nllb_accurate_info_name' : 'nllb_fast_info_name');
  const boxBody = qs(m === 'accurate' ? 'nllb_accurate_info_body' : 'nllb_fast_info_body');
  const boxWarn = qs(m === 'accurate' ? 'nllb_accurate_info_warning' : 'nllb_fast_info_warning');

  const info = infoFor(modelId);
  if(boxName) boxName.textContent = info.name || '—';

  if(boxBody){
    const rows = [
      {k: _tSafe('nllb.info.params','Parametry'), v: info.params || '—'},
      {k: _tSafe('nllb.info.languages','Języki'), v: info.langs || '—'},
      {k: _tSafe('nllb.info.offline','Offline'), v: info.offline || '—'},
      {k: _tSafe('nllb.info.quality','Jakość'), v: info.quality || '—'},
      {k: _tSafe('nllb.info.speed','Szybkość'), v: info.speed || '—'},
      {k: _tSafe('nllb.info.vram','VRAM'), v: info.vram || '—'},
      {k: _tSafe('nllb.info.ram','RAM'), v: info.ram || '—'},
      {k: _tSafe('nllb.info.disk','Dysk'), v: info.disk || '—'},
    ];
    let html = `<div class="nllb-kv">`;
    for(const r of rows){
      html += `<div class="kv-h">${esc(r.k)}</div><div>${esc(r.v)}</div>`;
    }
    if(info.use && info.use.length){
      html += `<div class="kv-h">${esc(_tSafe('nllb.info.use_cases','Zastosowania'))}</div><div>${esc(info.use.join(' • '))}</div>`;
    }
    if(info.notes){
      html += `<div class="kv-h">${esc(_tSafe('nllb.info.notes','Uwagi'))}</div><div>${esc(info.notes)}</div>`;
    }
    html += `</div>`;
    boxBody.innerHTML = html;
  }

  if(boxWarn){
    boxWarn.style.display = 'none';
    boxWarn.textContent = '';

    if(!depsInstalled()){
      boxWarn.style.display = 'block';
      boxWarn.textContent = _tSafe('nllb.warn_deps','⚠️ Zainstaluj zależności (Transformers + SentencePiece) przed pobieraniem modeli.');
    }
  }
}

async function runTask(path, payload){
  const res = await api(path, {
    method: "POST",
    headers: {"content-type":"application/json"},
    body: JSON.stringify(payload || {}),
    keepalive: true
  });

  NLLB_CURRENT_TASK_ID = res.task_id;
  setTaskLogsLink(NLLB_CURRENT_TASK_ID);

  // Persist task so progress can be resumed after changing tabs/pages.
  try{
    if(window.AISTATE && typeof AISTATE.setTaskId === "function"){
      AISTATE.setTaskId("nllb", NLLB_CURRENT_TASK_ID);
    }
  }catch(e){}

  setTaskUI({status:"running", progress:0});

  while(true){
    const tsk = await api(`/api/tasks/${NLLB_CURRENT_TASK_ID}`);
    setTaskUI(tsk);
    if(tsk.status === "done" || tsk.status === "error"){
      try{ if(window.AISTATE && typeof AISTATE.setTaskId === "function") AISTATE.setTaskId("nllb", ""); }catch(e){}
      setTaskLogsLink(NLLB_CURRENT_TASK_ID);
      return tsk;
    }
    await sleep(700);
  }
}

async function resumeNllbTaskIfAny(){
  try{
    const tid = (window.AISTATE && typeof AISTATE.getTaskId === "function") ? AISTATE.getTaskId("nllb") : "";
    if(!tid) return;
    NLLB_CURRENT_TASK_ID = tid;
    setTaskLogsLink(tid);

    const tsk = await api(`/api/tasks/${tid}`);
    setTaskUI(tsk);

    if(tsk.status === "running" || tsk.status === "queued"){
      while(true){
        const cur = await api(`/api/tasks/${tid}`);
        setTaskUI(cur);
        if(cur.status === "done" || cur.status === "error") break;
        await sleep(700);
      }
    }

    try{ if(window.AISTATE && typeof AISTATE.setTaskId === "function") AISTATE.setTaskId("nllb", ""); }catch(e){}
  }catch(e){
    try{ if(window.AISTATE && typeof AISTATE.setTaskId === "function") AISTATE.setTaskId("nllb", ""); }catch(_e){}
  }
}

async function installDeps(){
  const t1 = await runTask('/api/nllb/install_deps', {});
  await refreshStatus();
  await refreshModelStates(true);
  updateAllSelectLabels();
  updateAllInstallButtons();
  // Update infos for current selections
  const f = qs('nllb_fast_select');
  const a = qs('nllb_accurate_select');
  renderInfo('fast', f ? f.value : '');
  renderInfo('accurate', a ? a.value : '');
  return t1;
}

async function installModel(mode){
  const sel = (String(mode||'') === 'accurate') ? qs('nllb_accurate_select') : qs('nllb_fast_select');
  const id = sel ? (sel.value || '') : '';
  if(!id){
    updateInstallButton(mode);
    return;
  }

  // Ensure deps first
  await refreshStatus();
  if(!depsInstalled()){
    const t0 = await installDeps();
    if(t0.status === 'error') return;
  }

  await runTask('/api/nllb/predownload', {mode: String(mode||'fast'), model: id});

  await refreshStatus();
  await refreshModelStates(true);
  updateAllSelectLabels();
  updateAllInstallButtons();
  renderInfo(mode, id);
}

function bindUI(){
  const depsBtn = qs('nllb_deps_install_btn');
  if(depsBtn){
    depsBtn.addEventListener('click', async ()=>{
      try{ await installDeps(); }catch(e){ console.warn(e); }
    });
  }

  const fastSel = qs('nllb_fast_select');
  const accSel = qs('nllb_accurate_select');
  if(fastSel){
    fastSel.addEventListener('change', ()=>{ renderInfo('fast', fastSel.value || ''); updateInstallButton('fast'); });
    fastSel.addEventListener('click', ()=>{ renderInfo('fast', fastSel.value || ''); updateInstallButton('fast'); });
  }
  if(accSel){
    accSel.addEventListener('change', ()=>{ renderInfo('accurate', accSel.value || ''); updateInstallButton('accurate'); });
    accSel.addEventListener('click', ()=>{ renderInfo('accurate', accSel.value || ''); updateInstallButton('accurate'); });
  }

  const fastBtn = qs('nllb_fast_install_btn');
  const accBtn = qs('nllb_accurate_install_btn');
  if(fastBtn){
    fastBtn.addEventListener('click', async ()=>{
      try{ await installModel('fast'); }catch(e){ console.warn(e); }
    });
  }
  if(accBtn){
    accBtn.addEventListener('click', async ()=>{
      try{ await installModel('accurate'); }catch(e){ console.warn(e); }
    });
  }
}

document.addEventListener('DOMContentLoaded', async ()=>{
  setTaskUI(null);
  await resumeNllbTaskIfAny();
  await refreshStatus();
  await refreshModelStates(true);
  updateAllSelectLabels();
  updateAllInstallButtons();

  // render initial infos
  const fastSel = qs('nllb_fast_select');
  const accSel = qs('nllb_accurate_select');
  renderInfo('fast', fastSel ? fastSel.value : '');
  renderInfo('accurate', accSel ? accSel.value : '');

  bindUI();
});
