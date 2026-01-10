// Analysis tab/page logic (AISTATEweb)
// Depends on /static/app.js helpers: api(), AISTATE, t(), applyI18n()

(function(){
  const QS = (sel, root=document)=>root.querySelector(sel);
  const QSA = (sel, root=document)=>Array.from(root.querySelectorAll(sel));

  function _fmtBytes(n){
    try{
      const u = ["B","KB","MB","GB","TB"];
      let i=0; let x = Number(n||0);
      while(x>=1024 && i<u.length-1){ x/=1024; i++; }
      return `${x.toFixed(i?1:0)} ${u[i]}`;
    }catch{ return String(n||0); }
  }

  function _nowStamp(){
    const d = new Date();
    const pad = (x)=>String(x).padStart(2,"0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}`;
  }

  async function _safeJson(url, opts){
    try{ return await api(url, opts); }catch(e){ return null; }
  }

  const State = {
    projectId: "",
    prompts: {system:[], user:[]},
    selectedTemplates: [],
    quick: null,
    quickMeta: null,
    deepLatest: null,
    deepMeta: null,
    docs: [],
    generating: false,
    es: null,
    fullText: "",
    lastReport: null,
    ollamaOnline: null,
    modelSettings: { quick: null, deep: null },
    installedModels: { quick: [], deep: [] },
    taskId: null,
    progress: 0,
    stage: ""
  };

  function _setProgress(pct){
    const p = Math.max(0, Math.min(100, parseInt(pct||0,10) || 0));
    State.progress = p;
    const pctEl = QS("#an_prog_pct");
    if(pctEl) pctEl.textContent = `${p}%`;
    const bar = QS("#an_prog_bar");
    if(bar) bar.style.width = `${p}%`;
  }

  function _promptLabel(p){
    const icon = String((p && p.icon) || "").trim();
    let name = String((p && p.name) || "").trim();
    // Avoid duplicated emoji when both icon and name contain the same prefix.
    // e.g. icon="📋" and name="📋 Protokół" -> render just one.
    if(icon){
      if(name.startsWith(icon)){
        name = name.slice(icon.length).trim();
      }
      // also handle "icon icon name" cases
      const dbl = `${icon} ${icon}`;
      if(name.startsWith(dbl)){
        name = name.slice(dbl.length).trim();
      }
      return `${icon} ${name}`.trim();
    }
    return name;
  }

  function _status(msg, ok=true){
    const el = QS("#analysis_status_line");
    if(!el) return;
    el.textContent = msg || "";
    el.style.color = ok ? "var(--muted)" : "var(--danger)";
  }

  function _deepState(msg, warn=false){
    const el = QS("#deep_state");
    if(!el) return;
    el.textContent = msg || "";
    el.style.color = warn ? "var(--danger)" : "var(--muted)";
  }

  function _setGenerating(on){
    State.generating = !!on;
    const deepBox = QS("#deep_box");
    if(deepBox){
      deepBox.classList.toggle("generating", State.generating);
    }
    const genBtn = QS("#an_generate_btn");
    if(genBtn) genBtn.disabled = State.generating;
    const stopBtn = QS("#an_stop_btn");
    if(stopBtn) stopBtn.style.display = State.generating ? "" : "none";
  }

  function _renderSelectedCount(){
    const el = QS("#an_selected_count");
    if(el) el.textContent = `${State.selectedTemplates.length}`;
  }

  function _renderPrompts(){
    const box = QS("#prompts_box");
    if(!box) return;

    const mkItem = (p, editable)=>{
      const checked = State.selectedTemplates.includes(p.id) ? "checked" : "";
      const editBtn = editable ? `<button class="btn secondary mini" data-act="edit" data-id="${p.id}">✏️</button>
      <a class="btn secondary mini" href="/api/prompts/${encodeURIComponent(p.id)}/export" target="_blank" rel="noopener">⬇️</a>` : "";
      const label = _promptLabel(p);
      return `
        <div class="prompt-item">
          <label class="check">
            <input type="checkbox" data-act="toggle" data-id="${p.id}" ${checked}>
            <span class="prompt-name">${label}</span>
          </label>
          <div class="prompt-actions">${editBtn}</div>
        </div>
      `;
    };

    let html = "";
    html += `<div class="small section-title">Systemowe</div>`;
    if((State.prompts.system||[]).length){
      html += State.prompts.system.map(p=>mkItem(p, false)).join("");
    }else{
      html += `<div class="small muted">Brak</div>`;
    }

    html += `<div class="small section-title" style="margin-top:10px">Twoje</div>`;
    if((State.prompts.user||[]).length){
      html += State.prompts.user.map(p=>mkItem(p, true)).join("");
    }else{
      html += `<div class="small muted">Brak</div>`;
    }

    box.innerHTML = html;

    // bind
    box.onclick = async (ev)=>{
      const btn = ev.target.closest("[data-act]");
      if(!btn) return;
      const act = btn.getAttribute("data-act");
      const id = btn.getAttribute("data-id");
      if(act==="toggle"){
        // checkbox click handled below
        return;
      }
      if(act==="edit"){
        ev.preventDefault();
        await AnalysisManager.openPromptEditor(id);
      }
    };

    QSA('input[type="checkbox"][data-act="toggle"]', box).forEach(cb=>{
      cb.onchange = ()=>{
        const id = cb.getAttribute("data-id");
        if(!id) return;
        const idx = State.selectedTemplates.indexOf(id);
        if(cb.checked){
          if(idx===-1) State.selectedTemplates.push(id);
        }else{
          if(idx>-1) State.selectedTemplates.splice(idx,1);
        }
        _renderSelectedCount();
      };
    });

    _renderSelectedCount();
  }

  function _renderDocs(){
    const list = QS("#docs_list");
    if(!list) return;

    if(!State.projectId){
      list.innerHTML = `<div class="small muted">Brak projektu</div>`;
      return;
    }

    if(!State.docs.length){
      list.innerHTML = `<div class="small muted">Brak dokumentów</div>`;
      return;
    }

    list.innerHTML = State.docs.map(d=>{
      const id = `doc_${btoa(unescape(encodeURIComponent(d.filename))).replace(/=+/g,'')}`;
      return `
        <div class="doc-item">
          <label class="check">
            <input type="checkbox" class="doc-check" data-fn="${encodeURIComponent(d.filename)}" id="${id}">
            <span>${d.filename}</span>
          </label>
          <div class="small muted">${_fmtBytes(d.size||0)}</div>
          <div class="doc-actions">
            <a class="btn secondary mini" href="/api/documents/${encodeURIComponent(State.projectId)}/download/${encodeURIComponent(d.filename)}" target="_blank" rel="noopener">⬇️</a>
            <button class="btn danger mini" data-del="${encodeURIComponent(d.filename)}">🗑</button>
          </div>
        </div>
      `;
    }).join("");

    list.onclick = async (ev)=>{
      const del = ev.target.closest("button[data-del]");
      if(!del) return;
      const fn = decodeURIComponent(del.getAttribute("data-del")||"");
      if(!fn) return;
      if(!confirm(`Usunąć dokument: ${fn}?`)) return;
      await api(`/api/documents/${encodeURIComponent(State.projectId)}/${encodeURIComponent(fn)}`, {method:"DELETE"});
      await AnalysisManager.loadDocuments();
    };
  }

  function _getIncludeSources(){
    const docs = QSA(".doc-check:checked").map(cb=>decodeURIComponent(cb.getAttribute("data-fn")||"")).filter(Boolean);
    return {
      transcript: QS("#src_transcript")?.checked ?? true,
      diarization: QS("#src_diarization")?.checked ?? true,
      notes_global: QS("#src_notes_global")?.checked ?? false,
      notes_blocks: QS("#src_notes_blocks")?.checked ?? false,
      documents: docs
    };
  }

  function _renderQuick(){
    const body = QS("#quick_body");
    if(!body) return;

    if(!State.projectId){
      body.innerHTML = `<div class="small" data-i18n="analysis.no_project">Najpierw wybierz/utwórz projekt.</div>`;
      try{ applyI18n(); }catch{}
      return;
    }

    if(!State.quick){
      body.innerHTML = `<div class="small muted">Brak. Spróbuj odświeżyć lub uruchomić transkrypcję.</div>`;
      return;
    }

    const q = State.quick;
    const topics = (q.kluczowe_tematy || []).slice(0,12);
    const people = (q.uczestnicy || []).slice(0,12);
    const places = (q.miejsca || []).slice(0,12);
    const dates = (q.terminy || []).slice(0,12);

    body.innerHTML = `
      <div class="quick-grid">
        <div class="quick-row"><b>Tematy:</b> ${topics.length ? topics.join(", ") : "—"}</div>
        <div class="quick-row"><b>Uczestnicy:</b> ${people.length ? people.join(", ") : "—"}</div>
        <div class="quick-stats">
          <span><b>Decyzje:</b> ${q.decyzje ?? "—"}</span>
          <span><b>Zadania:</b> ${q.zadania ?? "—"}</span>
          <span><b>Terminy:</b> ${dates.length}</span>
        </div>
        ${places.length ? `<div class="quick-row"><b>Miejsca:</b> ${places.join(", ")}</div>` : ``}
        ${q.status ? `<div class="small muted">Status: ${q.status}</div>` : ``}
      </div>
    `;
  }

  
  function _fmtIso(iso){
    if(!iso) return "";
    const s = String(iso);
    // 2026-01-10T18:22:00 -> 2026-01-10 18:22:00
    return s.replace("T", " ").replace("Z", "");
  }

  function _renderQuickState(){
    const el = QS("#quick_state");
    if(!el) return;
    const m = State.quickMeta || null;
    if(m && m.model){
      const when = _fmtIso(m.generated_at);
      const dt = m.generation_time ? ` • ${m.generation_time}s` : "";
      el.textContent = `Model: ${m.model}${when ? " • " + when : ""}${dt}`;
    }else{
      el.textContent = "";
    }
  }

  function _renderDeepMeta(){
    if(State.generating) return; // during streaming we show stage/progress
    const m = State.deepMeta || null;
    if(m && m.model){
      const when = _fmtIso(m.generated_at);
      const dt = m.generation_time ? ` • ${m.generation_time}s` : "";
      _deepState(`Model: ${m.model}${when ? " • " + when : ""}${dt}`);
    }else{
      // keep existing hint text if no deep result loaded
    }
  }


  function _renderDeep(text){
    const box = QS("#deep_result");
    if(!box) return;
    // Keep simple rendering for now: preserve whitespace, fast, no external deps.
    box.innerHTML = `<pre class="deep-pre"></pre>`;
    const pre = QS("pre", box);
    pre.textContent = text || "";
  }
  async function _loadOllamaAndSettings(){
    const [st, ms] = await Promise.all([
      _safeJson("/api/ollama/status"),
      _safeJson("/api/settings/models")
    ]);

    // Settings models
    if(ms && typeof ms === 'object'){
      State.modelSettings = {
        quick: ms.quick || null,
        deep: ms.deep || null
      };
    }else{
      State.modelSettings = { quick: null, deep: null };
    }

    // Ollama status
    if(!st || st.status !== "online"){
      State.ollamaOnline = false;
      const hint = st && st.error ? String(st.error) : "offline (sprawdź czy działa usługa i port 11434)";
      _status(`Ollama: ${hint}.`, false);
      return;
    }

    State.ollamaOnline = true;
    const v = st.version ? ` v${st.version}` : "";
    const quick = State.modelSettings && State.modelSettings.quick ? ` | Quick: ${State.modelSettings.quick}` : "";
    const deep = State.modelSettings && State.modelSettings.deep ? ` | Deep: ${State.modelSettings.deep}` : "";
    _status(`Ollama: online${v}${quick}${deep}`, true);
  }

async function _loadInstalledModelChoices(){
  const list = await _safeJson("/api/models/list");
  const quick = Array.isArray(list && list.quick) ? list.quick.filter(m=>m && m.installed) : [];
  const deep = Array.isArray(list && list.deep) ? list.deep.filter(m=>m && m.installed) : [];
  State.installedModels = { quick, deep };
  _renderModelSelectors();
}

function _optionLabel(m){
  const name = m.display_name || m.id;
  const vram = m.vram ? ` • ${m.vram}` : "";
  const speed = m.speed ? ` • ${m.speed}` : "";
  return `${name}${vram}${speed}`;
}

function _renderModelSelectors(){
  const qSel = QS("#an_model_quick");
  const dSel = QS("#an_model_deep");
  if(!qSel || !dSel) return;

  const fill = (sel, arr, currentId)=>{
    sel.innerHTML = "";
    if(!arr.length){
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = t("analysis.no_installed_models") || "Brak zainstalowanych modeli";
      sel.appendChild(opt);
      sel.disabled = true;
      return false;
    }
    arr.forEach(m=>{
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = _optionLabel(m);
      if(m.id === currentId) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.disabled = false;

    const exists = arr.some(m=>m.id === currentId);
    if(!exists){
      sel.value = arr[0].id;
    }
    return !exists; // indicates fallback happened
  };

  const qFallback = fill(qSel, State.installedModels?.quick || [], State.modelSettings?.quick || null);
  const dFallback = fill(dSel, State.installedModels?.deep || [], State.modelSettings?.deep || null);

  // If fallback occurred (setting points to not-installed), persist selection silently
  if(qFallback || dFallback){
    const nextQuick = qSel.value || null;
    const nextDeep = dSel.value || null;
    _saveModelSettings({ quick: nextQuick, deep: nextDeep }).catch(()=>{});
  }
}

async function _saveModelSettings(next){
  const payload = {
    quick: next.quick || (State.modelSettings && State.modelSettings.quick) || null,
    deep: next.deep || (State.modelSettings && State.modelSettings.deep) || null
  };
  const res = await api("/api/settings/models", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });
  State.modelSettings = payload;
  await _loadOllamaAndSettings();
  return res;
}

async function _regenQuickIfNeeded(){
  if(!State.projectId) return;
  const body = QS("#quick_body");
  if(body){
    body.innerHTML = `<div class="small muted">${t("analysis.quick_regenerating") || "Aktualizuję szybką analizę…"}<\/div>`;
  }
  await _safeJson("/api/analysis/quick", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({project_id: State.projectId})
  });
  await _loadQuick();
}

  async function _loadPrompts(){
    const data = await api("/api/prompts/list");
    State.prompts = data || {system:[], user:[]};
    _renderPrompts();
  }

  async function _loadDocs(){
    if(!State.projectId) return;
    const docs = await _safeJson(`/api/documents/${encodeURIComponent(State.projectId)}/list`);
    State.docs = Array.isArray(docs) ? docs : [];
    _renderDocs();
  }

  async function _loadQuick(){
    if(!State.projectId) return;
    let q = await _safeJson(`/api/analysis/quick/${encodeURIComponent(State.projectId)}`);
    if(q && q.status==="success" && q.result){
      State.quick = q.result;
      State.quickMeta = q.meta || null;
      _renderQuick();
      _renderQuickState();
      return;
    }
    // If missing, try generate
    const gen = await _safeJson("/api/analysis/quick", {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({project_id: State.projectId})
    });
    if(gen && gen.status==="success"){
      State.quick = gen.result || null;
      State.quickMeta = gen.meta || null;
      _renderQuick();
      _renderQuickState();
    }
  }

  async function _loadDeep(opts){
    if(!State.projectId) return;
    const options = opts || {};
    const wantContent = options.content !== false;
    const resp = await _safeJson(`/api/analysis/deep/${encodeURIComponent(State.projectId)}`);
    if(resp && resp.status === "success" && resp.result){
      const obj = resp.result;
      State.deepLatest = obj;
      State.deepMeta = (obj && obj.meta) ? obj.meta : null;
      if(wantContent && obj && typeof obj.content === "string" && obj.content.trim()){
        // Only overwrite UI when not generating.
        if(!State.generating){
          State.fullText = obj.content;
          _renderDeep(State.fullText);
        }
      }
      _renderDeepMeta();
      return;
    }
    // No deep saved
    State.deepLatest = null;
    State.deepMeta = null;
  }



  async function _uploadDocs(files){
    if(!files || !files.length) return;
    if(!State.projectId) return;
    for(const f of files){
      const fd = new FormData();
      fd.append("project_id", State.projectId);
      fd.append("file", f, f.name);
      await api("/api/documents/upload", {method:"POST", body: fd});
    }
    await _loadDocs();
  }

  function _selectedFormat(){
    const r = QS('input[name="an_format"]:checked');
    return (r ? r.value : "html");
  }

  function _getDeepModel(){
    return (State.modelSettings && State.modelSettings.deep) ? State.modelSettings.deep : "qwen2.5:32b";
  }

  function _suggestTitle(){
    if(State.selectedTemplates.length){
      return State.selectedTemplates.join("+");
    }
    return "analysis";
  }

  async function _saveReport(content){
    if(!State.projectId) return null;
    const fmt = _selectedFormat();
    const model = _getDeepModel();
    const payload = {
      project_id: State.projectId,
      content: content || "",
      format: fmt,
      title: _suggestTitle(),
      template_ids: State.selectedTemplates,
      model: model
    };
    const res = await api("/api/analysis/save", {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    return res;
  }

  function _showDownload(downloadUrl, filename){
    const slot = QS("#an_download_slot");
    if(!slot) return;
    if(!downloadUrl){
      slot.innerHTML = "";
      return;
    }
    slot.innerHTML = `<a class="btn" href="${downloadUrl}" target="_blank" rel="noopener">📥 Pobierz</a> <span class="small muted">${filename||""}</span>`;
  }

  async function _startStream(){
    if(State.generating) return;
    if(!State.projectId){
      alert("Najpierw wybierz/utwórz projekt.");
      return;
    }
    if(State.ollamaOnline === false){
      alert("Ollama jest offline.");
      return;
    }

    State.fullText = "";
    State.taskId = null;
    _setProgress(0);
    _renderDeep("");
    _deepState("Przygotowanie…");
    _showDownload(null);

    const model = _getDeepModel();
    const include = _getIncludeSources();

    const params = new URLSearchParams();
    params.set("project_id", State.projectId);
    params.set("model", model);
    params.set("template_ids", State.selectedTemplates.join(","));
    params.set("include_sources", JSON.stringify(include));

    const url = "/api/analysis/stream?" + params.toString();

    _setGenerating(true);

    const es = new EventSource(url);
    State.es = es;

    es.onmessage = async (ev)=>{
      try{
        const data = JSON.parse(ev.data);
        if(data.task_id && !State.taskId){
          State.taskId = data.task_id;
        }
        if(typeof data.progress === "number"){
          _setProgress(data.progress);
        }else if(State.generating && data.chunk){
          // Best-effort incremental progress when backend does not provide one.
          _setProgress(Math.min(90, (State.progress||0) + 1));
        }
        if(data.stage){
          _deepState(String(data.stage));
        }
        if(data.chunk){
          State.fullText += data.chunk;
          _renderDeep(State.fullText);
        }
        if(data.done){
          es.close();
          State.es = null;
          _setGenerating(false);
          _setProgress(100);
          _deepState("Zakończono.");
          // Auto-save
          try{
            const saved = await _saveReport(State.fullText);
            if(saved && saved.status==="success"){
              State.lastReport = saved;
              _showDownload(saved.download_url, saved.filename);
            }
          }catch(e){
            console.warn(e);
          }
        }
          // Refresh saved deep meta (model/time) after backend persistence
          try{ await _loadDeep({content:false}); }catch{}
      }catch(e){
        console.error(e);
      }
    };

    es.onerror = ()=>{
      try{ es.close(); }catch{}
      State.es = null;
      _setGenerating(false);
      _deepState("Błąd streamingu.", true);
    };
  }

  async function _stopStream(){
    if(State.es){
      try{ State.es.close(); }catch{}
      State.es = null;
    }
    _setGenerating(false);
    _deepState("Przerwano.", true);
  }

  async function _copy(){
    try{
      await navigator.clipboard.writeText(State.fullText || "");
    }catch(e){
      alert("Nie udało się skopiować (sprawdź uprawnienia przeglądarki).");
    }
  }

  async function _saveManual(){
    if(!State.fullText){
      alert("Brak treści do zapisu.");
      return;
    }
    const saved = await _saveReport(State.fullText);
    if(saved && saved.status==="success"){
      State.lastReport = saved;
      _showDownload(saved.download_url, saved.filename);
      alert("Zapisano raport.");
    }
  }

  // Prompt dialog helpers
  let _editingPromptId = null;

  function _openDialog(){
    const dlg = QS("#prompt_dialog");
    if(dlg && typeof dlg.showModal==="function"){
      dlg.showModal();
    }else{
      alert("Twoja przeglądarka nie wspiera <dialog>. Użyj nowszej wersji.");
    }
  }

  function _closeDialog(){
    const dlg = QS("#prompt_dialog");
    try{ dlg.close(); }catch{}
  }

  function _fillPromptForm(data){
    QS("#prompt_name").value = data.name || "";
    QS("#prompt_icon").value = data.icon || "";
    QS("#prompt_category").value = data.category || "";
    QS("#prompt_description").value = data.description || "";
    QS("#prompt_text").value = data.prompt || "";
  }

  async function _createPrompt(){
    _editingPromptId = null;
    QS("#prompt_dialog_title").textContent = "Nowy prompt";
    QS("#prompt_delete_btn").style.display = "none";
    _fillPromptForm({name:"", icon:"📄", category:"", description:"", prompt:""});
    _openDialog();
  }

  async function _editPrompt(promptId){
    _editingPromptId = promptId;
    QS("#prompt_dialog_title").textContent = `Edycja: ${promptId}`;
    QS("#prompt_delete_btn").style.display = "";

    // Use export endpoint to load full JSON (user prompts)
    let data = null;
    try{
      const res = await fetch(`/api/prompts/${encodeURIComponent(promptId)}/export`);
      if(res.ok){
        data = await res.json();
      }
    }catch(e){ /* ignore */ }

    if(!data){
      alert("Nie udało się wczytać promptu do edycji (tylko custom prompty).");
      return;
    }
    _fillPromptForm(data);
    _openDialog();
  }

  async function _savePrompt(){
    const name = QS("#prompt_name").value.trim();
    const icon = QS("#prompt_icon").value.trim();
    const category = QS("#prompt_category").value.trim();
    const description = QS("#prompt_description").value.trim();
    const prompt = QS("#prompt_text").value;

    if(!name){
      alert("Nazwa jest wymagana.");
      return;
    }

    if(_editingPromptId){
      // update
      const updates = {name, icon, category, description, prompt};
      await api(`/api/prompts/${encodeURIComponent(_editingPromptId)}`, {
        method:"PUT",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(updates)
      });
    }else{
      // create
      await api("/api/prompts/create", {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({name, icon, category, description, prompt})
      });
    }

    await _loadPrompts();
    _closeDialog();
  }

  async function _deletePrompt(){
    if(!_editingPromptId) return;
    if(!confirm(`Usunąć prompt: ${_editingPromptId}?`)) return;
    await api(`/api/prompts/${encodeURIComponent(_editingPromptId)}`, {method:"DELETE"});
    // Remove from selection
    State.selectedTemplates = State.selectedTemplates.filter(x=>x!==_editingPromptId);
    _editingPromptId = null;
    await _loadPrompts();
    _closeDialog();
  }

  async function _importPrompt(file){
    if(!file) return;
    const fd = new FormData();
    fd.append("file", file, file.name);
    const res = await api("/api/prompts/import", {method:"POST", body: fd});
    await _loadPrompts();
    return res;
  }

  function _toggleSidebar(){
    const sb = QS("#analysis_sidebar");
    const btn = QS("#analysis_sidebar_toggle");
    if(!sb || !btn) return;
    const collapsed = sb.classList.toggle("collapsed");
    btn.textContent = collapsed ? "▶︎" : "◀︎";
  }

  function _toggleSettings(){
    const body = QS("#an_settings_body");
    const state = QS("#an_settings_state");
    if(!body || !state) return;
    const isOpen = body.style.display !== "none";
    body.style.display = isOpen ? "none" : "";
    state.textContent = isOpen ? "+" : "−";
  }

  function _toggleQuick(){
    const body = QS("#quick_body");
    const btn = QS("#quick_toggle_btn");
    if(!body || !btn) return;
    const isOpen = body.style.display !== "none";
    body.style.display = isOpen ? "none" : "";
    btn.textContent = isOpen ? "+" : "−";
  }

  async function _bind(){
    QS("#an_generate_btn").onclick = _startStream;
    QS("#an_stop_btn").onclick = _stopStream;
    QS("#an_copy_btn").onclick = _copy;
    QS("#an_save_btn").onclick = _saveManual;

    QS("#analysis_sidebar_toggle").onclick = _toggleSidebar;
    QS("#an_settings_hdr").onclick = _toggleSettings;
    QS("#quick_toggle_btn").onclick = _toggleQuick;

    // docs upload
    const docsBtn = QS("#docs_upload_btn");
    const docsInput = QS("#docs_file_input");
    docsBtn.onclick = ()=>docsInput.click();
    docsInput.onchange = async ()=>{
      await _uploadDocs(Array.from(docsInput.files||[]));
      docsInput.value = "";
    };

    // prompt create/import
    QS("#prompt_new_btn").onclick = _createPrompt;
    const pi = QS("#prompt_import_input");
    QS("#prompt_import_btn").onclick = ()=>pi.click();
    pi.onchange = async ()=>{
      const f = (pi.files||[])[0];
      if(f) await _importPrompt(f);
      pi.value="";
    };

    // dialog save/delete
    QS("#prompt_save_btn").onclick = (ev)=>{
      ev.preventDefault();
      _savePrompt();
    };
    QS("#prompt_delete_btn").onclick = (ev)=>{
      ev.preventDefault();
      _deletePrompt();
    };
  

// model selectors (installed-only)
const qSel = QS("#an_model_quick");
const dSel = QS("#an_model_deep");
if(qSel){
  qSel.onchange = async ()=>{
    const nextQuick = qSel.value || null;
    await _saveModelSettings({ quick: nextQuick });
    // regenerate quick summary so panel matches selected model
    await _regenQuickIfNeeded();
  };
}
if(dSel){
  dSel.onchange = async ()=>{
    const nextDeep = dSel.value || null;
    await _saveModelSettings({ deep: nextDeep });
  };
}
  }

  const AnalysisManager = {
    async init(){
      State.projectId = AISTATE.projectId || "";
      if(!State.projectId){
        _status("Brak aktywnego projektu — wybierz go w zakładce Projekty.", false);
      }
      await _bind();
      await _loadOllamaAndSettings();
      await _loadInstalledModelChoices();
      await _loadPrompts();
      await _loadDocs();
      await _loadQuick();
      await _loadDeep({content:true});
      _renderQuick();
      _renderQuickState();
      _renderDeepMeta();
      try{ applyI18n(); }catch{}
    },

    async loadDocuments(){
      await _loadDocs();
    },

    async openPromptEditor(promptId){
      await _editPrompt(promptId);
    }
  };

  window.AnalysisManager = AnalysisManager;
})();
