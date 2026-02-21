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

  function _utf8len(s){
    try{ return new TextEncoder().encode(String(s||"")).length; }catch{ return String(s||"").length; }
  }

  function _formatDateTimeMinutes(d){
    const pad = (n)=> String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function _buildAdditionalHeader(model){
    const ts = _formatDateTimeMinutes(new Date());
    return `\n\n## Dodatkowa analiza (${ts}, model=${String(model||"").trim() || "?"})\n\n`;
  }

  const State = {
    projectId: "",
    prompts: {system:[], user:[]},
    selectedTemplates: [],
    selectedDocs: [],
    quick: null,
    quickMeta: null,

    // Quick analysis task (GPU RM managed)
    quickTaskId: null,
    quickTaskStatus: "",
    quickTaskProgress: 0,
    quickTaskTimer: null,
    deepLatest: null,
    deepMeta: null,
    docs: [],
    generating: false,
    es: null,
    fullText: "",
    lastReport: null,
    ollamaOnline: null,
    modelSettings: { quick: null, deep: null },
    analysisSettings: { quick_enabled: true },
    installedModels: { quick: [], deep: [] },
    taskId: null,
    progress: 0,
    stage: "",

    // Deep analysis background task streaming (resilient to tab changes)
    pollTimer: null,
    outputOffset: 0,

    // Persisted per-project UI state
    uiSaveTimer: null
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

  // --- Persisted per-project UI state (custom prompt + sources) ---
  function _uiKey(){
    return State.projectId ? `aistate_analysis_ui_${State.projectId}` : null;
  }

  function _collectUiState(){
    const customPrompt = QS("#custom_prompt_text") ? (QS("#custom_prompt_text").value || "") : "";
    const useTemplates = QS("#custom_prompt_use_templates") ? !!QS("#custom_prompt_use_templates").checked : false;
    const sources = {
      transcript: QS("#src_transcript") ? !!QS("#src_transcript").checked : false,
      diarization: QS("#src_diarization") ? !!QS("#src_diarization").checked : false,
      notes_global: QS("#src_notes_global") ? !!QS("#src_notes_global").checked : false,
      notes_blocks: QS("#src_notes_blocks") ? !!QS("#src_notes_blocks").checked : false
    };
    const selectedTemplates = Array.isArray(State.selectedTemplates) ? State.selectedTemplates.slice() : [];
    const selectedDocs = Array.isArray(State.selectedDocs) ? State.selectedDocs.slice() : [];
    return {
      custom_prompt: customPrompt,
      custom_prompt_use_templates: useTemplates,
      sources,
      selected_templates: selectedTemplates,
      selected_docs: selectedDocs,
    };
  }

  function _applyUiState(st){
    if(!st || typeof st !== "object") return;
    if(QS("#custom_prompt_text") && typeof st.custom_prompt === "string"){
      QS("#custom_prompt_text").value = st.custom_prompt;
    }
    if(QS("#custom_prompt_use_templates") && typeof st.custom_prompt_use_templates === "boolean"){
      QS("#custom_prompt_use_templates").checked = st.custom_prompt_use_templates;
    }
    const src = st.sources && typeof st.sources === "object" ? st.sources : null;
    if(src){
      if(QS("#src_transcript") && typeof src.transcript === "boolean") QS("#src_transcript").checked = src.transcript;
      if(QS("#src_diarization") && typeof src.diarization === "boolean") QS("#src_diarization").checked = src.diarization;
      if(QS("#src_notes_global") && typeof src.notes_global === "boolean") QS("#src_notes_global").checked = src.notes_global;
      if(QS("#src_notes_blocks") && typeof src.notes_blocks === "boolean") QS("#src_notes_blocks").checked = src.notes_blocks;
    }

    // Selected prompts/docs + result mode
    if(Array.isArray(st.selected_templates)){
      State.selectedTemplates = st.selected_templates.map(x=>String(x));
    }
    if(Array.isArray(st.selected_docs)){
      State.selectedDocs = st.selected_docs.map(x=>String(x));
    }
    if(typeof st.result_mode === "string"){
      // result mode UI removed; always append
    }

    // Re-render dependent UIs if data already loaded
    if(State.prompts && (State.prompts.system.length || State.prompts.user.length)){
      _renderPrompts();
    }
    if(Array.isArray(State.docs) && State.docs.length){
      _renderDocs();
    }
  }

  async function _loadUiState(){
    // 1) backend state (preferred)
    const remote = await _safeJson(`/api/analysis/ui_state/${encodeURIComponent(State.projectId)}`);
    if(remote && remote.state){
      _applyUiState(remote.state);
      const k = _uiKey();
      if(k) {
        try{ localStorage.setItem(k, JSON.stringify(remote.state)); }catch{}
      }
      return;
    }
    // 2) localStorage fallback
    const k = _uiKey();
    if(!k) return;
    try{
      const raw = localStorage.getItem(k);
      if(raw){
        const obj = JSON.parse(raw);
        _applyUiState(obj);
      }
    }catch{}
  }

  function _scheduleUiStateSave(){
    if(State.uiSaveTimer) clearTimeout(State.uiSaveTimer);
    State.uiSaveTimer = setTimeout(()=>{ _saveUiState(); }, 350);
  }

  async function _saveUiState(){
    const st = _collectUiState();
    const k = _uiKey();
    if(k){
      try{ localStorage.setItem(k, JSON.stringify(st)); }catch{}
    }
    await _safeJson(`/api/analysis/ui_state/${encodeURIComponent(State.projectId)}` , {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(st)
    });
  }

  function _bindUiStateListeners(){
    const cp = QS("#custom_prompt_text");
    if(cp) cp.addEventListener("input", _scheduleUiStateSave);
    const ut = QS("#custom_prompt_use_templates");
    if(ut) ut.addEventListener("change", _scheduleUiStateSave);
    ["#src_transcript", "#src_diarization", "#src_notes_global", "#src_notes_blocks"].forEach(sel=>{
      const el = QS(sel);
      if(el) el.addEventListener("change", _scheduleUiStateSave);
    });
    // best-effort flush when navigating away
    window.addEventListener("beforeunload", ()=>{
      try{ _saveUiState(); }catch{}
    });
  }

  function _deepState(msg, warn=false){
    const el = QS("#deep_state");
    if(!el) return;
    el.textContent = msg || "";
    el.style.color = warn ? "var(--danger)" : "var(--muted)";
  }

  function _syncDeepGenerateAvailability(){
    const genBtn = QS("#an_generate_btn");
    if(!genBtn) return;
    const quickEnabled = !(State.analysisSettings && State.analysisSettings.quick_enabled === false);
    const blockedByQuick = quickEnabled && !!State.quickTaskId;
    genBtn.disabled = !!State.generating || blockedByQuick;
    if(blockedByQuick){
      genBtn.title = t("analysis.wait_for_quick") || "Quick LLM jeszcze działa — poczekaj aż się zakończy, potem uruchom Deep.";
    } else {
      genBtn.title = "";
    }
  }

  function _setGenerating(on){
    State.generating = !!on;
    const deepBox = QS("#deep_box");
    if(deepBox){
      deepBox.classList.toggle("generating", State.generating);
    }
    _syncDeepGenerateAvailability();
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
      const editBtn = editable ? `<button class="btn secondary mini" data-act="edit" data-id="${p.id}">${aiIcon('edit',12)}</button>
      <a class="btn secondary mini" href="/api/prompts/${encodeURIComponent(p.id)}/export" target="_blank" rel="noopener">${aiIcon('download',12)}</a>` : "";
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
        _scheduleUiStateSave();
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
      const checked = (State.selectedDocs||[]).includes(d.filename) ? "checked" : "";
      return `
        <div class="doc-item">
          <label class="check">
            <input type="checkbox" class="doc-check" data-fn="${encodeURIComponent(d.filename)}" id="${id}" ${checked}>
            <span>${d.filename}</span>
          </label>
          <div class="small muted">${_fmtBytes(d.size||0)}</div>
          <div class="doc-actions">
            <a class="btn secondary mini" href="/api/documents/${encodeURIComponent(State.projectId)}/download/${encodeURIComponent(d.filename)}" target="_blank" rel="noopener">${aiIcon('download',12)}</a>
            <button class="btn danger mini" data-del="${encodeURIComponent(d.filename)}">${aiIcon('delete',12)}</button>
          </div>
        </div>
      `;
    }).join("");

    // Persist selection
    QSA(".doc-check", list).forEach(cb=>{
      cb.addEventListener("change", ()=>{
        const fn = decodeURIComponent(cb.getAttribute("data-fn")||"");
        if(!fn) return;
        const idx = State.selectedDocs.indexOf(fn);
        if(cb.checked){
          if(idx===-1) State.selectedDocs.push(fn);
        }else{
          if(idx>-1) State.selectedDocs.splice(idx,1);
        }
        _scheduleUiStateSave();
      });
    });

    list.onclick = async (ev)=>{
      const del = ev.target.closest("button[data-del]");
      if(!del) return;
      const fn = decodeURIComponent(del.getAttribute("data-del")||"");
      if(!fn) return;
      const ok = await showConfirm({title:'Usunięcie dokumentu',message:'Czy na pewno chcesz usunąć dokument?',detail:fn,confirmText:'Usuń',type:'danger',warning:'Ta operacja jest nieodwracalna.'});
      if(!ok) return;
      await api(`/api/documents/${encodeURIComponent(State.projectId)}/${encodeURIComponent(fn)}`, {method:"DELETE"});
      await AnalysisManager.loadDocuments();
    };
  }

  function _getIncludeSources(){
    const docs = QSA(".doc-check:checked").map(cb=>decodeURIComponent(cb.getAttribute("data-fn")||"")).filter(Boolean);
    return {
      transcript: QS("#src_transcript")?.checked ?? false,
      diarization: QS("#src_diarization")?.checked ?? false,
      notes_global: QS("#src_notes_global")?.checked ?? false,
      notes_blocks: QS("#src_notes_blocks")?.checked ?? false,
      documents: docs
    };
  }

  function _renderQuick(){
    const body = QS("#quick_body");
    if(!body) return;

    if(State.analysisSettings && State.analysisSettings.quick_enabled === false){
      _renderQuickEnabledState();
      return;
    }

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

    // Helper: format number as PLN
    function _fmtPLN(v) {
      if (v == null) return "—";
      return Number(v).toLocaleString("pl-PL", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " " + (q.waluta || "PLN");
    }

    // Detect bank statement response
    const isBankMode = !!(q.wlasciciel_rachunku || q.nr_rachunku_iban || q.saldo_poczatkowe != null || q.saldo_dostepne != null);
    // Detect generic document response
    const isDocMode = !isBankMode && !!(q.typ_dokumentu || q.podmioty || q.kwoty || q.podsumowanie);

    if (isBankMode) {
      body.innerHTML = `
        <div class="quick-grid">
          <div class="quick-row"><b>Właściciel:</b> ${q.wlasciciel_rachunku || "—"}</div>
          <div class="quick-row"><b>Bank:</b> ${q.bank || "—"}</div>
          <div class="quick-row"><b>Nr rachunku (IBAN):</b> <span style="font-family:monospace">${q.nr_rachunku_iban || "—"}</span></div>
          ${q.okres ? `<div class="quick-row"><b>Okres:</b> ${q.okres}</div>` : ``}
          <div class="quick-stats">
            <span><b>Saldo pocz.:</b> ${_fmtPLN(q.saldo_poczatkowe)}</span>
            <span><b>Saldo końc.:</b> ${_fmtPLN(q.saldo_koncowe)}</span>
          </div>
          ${q.saldo_dostepne != null ? `<div class="quick-row"><b>Saldo dostępne:</b> ${_fmtPLN(q.saldo_dostepne)}</div>` : ``}
          ${q.liczba_transakcji != null ? `<div class="small muted">Transakcje: ~${q.liczba_transakcji} | Waluta: ${q.waluta || "PLN"}</div>` : ``}
        </div>
      `;
    } else if (isDocMode) {
      const podmioty = (q.podmioty || []).slice(0,12);
      const kwoty = (q.kwoty || []).slice(0,12);
      const daty = (q.daty || []).slice(0,12);
      const topics = (q.kluczowe_tematy || []).slice(0,12);
      body.innerHTML = `
        <div class="quick-grid">
          ${q.typ_dokumentu ? `<div class="quick-row"><b>Typ dokumentu:</b> ${q.typ_dokumentu}</div>` : ``}
          ${q.podsumowanie ? `<div class="quick-row"><b>Podsumowanie:</b> ${q.podsumowanie}</div>` : ``}
          ${topics.length ? `<div class="quick-row"><b>Tematy:</b> ${topics.join(", ")}</div>` : ``}
          ${podmioty.length ? `<div class="quick-row"><b>Podmioty:</b> ${podmioty.join(", ")}</div>` : ``}
          ${kwoty.length ? `<div class="quick-row"><b>Kwoty:</b> ${kwoty.join(", ")}</div>` : ``}
          ${daty.length ? `<div class="quick-row"><b>Daty:</b> ${daty.join(", ")}</div>` : ``}
          ${q.waluta ? `<div class="small muted">Waluta: ${q.waluta}</div>` : ``}
        </div>
      `;
    } else {
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
    if(State.analysisSettings && State.analysisSettings.quick_enabled === false){
      el.textContent = t("analysis.quick_disabled_state") || "Wyłączona";
      el.style.color = "var(--muted)";
      _syncDeepGenerateAvailability();
      return;
    }
    if(State.quickTaskId){
      const s = String(State.quickTaskStatus || "queued");
      const p = (typeof State.quickTaskProgress === "number") ? State.quickTaskProgress : 0;
      el.textContent = `Quick LLM: ${s}${p ? " (" + p + "%)" : ""}`;
      el.style.color = "var(--muted)";
      _syncDeepGenerateAvailability();
      return;
    }
    const m = State.quickMeta || null;
    if(m && m.model){
      const when = _fmtIso(m.generated_at);
      const dt = m.generation_time ? ` • ${m.generation_time}s` : "";
      el.textContent = `Model: ${m.model}${when ? " • " + when : ""}${dt}`;
    }else{
      el.textContent = "";
    }

    _syncDeepGenerateAvailability();
  }

  function _stopQuickTaskPoll(){
    if(State.quickTaskTimer){
      clearTimeout(State.quickTaskTimer);
      State.quickTaskTimer = null;
    }
  }

  async function _pollQuickTask(taskId){
    if(!taskId) return;
    _stopQuickTaskPoll();

    State.quickTaskId = String(taskId);
    State.quickTaskStatus = State.quickTaskStatus || "queued";
    State.quickTaskProgress = State.quickTaskProgress || 0;
    _renderQuickState();

    const tick = async () => {
      if(!State.quickTaskId) return;
      try{
        const tsk = await _safeJson(`/api/tasks/${encodeURIComponent(taskId)}`);
        if(tsk && tsk.task_id){
          State.quickTaskStatus = String(tsk.status || "");
          State.quickTaskProgress = (typeof tsk.progress === "number") ? tsk.progress : 0;
          _renderQuickState();

          if(State.quickTaskStatus === "done"){
            State.quickTaskId = null;
            State.quickTaskStatus = "";
            State.quickTaskProgress = 0;
            _renderQuickState();
            try{ await _loadQuick(); }catch{}
            return;
          }
          if(State.quickTaskStatus === "error"){
            const body = QS("#quick_body");
            if(body){
              const msg = tsk.error ? String(tsk.error) : (t("analysis.error") || "Błąd");
              const div = document.createElement("div");
              div.className = "small muted";
              div.textContent = `Quick LLM error: ${msg}`;
              body.innerHTML = "";
              body.appendChild(div);
            }
            State.quickTaskId = null;
            State.quickTaskStatus = "";
            State.quickTaskProgress = 0;
            _renderQuickState();
            return;
          }
        }
      }catch(e){
        // ignore transient errors
      }
      State.quickTaskTimer = setTimeout(tick, 2500);
    };

    tick();
  }


  function _renderQuickEnabledState(){
    const enabled = State.analysisSettings ? (State.analysisSettings.quick_enabled !== false) : true;
    const cb = QS("#quick_enabled_toggle");
    if(cb) cb.checked = !!enabled;

    if(!enabled){
      const body = QS("#quick_body");
      if(body){
        body.innerHTML = `<div class="small muted">${t("analysis.quick_disabled") || "Szybka analiza jest wyłączona."}</div>`;
      }
      const el = QS("#quick_state");
      if(el){
        el.textContent = t("analysis.quick_disabled_state") || "Wyłączona";
        el.style.color = "var(--muted)";
      }
    }else{
      // when enabled, quick_state will be rendered by _renderQuickState()
      // keep existing content
    }

    _syncDeepGenerateAvailability();
  }

  async function _loadAnalysisSettings(){
    const s = await _safeJson("/api/settings/analysis");
    let enabled = true;
    if(s && typeof s === "object" && "quick_enabled" in s){
      enabled = !!s.quick_enabled;
    }
    State.analysisSettings = { quick_enabled: enabled };
    _renderQuickEnabledState();
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
    _status(`Ollama: online${v}`, true);
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
  if(State.analysisSettings && State.analysisSettings.quick_enabled === false){
    _renderQuickEnabledState();
    return;
  }
  if(!State.projectId) return;
  const body = QS("#quick_body");
  if(body){
    body.innerHTML = `<div class="small muted">${t("analysis.quick_regenerating") || "Aktualizuję szybką analizę…"}<\/div>`;
  }
  const gen = await _safeJson("/api/analysis/quick", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({project_id: State.projectId})
  });
  if(gen && (gen.status === "queued" || gen.status === "started") && gen.task_id){
    _pollQuickTask(String(gen.task_id));
    return;
  }
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
    if(State.analysisSettings && State.analysisSettings.quick_enabled === false){
      _renderQuickEnabledState();
      return;
    }
    let q = await _safeJson(`/api/analysis/quick/${encodeURIComponent(State.projectId)}`);
    if(q && q.status==="success" && q.result){
      State.quick = q.result;
      State.quickMeta = q.meta || null;
      _renderQuick();
      _renderQuickState();
      return;
    }
    if(State.quickTaskId){
      _renderQuickState();
      return;
    }
    // If missing, request generation (may be queued by GPU RM)
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
      return;
    }
    if(gen && (gen.status === "queued" || gen.status === "started") && gen.task_id){
      const body = QS("#quick_body");
      if(body){
        body.innerHTML = `<div class="small muted">${t("analysis.quick_regenerating") || "Quick analysis queued…"}<\/div>`;
      }
      _pollQuickTask(String(gen.task_id));
      _renderQuickState();
      return;
    }
    _renderQuickState();
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
    if(!State.projectId){
      try { await ensureProjectId("analysis"); State.projectId = AISTATE.projectId; } catch(e) { return; }
    }
    for(const f of files){
      const fd = new FormData();
      fd.append("project_id", State.projectId);
      fd.append("file", f, f.name);
      await api("/api/documents/upload", {method:"POST", body: fd});
    }
    await _loadDocs();
  }

  function _selectedReportFormats(){
    return QSA('input[name="an_report_fmt"]:checked').map(cb=>String(cb.value||"").trim()).filter(Boolean);
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

  function _extractSavedReportInfo(res){
    if(!res || typeof res !== "object") return null;
    // Current API: {status, report:{filename,format,size_bytes,download_url}, ...}
    if(res.report && typeof res.report === "object" && res.report.download_url){
      return {
        filename: res.report.filename || "",
        format: res.report.format || "",
        download_url: res.report.download_url || "",
        size_bytes: res.report.size_bytes || 0,
      };
    }
    // Backward-compat: {filename, format, download_url}
    if(res.download_url || res.filename){
      return {
        filename: res.filename || "",
        format: res.format || "",
        download_url: res.download_url || "",
        size_bytes: res.size_bytes || 0,
      };
    }
    return null;
  }

  async function _saveReport(content, fmt){
    if(!State.projectId) return null;
    const outFmt = String(fmt || "html").toLowerCase().trim();
    const model = _getDeepModel();
    const payload = {
      project_id: State.projectId,
      content: content || "",
      format: outFmt,
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

  function _showDownloads(reports){
    const slot = QS("#an_download_slot");
    if(!slot) return;
    const arr = Array.isArray(reports) ? reports : [];
    if(!arr.length){ slot.innerHTML = ""; return; }
    const links = arr.map(r=>{
      const fmt = String(r.format||"").toUpperCase() || "PLIK";
      const url = r.download_url || "";
      const fn = r.filename || "";
      return `<a class="btn" href="${url}" target="_blank" rel="noopener">${aiIcon('import',14)} ${fmt}</a><span class="small muted">${fn}</span>`;
    }).join(" ");
    slot.innerHTML = `<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center">${links}</div>`;
  }

  async function _pollDeepTask(){
    if(!State.projectId || !State.taskId) return;

    // 1) Update task progress/status
    try{
      const r = await api(`/api/tasks/${encodeURIComponent(State.taskId)}`);
      const task = r || null;
      if(task){
        if(typeof task.progress === "number") _setProgress(task.progress);
        if(task.status) _deepState(String(task.status));

        if(task.status && !["queued", "running"].includes(String(task.status))){
          // Fetch remaining output once more
          try{
            const outFinal = await api(`/api/analysis/task_output/${encodeURIComponent(State.projectId)}?from=${State.outputOffset}&max=524288`);
            if(outFinal?.chunk){
              State.fullText += String(outFinal.chunk);
              State.outputOffset = Number(outFinal.next ?? State.outputOffset);
              _renderDeep(State.fullText);
            }
          }catch{}

          // Stop polling
          if(State.pollTimer){
            clearInterval(State.pollTimer);
            State.pollTimer = null;
          }

          _setGenerating(false);

          if(String(task.status) === "done"){
            _setProgress(100);
            _deepState("Zakończono.");
            try{ await _loadDeep({content:true}); }catch{}
            // Show finance entities panel if finance analysis was run
            _tryLoadFinanceEntities();
          }else{
            _deepState(task && task.error ? ("Błąd: " + String(task.error)) : "Zatrzymano / błąd.", true);
          }
          return;
        }
      }
    }catch(e){
      // ignore transient errors
    }

    // 2) Append output increment
    try{
      const out = await api(`/api/analysis/task_output/${encodeURIComponent(State.projectId)}?from=${State.outputOffset}&max=131072`);
      if(out?.chunk){
        State.fullText += String(out.chunk);
        State.outputOffset = Number(out.next ?? State.outputOffset);
        _renderDeep(State.fullText);
      }
    }catch(e){
      // ignore
    }
  }

  async function _resumeDeepTaskIfAny(){
    if(!State.projectId) return;
    try{
      const st = await api(`/api/analysis/task_state/${encodeURIComponent(State.projectId)}`);
      if(!st || st.status !== "ok" || !st.state || !st.state.task_id) return;
      const t = st.task || {};
      if(!(t.status === "running" || t.status === "queued")) return;

      State.taskId = st.state.task_id;
      _setGenerating(true);

      // If task was started in append-mode, restore prefix (deep_latest + header)
      const base = String(State.deepLatest?.content || "");
      const mode = String(st.state.result_mode || "replace");
      const header = String(st.state.append_header || "");

      if(mode === "append" && header && base.trim()){
        State.fullText = base + header;
        State.outputOffset = _utf8len(State.fullText);
        _renderDeep(State.fullText);
      } else {
        State.fullText = "";
        State.outputOffset = 0;
        _renderDeep("");
      }

      _deepState(st.state.stage || (t.status === "queued" ? "W kolejce…" : "Wznowiono"));
      _setProgress(Number(t.progress || 0));

      if(State.pollTimer) clearInterval(State.pollTimer);
      await _pollDeepTask();
      State.pollTimer = setInterval(_pollDeepTask, 3000);
    } catch(_e) {}
  }

  async function _startStream(){
    // NOTE: kept name for backward UI binding (button "Generuj")
    if(State.generating) return;
    if(!State.projectId){
      try { await ensureProjectId("analysis"); State.projectId = AISTATE.projectId; } catch(e) { return; }
    }
    if(State.ollamaOnline === false){
      showToast("Ollama jest offline.", 'error');
      return;
    }

    // Ensure Quick LLM completes first when the Analysis tab just started generating it.
    const quickEnabled = !(State.analysisSettings && State.analysisSettings.quick_enabled === false);
    if(quickEnabled && State.quickTaskId){
      showToast(t("analysis.wait_for_quick") || "Quick LLM jeszcze działa — poczekaj aż się zakończy, potem uruchom Deep.", 'warning');
      return;
    }

    // Persist UI state before run
    try{ await _saveUiState(); }catch{}

    const model = _getDeepModel();
    const include = _getIncludeSources();

    // Reset UI: always append additional analysis if there is an existing deep result
    const baseText = String(State.deepLatest?.content || State.fullText || "");
    let appendHeader = "";

    State.taskId = null;
    _setProgress(0);
    _showDownloads([]);

    if(baseText.trim()){
      appendHeader = _buildAdditionalHeader(model);
      State.fullText = baseText + appendHeader;
      State.outputOffset = _utf8len(State.fullText);
      _renderDeep(State.fullText);
    } else {
      State.fullText = "";
      State.outputOffset = 0;
      _renderDeep("");
    }
    _deepState("Przygotowanie…");

    const customPrompt = String(QS("#custom_prompt_text")?.value || "").trim();
    const useTemplates = QS("#custom_prompt_use_templates") ? !!QS("#custom_prompt_use_templates").checked : true;

    let templateIds = Array.isArray(State.selectedTemplates) ? State.selectedTemplates.slice() : [];
    if(customPrompt && !useTemplates){
      templateIds = [];
    }

    const payload = {
      project_id: State.projectId,
      model: model,
      template_ids: templateIds,
      include_sources: include,
      custom_prompt: customPrompt,
      custom_prompt_use_templates: useTemplates
    };
    // Result mode: always append (server will fallback to replace if there is no base)
    payload.result_mode = 'append';
    if(appendHeader){
      payload.append_header = appendHeader;
    }

    _setGenerating(true);
    let taskId = null;
    try{
      const r = await api("/api/analysis/start", {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });
      taskId = r?.task_id || r?.task?.task_id || null;
      if(!taskId && r?.state?.task_id) taskId = r.state.task_id;
    }catch(e){
      _setGenerating(false);
      _deepState("Nie udało się uruchomić analizy: " + String(e?.message || e), true);
      return;
    }

    if(!taskId){
      _setGenerating(false);
      _deepState("Brak task_id (błąd uruchomienia).", true);
      return;
    }

    State.taskId = String(taskId);

    if(State.pollTimer){
      clearInterval(State.pollTimer);
      State.pollTimer = null;
    }

    // Immediate poll + periodic updates
    await _pollDeepTask();
    State.pollTimer = setInterval(_pollDeepTask, 3000);
  }

  async function _stopStream(){
    // NOTE: does not cancel server-side analysis; it only detaches UI polling.
    if(State.pollTimer){
      clearInterval(State.pollTimer);
      State.pollTimer = null;
    }
    _setGenerating(false);
    _deepState("Odłączono podgląd.", true);
  }

  async function _copy(){
    try{
      await navigator.clipboard.writeText(State.fullText || "");
    }catch(e){
      showToast("Nie udało się skopiować (sprawdź uprawnienia przeglądarki).", 'error');
    }
  }

  async function _saveManual(){
    if(!State.fullText || !String(State.fullText).trim()){
      showToast(t("analysis.no_content") || "Brak treści do zapisu.", 'warning');
      return;
    }
    const fmts = _selectedReportFormats();
    if(!fmts.length){
      showToast(t("analysis.select_report_format") || "Zaznacz co najmniej jeden format raportu (HTML/DOC/TXT).", 'warning');
      return;
    }

    const savedReports = [];
    for(const fmt of fmts){
      try{
        const res = await _saveReport(State.fullText, fmt);
        const info = _extractSavedReportInfo(res);
        if(info && info.download_url){
          savedReports.push(info);
        }
      }catch(e){
        console.warn(e);
      }
    }
    if(savedReports.length){
      _showDownloads(savedReports);
      showToast(t("analysis.saved") || "Zapisano raport(y).", 'success');
    }else{
      showToast(t("analysis.save_failed") || "Nie udało się zapisać raportu.", 'error');
    }
  }

  // Prompt dialog helpers
  let _editingPromptId = null;

  function _openDialog(){
    const dlg = QS("#prompt_dialog");
    if(dlg && typeof dlg.showModal==="function"){
      dlg.showModal();
    }else{
      showToast("Twoja przeglądarka nie wspiera <dialog>. Użyj nowszej wersji.", 'error');
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
    _fillPromptForm({name:"", icon:"document", category:"", description:"", prompt:""});
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
      showToast("Nie udało się wczytać promptu do edycji (tylko custom prompty).", 'error');
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
      showToast("Nazwa jest wymagana.", 'warning');
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
    const ok = await showConfirm({title:'Usunięcie promptu',message:'Czy na pewno chcesz usunąć ten prompt?',detail:_editingPromptId,confirmText:'Usuń',type:'danger',warning:'Ta operacja jest nieodwracalna.'});
    if(!ok) return;
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
    const saveBtn = QS("#an_save_btn");
    if(saveBtn) saveBtn.onclick = _saveManual;
    const topSave = QS("#an_report_save_btn");
    if(topSave) topSave.onclick = _saveManual;

    QS("#analysis_sidebar_toggle").onclick = _toggleSidebar;
    const _stHdr = QS("#an_settings_hdr");
    if(_stHdr) _stHdr.onclick = _toggleSettings;
    QS("#quick_toggle_btn").onclick = _toggleQuick;

    const qEn = QS("#quick_enabled_toggle");
    if(qEn){
      qEn.onchange = async ()=>{
        const enabled = !!qEn.checked;
        State.analysisSettings = { quick_enabled: enabled };
        try{
          await api("/api/settings/analysis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ quick_enabled: enabled })
          });
        }catch(e){
          console.warn(e);
        }
        if(enabled){
          await _loadQuick();
        }else{
          _renderQuickEnabledState();
        }
      };
    }

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
    // regenerate quick summary so panel matches selected model (only if enabled)
    if(!(State.analysisSettings && State.analysisSettings.quick_enabled === false)){
      await _regenQuickIfNeeded();
    }else{
      _renderQuickEnabledState();
    }
  };
}
if(dSel){
  dSel.onchange = async ()=>{
    const nextDeep = dSel.value || null;
    await _saveModelSettings({ deep: nextDeep });
  };
}

    _bindUiStateListeners();
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
      await _loadAnalysisSettings();
      await _loadUiState();
      await _loadQuick();
      await _loadDeep({content:true});

      // Resume background deep analysis (if running) to avoid losing progress on tab changes
      await _resumeDeepTaskIfAny();
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

  // --- Finance Entity Memory UI ---

  async function _tryLoadFinanceEntities(){
    if(!State.projectId) return;
    // Check if finance parsed data exists
    try{
      const parsed = await _safeJson(`/api/finance/parsed/${encodeURIComponent(State.projectId)}`);
      if(!parsed || !parsed.files || parsed.files.length === 0) return;
      _loadFinanceEntities();
    }catch{}
  }

  async function _loadFinanceEntities(){
    const box = QS("#finance_entities_box");
    const list = QS("#finance_entities_list");
    if(!box || !list) return;

    try{
      const entities = await api(`/api/finance/entities/${encodeURIComponent(State.projectId)}`);
      if(!entities || !Array.isArray(entities) || entities.length === 0){
        box.style.display = "none";
        return;
      }

      box.style.display = "";
      list.innerHTML = "";

      // Group: flagged first, then by type
      for(const ent of entities){
        const row = document.createElement("div");
        row.className = "finance-entity-row" + (ent.flagged ? " flagged" : "");
        row.innerHTML = `
          <span class="fe-name">${_esc(ent.display_name || ent.name)}</span>
          <span class="fe-type small">${_esc(ent.auto_category || ent.entity_type || "—")}</span>
          <span class="fe-seen small">${ent.times_seen || 0}x</span>
          <span class="fe-amount small">${(ent.total_amount||0).toFixed(0)} PLN</span>
          <button class="btn mini fe-flag" title="${ent.flagged ? "Odznacz" : "Oznacz jako podejrzany"}">${ent.flagged ? aiIcon("flag",14) : aiIcon("circle",14)}</button>
        `;
        const btn = row.querySelector(".fe-flag");
        btn.addEventListener("click", ()=> _toggleEntityFlag(ent.name, !ent.flagged, btn));
        list.appendChild(row);
      }
    }catch(e){
      box.style.display = "none";
    }
  }

  async function _toggleEntityFlag(name, flagged, btn){
    try{
      const endpoint = flagged ? "flag" : "unflag";
      await api(`/api/finance/entities/${encodeURIComponent(State.projectId)}/${endpoint}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: name, flagged: flagged}),
      });
      if(btn){
        btn.innerHTML = flagged ? aiIcon("flag",14) : aiIcon("circle",14);
        btn.title = flagged ? "Odznacz" : "Oznacz jako podejrzany";
        const row = btn.closest(".finance-entity-row");
        if(row) row.classList.toggle("flagged", flagged);
      }
    }catch(e){
      console.error("Flag entity error:", e);
    }
  }

  function _esc(s){
    const d = document.createElement("div");
    d.textContent = String(s || "");
    return d.innerHTML;
  }

  // Bind refresh button
  document.addEventListener("DOMContentLoaded", ()=>{
    const refreshBtn = QS("#finance_entities_refresh");
    if(refreshBtn) refreshBtn.addEventListener("click", ()=> _loadFinanceEntities());
  });

  window.AnalysisManager = AnalysisManager;
})();
