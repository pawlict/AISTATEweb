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


// ---------- Helper: parse timestamps from a line ----------
// Supports:
// 1) diarization: [12.34-15.67] SPEAKER_00: ...
// 2) transcription: [HH:MM:SS(.ms) - HH:MM:SS(.ms)] ...
function parseLineTimes(line){
  if(!line) return null;

  // diarization seconds
  let m = line.match(/^\s*\[(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\]/);
  if(m){
    const s0 = parseFloat(m[1]);
    const s1 = parseFloat(m[2]);
    if(isFinite(s0) && isFinite(s1) && s1 > s0) return {start: s0, end: s1};
  }

  // transcription HH:MM:SS(.ms)
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


// ---------- Helper: project audio URL ----------
function getProjectAudioUrl(){
  try{
    const pid = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) ? String(AISTATE.projectId) : "";
    const af  = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.audioFile) ? String(AISTATE.audioFile) : "";
    if(!pid || !af) return "";
    return `/api/projects/${pid}/download/${encodeURIComponent(af)}`;
  }catch(e){
    return "";
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
        audioEl.currentTime = end; // stop at end of block
      }
    }catch(e){}
  };

  const onSeeking = clamp;

  audioEl.addEventListener("play", onPlay);
  audioEl.addEventListener("timeupdate", onTimeUpdate);
  audioEl.addEventListener("seeking", onSeeking);

  // initial clamp
  clamp();

  return function cleanup(){
    try{ audioEl.removeEventListener("play", onPlay); }catch(e){}
    try{ audioEl.removeEventListener("timeupdate", onTimeUpdate); }catch(e){}
    try{ audioEl.removeEventListener("seeking", onSeeking); }catch(e){}
  };
}

}

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

