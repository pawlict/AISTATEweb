
/

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
    "projects.none": t("projects.none"),
    "projects.no_file": t("projects.no_file"),
    "projects.no_data": t("projects.no_data"),
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

/ Minimal helper: create/load current project id from localStorage
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
