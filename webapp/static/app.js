// ---------- UI language (i18n) ----------
const I18N = {
  pl: {
    "nav.new_project": "Nowy projekt",
    "nav.transcription": "Transkrypcja",
    "nav.diarization": "Diaryzacja",
    "nav.settings": "Ustawienia",
    "nav.logs": "Logi",
    "nav.info": "Info",
    "nav.save": "Zapis",
    "top.current_project": "Bieżący projekt",
    "top.source_file": "Plik źródłowy projektu",
    "btn.refresh": "Odśwież",
    "logs.copy_sel": "Kopiuj zaznaczenie",
    "logs.copy_all": "Kopiuj wszystko",
    "btn.create_project": "Utwórz projekt",
    "btn.diarize": "Diaryzuj",
    "btn.transcribe": "Transkrybuj",
    "page.new_project.title": "Nowy projekt",
    "page.logs.title": "Logi",
    "page.diarization.title": "Diaryzacja",
    "page.transcription.title": "Transkrypcja",
    "projects.current_auto": "(bieżący / auto)",
    "projects.unnamed": "projekt",
"projects.none": "Brak projektów",
"projects.no_file": "Brak pliku",
"projects.no_data": "Brak danych",
    "settings.ui_language": "Język interfejsu",
    "settings.hf_placeholder": "Wklej token (zapis lokalnie na serwerze)",
    "settings.save": "Zapisz ustawienia",
    "settings.saved": "Zapisano ✅",
    "lang.pl": "Polski",
    "lang.en": "English",
  },
  en: {
    "nav.new_project": "New project",
    "nav.transcription": "Transcription",
    "nav.diarization": "Diarization",
    "nav.settings": "Settings",
    "nav.logs": "Logs",
    "nav.info": "Info",
    "nav.save": "Save",
    "top.current_project": "Current project",
    "top.source_file": "Project source file",
    "btn.refresh": "Refresh",
    "logs.copy_sel": "Copy selection",
    "logs.copy_all": "Copy all",
    "btn.create_project": "Create project",
    "btn.diarize": "Diarize",
    "btn.transcribe": "Transcribe",
    "page.new_project.title": "New project",
    "page.logs.title": "Logs",
    "page.diarization.title": "Diarization",
    "page.transcription.title": "Transcription",
    "projects.current_auto": "(current / auto)",
    "projects.unnamed": "project",
    "projects.none": "(none)",
    "projects.no_file": "(no file)",
    "projects.no_data": "(no data)",
    "settings.ui_language": "UI language",
    "settings.hf_placeholder": "Paste token (stored locally on server)",
    "settings.save": "Save settings",
    "settings.saved": "Saved ✅",
    "lang.pl": "Polish",
    "lang.en": "English",
  }
};

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

function applyI18n(){
  const lang = getUiLang();
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(el=>{
    const key = el.getAttribute("data-i18n");
    if(key) el.textContent = t(key);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el=>{
    const key = el.getAttribute("data-i18n-placeholder");
    if(key) el.setAttribute("placeholder", t(key));
  });
}

// Minimal helper: create/load current project id from localStorage
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
  }
};

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

async function ensureProject(){
  // Legacy helper: create project if missing. Prefer requireProjectId() in new UX.
  if(AISTATE.projectId) return AISTATE.projectId;
  const j = await api("/api/projects/new", {method:"POST"});
  AISTATE.projectId = j.project_id;
  return j.project_id;
}

function requireProjectId(){
  const pid = AISTATE.projectId || "";
  if(!pid){
    alert("Najpierw utwórz projekt w: Nowy projekt (podaj nazwę i wybierz plik audio). ");
    window.location.href = "/new-project";
    throw new Error("Brak aktywnego projektu");
  }
  return pid;
}


async function refreshCurrentProjectInfo(){
  const elCur = document.getElementById("current_project");
  const elAud = document.getElementById("current_audio");
  const pid = AISTATE.projectId || "";

  if(!pid){
    if(elCur) elCur.textContent = t("projects.none");
    if(elAud) elAud.textContent = t("projects.none");
    AISTATE.audioFile = "";
    return;
  }

  try{
    const meta = await api(`/api/projects/${pid}/meta`);
    const name = meta.name || t("projects.unnamed");
    const audio = meta.audio_file || "";

    if(elCur) elCur.textContent = `${name} (${pid.slice(0,8)})`;
    if(elAud) elAud.textContent = audio ? audio : t("projects.no_file");

    AISTATE.audioFile = audio || "";
  }catch(e){
    if(elCur) elCur.textContent = pid.slice(0,8);
    if(elAud) elAud.textContent = t("projects.no_data");
    AISTATE.audioFile = "";
  }
}

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
}