// Export editor helpers (needed for global PPM handler)
window.ensureModal = ensureModal;
window.findBlock = findBlock;
window.openManualEditor = openManualEditor;
  window.parseLineTimes = parseLineTimes;
  window.getProjectAudioUrl = getProjectAudioUrl;
  window.attachSegmentGuards = attachSegmentGuards;


  // ===== Block editor modal (Transcription-like UI) =====
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

    m.innerHTML = `
      <div style="max-width:1200px;margin:0 auto;background:#fff;border-radius:14px;padding:14px 14px 16px 14px;box-shadow:0 12px 36px rgba(0,0,0,.22);">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
          <div>
            <div style="font-weight:800;font-size:18px;line-height:1;">Edycja bloku</div>
            <div id="aistate_block_range" style="margin-top:6px;font-size:12px;opacity:.75;">—</div>
          </div>
          <button id="aistate_modal_close" class="btn secondary" type="button">Zamknij</button>
        </div>

        <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
          <button id="aistate_play" class="btn" type="button" title="Play">
            ▶
          </button>
          <button id="aistate_pause" class="btn secondary" type="button" title="Pause">
            ⏸
          </button>
          <button id="aistate_stop" class="btn secondary" type="button" title="Stop">
            ⏹
          </button>

          <span style="width:1px;height:22px;background:#ddd;margin:0 4px;"></span>

          <button id="aistate_back3" class="btn secondary" type="button">-3s</button>
          <button id="aistate_back1" class="btn secondary" type="button">-1s</button>
          <button id="aistate_fwd1"  class="btn secondary" type="button">+1s</button>
          <button id="aistate_fwd3"  class="btn secondary" type="button">+3s</button>

          <span style="width:1px;height:22px;background:#ddd;margin:0 4px;"></span>

          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:12px;opacity:.8;">Tempo:</span>
            <select id="aistate_rate" class="input" style="min-width:82px;">
              <option value="0.5">0.5×</option>
              <option value="0.75">0.75×</option>
              <option value="1" selected>1×</option>
              <option value="1.25">1.25×</option>
              <option value="1.5">1.5×</option>
              <option value="2">2×</option>
            </select>
          </div>

          <div style="display:flex;align-items:center;gap:8px;margin-left:auto;">
            <span style="font-size:12px;opacity:.8;">Loop:</span>
            <input id="aistate_loop_start" class="input" type="number" step="0.1" placeholder="start (s)" style="width:110px;">
            <input id="aistate_loop_end"   class="input" type="number" step="0.1" placeholder="koniec (s)" style="width:110px;">
            <button id="aistate_set_start" class="btn secondary" type="button">Ustaw start</button>
            <button id="aistate_set_end"   class="btn secondary" type="button">Ustaw koniec</button>
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;opacity:.85;">
              <input id="aistate_loop_on" type="checkbox"> włącz
            </label>
          </div>
        </div>

        <div style="margin-top:10px;">
          <audio id="aistate_block_audio" controls style="width:100%"></audio>
        </div>

        <div style="margin-top:10px;">
          <textarea id="aistate_edit" style="width:100%;min-height:240px;font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;"></textarea>
        </div>

        <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;">
          <button id="aistate_apply" class="btn" type="button">Zastosuj</button>
          <button id="aistate_save_project" class="btn secondary" type="button">Zapisz w projekcie</button>
          <span style="font-size:12px;opacity:.7;align-self:center;margin-left:auto;">
            Skróty: Esc zamknij • Ctrl+Enter zastosuj
          </span>
        </div>
      </div>
    `;

    document.body.appendChild(m);

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

  function findBlock(textarea, lineIndex){
    const lines = (textarea.value || "").split("\n");

    // Diaryzacja: zawsze 1 linia = 1 blok
    if(textarea.id === "di_out"){
      const idx = Math.max(0, Math.min(lineIndex, lines.length - 1));
      return { start: idx, end: idx, text: lines[idx] || "" };
    }

    // Transkrypcja: jeśli jest zaznaczenie, edytuj zaznaczenie
    try{
      const s = textarea.selectionStart, e = textarea.selectionEnd;
      if(typeof s === "number" && typeof e === "number" && e > s){
        const txt = textarea.value.slice(s, e);
        return { start: null, end: null, text: txt, selStart: s, selEnd: e, mode: "selection" };
      }
    }catch(e){}

    // W przeciwnym razie: akapit/blok do pustej linii
    let start = Math.max(0, Math.min(lineIndex, lines.length - 1));
    let end = start;

    while(start > 0 && (lines[start-1] || "").trim() !== "") start--;
    while(end < lines.length-1 && (lines[end+1] || "").trim() !== "") end++;

    return { start, end, text: lines.slice(start, end+1).join("\n"), mode: "paragraph" };
  }

  function openManualEditor(textarea, lineIndex){
    const modal = ensureModal();
    const taEdit = modal.querySelector("#aistate_edit");
    const rangeLbl = modal.querySelector("#aistate_block_range");
    const audio = modal.querySelector("#aistate_block_audio");

    // remove previous block guards (if any)
    try{ if(modal._cleanupAudio){ modal._cleanupAudio(); modal._cleanupAudio = null; } }catch(e){}

    const block = findBlock(textarea, lineIndex);
    taEdit.value = block.text || "";

    

    // Show modal early (so UI appears even if audio helpers fail)
    modal.style.display = "block";
// zakres czasu (jeśli mamy timestamp w pierwszej linii bloku)
    const firstLine = (block.text || "").split("\n")[0] || "";
    const times = parseLineTimes(firstLine); // masz już tę funkcję w pliku
    if(times){
      rangeLbl.textContent = `${times.start.toFixed(3)}s → ${times.end.toFixed(3)}s`;
    }else{
      rangeLbl.textContent = "—";
    }

    // ustaw audio src do pliku projektu
    const url = getProjectAudioUrl(); // masz już tę funkcję w pliku
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


    // tempo
    const rateSel = modal.querySelector("#aistate_rate");
    const applyRate = ()=>{ try{ audio.playbackRate = parseFloat(rateSel.value || "1"); }catch(e){} };
    rateSel.onchange = applyRate;
    applyRate();

    // loop
    const loopOn = modal.querySelector("#aistate_loop_on");
    const loopStart = modal.querySelector("#aistate_loop_start");
    const loopEnd = modal.querySelector("#aistate_loop_end");
    const setStart = modal.querySelector("#aistate_set_start");
    const setEnd = modal.querySelector("#aistate_set_end");

    if(times){
      loopStart.value = String(times.start.toFixed(1));
      loopEnd.value = String(times.end.toFixed(1));
    }

    setStart.onclick = ()=>{ loopStart.value = String((audio.currentTime||0).toFixed(1)); };
    setEnd.onclick   = ()=>{ loopEnd.value = String((audio.currentTime||0).toFixed(1)); };

    // loop enforcement
    const loopHandler = ()=>{
      if(!loopOn.checked) return;
      const s = parseFloat(loopStart.value || "0");
      const e = parseFloat(loopEnd.value || "0");
      if(isFinite(s) && isFinite(e) && e > s && (audio.currentTime || 0) >= e){
        audio.currentTime = Math.max(0, s);
        audio.play().catch(()=>{});
      }
    };
    audio.ontimeupdate = loopHandler;

    // sterowanie
    modal.querySelector("#aistate_play").onclick  = ()=>{ audio.play().catch(()=>{}); };
    modal.querySelector("#aistate_pause").onclick = ()=>{ try{ audio.pause(); }catch(e){} };
    modal.querySelector("#aistate_stop").onclick  = ()=>{
      try{ audio.pause(); audio.currentTime = times ? Math.max(0, times.start) : 0; }catch(e){}
    };

    const seek = (delta)=>{
      try{ audio.currentTime = Math.max(0, (audio.currentTime || 0) + delta); }catch(e){}
    };
    modal.querySelector("#aistate_back3").onclick = ()=>seek(-3);
    modal.querySelector("#aistate_back1").onclick = ()=>seek(-1);
    modal.querySelector("#aistate_fwd1").onclick  = ()=>seek(+1);
    modal.querySelector("#aistate_fwd3").onclick  = ()=>seek(+3);

    // kontekst do zapisania
    modal._ctx = {
      textareaId: textarea.id,
      block,
      times
    };

    // zastosuj do wyniku
    modal.querySelector("#aistate_apply").onclick = ()=>{
      const ctx = modal._ctx;
      if(!ctx) return;
      const outTa = document.getElementById(ctx.textareaId);
      if(!outTa) return;

      if(ctx.block.mode === "selection"){
        outTa.value = outTa.value.slice(0, ctx.block.selStart) + taEdit.value + outTa.value.slice(ctx.block.selEnd);
      }else{
        const arr = (outTa.value || "").split("\n");
        if(ctx.block.start != null && ctx.block.end != null){
          const replacement = (taEdit.value || "").split("\n");
          arr.splice(ctx.block.start, ctx.block.end - ctx.block.start + 1, ...replacement);
          outTa.value = arr.join("\n");
        }
      }

      // zapisz draft, żeby nie znikało po przełączeniu zakładek
      try{ localStorage.setItem(draftKey(outTa.id), outTa.value || ""); }catch(e){}
    };

    // zapis do projektu (jak masz już endpointy save_transcript/save_diarized)
    modal.querySelector("#aistate_save_project").onclick = async ()=>{
      const ctx = modal._ctx;
      if(!ctx) return;
      const outTa = document.getElementById(ctx.textareaId);
      if(!outTa) return;
      const pid = requireProjectId();

      try{
        if(ctx.textareaId === "tr_out"){
          await api(`/api/projects/${pid}/save_transcript`, {
            method:"POST",
            headers:{ "content-type":"application/json" },
            body: JSON.stringify({ text: outTa.value || "" })
          });
          alert("Zapisano transkrypcję ✅");
        }else if(ctx.textareaId === "di_out"){
          await api(`/api/projects/${pid}/save_diarized`, {
            method:"POST",
            headers:{ "content-type":"application/json" },
            body: JSON.stringify({ text: outTa.value || "" })
          });
          alert("Zapisano diaryzację ✅");
        }
      }catch(e){
        alert(e.message || "Błąd zapisu");
      }
    };

    
  }
