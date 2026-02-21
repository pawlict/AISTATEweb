// ---------- UI language (i18n) ----------
// ---------- UI language (i18n) ----------
// Translations are stored in: webapp/static/lang/{lang}.json
// (e.g., /static/lang/pl.json, /static/lang/en.json)

const LANG_BASE = "/static/lang";
let I18N = { en: {} };
let LANG_INDEX = null;
const _I18N_LOADED = Object.create(null);

// Try to reuse the same cache-busting version used for /static/app.js?v=...
function _assetVersion(){
  try{
    const s = document.querySelector('script[src*="/static/app.js"]');
    if(s){
      const u = new URL(s.src, location.href);
      return u.searchParams.get("v") || "";
    }
  }catch(e){}
  return "";
}
const _ASSET_V = _assetVersion();

function _langUrl(file){
  return `${LANG_BASE}/${file}${_ASSET_V ? `?v=${encodeURIComponent(_ASSET_V)}` : ""}`;
}

async function _fetchJson(url){
  const res = await fetch(url, { cache: "no-cache" });
  if(!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return await res.json();
}

async function loadLangIndex(){
  if(LANG_INDEX) return LANG_INDEX;
  try{
    LANG_INDEX = await _fetchJson(_langUrl("index.json"));
  }catch(e){
    // Fallback if index.json is missing
    LANG_INDEX = {
      "default": "pl",
      "supported": [
        {"code":"pl","name":"Polski"},
        {"code":"en","name":"English"}
      ]
    };
  }
  return LANG_INDEX;
}

function _normalizeLang(code, supported, fallback){
  if(!code) return fallback;
  const c = String(code);
  if(supported.includes(c)) return c;

  const base = c.split("-")[0];
  if(supported.includes(base)) return base;

  const lower = c.toLowerCase();
  const exact = supported.find(s => String(s).toLowerCase() === lower);
  if(exact) return exact;

  const baseLower = base.toLowerCase();
  const byBase = supported.find(s => String(s).split("-")[0].toLowerCase() === baseLower);
  if(byBase) return byBase;

  return fallback;
}

function detectBrowserLang(supported, fallback){
  try{
    const cands = [];
    if(Array.isArray(navigator.languages)) cands.push(...navigator.languages);
    if(navigator.language) cands.push(navigator.language);

    for(const c of cands){
      const n = _normalizeLang(c, supported, null);
      if(n) return n;
    }
  }catch(e){}
  return fallback;
}

async function loadI18n(lang){
  const idx = await loadLangIndex();
  const supported = (idx.supported || []).map(o => o.code);
  const fallback = idx.default || "pl";
  const chosen = _normalizeLang(lang, supported, fallback);

  // Always load EN as fallback (if present)
  if(!_I18N_LOADED.en){
    try{ I18N.en = await _fetchJson(_langUrl("en.json")); }catch(e){ I18N.en = I18N.en || {}; }
    _I18N_LOADED.en = true;
  }

  if(!_I18N_LOADED[chosen]){
    try{ I18N[chosen] = await _fetchJson(_langUrl(`${chosen}.json`)); }catch(e){ I18N[chosen] = I18N[chosen] || {}; }
    _I18N_LOADED[chosen] = true;
  }

  return chosen;
}

// Call this once at startup before applyI18n()
async function initI18n(){
  const idx = await loadLangIndex();
  const supported = (idx.supported || []).map(o => o.code);
  const fallback = idx.default || "pl";

  const saved = localStorage.getItem("aistate_ui_lang");
  const initial = saved || detectBrowserLang(supported, fallback);
  const chosen = await loadI18n(initial);

  // Persist normalized choice
  localStorage.setItem("aistate_ui_lang", chosen);
  return chosen;
}

// Optional helper: populate <select> from lang/index.json (future-proof for many languages)
async function populateUiLangSelect(selectEl){
  if(!selectEl) return;
  const idx = await loadLangIndex();
  const list = idx.supported || [];
  // Replace options with index.json list
  selectEl.innerHTML = "";
  for(const it of list){
    const opt = document.createElement("option");
    opt.value = it.code;
    opt.textContent = it.name || it.code;
    selectEl.appendChild(opt);
  }
}





// ---------- Helper: parse timestamps from a line ----------
// Supports:
// 1) diarization: [12.34-15.67] SPEAKER_00: ...
// 2) transcription: [HH:MM:SS(.ms) - HH:MM:SS(.ms)] ...
function parseLineTimes(line){
  if(!line) return null;

  // Diarization seconds format
  let m = line.match(/^\s*\[(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\]/);
  if(m){
    const s0 = parseFloat(m[1]);
    const s1 = parseFloat(m[2]);
    if(isFinite(s0) && isFinite(s1) && s1 > s0) return {start: s0, end: s1};
  }

  // Transcription HH:MM:SS(.ms) format
  m = line.match(/^\s*\[(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?\s*-\s*(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?\]/);
  if(m){
    const h0=+m[1], mi0=+m[2], se0=+m[3], ms0=+(m[4]||"0");
    const h1=+m[5], mi1=+m[6], se1=+m[7], ms1=+(m[8]||"0");
    const s0 = h0*3600 + mi0*60 + se0 + ms0/1000;
    const s1 = h1*3600 + mi1*60 + se1 + ms1/1000;
    if(isFinite(s0) && isFinite(s1) && s1 > s0) return {start: s0, end: s1};
  }

  return null;
}


// ---------- Helper: get project audio URL ----------
function getProjectAudioUrl(){
  try{
    const pid = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) ? String(AISTATE.projectId) : "";
    const af  = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.audioFile) ? String(AISTATE.audioFile) : "";
    if(!pid || !af) return "";
    return `/api/projects/${pid}/download/${encodeURIComponent(af)}`;
  }catch(e){
    return "";
  }
}


// ---------- Helper: enforce playback within a diarization/transcription block ----------
// If `times` is provided, playback/seek is constrained to [start,end] seconds.
function attachSegmentGuards(audioEl, times){
  if(!audioEl || !times || !isFinite(times.start) || !isFinite(times.end) || times.end <= times.start){
    return function(){};
  }
  const start = Math.max(0, times.start);
  const end   = Math.max(start, times.end);
  const EPS   = 0.03;

  const clamp = ()=>{
    try{
      if(audioEl.currentTime < start) audioEl.currentTime = start;
      if(audioEl.currentTime > end) audioEl.currentTime = end;
    }catch(e){}
  };

  const onPlay = ()=>{
    // If user hits play from outside the segment, jump to segment start
    try{
      if(audioEl.currentTime < start || audioEl.currentTime >= (end - EPS)){
        audioEl.currentTime = start;
      }
    }catch(e){}
  };

  const onTimeUpdate = ()=>{
    try{
      if(audioEl.currentTime >= (end - EPS)){
        audioEl.pause();
        audioEl.currentTime = end; // Stop at end of block
      }
    }catch(e){}
  };

  const onSeeking = clamp;

  audioEl.addEventListener("play", onPlay);
  audioEl.addEventListener("timeupdate", onTimeUpdate);
  audioEl.addEventListener("seeking", onSeeking);

  // Initial clamp
  clamp();

  return function cleanup(){
    try{ audioEl.removeEventListener("play", onPlay); }catch(e){}
    try{ audioEl.removeEventListener("timeupdate", onTimeUpdate); }catch(e){}
    try{ audioEl.removeEventListener("seeking", onSeeking); }catch(e){}
  };
}

// ---------- Helper: generate localStorage key for drafts ----------
function draftKey(id){
  return `aistate_draft_${id}`;
}

// ---------- i18n helpers ----------
function getUiLang(){
  return localStorage.getItem("aistate_ui_lang") || "pl";
}
function setUiLang(lang){
  localStorage.setItem("aistate_ui_lang", lang || "pl");
}
function t(key){
  const lang = getUiLang();
  return (I18N[lang] && I18N[lang][key]) || (I18N.en && I18N.en[key]) || key;
}

// Very small templating helper: tFmt("key", {count: 3}) -> replaces {count}
function tFmt(key, vars={}){
  let s = String(t(key));
  try{
    Object.keys(vars || {}).forEach(k=>{
      s = s.split(`{${k}}`).join(String(vars[k]));
    });
  }catch(e){}
  return s;
}

function applyI18n(){
  const lang = getUiLang();
  document.documentElement.lang = lang;

  // Text content
  document.querySelectorAll("[data-i18n]").forEach(el=>{
    const key = el.getAttribute("data-i18n");
    if(!key) return;
    const v = t(key);
    // If translation is missing, keep the original (template) text instead of showing the key.
    if(v !== key) el.textContent = v;
  });

  // HTML content (use carefully; trusted templates only)
  document.querySelectorAll("[data-i18n-html]").forEach(el=>{
    const key = el.getAttribute("data-i18n-html");
    if(!key) return;
    const v = t(key);
    if(v !== key) el.innerHTML = v;
  });

  // Placeholders
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el=>{
    const key = el.getAttribute("data-i18n-placeholder");
    if(!key) return;
    const v = t(key);
    if(v !== key) el.setAttribute("placeholder", v);
  });

  // Title attributes
  document.querySelectorAll("[data-i18n-title]").forEach(el=>{
    const key = el.getAttribute("data-i18n-title");
    if(!key) return;
    const v = t(key);
    if(v !== key) el.setAttribute("title", v);
  });
}

// ---------- Sidebar: collapse/expand (sticky, scrollable) ----------
function _setSidebarCollapsed(collapsed){
  try{
    document.body.classList.toggle("sidebar-collapsed", !!collapsed);
    localStorage.setItem("aistate_sidebar_collapsed", collapsed ? "1" : "0");

    const btn = document.getElementById("sidebar_toggle");
    if(btn){
      const key = collapsed ? "sidebar.expand" : "sidebar.collapse";
      btn.setAttribute("data-i18n-title", key);
      const lbl = t(key);
      btn.setAttribute("aria-label", lbl);
      btn.setAttribute("title", lbl);
    }
  }catch(e){}
}

function initSidebar(){
  try{
    const collapsed = localStorage.getItem("aistate_sidebar_collapsed") === "1";
    _setSidebarCollapsed(collapsed);

    const btn = document.getElementById("sidebar_toggle");
    if(btn && !btn._aistateBound){
      btn._aistateBound = true;
      btn.addEventListener("click", ()=>{
        const now = !document.body.classList.contains("sidebar-collapsed");
        _setSidebarCollapsed(now);
        // Apply translated tooltip after we swapped the key
        applyI18n();
      });
    }
  }catch(e){}
}

// ---------- Global state: current project ----------
const AISTATE = {
  get projectId(){
    return localStorage.getItem("aistate_project_id") || "";
  },
  set projectId(v){
    if(v) localStorage.setItem("aistate_project_id", v);
    else localStorage.removeItem("aistate_project_id");
  },

  get audioFile(){
    return localStorage.getItem("aistate_audio_file") || "";
  },
  set audioFile(v){
    if(v) localStorage.setItem("aistate_audio_file", v);
    else localStorage.removeItem("aistate_audio_file");
  },

  getTaskId(prefix){
    return localStorage.getItem(`aistate_task_${prefix}`) || "";
  },
  setTaskId(prefix, v){
    if(v) localStorage.setItem(`aistate_task_${prefix}`, v);
    else localStorage.removeItem(`aistate_task_${prefix}`);
  },

  get lastTaskId(){
    return localStorage.getItem("aistate_last_task_id") || "";
  },
  set lastTaskId(v){
    if(v) localStorage.setItem("aistate_last_task_id", v);
    else localStorage.removeItem("aistate_last_task_id");
  }
};

// ---------- API helper ----------
async function api(url, opts={}){
  const res = await fetch(url, opts);
  const ct = (res.headers.get("content-type") || "").toLowerCase();

  // Read body once (json preferred). We also try to interpret text as JSON.
  let dataJson = null;
  let dataText = "";
  if(ct.includes("application/json")){
    try{ dataJson = await res.json(); }catch(e){ dataJson = null; }
  }else{
    try{ dataText = await res.text(); }catch(e){ dataText = ""; }
    const t = (dataText || "").trim();
    if(t.startsWith("{") || t.startsWith("[")){
      try{ dataJson = JSON.parse(t); }catch(e){ /* ignore */ }
    }
  }

  if(!res.ok){
    const msg = (dataJson && (dataJson.detail || dataJson.error || dataJson.message)) || dataText || ("HTTP " + res.status);
    throw new Error(String(msg).replace(/^\s+|\s+$/g, ""));
  }

  return (dataJson !== null) ? dataJson : dataText;
}

// ---------- Require active project (show dialog if missing, no redirect) ----------
async function requireProjectId(moduleType){
  _dbgLog("requireProjectId", `called with moduleType="${moduleType}", current projectId="${AISTATE.projectId}"`);
  const pid = AISTATE.projectId || "";

  if(pid){
    // Validate project still exists on backend
    try{
      await api(`/api/projects/${pid}/meta`);
      _dbgLog("requireProjectId", `project "${pid}" validated OK`);
      return pid;
    }catch(e){
      _dbgLog("requireProjectId", `project "${pid}" NOT FOUND on backend (${e.message}), clearing`);
      AISTATE.projectId = "";
      AISTATE.audioFile = "";
      // Fall through to show dialog
    }
  }

  // No project — show creation dialog and wait for result
  _dbgLog("requireProjectId", `no valid project, showing create dialog`);
  const newPid = await _showCreateProjectDialog();
  _dbgLog("requireProjectId", `dialog resolved with project_id="${newPid}"`);
  return newPid;
}

// ---------- Debug panel ----------
const _DBG_LOG = [];
function _dbgLog(fn, msg){
  const ts = new Date().toLocaleTimeString();
  const entry = `[${ts}] ${fn}: ${msg}`;
  _DBG_LOG.push(entry);
  if(_DBG_LOG.length > 200) _DBG_LOG.shift();
  console.log("%c[AISTATE-DBG]", "color:#0af;font-weight:bold", entry);
  // Update panel if open
  const el = document.getElementById("_dbg_panel_log");
  if(el) el.textContent = _DBG_LOG.join("\n");
}

function showDebugPanel(){
  let panel = document.getElementById("_dbg_panel");
  if(panel){ panel.style.display = panel.style.display === "none" ? "block" : "none"; return; }

  panel = document.createElement("div");
  panel.id = "_dbg_panel";
  panel.style.cssText = "position:fixed;bottom:0;right:0;width:600px;max-height:60vh;background:#1a1a2e;color:#0f0;font-family:monospace;font-size:12px;z-index:99999;border:2px solid #0af;border-radius:8px 0 0 0;display:flex;flex-direction:column;";
  panel.innerHTML = `
    <div style="padding:6px 12px;background:#0af;color:#000;font-weight:bold;display:flex;justify-content:space-between;align-items:center;cursor:move;">
      <span>AISTATE Debug Panel</span>
      <div>
        <button onclick="document.getElementById('_dbg_panel_log').textContent='';window._DBG_LOG_REF.length=0;" style="margin-right:8px;cursor:pointer;background:#333;color:#fff;border:1px solid #666;padding:2px 8px;border-radius:3px;">Clear</button>
        <button onclick="_dbgRunDiag()" style="margin-right:8px;cursor:pointer;background:#060;color:#0f0;border:1px solid #0f0;padding:2px 8px;border-radius:3px;">Run Diagnostics</button>
        <button onclick="document.getElementById('_dbg_panel').style.display='none'" style="cursor:pointer;background:#600;color:#f66;border:1px solid #f66;padding:2px 8px;border-radius:3px;">X</button>
      </div>
    </div>
    <div id="_dbg_panel_info" style="padding:8px 12px;border-bottom:1px solid #333;font-size:11px;color:#aaa;"></div>
    <pre id="_dbg_panel_log" style="flex:1;overflow:auto;padding:8px 12px;margin:0;white-space:pre-wrap;word-break:break-all;max-height:45vh;"></pre>
  `;
  document.body.appendChild(panel);

  window._DBG_LOG_REF = _DBG_LOG;

  // Show current state info
  _dbgUpdateInfo();
  document.getElementById("_dbg_panel_log").textContent = _DBG_LOG.join("\n");
}

function _dbgUpdateInfo(){
  const info = document.getElementById("_dbg_panel_info");
  if(!info) return;
  const lines = [
    `projectId: "${AISTATE.projectId || "(empty)"}"`,
    `audioFile: "${AISTATE.audioFile || "(empty)"}"`,
    `localStorage keys: ${Object.keys(localStorage).filter(k=>k.startsWith("aistate")).join(", ") || "(none)"}`,
    `URL: ${location.pathname}`,
  ];
  info.innerHTML = lines.map(l => `<div>${l}</div>`).join("");
}

async function _dbgRunDiag(){
  _dbgLog("DIAG", "=== Running full diagnostics ===");
  _dbgUpdateInfo();

  // 1. Check current state
  _dbgLog("DIAG", `AISTATE.projectId = "${AISTATE.projectId}"`);
  _dbgLog("DIAG", `AISTATE.audioFile = "${AISTATE.audioFile}"`);
  _dbgLog("DIAG", `localStorage aistate_project_id = "${localStorage.getItem("aistate_project_id")}"`);

  // 2. Test backend connectivity
  try{
    const r = await fetch("/api/projects/auto-create", {method:"OPTIONS"});
    _dbgLog("DIAG", `OPTIONS /api/projects/auto-create → ${r.status} ${r.statusText}`);
  }catch(e){
    _dbgLog("DIAG", `OPTIONS /api/projects/auto-create FAILED: ${e.message}`);
  }

  // 3. Test debug endpoint
  try{
    const r = await fetch("/api/debug/auto-create-check");
    const j = await r.json();
    _dbgLog("DIAG", `GET /api/debug/auto-create-check → ${JSON.stringify(j, null, 2)}`);
  }catch(e){
    _dbgLog("DIAG", `GET /api/debug/auto-create-check FAILED: ${e.message}`);
  }

  // 4. Try an actual auto-create
  _dbgLog("DIAG", "Attempting POST /api/projects/auto-create with type=debug_test...");
  try{
    const r = await fetch("/api/projects/auto-create", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({type: "debug_test"})
    });
    _dbgLog("DIAG", `POST status: ${r.status} ${r.statusText}`);
    const ct = r.headers.get("content-type") || "";
    _dbgLog("DIAG", `Content-Type: ${ct}`);
    const text = await r.text();
    _dbgLog("DIAG", `Response body: ${text.substring(0, 2000)}`);
  }catch(e){
    _dbgLog("DIAG", `POST FAILED: ${e.message}\n${e.stack}`);
  }

  // 5. Check if requireProjectId is the patched version
  _dbgLog("DIAG", `requireProjectId source contains _dbgLog: ${String(requireProjectId).includes("_dbgLog")}`);
  _dbgLog("DIAG", `window.requireProjectId === requireProjectId: ${window.requireProjectId === requireProjectId}`);

  // 6. Check startTask
  _dbgLog("DIAG", `startTask source contains requireProjectId: ${String(startTask).includes("requireProjectId")}`);

  _dbgLog("DIAG", "=== Diagnostics complete ===");
  _dbgUpdateInfo();
}