async function startTask(prefix, endpoint, formData, onDone){
  try{
    setStatus(prefix, "Startuję…");
    setProgress(prefix, 0);
    setLogs(prefix, "");

    // New UX: project must exist (created in "Nowy projekt").
    const project_id = requireProjectId();
    formData.set("project_id", project_id);

    const j = await api(endpoint, {method:"POST", body: formData});
    const task_id = j.task_id;
    AISTATE.setTaskId(prefix, task_id);
    setStatus(prefix, "W toku…");
    pollTask(prefix, task_id, onDone);
  }catch(e){
    const msg = (e && e.message) ? e.message : "Błąd";
    setStatus(prefix, "Błąd ❌: " + msg);
    alert(msg);
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
      setStatus(prefix, "Zakończono ✅");
      done=true;
      AISTATE.setTaskId(prefix, "");
      if(onDone) onDone(j);
    }else if(j.status === "error"){
      const msg = (j.error || "Błąd");
      setStatus(prefix, "Błąd ❌: " + msg);
      done=true;
      AISTATE.setTaskId(prefix, "");
    }else{
      setStatus(prefix, j.status === "running" ? "W toku…" : j.status);
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
      setStatus(prefix, "Zakończono ✅");
      AISTATE.setTaskId(prefix, "");
      if(onDone) onDone(j);
      return;
    }
    if(j.status === "error"){
      setStatus(prefix, "Błąd ❌");
      AISTATE.setTaskId(prefix, "");
      return;
    }
    setStatus(prefix, "W toku… (wznowiono)");
    pollTask(prefix, tid, onDone);
  }catch(e){
    AISTATE.setTaskId(prefix, "");
  }
}

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

// Export helpers globally (templates call these functions directly)
window.AISTATE = AISTATE;
window.api = api;
window.applyI18n = applyI18n;
window.refreshProjects = refreshProjects;
window.refreshCurrentProjectInfo = refreshCurrentProjectInfo;
window.startTask = startTask;
window.resumeTask = resumeTask;
window.setProjectFromSelect = setProjectFromSelect;

// ---------------- Manual editor (right-click) ----------------
// Right-click on transcription/diarization result textareas opens a modal editor + audio controls.
// Works with:
//   - #tr_out (Transkrypcja)
//   - #di_out (Diaryzacja)
//
// Keyboard shortcuts (when modal is open):
//   Esc = close
//   Ctrl+Enter = apply changes
//   Alt+Space = play/pause
//   Alt+Left/Right = -1s/+1s
//   Alt+Shift+Left/Right = -5s/+5s