// ===== Global PPM handler (event delegation) =====
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

  // jeśli Twoje openManualEditor oczekuje textarea, to robimy wrapper
  // Open editor for textarea/div (di_out/tr_out are textareas in this app)
  function _openEditorFor(el, lineIdx){
    try{
      if(typeof openManualEditor === "function"){
        return openManualEditor(el, lineIdx);
      }
      if(typeof window.openManualEditor === "function"){
        return window.openManualEditor(el, lineIdx);
      }
      _toast("Brak openManualEditor() — app.js nie załadował się poprawnie.");
    }catch(e){
      _toast(e && e.message ? e.message : "Błąd otwierania edytora");
    }
  }

  document.addEventListener("contextmenu", (evt)=>{
    const t = evt.target;
    const el =
      t?.closest?.("#tr_out") ||
      t?.closest?.("#di_out") ||
      t?.closest?.("[data-editor='tr_out']") ||
      t?.closest?.("[data-editor='di_out']");
    if(!el) return;

    evt.preventDefault();
    evt.stopPropagation();
    if(typeof evt.stopImmediatePropagation === 'function') evt.stopImmediatePropagation();

    const idx = _lineIndexFromMouse(el, evt);
    try{ _openEditorFor(el, idx); }catch(e){ _toast(e && e.message ? e.message : "Błąd PPM"); }
    return false;
  }, true);
})();