window.showDebugPanel = showDebugPanel;
window._dbgRunDiag = _dbgRunDiag;

// ---------- Refresh current project info in UI ----------
async function refreshCurrentProjectInfo(){
  const pid = AISTATE.projectId || "";

  if(!pid){
    AISTATE.audioFile = "";
    return;
  }

  try{
    const meta = await api(`/api/projects/${pid}/meta`);
    AISTATE.audioFile = meta.audio_file || "";
  }catch(e){
    AISTATE.audioFile = "";
  }
}

// ---------- Project status banner (auto-injected on module pages) ----------
function _injectProjectBanner(){
  // Only show on module pages (not projects page itself)
  const modulePaths = ["/diarization", "/transcription", "/analysis", "/analiza", "/translation", "/chat"];
  const path = location.pathname;
  if(!modulePaths.some(p => path.startsWith(p))) return;

  const pid = AISTATE.projectId || "";

  if(pid){
    // Project active — no banner, just silently validate in background
    api(`/api/projects/${pid}/meta`).catch(() => {
      // Project doesn't exist on backend anymore — clear it
      AISTATE.projectId = "";
      AISTATE.audioFile = "";
    });
    return;
  }

  // No project — show modal dialog (fire-and-forget, don't block page load)
  _showCreateProjectDialog().catch(() => {
    // User dismissed the dialog — warning banner is already shown by _showNoBanner
  });
}