(function(){
  const STYLE_ID = "aistate-manual-edit-style";
  const OVERLAY_ID = "aistate-manual-edit-overlay";

  /** @type {{ta: HTMLTextAreaElement, rangeStart: number, rangeEnd: number, mode: 'tr'|'di'} | null} */
  let state = null;

  function injectStyles(){
    if(document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .aistate-me-overlay{
        position: fixed; inset: 0;
        background: rgba(15,23,42,.45);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 18px;
        z-index: 9999;
      }
      .aistate-me-modal{
        width: min(980px, 96vw);
        max-height: 92vh;
        background: rgba(255,255,255,.96);
        border: 1px solid rgba(15,23,42,.14);
        border-radius: 18px;
        box-shadow: 0 18px 50px rgba(15,23,42,.25);
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }
      .aistate-me-header{
        padding: 12px 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid rgba(15,23,42,.10);
      }
      .aistate-me-title{
        font-weight: 900;
        letter-spacing: .2px;
      }
      .aistate-me-close{
        border: 1px solid rgba(15,23,42,.14);
        background: rgba(15,23,42,.06);
        border-radius: 14px;
        padding: 8px 12px;
        cursor: pointer;
        font-weight: 800;
      }
      .aistate-me-close:hover{ background: rgba(15,23,42,.10); }
      .aistate-me-body{
        padding: 14px;
        overflow: auto;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .aistate-me-text{
        width: 100%;
        min-height: 220px;
        resize: vertical;
        padding: 12px;
        border-radius: 14px;
        border: 1px solid rgba(15,23,42,.14);
        outline: none;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }
      .aistate-me-row{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        align-items: center;
      }
      .aistate-me-audio{ width: 100%; }
      .aistate-me-mini{
        font-size: 12px;
        color: rgba(71,85,105,1);
      }
      .aistate-me-btn{
        padding: 10px 14px;
        border-radius: 14px;
        border: 1px solid rgba(31,90,166,.22);
        background: rgba(31,90,166,.10);
        cursor: pointer;
        font-weight: 800;
      }
      .aistate-me-btn:hover{ background: rgba(31,90,166,.14); }
      .aistate-me-btn.secondary{
        border-color: rgba(15,23,42,.14);
        background: rgba(15,23,42,.06);
      }
      .aistate-me-btn.secondary:hover{ background: rgba(15,23,42,.10); }
      .aistate-me-btn.danger{
        border-color: rgba(185,28,28,.22);
        background: rgba(185,28,28,.10);
      }
      .aistate-me-btn.danger:hover{ background: rgba(185,28,28,.14); }
      .aistate-me-input{
        width: 110px;
        padding: 9px 10px;
        border-radius: 14px;
        border: 1px solid rgba(15,23,42,.14);
        outline: none;
      }
      .aistate-me-footer{
        padding: 12px 14px;
        border-top: 1px solid rgba(15,23,42,.10);
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        justify-content: flex-end;
      }
      .aistate-me-kbd{
        user-select: none;
        background: rgba(15,23,42,.06);
        border: 1px solid rgba(15,23,42,.10);
        border-radius: 10px;
        padding: 2px 8px;
        font-weight: 800;
        font-size: 12px;
      }
    `;
    document.head.appendChild(style);
  }

  function audioUrl(){
    const pid = (window.AISTATE && window.AISTATE.projectId) ? window.AISTATE.projectId : "";
    const af = (window.AISTATE && window.AISTATE.audioFile) ? window.AISTATE.audioFile : "";
    if(!pid || !af) return "";
    return `/api/projects/${pid}/download/${encodeURIComponent(af)}`;
  }

  function ensureModal(){
    injectStyles();
    let overlay = document.getElementById(OVERLAY_ID);
    if(overlay) return overlay;

    overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.className = "aistate-me-overlay";
    overlay.innerHTML = `
      <div class="aistate-me-modal" role="dialog" aria-modal="true">
        <div class="aistate-me-header">
          <div>
            <div class="aistate-me-title">Edycja manualna</div>
            <div class="aistate-me-mini">
              Skróty: <span class="aistate-me-kbd">Esc</span> zamknij •
              <span class="aistate-me-kbd">Ctrl</span>+<span class="aistate-me-kbd">Enter</span> zastosuj •
              <span class="aistate-me-kbd">Alt</span>+<span class="aistate-me-kbd">Space</span> play/pause •
              <span class="aistate-me-kbd">Alt</span>+<span class="aistate-me-kbd">←</span>/<span class="aistate-me-kbd">→</span> 1s •
              <span class="aistate-me-kbd">Alt</span>+<span class="aistate-me-kbd">Shift</span>+<span class="aistate-me-kbd">←</span>/<span class="aistate-me-kbd">→</span> 5s
            </div>
          </div>
          <button class="aistate-me-close" id="aistate_me_close" type="button">Zamknij</button>
        </div>

        <div class="aistate-me-body">
          <textarea id="aistate_me_text" class="aistate-me-text" placeholder="Edytuj tekst…"></textarea>

          <div class="aistate-me-row">
            <audio id="aistate_me_audio" class="aistate-me-audio" controls preload="metadata"></audio>
          </div>

          <div class="aistate-me-row">
            <button class="aistate-me-btn secondary" id="aistate_me_back5" type="button">-5s</button>
            <button class="aistate-me-btn secondary" id="aistate_me_back1" type="button">-1s</button>
            <button class="aistate-me-btn secondary" id="aistate_me_fwd1" type="button">+1s</button>
            <button class="aistate-me-btn secondary" id="aistate_me_fwd5" type="button">+5s</button>

            <span class="aistate-me-mini" style="margin-left:6px">Loop:</span>
            <input id="aistate_me_in" class="aistate-me-input" type="number" min="0" step="0.1" placeholder="start (s)"/>
            <input id="aistate_me_out" class="aistate-me-input" type="number" min="0" step="0.1" placeholder="koniec (s)"/>
            <button class="aistate-me-btn secondary" id="aistate_me_mark_in" type="button">Ustaw start</button>
            <button class="aistate-me-btn secondary" id="aistate_me_mark_out" type="button">Ustaw koniec</button>
            <label class="aistate-me-mini" style="display:flex; align-items:center; gap:8px">
              <input id="aistate_me_loop" type="checkbox"/> włącz
            </label>

            <span class="aistate-me-mini" style="margin-left:6px">Tempo:</span>
            <select id="aistate_me_rate" class="aistate-me-input" style="width:120px">
              <option value="0.75">0.75×</option>
              <option value="1" selected>1×</option>
              <option value="1.25">1.25×</option>
              <option value="1.5">1.5×</option>
              <option value="2">2×</option>
            </select>
          </div>

          <div class="aistate-me-mini">
            Wskazówka: ustaw kursor (albo zaznacz fragment) w polu wynikowym, potem kliknij PPM, aby edytować tylko dany „blok”.
          </div>
        </div>

        <div class="aistate-me-footer">
          <button class="aistate-me-btn secondary" id="aistate_me_save_project" type="button" title="Zapisuje aktualny wynik w projekcie">Zapisz w projekcie</button>
          <button class="aistate-me-btn" id="aistate_me_apply" type="button">Zastosuj zmiany</button>
          <button class="aistate-me-btn danger" id="aistate_me_cancel" type="button">Anuluj</button>
        </div>
      </div>
    `;

    overlay.addEventListener("mousedown", (e)=>{
      if(e.target === overlay) closeEditor();
    });

    document.body.appendChild(overlay);

    const byId = (id)=>document.getElementById(id);
    const audio = /** @type {HTMLAudioElement} */(byId("aistate_me_audio"));
    const inEl = /** @type {HTMLInputElement} */(byId("aistate_me_in"));
    const outEl = /** @type {HTMLInputElement} */(byId("aistate_me_out"));
    const loopEl = /** @type {HTMLInputElement} */(byId("aistate_me_loop"));
    const rateEl = /** @type {HTMLSelectElement} */(byId("aistate_me_rate"));

    function seek(delta){
      if(!audio || Number.isNaN(audio.currentTime)) return;
      audio.currentTime = Math.max(0, audio.currentTime + delta);
    }

    byId("aistate_me_close").addEventListener("click", closeEditor);
    byId("aistate_me_cancel").addEventListener("click", closeEditor);
    byId("aistate_me_apply").addEventListener("click", applyEdits);
    byId("aistate_me_save_project").addEventListener("click", saveToProject);

    byId("aistate_me_back5").addEventListener("click", ()=>seek(-5));
    byId("aistate_me_back1").addEventListener("click", ()=>seek(-1));
    byId("aistate_me_fwd1").addEventListener("click", ()=>seek(+1));
    byId("aistate_me_fwd5").addEventListener("click", ()=>seek(+5));

    byId("aistate_me_mark_in").addEventListener("click", ()=>{
      if(audio) inEl.value = String(Math.max(0, Number(audio.currentTime || 0)).toFixed(1));
      if(loopEl.checked) audio.currentTime = Number(inEl.value || "0");
    });
    byId("aistate_me_mark_out").addEventListener("click", ()=>{
      if(audio) outEl.value = String(Math.max(0, Number(audio.currentTime || 0)).toFixed(1));
    });

    rateEl.addEventListener("change", ()=>{
      const r = Number(rateEl.value || "1");
      audio.playbackRate = (Number.isFinite(r) && r > 0) ? r : 1;
    });

    audio.addEventListener("timeupdate", ()=>{
      if(!loopEl.checked) return;
      const a = Number(inEl.value || "0");
      const b = Number(outEl.value || "0");
      if(!(b > a)) return;
      if(audio.currentTime > b){
        audio.currentTime = a;
        if(!audio.paused) audio.play().catch(()=>{});
      }
    });

    document.addEventListener("keydown", (e)=>{
      const ov = document.getElementById(OVERLAY_ID);
      if(!ov || ov.style.display !== "flex") return;

      if(e.key === "Escape"){
        e.preventDefault();
        closeEditor();
        return;
      }
      if(e.ctrlKey && e.key === "Enter"){
        e.preventDefault();
        applyEdits();
        return;
      }
      if(e.altKey && e.code === "Space"){
        e.preventDefault();
        if(audio.paused) audio.play().catch(()=>{});
        else audio.pause();
        return;
      }
      if(e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")){
        e.preventDefault();
        const dir = (e.key === "ArrowLeft") ? -1 : 1;
        const step = e.shiftKey ? 5 : 1;
        seek(dir * step);
      }
    });

    return overlay;
  }

  function getRangeFromSelection(ta){
    const s = Number(ta.selectionStart || 0);
    const e = Number(ta.selectionEnd || 0);
    if(e > s) return {start: s, end: e, text: ta.value.slice(s, e)};
    return null;
  }

  function getBlockRangeAtCaret(ta){
    const text = ta.value || "";
    const pos = Number(ta.selectionStart || 0);

    const before = text.slice(0, pos);
    const after = text.slice(pos);

    const prevSep = before.lastIndexOf("\n\n");
    const nextSep = after.indexOf("\n\n");

    const start = (prevSep === -1) ? 0 : (prevSep + 2);
    const end = (nextSep === -1) ? text.length : (pos + nextSep);

    return {start, end, text: text.slice(start, end)};
  }

  function openEditor(ta){
    const overlay = ensureModal();
    const textEl = /** @type {HTMLTextAreaElement} */(document.getElementById("aistate_me_text"));
    const audio = /** @type {HTMLAudioElement} */(document.getElementById("aistate_me_audio"));
    const saveBtn = /** @type {HTMLButtonElement} */(document.getElementById("aistate_me_save_project"));

    const mode = (ta.id === "tr_out") ? "tr" : (ta.id === "di_out" ? "di" : "tr");

    const sel = getRangeFromSelection(ta);
    const block = sel || getBlockRangeAtCaret(ta);

    state = { ta, rangeStart: block.start, rangeEnd: block.end, mode };

    textEl.value = block.text;

    const url = audioUrl();
    if(url){
      if(audio.getAttribute("src") !== url){
        audio.setAttribute("src", url);
        audio.load();
      }
      audio.style.display = "block";
    }else{
      audio.removeAttribute("src");
      audio.load();
      audio.style.display = "none";
    }

    const hasProject = (window.AISTATE && window.AISTATE.projectId);
    saveBtn.disabled = !hasProject;

    overlay.style.display = "flex";
    setTimeout(()=>textEl.focus(), 0);
  }

  function applyEdits(){
    if(!state) return closeEditor();
    const textEl = /** @type {HTMLTextAreaElement} */(document.getElementById("aistate_me_text"));
    const ta = state.ta;
    const before = ta.value.slice(0, state.rangeStart);
    const after = ta.value.slice(state.rangeEnd);

    ta.value = before + textEl.value + after;

    const newEnd = (before + textEl.value).length;
    try{
      ta.focus();
      ta.setSelectionRange(state.rangeStart, newEnd);
    }catch(e){ /* ignore */ }

    closeEditor(false);
  }

  async function saveToProject(){
    if(!state) return;
    const pid = (window.AISTATE && window.AISTATE.projectId) ? window.AISTATE.projectId : "";
    if(!pid){
      alert("Brak aktywnego projektu. Utwórz projekt w zakładce: Nowy projekt.");
      return;
    }
    const ta = state.ta;
    const text = ta.value || "";
    const endpoint = (state.mode === "tr") ? `/api/projects/${pid}/save_transcript` : `/api/projects/${pid}/save_diarized`;
    try{
      await window.api(endpoint, {
        method: "POST",
        headers: {"content-type":"application/json"},
        body: JSON.stringify({ text })
      });
      alert("Zapisano w projekcie ✅");
    }catch(e){
      const msg = (e && e.message) ? e.message : "Błąd zapisu";
      alert("Nie udało się zapisać: " + msg);
    }
  }

  function closeEditor(keepState=false){
    const overlay = document.getElementById(OVERLAY_ID);
    if(overlay) overlay.style.display = "none";
    if(!keepState) state = null;
  }

  function attachToTextarea(id){
    const ta = document.getElementById(id);
    if(!ta) return;

    ta.addEventListener("contextmenu", (e)=>{
      e.preventDefault();
      openEditor(/** @type {HTMLTextAreaElement} */(ta));
    });
  }

  function ready(fn){
    if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  ready(()=>{
    attachToTextarea("tr_out");
    attachToTextarea("di_out");
  });

  window.openManualEditor = openEditor;
})();