/** Detect module type from current URL path */
function _detectModuleType(){
  const path = location.pathname;
  const typeMap = {"/diarization":"diarization", "/transcription":"transcription", "/analysis":"analysis", "/analiza":"analysis", "/translation":"translation", "/chat":"chat"};
  for(const [p, typ] of Object.entries(typeMap)){
    if(path.startsWith(p)) return typ;
  }
  return "analysis";
}

/** Module type → user-friendly label */
function _moduleLabel(type){
  const map = {
    transcription: t("banner.type_transcription") || "Transkrypcja",
    diarization: t("banner.type_diarization") || "Diaryzacja",
    analysis: t("banner.type_analysis") || "Analiza",
    chat: t("banner.type_chat") || "Chat",
    translation: t("banner.type_translation") || "Tłumaczenie"
  };
  return map[type] || type;
}

/**
 * Show project creation dialog (modal overlay).
 * Returns a Promise that resolves with the new project_id,
 * or rejects if the user dismisses the dialog.
 * Does NOT reload the page — caller can continue working.
 */
function _showCreateProjectDialog(){
  const moduleType = _detectModuleType();
  const moduleLabel = _moduleLabel(moduleType);

  // Remove previous dialog if still in DOM
  const prev = document.getElementById("_project_create_overlay");
  if(prev) prev.remove();

  return new Promise((resolve, reject) => {
    // Build modal overlay
    const overlay = document.createElement("div");
    overlay.id = "_project_create_overlay";
    overlay.className = "modal-overlay";
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:9999;padding:18px;";

    const panel = document.createElement("div");
    panel.style.cssText = "background:var(--card-bg,#fff);border-radius:12px;padding:0;box-shadow:0 8px 32px rgba(0,0,0,.18);width:90%;max-width:440px;overflow:hidden;";

    // Header
    const header = document.createElement("div");
    header.style.cssText = "padding:20px 24px 12px;border-bottom:1px solid var(--border,#e2e8f0);";
    header.innerHTML = `
      <div style="font-size:16px;font-weight:700;color:var(--text,#1e293b);">
        ${t("banner.dialog_title") || "Utwórz nowy projekt"}
      </div>
      <div style="font-size:13px;color:var(--text-muted,#64748b);margin-top:4px;">
        ${t("banner.dialog_subtitle") || "Utwórz projekt, aby rozpocząć pracę. Projekt będzie dostępny we wszystkich modułach."}
      </div>
    `;

    // Body
    const body = document.createElement("div");
    body.style.cssText = "padding:16px 24px;";
    body.innerHTML = `
      <label style="font-size:12px;font-weight:600;color:var(--text,#475569);display:block;margin-bottom:4px;">
        ${t("banner.project_name") || "Nazwa projektu"}
      </label>
      <input id="_pcd_name" class="input" type="text"
        placeholder="${(t("banner.project_name_placeholder") || "np. {module} {date}").replace("{module}", moduleLabel).replace("{date}", new Date().toLocaleDateString("pl"))}"
        style="width:100%;box-sizing:border-box;padding:8px 12px;font-size:14px;border:1px solid var(--border,#cbd5e1);border-radius:8px;"/>
      <div style="font-size:11px;color:var(--text-muted,#94a3b8);margin-top:4px;">
        ${t("banner.project_name_hint") || "Zostaw puste, aby wygenerować nazwę automatycznie."}
      </div>
    `;

    // Footer
    const footer = document.createElement("div");
    footer.style.cssText = "padding:12px 24px 20px;display:flex;gap:8px;justify-content:flex-end;";
    footer.innerHTML = `
      <a href="/projects" class="btn secondary" style="padding:8px 16px;font-size:13px;text-decoration:none;">
        ${t("banner.go_to_projects") || "Lista projektów"}
      </a>
      <button id="_pcd_submit" class="btn" type="button" style="padding:8px 20px;font-size:13px;font-weight:600;">
        ${t("banner.create_and_start") || "Utwórz i rozpocznij"}
      </button>
    `;

    panel.appendChild(header);
    panel.appendChild(body);
    panel.appendChild(footer);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    // Focus name input
    const nameInput = document.getElementById("_pcd_name");
    if(nameInput) setTimeout(() => nameInput.focus(), 100);

    // Enter key triggers submit
    if(nameInput){
      nameInput.addEventListener("keydown", (e) => {
        if(e.key === "Enter"){ e.preventDefault(); document.getElementById("_pcd_submit")?.click(); }
      });
    }

    // Submit handler
    const submitBtn = document.getElementById("_pcd_submit");
    if(submitBtn){
      submitBtn.addEventListener("click", async () => {
        submitBtn.disabled = true;
        submitBtn.textContent = t("banner.creating");

        try{
          let projectName = (nameInput ? nameInput.value.trim() : "");
          if(!projectName){
            const ts = new Date().toLocaleString("pl", {year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
            projectName = moduleLabel + " " + ts;
          }

          console.log("[ProjectDialog] Creating project:", {type: "general", name: projectName});

          // Step 1: Ensure we have a workspace ID
          let wsId = localStorage.getItem("aistate_workspace_id") || "";
          if(!wsId){
            console.log("[ProjectDialog] No workspace ID, fetching default...");
            const wsRes = await fetch("/api/workspaces/default");
            if(wsRes.ok){
              const wsData = await wsRes.json();
              const ws = wsData.workspace || wsData;
              wsId = ws.id || "";
              if(wsId) localStorage.setItem("aistate_workspace_id", wsId);
              console.log("[ProjectDialog] Default workspace:", wsId);
            }
          }

          if(!wsId){
            throw new Error("Brak workspace — przejdź na stronę Projekty i utwórz pierwszy projekt.");
          }

          // Step 2: Create subproject with type "general" (shared across all modules)
          console.log("[ProjectDialog] POST /api/workspaces/" + wsId + "/subprojects", {name: projectName, type: "general"});
          const spRes = await fetch("/api/workspaces/" + wsId + "/subprojects", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({name: projectName, type: "general"})
          });
          if(!spRes.ok){
            const errData = await spRes.json().catch(() => ({}));
            throw new Error(errData.message || errData.detail || "HTTP " + spRes.status);
          }
          const spData = await spRes.json();
          console.log("[ProjectDialog] Created:", spData);

          const sp = spData.subproject || {};
          const dir = sp.data_dir || "";
          const projectId = dir.replace("projects/", "");
          if(!projectId){
            throw new Error("Server did not return project data directory");
          }

          // Step 3: Set project in AISTATE (no reload!)
          AISTATE.projectId = projectId;
          AISTATE.audioFile = sp.audio_file || "";
          localStorage.setItem("aistate_workspace_id", wsId);
          localStorage.setItem("aistate_subproject_name", sp.name || projectName);

          showToast(tFmt("banner.project_created", {name: sp.name || projectName}), "success", 3000);

          // Remove overlay — do NOT reload
          overlay.remove();
          // Remove fallback warning banner if present
          const bannerEl = document.getElementById("_project_banner");
          if(bannerEl) bannerEl.remove();

          _dbgLog("_showCreateProjectDialog", `project created: ${projectId}, resolving promise`);
          resolve(projectId);
        }catch(e){
          console.error("[ProjectDialog] Error:", e);
          showToast(t("alert.project_create_failed") + ": " + e.message, "error", 5000);
          submitBtn.disabled = false;
          submitBtn.textContent = t("banner.create_and_start");
        }
      });
    }

    // Click outside panel closes — show warning bar, reject promise
    overlay.addEventListener("click", (e) => {
      if(e.target === overlay){
        overlay.remove();
        _showNoBanner();
        reject(new Error("User dismissed project creation dialog"));
      }
    });
  });
}

/** Fallback: thin warning bar shown if user dismisses the create dialog */
function _showNoBanner(){
  const existing = document.getElementById("_project_banner");
  if(existing) existing.remove();

  const banner = document.createElement("div");
  banner.id = "_project_banner";
  banner.style.cssText = "padding:6px 14px;display:flex;align-items:center;gap:8px;font-size:12px;border-radius:6px;margin:0 16px 4px 16px;background:#fef3c7;border:1px solid #fbbf24;color:#92400e;cursor:pointer;";
  banner.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    <span style="font-weight:500">${t("alert.no_project_selected") || "Wybierz lub utwórz projekt przed rozpoczęciem pracy."}</span>
    <span style="margin-left:auto;font-size:11px;text-decoration:underline;opacity:0.7">${t("banner.create_project") || "Utwórz projekt"}</span>
  `;
  banner.addEventListener("click", () => {
    banner.remove();
    _showCreateProjectDialog().catch(() => {});
  });

  const target = document.querySelector(".content") || document.querySelector(".card");
  if(target && target.parentNode){
    target.parentNode.insertBefore(banner, target);
  }
}

function _buildProjectReturnParams(){
  const params = new URLSearchParams();
  const path = location.pathname;
  const typeMap = {"/diarization":"diarization", "/transcription":"transcription", "/analysis":"analysis", "/analiza":"analysis", "/translation":"translation", "/chat":"chat"};
  for(const [p, t] of Object.entries(typeMap)){
    if(path.startsWith(p)){ params.set("type", t); break; }
  }
  if(path !== "/projects") params.set("return", path);
  const s = params.toString();
  return s ? "?" + s : "";
}

// NOTE: _injectProjectBanner() is called from base.html AFTER initI18n()
// so that translations are available when the dialog is rendered.

// ---------- DOM helpers ----------
function el(id){ return document.getElementById(id); }

function setStatus(prefix, status){
  const s = el(prefix+"_status"); if(s) s.textContent = status;
}
function setProgress(prefix, pct){
  const bar = el(prefix+"_bar"); if(bar) bar.style.width = `${pct}%`;
  const p = el(prefix+"_pct"); if(p) p.textContent = `${pct}%`;
}
function setLogs(prefix, text){
  const lb = el(prefix+"_logs"); if(lb) lb.textContent = text;
  // Auto-show logs details if there are logs
  const det = el(prefix+"_logs_details");
  if(det) det.style.display = (text && text.trim()) ? "" : "none";
}

// ---------- Task management ----------
async function startTask(prefix, endpoint, formData, onDone){
  _dbgLog("startTask", `called: prefix="${prefix}", endpoint="${endpoint}"`);
  try{
    setStatus(prefix, "Starting…");
    setProgress(prefix, 0);
    setLogs(prefix, "");

    // Auto-create project if none exists
    const _moduleMap = {tr:"transcription", di:"diarization", an:"analysis"};
    _dbgLog("startTask", `resolving projectId via requireProjectId("${_moduleMap[prefix] || prefix}")`);
    const project_id = await requireProjectId(_moduleMap[prefix] || prefix);
    _dbgLog("startTask", `got project_id="${project_id}", setting in formData`);
    formData.set("project_id", project_id);

    _dbgLog("startTask", `POSTing to ${endpoint}...`);
    const j = await api(endpoint, {method:"POST", body: formData});
    _dbgLog("startTask", `response: ${JSON.stringify(j)}`);
    const task_id = j.task_id;
    try{ AISTATE.lastTaskId = task_id; }catch(e){}
    AISTATE.setTaskId(prefix, task_id);
    setStatus(prefix, "Running…");
    pollTask(prefix, task_id, onDone);
  }catch(e){
    const msg = (e && e.message) ? e.message : "Error";
    _dbgLog("startTask", `ERROR: ${msg}\n${e.stack || ""}`);
    setStatus(prefix, "Error: " + msg);
    showToast(msg, 'error');
    throw e;
  }
}

async function pollTask(prefix, taskId, onDone){
  let done=false;
  while(!done){
    await new Promise(r => setTimeout(r, 900));
    const j = await api(`/api/tasks/${taskId}`);
    setProgress(prefix, j.progress || 0);
    setLogs(prefix, (j.logs || []).join("\n"));
    if(j.status === "done"){
      setStatus(prefix, "Completed");
      done=true;
      AISTATE.setTaskId(prefix, "");
      if(onDone) onDone(j);
    }else if(j.status === "error"){
      const msg = (j.error || "Error");
      setStatus(prefix, "Error: " + msg);
      done=true;
      AISTATE.setTaskId(prefix, "");
    }else{
      setStatus(prefix, j.status === "running" ? "Running…" : j.status);
    }
  }
}

// Resume polling if the user navigates between tabs/pages while a task is running.
async function resumeTask(prefix, onDone){
  const tid = AISTATE.getTaskId(prefix);
  if(!tid) return;
  try{
    const j = await api(`/api/tasks/${tid}`);
    // Show last known logs/progress immediately
    setProgress(prefix, j.progress || 0);
    setLogs(prefix, (j.logs || []).join("\n"));

    if(j.status === "done"){
      setStatus(prefix, "Completed");
      AISTATE.setTaskId(prefix, "");
      if(onDone) onDone(j);
      return;
    }
    if(j.status === "error"){
      setStatus(prefix, "Error");
      AISTATE.setTaskId(prefix, "");
      return;
    }
    setStatus(prefix, "Running… (resumed)");
    pollTask(prefix, tid, onDone);
  }catch(e){
    AISTATE.setTaskId(prefix, "");
  }
}



// ---------- Project list management ----------
async function refreshProjects(selectId){
  const j = await api("/api/projects");
  const sel = el(selectId);
  if(!sel) return;
  sel.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = t("projects.current_auto");
  sel.appendChild(opt0);

  for(const p of j.projects){
    const o = document.createElement("option");
    o.value = p.project_id;
    o.textContent = `${p.project_id.slice(0,8)} — ${p.name || t("projects.unnamed")} — ${p.created_at || ""}`;
    sel.appendChild(o);
  }
  sel.value = AISTATE.projectId || "";
}

async function setProjectFromSelect(selectId){
  const sel = el(selectId);
  if(!sel) return;
  AISTATE.projectId = sel.value || "";
  AISTATE.audioFile = "";
  location.reload();
}

// ---------- Export global helpers ----------
window.AISTATE = AISTATE;
window.api = api;
window.applyI18n = applyI18n;
window.refreshProjects = refreshProjects;
window.refreshCurrentProjectInfo = refreshCurrentProjectInfo;
window.requireProjectId = requireProjectId;
window.startTask = startTask;
window.resumeTask = resumeTask;
window.setProjectFromSelect = setProjectFromSelect;

// Export editor helpers (needed for global PPM handler)
window.ensureModal = ensureModal;
window.findBlock = findBlock;
window.openManualEditor = openManualEditor;
window.parseLineTimes = parseLineTimes;
window.getProjectAudioUrl = getProjectAudioUrl;
window.attachSegmentGuards = attachSegmentGuards;


// ===== Block editor modal =====
function ensureModal(){
  let m = document.getElementById("aistate_modal");
  if(m) return m;

  m = document.createElement("div");
  m.id = "aistate_modal";
  m.style.position = "fixed";
  m.style.inset = "0";
  m.style.background = "rgba(0,0,0,0.45)";
  m.style.display = "none";
  m.style.zIndex = "9999";
  m.style.padding = "18px";
  m.style.boxSizing = "border-box";

  // Build modal HTML in parts to avoid editor parsing issues
  var html = '';
  html += '<div style="max-width:1200px;margin:0 auto;background:#fff;border-radius:14px;padding:14px 14px 16px 14px;box-shadow:0 12px 36px rgba(0,0,0,.22);">';
  html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">';
  html += '<div style="flex:1;min-width:200px;">';
  html += '<div style="font-weight:800;font-size:18px;line-height:1;" data-i18n="modal.edit_block.title">Edit Block</div>';
  html += '<div id="aistate_block_range" style="margin-top:6px;font-size:12px;opacity:.75;">—</div>';
  html += '</div>';
  html += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">';
  html += '<div style="display:flex;align-items:center;gap:8px;">';
  html += '<label style="font-size:13px;font-weight:600;color:#555;" data-i18n="modal.speaker.label">' + (typeof aiIcon==="function"?aiIcon("speaker",14):"") + ' Speaker:</label>';
  html += '<input id="aistate_speaker_name" class="input" type="text" data-i18n-placeholder="modal.speaker.placeholder" placeholder="SPEAKER_00" style="width:140px;padding:6px 10px;font-size:13px;">';
  html += '<button id="aistate_apply_speaker" class="btn secondary" type="button" title="Replace speaker in this block" style="padding:6px 12px;font-size:12px;" data-i18n="modal.speaker.change">' + (typeof aiIcon==="function"?aiIcon("check",12):"") + ' Change</button>';
  html += '</div>';
  html += '<button id="aistate_modal_close" class="btn secondary" type="button" data-i18n="modal.close">' + (typeof aiIcon==="function"?aiIcon("close",14):"") + ' Close</button>';
  html += '</div>';
  html += '</div>';
  
  html += '<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;">';
  var _ic = typeof aiIcon==="function"?aiIcon:function(){return "";};
  html += '<button id="aistate_play" class="btn" type="button" title="Play" data-i18n="modal.play">' + _ic("play",16) + ' Play</button>';
  html += '<button id="aistate_pause" class="btn secondary" type="button" title="Pause" data-i18n="modal.pause">' + _ic("pause",16) + ' Pause</button>';
  html += '<button id="aistate_stop" class="btn secondary" type="button" title="Stop" data-i18n="modal.stop">' + _ic("stop",16) + ' Stop</button>';
  html += '<span style="width:1px;height:22px;background:#ddd;margin:0 4px;"></span>';
  html += '<button id="aistate_back3" class="btn secondary" type="button">' + _ic("skip_back_3",16) + ' -3s</button>';
  html += '<button id="aistate_back1" class="btn secondary" type="button">' + _ic("skip_back_3",16) + ' -1s</button>';
  html += '<button id="aistate_fwd1" class="btn secondary" type="button">' + _ic("skip_fwd_3",16) + ' +1s</button>';
  html += '<button id="aistate_fwd3" class="btn secondary" type="button">' + _ic("skip_fwd_3",16) + ' +3s</button>';
  html += '<span style="width:1px;height:22px;background:#ddd;margin:0 4px;"></span>';
  html += '<div style="display:flex;align-items:center;gap:8px;">';
  html += '<span style="font-size:12px;opacity:.8;" data-i18n="modal.speed">' + _ic("speed",14) + ' Speed:</span>';
  html += '<select id="aistate_rate" class="input" style="min-width:82px;">';
  html += '<option value="0.5">0.5×</option>';
  html += '<option value="0.75">0.75×</option>';
  html += '<option value="1" selected>1×</option>';
  html += '<option value="1.25">1.25×</option>';
  html += '<option value="1.5">1.5×</option>';
  html += '<option value="2">2×</option>';
  html += '</select>';
  html += '</div>';
  html += '</div>';
  
  html += '<div style="margin-top:10px;">';
  html += '<audio id="aistate_block_audio" controls style="width:100%"></audio>';
  html += '</div>';
  
  html += '<div style="margin-top:10px;">';
  html += '<textarea id="aistate_edit" style="width:100%;min-height:240px;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,\'DejaVu Sans Mono\',\'Noto Sans Mono\',\'Liberation Mono\',\'Courier New\',monospace;"></textarea>';
  html += '</div>';
  
  html += '<div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;">';
  html += '<button id="aistate_apply" class="btn" type="button" data-i18n="modal.apply">' + _ic("success",14) + ' Apply</button>';
  html += '<button id="aistate_save_project" class="btn secondary" type="button" data-i18n="modal.save_project">' + _ic("save",14) + ' Save to Project</button>';
  html += '<span style="font-size:12px;opacity:.7;align-self:center;margin-left:auto;" data-i18n="modal.shortcuts">Shortcuts: Esc close • Ctrl+Enter apply</span>';
  html += '</div>';
  html += '</div>';
  
  m.innerHTML = html;

  document.body.appendChild(m);

  // Localize freshly-created modal
  try{ applyI18n(); }catch(e){}

  // Allow AltGr/Polish programmer layout in modal inputs (avoid global shortcut interference)
  function _shieldAltGrInput(el){
    if(!el) return;
    const stop = (e)=>{
      const isAltGr = (e.key === "AltGraph") || (e.code === "AltRight") || (e.ctrlKey && e.altKey);
      if(isAltGr){
        try{ e.stopImmediatePropagation(); }catch(_){}
        try{ e.stopPropagation(); }catch(_){}
        // Do NOT preventDefault — we want the character to be inserted.
      }
    };
    ["keydown","keypress","keyup"].forEach(evt=>{
      try{ el.addEventListener(evt, stop, true); }catch(_){}
    });
  }
  try{
    _shieldAltGrInput(m.querySelector("#aistate_edit"));
    _shieldAltGrInput(m.querySelector("#aistate_speaker_name"));
  }catch(e){}

  function close(){
    m.style.display = "none";
    m._ctx = null;
    const a = m.querySelector("#aistate_block_audio");
    try{ a.pause(); }catch(e){}
    try{ if(m._cleanupAudio){ m._cleanupAudio(); m._cleanupAudio = null; } }catch(e){}
  }
  m.querySelector("#aistate_modal_close").addEventListener("click", close);
  m.addEventListener("click", (e)=>{ if(e.target === m) close(); });

  document.addEventListener("keydown", (e)=>{
    if(m.style.display === "none") return;
    if(e.key === "Escape"){ e.preventDefault(); close(); }
    if(e.key === "Enter" && (e.ctrlKey || e.metaKey)){
      e.preventDefault();
      m.querySelector("#aistate_apply").click();
    }
  });

  return m;
}

// ---------- Find block based on cursor position or block index ----------
function findBlock(textarea, lineIndexOrBlockIdx){
  const lines = (textarea.value || "").split("\n");

  // Diarization with blocks: use block index directly
  if(textarea.id === "di_out"){
    // Check if we have block-based segments
    if(typeof window.DI !== 'undefined' && window.DI.segments && window.DI.segments.length > 0){
      const idx = Math.max(0, Math.min(lineIndexOrBlockIdx, window.DI.segments.length - 1));
      const seg = window.DI.segments[idx];
      if(seg){
        // Return the formatted line for this segment
        const text = `[${seg.start.toFixed(2)}-${seg.end.toFixed(2)}] ${seg.speaker}: ${seg.text}`;
        return { start: idx, end: idx, text: text, mode: "block-segment" };
      }
    }
    
    // Fallback: treat as line-based
    const idx = Math.max(0, Math.min(lineIndexOrBlockIdx, lines.length - 1));
    return { start: idx, end: idx, text: lines[idx] || "" };
  }

  // Transcription with blocks: use block index directly
  if(textarea.id === "tr_out"){
    // Check if we have block-based segments
    if(typeof window.TR !== 'undefined' && window.TR.segments && window.TR.segments.length > 0){
      const idx = Math.max(0, Math.min(lineIndexOrBlockIdx, window.TR.segments.length - 1));
      const seg = window.TR.segments[idx];
      if(seg){
        const formatTs = (s) => {
          const hh = Math.floor(s/3600);
          const mm = Math.floor((s%3600)/60);
          const ss = s - hh*3600 - mm*60;
          const pad = (n) => String(Math.floor(n)).padStart(2,'0');
          const pad3 = (n) => String(Math.round((ss-Math.floor(ss))*1000)).padStart(3,'0');
          return `${pad(hh)}:${pad(mm)}:${pad(ss)}.${pad3(ss)}`;
        };
        const text = `[${formatTs(seg.start)} - ${formatTs(seg.end)}] ${seg.text || ""}`;
        return { start: idx, end: idx, text: text, mode: "block-segment" };
      }
    }
  }

  // Transcription fallback: if there's a selection, edit selection
  try{
    const s = textarea.selectionStart, e = textarea.selectionEnd;
    if(typeof s === "number" && typeof e === "number" && e > s){
      const txt = textarea.value.slice(s, e);
      return { start: null, end: null, text: txt, selStart: s, selEnd: e, mode: "selection" };
    }
  }catch(e){}

  // Otherwise: paragraph/block until empty line
  let start = Math.max(0, Math.min(lineIndexOrBlockIdx, lines.length - 1));
  let end = start;

  while(start > 0 && (lines[start-1] || "").trim() !== "") start--;
  while(end < lines.length-1 && (lines[end+1] || "").trim() !== "") end++;

  return { start, end, text: lines.slice(start, end+1).join("\n"), mode: "paragraph" };
}

// ---------- Open manual editor modal ----------
function openManualEditor(textarea, lineIndex){
  const modal = ensureModal();
  // Refresh localized labels each time we open (in case language changed)
  try{ applyI18n(); }catch(e){}
  const taEdit = modal.querySelector("#aistate_edit");
  const rangeLbl = modal.querySelector("#aistate_block_range");
  const audio = modal.querySelector("#aistate_block_audio");
  const speakerInput = modal.querySelector("#aistate_speaker_name");

  // Remove previous block guards (if any)
  try{ if(modal._cleanupAudio){ modal._cleanupAudio(); modal._cleanupAudio = null; } }catch(e){}

  const block = findBlock(textarea, lineIndex);
  taEdit.value = block.text || "";

  // Show modal early (so UI appears even if audio helpers fail)
  modal.style.display = "block";

  // Time range (if we have timestamp in first line of block)
  const firstLine = (block.text || "").split("\n")[0] || "";
  const times = parseLineTimes(firstLine);
  if(times){
    rangeLbl.textContent = `${times.start.toFixed(3)}s → ${times.end.toFixed(3)}s`;
  }else{
    rangeLbl.textContent = "—";
  }

  // Detect current speaker from first line
  let currentSpeaker = "";
  const cleanedLine = firstLine.replace(/^\s*\[[\d\.\-]+\]\s*/, '');
  // Allow Unicode letters in speaker name (e.g. Łukasz) in addition to SPEAKER_00
  const speakerMatch = cleanedLine.match(/^\s*([\p{L}0-9_\-]{1,40})\s*:/u);
  if(speakerMatch && speakerMatch[1]){
    currentSpeaker = speakerMatch[1].trim();
  }
  
  if(speakerInput){
    speakerInput.value = currentSpeaker;
    speakerInput.placeholder = currentSpeaker || t("modal.speaker.placeholder");
    try{ speakerInput.setAttribute("lang", getUiLang()); }catch(e){}
  }

  // Ensure editor uses current UI language (helps with IME/diacritics on some systems)
  try{ taEdit.setAttribute("lang", getUiLang()); }catch(e){}

  // Set audio src to project file
  const url = getProjectAudioUrl();
  if(url){
    if(audio.getAttribute("data-src") !== url){
      audio.src = url;
      audio.setAttribute("data-src", url);
    }
    if(times){
      audio.currentTime = Math.max(0, times.start);
    }
  }

  // Constrain playback to this block (start→end) by default
  try{ modal._cleanupAudio = attachSegmentGuards(audio, times); }catch(e){}

  // Playback speed
  const rateSel = modal.querySelector("#aistate_rate");
  const applyRate = ()=>{ try{ audio.playbackRate = parseFloat(rateSel.value || "1"); }catch(e){} };
  rateSel.onchange = applyRate;
  applyRate();

  // Playback controls
  modal.querySelector("#aistate_play").onclick  = ()=>{ audio.play().catch(()=>{}); };
  modal.querySelector("#aistate_pause").onclick = ()=>{ try{ audio.pause(); }catch(e){} };
  modal.querySelector("#aistate_stop").onclick  = ()=>{
    try{ 
      audio.pause(); 
      audio.currentTime = times ? Math.max(0, times.start) : 0; 
    }catch(e){}
  };

  const seek = (delta)=>{
    try{ audio.currentTime = Math.max(0, (audio.currentTime || 0) + delta); }catch(e){}
  };
  modal.querySelector("#aistate_back3").onclick = ()=>seek(-3);
  modal.querySelector("#aistate_back1").onclick = ()=>seek(-1);
  modal.querySelector("#aistate_fwd1").onclick  = ()=>seek(+1);
  modal.querySelector("#aistate_fwd3").onclick  = ()=>seek(+3);

  // Speaker change button
  const applySpeakerBtn = modal.querySelector("#aistate_apply_speaker");
  if(applySpeakerBtn){
    applySpeakerBtn.onclick = ()=>{
      const newSpeaker = (speakerInput.value || "").trim();
      if(!newSpeaker){
        showToast(t("modal.alert.enter_speaker"), 'warning');
        return;
      }

      if(!currentSpeaker){
        showToast(t("modal.alert.no_original_speaker"), 'warning');
        return;
      }

      if(newSpeaker === currentSpeaker){
        showToast(t("modal.alert.same_speaker"), 'info');
        return;
      }
      
      // Replace all occurrences of currentSpeaker with newSpeaker in edited text
      let text = taEdit.value || "";
      const escapedOld = currentSpeaker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escapedOld, 'g');
      const count = (text.match(regex) || []).length;
      
      text = text.split(currentSpeaker).join(newSpeaker);
      taEdit.value = text;
      
      // Update input
      speakerInput.value = newSpeaker;
      currentSpeaker = newSpeaker;
      
      console.log(`Changed speaker: ${count} occurrences`);
      showToast(tFmt("modal.alert.changed_speaker", {count}), 'success');
    };
  }

  // Context for saving
  modal._ctx = {
    textareaId: textarea.id,
    block,
    times
  };

  // Apply to output
  modal.querySelector("#aistate_apply").onclick = ()=>{
    const ctx = modal._ctx;
    if(!ctx) return;
    const outTa = document.getElementById(ctx.textareaId);
    if(!outTa) return;

    // Handle block-segment mode (from DI.segments or TR.segments)
    if(ctx.block.mode === "block-segment"){
      // Update the segment in memory
      if(ctx.textareaId === "di_out" && typeof window.DI !== 'undefined' && window.DI.segments){
        const idx = ctx.block.start;
        if(window.DI.segments[idx]){
          // Parse the edited text to extract speaker and text
          const edited = taEdit.value || "";
          // Allow Unicode letters in speaker name
          const match = edited.match(/^\s*\[[\d\.\-]+\]\s*([\p{L}0-9_\-]+)\s*:\s*(.*)$/u);
          if(match){
            window.DI.segments[idx].speaker = match[1].trim();
            window.DI.segments[idx].text = match[2].trim();
          } else {
            // If format is broken, just update text
            window.DI.segments[idx].text = edited;
          }
          // Rebuild textarea and re-render blocks
          if(typeof window.diBuildRawText === 'function'){
            outTa.value = window.diBuildRawText();
          }
          if(typeof window.diRender === 'function'){
            window.diRender();
          }
        }
      } else if(ctx.textareaId === "tr_out" && typeof window.TR !== 'undefined' && window.TR.segments){
        const idx = ctx.block.start;
        if(window.TR.segments[idx]){
          // Parse edited text
          const edited = taEdit.value || "";
          const match = edited.match(/^\s*\[[^\]]+\]\s*(.*)$/);
          if(match){
            window.TR.segments[idx].text = match[1].trim();
          } else {
            window.TR.segments[idx].text = edited;
          }
          // Rebuild and re-render
          if(typeof window.trBuildRawText === 'function'){
            outTa.value = window.trBuildRawText();
          }
          if(typeof window.trRender === 'function'){
            window.trRender();
          }
        }
      }
    } else if(ctx.block.mode === "selection"){
      outTa.value = outTa.value.slice(0, ctx.block.selStart) + taEdit.value + outTa.value.slice(ctx.block.selEnd);
    } else {
      const arr = (outTa.value || "").split("\n");
      if(ctx.block.start != null && ctx.block.end != null){
        const replacement = (taEdit.value || "").split("\n");
        arr.splice(ctx.block.start, ctx.block.end - ctx.block.start + 1, ...replacement);
        outTa.value = arr.join("\n");
      }
    }

    // Save draft (so it doesn't disappear when switching tabs)
    try{ localStorage.setItem(draftKey(outTa.id), outTa.value || ""); }catch(e){}
    
    // Dispatch event to notify UI to refresh speaker mapping
    try{
      const event = new CustomEvent('aistate:output-updated', { 
        detail: { textareaId: ctx.textareaId }
      });
      document.dispatchEvent(event);
    }catch(e){
      // dispatch event failed — non-critical
    }
  };

  // Save to project
  modal.querySelector("#aistate_save_project").onclick = async ()=>{
    const ctx = modal._ctx;
    if(!ctx) return;
    const outTa = document.getElementById(ctx.textareaId);
    if(!outTa) return;
    const pid = await requireProjectId();

    try{
      if(ctx.textareaId === "tr_out"){
        await api(`/api/projects/${pid}/save_transcript`, {
          method:"POST",
          headers:{ "content-type":"application/json" },
          body: JSON.stringify({ text: outTa.value || "" })
        });
        showToast(t("modal.alert.saved_transcription"), 'success');
      }else if(ctx.textareaId === "di_out"){
        await api(`/api/projects/${pid}/save_diarized`, {
          method:"POST",
          headers:{ "content-type":"application/json" },
          body: JSON.stringify({ text: outTa.value || "" })
        });
        showToast(t("modal.alert.saved_diarization"), 'success');
      }
    }catch(e){
      showToast(e.message || t("modal.alert.save_error"), 'error');
    }
  };
}

// ===== Global PPM (right-click) handler =====
(function(){
  function _lineIndexFromMouse(el, evt){
    const rect = el.getBoundingClientRect();
    const y = evt.clientY - rect.top + (el.scrollTop || 0);
    const cs = window.getComputedStyle(el);
    let lh = parseFloat(cs.lineHeight);
    if(!isFinite(lh) || lh <= 0){
      const fs = parseFloat(cs.fontSize) || 14;
      lh = fs * 1.35;
    }
    return Math.max(0, Math.floor(y / lh));
  }

  function _getText(el){
    if("value" in el) return el.value || "";
    return (el.textContent || "");
  }

  function _setText(el, txt){
    if("value" in el) el.value = txt;
    else el.textContent = txt;
  }

  function _toast(msg){
    try{
      console.error(msg);
      let t = document.getElementById("_aistate_toast");
      if(!t){
        t = document.createElement("div");
        t.id = "_aistate_toast";
        t.style.position = "fixed";
        t.style.left = "18px";
        t.style.bottom = "18px";
        t.style.zIndex = "10000";
        t.style.background = "rgba(20,20,20,0.92)";
        t.style.color = "#fff";
        t.style.padding = "10px 12px";
        t.style.borderRadius = "10px";
        t.style.boxShadow = "0 10px 30px rgba(0,0,0,.25)";
        t.style.fontSize = "12px";
        t.style.maxWidth = "420px";
        t.style.display = "none";
        document.body.appendChild(t);
      }
      t.textContent = msg;
      t.style.display = "block";
      clearTimeout(t._timer);
      t._timer = setTimeout(()=>{ t.style.display = "none"; }, 3500);
    }catch(e){}
  }

  function _openEditorFor(el, lineIdx){
    try{
      if(typeof openManualEditor === "function"){
        return openManualEditor(el, lineIdx);
      }
      if(typeof window.openManualEditor === "function"){
        return window.openManualEditor(el, lineIdx);
      }
      _toast("Missing openManualEditor() – app.js did not load correctly.");
    }catch(e){
      _toast(e && e.message ? e.message : "Error opening editor");
    }
  }

  document.addEventListener("contextmenu", (evt)=>{
    const t = evt.target;
    let el = null;
    
    // Check if element has closest method
    if(t && typeof t.closest === 'function'){
      el = t.closest("#tr_out") ||
           t.closest("#di_out") ||
           t.closest("[data-editor='tr_out']") ||
           t.closest("[data-editor='di_out']") ||
           t.closest(".seg"); // Support for block-based views
    }
    
    if(!el) return;

    evt.preventDefault();
    evt.stopPropagation();
    if(typeof evt.stopImmediatePropagation === 'function') evt.stopImmediatePropagation();

    // Handle block clicks differently
    if(el.classList && el.classList.contains('seg')){
      
      const idx = parseInt(el.dataset.idx || '0', 10);
      
      // Determine which textarea to use based on parent container
      let textarea = null;
      if(el.closest('#di_blocks')){
        textarea = document.getElementById('di_out');
      } else if(el.closest('#tr_blocks')){
        textarea = document.getElementById('tr_out');
      }
      
      // Diarization page: prefer inline editor in Sterowanie (no modal window)
      if(el.closest && el.closest('#di_blocks') && typeof window.diOpenInlineEditor === 'function'){
        try{
          window.diOpenInlineEditor(idx);
        }catch(e){
          _toast(e && e.message ? e.message : "PPM error");
        }
        return false;
      }

      if(textarea){
        try{ 
          _openEditorFor(textarea, idx); 
        }catch(e){ 
          _toast(e && e.message ? e.message : "PPM error"); 
        }
      }
    } else {
      // Original textarea-based handling
      const idx = _lineIndexFromMouse(el, evt);
      try{ 
        _openEditorFor(el, idx); 
      }catch(e){ 
        _toast(e && e.message ? e.message : "PPM error"); 
      }
    }
    
    return false;
  }, true);
})();