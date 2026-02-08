// Translation Module - Frontend Logic

let currentTaskId = null;
let currentResults = {};
let currentLanguages = [];
let trProgressInterval = null;

// Draft persistence
let TR_RESTORING = false;
let TR_SAVE_TIMER = null;
let TR_LAST_SAVED_AT = 0;

// Installed NLLB models as reported by /api/nllb/models_state
// { fast: [modelId...], accurate: [modelId...] }
let NLLB_INSTALLED = { fast: [], accurate: [] };

// Whisper 2-letter language code → NLLB source_lang dropdown value
const WHISPER_TO_NLLB = {
    pl: 'polish', en: 'english', ru: 'russian',
    be: 'belarusian', uk: 'ukrainian', zh: 'chinese'
};

function _byId(id){ return document.getElementById(id); }

function _trProjectId(){
    try{
        if(typeof AISTATE !== 'undefined' && AISTATE && AISTATE.projectId) return String(AISTATE.projectId);
    }catch(e){}
    return '';
}

function _trDraftStorageKey(){
    const pid = _trProjectId() || 'global';
    return `aistate_translation_draft_${pid}`;
}

function _trClientIdStorageKey(){
    return 'aistate_translation_client_id';
}

function _trGetOrCreateClientId(){
    try{
        const existing = localStorage.getItem(_trClientIdStorageKey());
        if(existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
    }catch(e){}
    let cid = '';
    try{
        if(window.crypto && crypto.getRandomValues){
            const a = new Uint8Array(16);
            crypto.getRandomValues(a);
            cid = Array.from(a).map(b=>b.toString(16).padStart(2,'0')).join('');
        }else{
            cid = (Math.random().toString(16).slice(2) + Date.now().toString(16)).slice(0, 32);
        }
    }catch(e){
        cid = String(Date.now());
    }
    cid = ('tr_' + cid).replace(/[^A-Za-z0-9_-]/g,'_').slice(0, 64);
    try{ localStorage.setItem(_trClientIdStorageKey(), cid); }catch(e){}
    return cid;
}

function _trEnsureClientId(){
    try{ _trGetOrCreateClientId(); }catch(e){}
}

function _trStatusLine(msg){
    const el = _byId('translation_status_line');
    if(!el) return;
    el.textContent = msg || '';
}

function _trNowHHMM(){
    try{
        const d = new Date();
        const hh = String(d.getHours()).padStart(2,'0');
        const mm = String(d.getMinutes()).padStart(2,'0');
        return `${hh}:${mm}`;
    }catch(e){
        return '';
    }
}

function _trSafeJsonParse(s){
    try{ return JSON.parse(String(s||'')); }catch(e){ return null; }
}

function _trLoadLocalDraft(){
    try{
        const raw = localStorage.getItem(_trDraftStorageKey());
        const j = _trSafeJsonParse(raw);
        return (j && typeof j === 'object') ? j : null;
    }catch(e){
        return null;
    }
}

async function _trLoadServerDraft(){
    const pid = _trProjectId();
    try{
        if(pid){
            const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/translation/draft`);
            if(!res.ok) return null;
            const j = await res.json();
            const d = j && j.draft;
            const draft = (d && typeof d === 'object') ? d : null;
            // Attach Whisper detected_lang from project meta (returned alongside draft)
            if(draft && j.detected_lang && !draft._detected_lang){
                draft._detected_lang = String(j.detected_lang);
            }
            return draft;
        }
        // Global fallback (not tied to a project)
        const cid = _trGetOrCreateClientId();
        const res = await fetch(`/api/translation/draft/${encodeURIComponent(cid)}`);
        if(!res.ok) return null;
        const j = await res.json();
        const d = j && j.draft;
        return (d && typeof d === 'object') ? d : null;
    }catch(e){
        return null;
    }
}

function _trPickNewerDraft(a, b){
    const ta = (a && typeof a.saved_at === 'number') ? a.saved_at : 0;
    const tb = (b && typeof b.saved_at === 'number') ? b.saved_at : 0;
    if(tb > ta) return b;
    return a;
}

function _trGetActiveOutputLang(){
    const activeTab = document.querySelector('#language-tabs .tab.active');
    if(!activeTab) return '';
    try{
        const dl = activeTab.dataset ? String(activeTab.dataset.lang || '') : '';
        if(dl) return dl;
    }catch(e){}
    const langs = Object.keys(currentResults || {});
    for(const l of langs){
        try{
            if(activeTab.textContent.includes(getLangName(l))) return l;
        }catch(e){}
    }
    return '';
}

function _trCollectDraftState(){
    const inputText = (_byId('input-text') && _byId('input-text').value) ? String(_byId('input-text').value) : '';
    const sourceLang = _byId('source_lang') ? String(_byId('source_lang').value || 'auto') : 'auto';
    const mode = (()=>{ try{ return getSelectedMode(); }catch(e){ return 'fast'; } })();
    const nllbModel = (()=>{ try{ return getSelectedModel(); }catch(e){ return ''; } })();

    const targets = Array.from(document.querySelectorAll('.lang-checkboxes input[type="checkbox"]:checked'))
        .map(cb => String(cb.value||'').trim())
        .filter(Boolean);

    const genSum = _byId('generate_summary') ? !!_byId('generate_summary').checked : false;
    const sumDetail = _byId('summary_detail') ? parseInt(String(_byId('summary_detail').value||'5'), 10) : 5;
    const useGlossary = _byId('use_glossary') ? !!_byId('use_glossary').checked : false;
    const preserveFormatting = _byId('preserve_formatting') ? !!_byId('preserve_formatting').checked : true;

    const reportFormats = Array.from(document.querySelectorAll('input[name="tr_report_fmt"]:checked')).map(el=>String(el.value));

    // Capture output edits for active language (even if user didn't click "Save edits")
    let results = currentResults || {};
    const activeLang = _trGetActiveOutputLang();
    const outEl = _byId('output-text');
    if(activeLang && outEl){
        try{
            results = Object.assign({}, results);
            results[activeLang] = String(outEl.value || '');
        }catch(e){}
    }

    const summaryText = _byId('summary-text') ? String(_byId('summary-text').textContent || '') : '';

    const outputContainer = _byId('output-container');
    const outputVisible = outputContainer ? !outputContainer.classList.contains('hidden') : false;

    return {
        saved_at: Date.now(),
        project_id: _trProjectId() || null,
        input_text: inputText,
        source_lang: sourceLang,
        target_langs: targets,
        mode,
        nllb_model: nllbModel,
        options: {
            generate_summary: genSum,
            summary_detail: isFinite(sumDetail) ? sumDetail : 5,
            use_glossary: useGlossary,
            preserve_formatting: preserveFormatting
        },
        report_formats: reportFormats,
        task_id: currentTaskId || null,
        results: (results && typeof results === 'object' && Object.keys(results).length) ? results : null,
        active_output_lang: activeLang || null,
        summary: summaryText || null,
        output_visible: outputVisible
    };
}

function _trSaveLocalDraft(state){
    try{
        localStorage.setItem(_trDraftStorageKey(), JSON.stringify(state));
        TR_LAST_SAVED_AT = Date.now();
        _trStatusLine(trFmt('translation.status.draft_saved',{time:_trNowHHMM()}, `Zapisano szkic • ${_trNowHHMM()}`));
    }catch(e){
        // localStorage quota can be exceeded for very large texts
        _trStatusLine(tr('translation.status.draft_not_saved','Nie udało się zapisać szkicu (limit pamięci przeglądarki). Zapisałem kopię po stronie serwera.'));
        try{ _trSaveServerDraft(state); }catch(e){}
    }
}

async function _trSaveServerDraft(state){
    try{
        const pid = _trProjectId();
        if(pid){
            await fetch(`/api/projects/${encodeURIComponent(pid)}/translation/draft`, {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({draft: state})
            });
            return;
        }
        // Global fallback (not tied to a project)
        const cid = _trGetOrCreateClientId();
        await fetch(`/api/translation/draft/${encodeURIComponent(cid)}`, {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({draft: state})
        });
    }catch(e){
        // Silent: draft may still exist in localStorage.
    }
}

function _trScheduleSave(reason){
    if(TR_RESTORING) return;
    if(TR_SAVE_TIMER) clearTimeout(TR_SAVE_TIMER);
    TR_SAVE_TIMER = setTimeout(async ()=>{
        const st = _trCollectDraftState();
        _trSaveLocalDraft(st);
        // Best-effort server save (project-scoped)
        await _trSaveServerDraft(st);
    }, 450);
}

function _trSaveLocalOnlyImmediate(){
    if(TR_RESTORING) return;
    try{
        const st = _trCollectDraftState();
        _trSaveLocalDraft(st);
    }catch(e){}
}

function _trRenderResultsFromState(state){
    const results = (state && state.results && typeof state.results === 'object') ? state.results : null;
    if(!results) return;

    currentResults = results || {};

    const outputContainer = _byId('output-container');
    const progressContainer = _byId('progress-container');
    if(progressContainer) progressContainer.classList.add('hidden');
    if(outputContainer) outputContainer.classList.remove('hidden');

    // Create language tabs
    const tabsContainer = _byId('language-tabs');
    if(tabsContainer){
        tabsContainer.innerHTML = '';
        const languages = Object.keys(currentResults);
        languages.forEach((lang, index) => {
            const tab = document.createElement('button');
            tab.className = 'tab' + (index === 0 ? ' active' : '');
            tab.dataset.lang = lang;
            tab.textContent = getLangFlag(lang) + ' ' + getLangName(lang);
            tab.onclick = () => { switchLanguageTab(lang); };
            tabsContainer.appendChild(tab);
        });

        if(languages.length > 0){
            const want = state.active_output_lang && currentResults[state.active_output_lang] ? state.active_output_lang : languages[0];
            switchLanguageTab(want);
        }
    }

    const summary = state.summary;
    const summaryContainer = _byId('summary-container');
    const summaryText = _byId('summary-text');
    if(summary && summaryContainer && summaryText){
        summaryContainer.classList.remove('hidden');
        summaryText.textContent = String(summary);
    }
}

function _trApplyDraftState(state){
    if(!state || typeof state !== 'object') return;

    // Input text
    const inEl = _byId('input-text');
    if(inEl && typeof state.input_text === 'string') inEl.value = state.input_text;

    // Source lang
    const srcEl = _byId('source_lang');
    if(srcEl && typeof state.source_lang === 'string') srcEl.value = state.source_lang;

    // Mode
    if(state.mode){
        const m = String(state.mode);
        const radio = document.querySelector(`input[name="translation_mode"][value="${m}"]`);
        if(radio){
            radio.checked = true;
            radio.dispatchEvent(new Event('change'));
        }
    }

    // Target langs
    const tgt = Array.isArray(state.target_langs) ? state.target_langs.map(String) : [];
    const cbs = document.querySelectorAll('.lang-checkboxes input[type="checkbox"]');
    cbs.forEach(cb => { cb.checked = tgt.includes(String(cb.value)); });
    updateLanguageSelection();

    // Options
    const opts = (state.options && typeof state.options === 'object') ? state.options : {};
    const genSumEl = _byId('generate_summary');
    if(genSumEl) genSumEl.checked = !!opts.generate_summary;
    if(genSumEl) genSumEl.dispatchEvent(new Event('change'));

    const sdEl = _byId('summary_detail');
    if(sdEl && opts.summary_detail !== undefined) sdEl.value = String(opts.summary_detail);

    const ugEl = _byId('use_glossary');
    if(ugEl) ugEl.checked = !!opts.use_glossary;

    const pfEl = _byId('preserve_formatting');
    if(pfEl) pfEl.checked = (opts.preserve_formatting === undefined) ? true : !!opts.preserve_formatting;

    // Report formats
    const rf = Array.isArray(state.report_formats) ? state.report_formats.map(String) : [];
    document.querySelectorAll('input[name="tr_report_fmt"]').forEach(el => {
        el.checked = rf.includes(String(el.value));
    });

    // Model selection (must happen after mode is applied)
    const sel = _byId('tr_model_select');
    if(sel && state.nllb_model){
        const v = String(state.nllb_model);
        // Only set if available in the select
        const has = Array.from(sel.options || []).some(o => String(o.value) === v);
        if(has){
            sel.value = v;
        }
    }

    // Results + summary
    _trRenderResultsFromState(state);

    // Task id
    if(state.task_id) currentTaskId = String(state.task_id);
}

async function _trRestoreDraft(){
    TR_RESTORING = true;
    const local = _trLoadLocalDraft();
    const server = await _trLoadServerDraft();
    const chosen = _trPickNewerDraft(local, server);

    // Auto-set source_lang from Whisper detected language (if no explicit choice saved)
    const detectedLang = (server && server._detected_lang) || (chosen && chosen._detected_lang) || null;
    if(chosen && detectedLang){
        const nllbName = WHISPER_TO_NLLB[detectedLang];
        if(nllbName && (!chosen.source_lang || chosen.source_lang === 'auto')){
            chosen.source_lang = nllbName;
        }
    }

    if(chosen){
        _trApplyDraftState(chosen);
    }

    // Even without a draft, auto-set source_lang from detected language
    if(!chosen && detectedLang){
        const nllbName = WHISPER_TO_NLLB[detectedLang];
        if(nllbName){
            const srcEl = _byId('source_lang');
            if(srcEl) srcEl.value = nllbName;
        }
    }

    TR_RESTORING = false;

    if(chosen){
        _trStatusLine(trFmt('translation.status.draft_restored',{time:_trNowHHMM()}, `Przywrócono szkic • ${_trNowHHMM()}`));
        // Resume task polling if needed
        await _trResumeTaskIfAny(chosen);
        // Ensure we have a local copy (server-only drafts included)
        try{ _trSaveLocalDraft(chosen); }catch(e){}
    }
}

function _trHookDraftAutosave(){
    // Save on navigation away
    window.addEventListener('beforeunload', _trSaveLocalOnlyImmediate);

    // Save when clicking sidebar links
    document.addEventListener('click', (e)=>{
        const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
        if(!a) return;
        if(a.closest && a.closest('.nav')) _trSaveLocalOnlyImmediate();
    }, true);

    // Input text
    const inEl = _byId('input-text');
    if(inEl) inEl.addEventListener('input', ()=>_trScheduleSave('input'));

    // Source lang
    const srcEl = _byId('source_lang');
    if(srcEl) srcEl.addEventListener('change', ()=>_trScheduleSave('source_lang'));

    // Target lang checkboxes
    document.querySelectorAll('.lang-checkboxes input[type="checkbox"]').forEach(cb=>{
        cb.addEventListener('change', ()=>_trScheduleSave('target_langs'));
    });

    // Options
    ['generate_summary','use_glossary','preserve_formatting','summary_detail'].forEach(id=>{
        const el = _byId(id);
        if(!el) return;
        const ev = (id === 'summary_detail') ? 'input' : 'change';
        el.addEventListener(ev, ()=>_trScheduleSave(id));
    });

    // Mode changes
    document.querySelectorAll('input[name="translation_mode"]').forEach(r=>{
        r.addEventListener('change', ()=>_trScheduleSave('mode'));
    });

    // Model selection
    const ms = _byId('tr_model_select');
    if(ms) ms.addEventListener('change', ()=>_trScheduleSave('model'));

    // Report format checkboxes
    document.querySelectorAll('input[name="tr_report_fmt"]').forEach(el=>{
        el.addEventListener('change', ()=>_trScheduleSave('report_formats'));
    });

    // Output edits
    const outEl = _byId('output-text');
    if(outEl) outEl.addEventListener('input', ()=>_trScheduleSave('output'));
}

async function _trResumeTaskIfAny(state){
    const tid = state && state.task_id ? String(state.task_id) : '';
    if(!tid) return;

    currentTaskId = tid;

    try{
        const res = await fetch(`/api/translation/progress/${encodeURIComponent(tid)}`);
        if(!res.ok) return;
        const data = await res.json();
        if(data.status === 'completed'){
            displayResults(data);
            return;
        }
        if(data.status === 'processing'){
            // Show progress and keep polling
            const pc = _byId('progress-container');
            if(pc) pc.classList.remove('hidden');
            const oc = _byId('output-container');
            if(oc) oc.classList.add('hidden');
            const btn = _byId('generate-btn');
            if(btn){
                btn.disabled = true;
                btn.textContent = tr('translation.btn.translating','⏳ Tłumaczenie...');
            }
            monitorProgress();
        }
        if(data.status === 'failed'){
            // Keep draft, but clear task id so user can run again
            currentTaskId = null;
            _trScheduleSave('task_failed');
        }
    }catch(e){
        // Ignore resume errors
    }
}

function tr(key, fallback){
    try{
        if(typeof t === 'function'){
            const v = t(key);
            if(v !== key) return v;
        }
    }catch(e){}
    return (fallback !== undefined) ? fallback : key;
}

function trFmt(key, vars={}, fallback){
    // Prefer global tFmt if available
    try{
        if(typeof tFmt === 'function'){
            const v = tFmt(key, vars);
            if(v !== key) return v;
        }
    }catch(e){}
    let s = tr(key, fallback);
    try{
        Object.keys(vars || {}).forEach(k=>{
            s = s.split(`{${k}}`).join(String(vars[k]));
        });
    }catch(e){}
    return s;
}

function alertError(msg){
    alert(tr('translation.alert.error_prefix','Błąd') + ': ' + msg);
}

async function loadNllbInstalledModels(){
    try{
        const res = await fetch('/api/nllb/models_state');
        const ms = await res.json();
        const fast = Object.keys((ms && ms.fast) || {}).filter(k => !!ms.fast[k]);
        const acc  = Object.keys((ms && ms.accurate) || {}).filter(k => !!ms.accurate[k]);
        NLLB_INSTALLED = { fast, accurate: acc };
    }catch(e){
        console.warn('NLLB models_state failed', e);
        NLLB_INSTALLED = { fast: [], accurate: [] };
    }
    return NLLB_INSTALLED;
}

function getSelectedModel(){
    const sel = _byId('tr_model_select');
    return sel ? String(sel.value || '') : '';
}

function _modelStorageKey(mode){
    return `aistate_translation_nllb_model_${mode}`;
}

function populateModelSelect(){
    const mode = getSelectedMode();
    const sel = _byId('tr_model_select');
    if(!sel) return;

    const models = (mode === 'fast') ? (NLLB_INSTALLED.fast || []) : (NLLB_INSTALLED.accurate || []);

    // Preserve previous selection if still available.
    const saved = localStorage.getItem(_modelStorageKey(mode)) || '';
    const prev = sel.value || '';
    const want = (saved && models.includes(saved)) ? saved : (prev && models.includes(prev) ? prev : (models[0] || ''));

    sel.innerHTML = '';
    if(models.length === 0){
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = tr('translation.model.none_installed','Brak zainstalowanych modeli (zainstaluj w Ustawieniach NLLB)');
        sel.appendChild(opt);
        sel.disabled = true;
        return;
    }

    const opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = tr('translation.model.select_placeholder','Wybierz model…');
    sel.appendChild(opt0);

    for(const m of models){
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        sel.appendChild(opt);
    }

    sel.disabled = false;
    sel.value = want || '';
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    setupModeSelector();
    setupLanguageCheckboxes();
    setupUploadArea();
    setupFileInput();
    setupSummaryToggle();

    // Ensure stable client id (needed for server-side global drafts)
    _trEnsureClientId();

    // Draft autosave hooks (local + per-project server copy)
    _trHookDraftAutosave();

    // Populate model selector from NLLB Settings (installed models) + restore draft
    (async()=>{
        await loadNllbInstalledModels();
        populateModelSelect();

        const sel = _byId('tr_model_select');
        if(sel){
            sel.addEventListener('change', ()=>{
                const mode = getSelectedMode();
                const v = String(sel.value || '');
                localStorage.setItem(_modelStorageKey(mode), v);
            });
        }

        // Restore draft (must happen after model list is loaded)
        await _trRestoreDraft();
    })();
});

// Mode selector (toolbar pills)
function setupModeSelector() {
    const radios = document.querySelectorAll('input[name="translation_mode"]');
    if (!radios || radios.length === 0) return;

    const sync = () => {
        radios.forEach(radio => {
            const label = radio.closest('label');
            if (!label) return;
            if (radio.checked) label.classList.add('selected');
            else label.classList.remove('selected');
        });

        // Mode affects which NLLB models are available
        populateModelSelect();
    };

    radios.forEach(radio => radio.addEventListener('change', sync));
    sync();
}

// Language checkboxes
function setupLanguageCheckboxes() {
    // NOTE: Do NOT use `.lang-checkbox` here because that class is also used for
    // other options (summary/glossary/formatting) which don't have explicit values
    // and default to "on". We only want *target language* checkboxes.
    const checkboxes = document.querySelectorAll('.lang-checkboxes input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.addEventListener('change', updateLanguageSelection);
    });

    // Initial state (defaults may be checked in HTML)
    updateLanguageSelection();
}

function updateLanguageSelection() {
    const supported = new Set(['polish','english','russian','ukrainian','belarusian','chinese']);
    const selected = Array.from(document.querySelectorAll('.lang-checkboxes input[type="checkbox"]:checked'))
        .map(cb => String(cb.value || '').trim())
        .filter(v => supported.has(v));

    currentLanguages = selected;
}

// Upload area - drag & drop
function setupUploadArea() {
    const inputText = document.getElementById('input-text');
    if (!inputText) return;

    // The dedicated drop-zone was removed from the UI.
    // If a drop-zone exists (older templates), use it; otherwise allow drop on the textarea.
    const uploadArea = document.getElementById('upload-area') || inputText;
    
    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    // Highlight drop area
    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.add('dragging');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.remove('dragging');
        }, false);
    });
    
    // Handle drop
    uploadArea.addEventListener('drop', handleDrop, false);
    
    // Allow paste
    inputText.addEventListener('paste', function(e) {
        setTimeout(() => {
            const text = inputText.value;
            if (text.length > 100) {
                estimateTranslationTime(text);
            }
        }, 100);
    });
}

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    
    if (files.length > 0) {
        handleFile(files[0]);
    }
}

// File input
function setupFileInput() {
    const fileInput = document.getElementById('file-input');
    if(!fileInput) return;
    fileInput.addEventListener('change', function(e) {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });
}

async function handleFile(file) {
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileSize = document.getElementById('file-size');
    
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    fileInfo.classList.remove('hidden');
    
    // Upload and extract text
    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('source_lang', document.getElementById('source_lang').value);
        formData.append('target_langs', currentLanguages.join(','));
        formData.append('mode', getSelectedMode());
        
        const response = await fetch('/api/translation/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            const msg = (data && (data.detail || data.error)) || 'Upload failed';
            alertError(msg);
            return;
        }
        
        // Display extracted text
        document.getElementById('input-text').value = data.text;
        estimateTranslationTime(data.text);
        _trScheduleSave('upload');
        
    } catch (error) {
        console.error('Upload error:', error);
        alert(trFmt('translation.alert.upload_error',{msg: error.message},'Błąd podczas wczytywania pliku: {msg}'));
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// Summary toggle
function setupSummaryToggle() {
    const summaryCheckbox = document.getElementById('generate_summary');
    const detailContainer = document.getElementById('summary-detail-container');
    
    summaryCheckbox.addEventListener('change', function() {
        detailContainer.style.display = this.checked ? 'block' : 'none';
    });
}

// Estimate translation time
function estimateTranslationTime(text) {
    const words = text.split(/\s+/).length;
    const mode = getSelectedMode();
    
    const timePerWord = mode === 'fast' ? 0.01 : 0.05; // seconds
    const estimated = Math.ceil(words * timePerWord);
    
    console.log(`Estimated time: ${estimated}s for ${words} words in ${mode} mode`);
}

// Get selected mode
function getSelectedMode() {
    return document.querySelector('input[name="translation_mode"]:checked').value;
}

// Start translation
async function startTranslation() {
    const text = document.getElementById('input-text').value.trim();
    
    if (!text) {
        alert(tr('translation.alert.enter_text','Proszę wprowadzić tekst do przetłumaczenia!'));
        return;
    }
    
    if (currentLanguages.length === 0) {
        alert(tr('translation.alert.choose_target','Proszę wybrać przynajmniej jeden język docelowy!'));
        return;
    }
    
    const sourceLang = document.getElementById('source_lang').value;
    const mode = getSelectedMode();
    const nllbModel = getSelectedModel();
    const generateSummary = document.getElementById('generate_summary').checked;
    const summaryDetail = parseInt(document.getElementById('summary_detail').value);
    const useGlossary = document.getElementById('use_glossary').checked;
    const preserveFormatting = document.getElementById('preserve_formatting').checked;

    if (!nllbModel) {
        alert(tr('translation.alert.choose_model','Wybierz model NLLB (zainstalowany w Ustawieniach NLLB).'));
        return;
    }
    
    // Show progress
    document.getElementById('progress-container').classList.remove('hidden');
    document.getElementById('output-container').classList.add('hidden');
    document.getElementById('generate-btn').disabled = true;
    document.getElementById('generate-btn').textContent = tr('translation.btn.translating','⏳ Tłumaczenie...');
    
    try {
        // Start translation
        const formData = new FormData();
        formData.append('text', text);
        formData.append('source_lang', sourceLang);
        formData.append('target_langs', currentLanguages.join(','));
        formData.append('mode', mode);
        formData.append('nllb_model', nllbModel);
        formData.append('generate_summary', generateSummary);
        formData.append('summary_detail', summaryDetail);
        formData.append('use_glossary', useGlossary);
        formData.append('preserve_formatting', preserveFormatting);
        
        const response = await fetch('/api/translation/translate', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            const msg = (data && (data.detail || data.error)) || 'Translation failed';
            throw new Error(msg);
        }
        
        currentTaskId = data.task_id;
        _trScheduleSave('task_started');
        
        // Monitor progress
        monitorProgress();
        
    } catch (error) {
        console.error('Translation error:', error);
        alert(trFmt('translation.alert.translate_error',{msg: error.message},'Błąd podczas tłumaczenia: {msg}'));
        resetUI();
    }
}

// Monitor translation progress
async function monitorProgress() {
    if(trProgressInterval){
        try{ clearInterval(trProgressInterval); }catch(e){}
        trProgressInterval = null;
    }

    // Cache DOM elements to avoid querySelector every poll
    var _trProgFill = document.getElementById('progress-fill');
    var _trProgText = document.getElementById('progress-text');
    var _trProgStatus = document.getElementById('progress-status');

    trProgressInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/translation/progress/${currentTaskId}`);
            const data = await response.json();

            if (_trProgFill) _trProgFill.style.width = data.progress + '%';
            if (_trProgText) _trProgText.textContent = data.progress + '%';
            if (_trProgStatus) _trProgStatus.textContent = data.status;
            
            // Check if completed
            if (data.status === 'completed') {
                try{ clearInterval(trProgressInterval); }catch(e){}
                trProgressInterval = null;
                displayResults(data);
            } else if (data.status === 'failed') {
                try{ clearInterval(trProgressInterval); }catch(e){}
                trProgressInterval = null;
                throw new Error(data.error || 'Translation failed');
            }
            
        } catch (error) {
            try{ clearInterval(trProgressInterval); }catch(e){}
            trProgressInterval = null;
            console.error('Progress monitoring error:', error);
            alert(trFmt('translation.alert.progress_error',{msg: error.message},'Błąd: {msg}'));
            resetUI();
        }
    }, 3000);
}

// Display translation results
function displayResults(data) {
    currentResults = data.results;
    
    // Hide progress, show output
    document.getElementById('progress-container').classList.add('hidden');
    document.getElementById('output-container').classList.remove('hidden');
    
    // Create language tabs
    const tabsContainer = document.getElementById('language-tabs');
    tabsContainer.innerHTML = '';
    
    const languages = Object.keys(currentResults);
    languages.forEach((lang, index) => {
        const tab = document.createElement('button');
        tab.className = 'tab' + (index === 0 ? ' active' : '');
        tab.dataset.lang = lang;

        // Flag + name
        const labelSpan = document.createElement('span');
        labelSpan.textContent = getLangFlag(lang) + ' ' + getLangName(lang);
        tab.appendChild(labelSpan);

        // TTS speak button inside tab
        const ttsBtn = document.createElement('span');
        ttsBtn.className = 'tts-tab-btn';
        ttsBtn.title = 'Odsłuchaj';
        ttsBtn.innerHTML = (typeof aiIcon === 'function') ? aiIcon('tts_read', 13) : '🔊';
        ttsBtn.onclick = (e) => { e.stopPropagation(); _ttsSpeak(lang, 'output', ttsBtn); };
        tab.appendChild(ttsBtn);

        tab.onclick = () => { switchLanguageTab(lang); };
        tabsContainer.appendChild(tab);
    });
    
    // Display first language
    if (languages.length > 0) {
        switchLanguageTab(languages[0]);
    }
    
    // Display summary if available
    if (data.summary) {
        document.getElementById('summary-container').classList.remove('hidden');
        document.getElementById('summary-text').textContent = data.summary;
    }
    
    // Reset button
    resetUI();

    // Persist results
    _trScheduleSave('results');
}

// Switch language tab
function switchLanguageTab(lang) {
    // Persist current textarea into the previously active language (so user doesn't lose edits)
    try{
        const prev = _trGetActiveOutputLang();
        const outEl = document.getElementById('output-text');
        if(prev && String(prev) !== String(lang) && outEl && currentResults && typeof currentResults === 'object'){
            // Only persist if we were actually on another language tab
            currentResults[String(prev)] = String(outEl.value || '');
        }
    }catch(e){}

    // Update tab active state (scoped)
    const tabs = document.querySelectorAll('#language-tabs .tab');
    tabs.forEach(tab => {
        const dl = tab.dataset ? String(tab.dataset.lang || '') : '';
        if (dl === String(lang)) tab.classList.add('active');
        else tab.classList.remove('active');
    });

    // Display translation for this language
    const out = document.getElementById('output-text');
    if(out){
        const has = (currentResults && Object.prototype.hasOwnProperty.call(currentResults, String(lang)));
        out.value = has ? String(currentResults[String(lang)] || '') : '';
    }

    _trScheduleSave('tab_switch');
}


// Language utilities
function getLangFlag(lang) {
    const flags = {
        'polish': '🇵🇱',
        'english': '🇬🇧',
        'russian': '🇷🇺',
        'belarusian': '🇧🇾',
        'ukrainian': '🇺🇦',
        'chinese': '🇨🇳'
    };
    return flags[lang] || '🌐';
}

function getLangName(lang) {
    // Use UI i18n first (PL/EN), fallback to native names
    try{
        if(typeof t === 'function'){
            const key = `translation.lang_name.${lang}`;
            const v = t(key);
            if(v && v !== key) return v;
        }
    }catch(e){}
    const names = {
        'polish': 'Polski',
        'english': 'English',
        'russian': 'Русский',
        'belarusian': 'Беларускі',
        'ukrainian': 'Українська',
        'chinese': '中文'
    };
    return names[lang] || lang;
}

// Reset UI
function resetUI() {
    document.getElementById('generate-btn').disabled = false;
    document.getElementById('generate-btn').textContent = tr('translation.btn.generate','🚀 Generuj');
}

// Export selected reports is implemented below (single definition)

// Save edits
function saveEdits() {
    // Get current active language
    const activeTab = document.querySelector('#language-tabs .tab.active');
    if (!activeTab) return;

    const lang = (activeTab.dataset && activeTab.dataset.lang) ? String(activeTab.dataset.lang) : Object.keys(currentResults).find(l => activeTab.textContent.includes(getLangName(l)));
    
    if (lang) {
        currentResults[lang] = document.getElementById('output-text').value;
        alert(tr('translation.alert.saved','Zmiany zapisane ✅'));
        _trScheduleSave('save_edits');
    }
}

// Reset output
function resetOutput() {
    if (confirm(tr('translation.confirm.reset','Czy na pewno chcesz zresetować wyniki?'))) {
        document.getElementById('output-container').classList.add('hidden');
        document.getElementById('summary-container').classList.add('hidden');
        currentResults = {};
        currentTaskId = null;
        _trScheduleSave('reset_output');
    }
}

// Export functions
async function exportAs(format) {
    const text = document.getElementById('output-text').value;
    
    if (!text) {
        alert(tr('translation.alert.no_text_to_export','Brak tekstu do eksportu!'));
        return;
    }
    
    try {
        const formData = new FormData();
        formData.append('text', text);
        formData.append('format', format);
        formData.append('filename', 'translation');
        
        const response = await fetch('/api/translation/export', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `translation.${format}`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } else {
            throw new Error('Export failed');
        }
        
    } catch (error) {
        console.error('Export error:', error);
        alert(trFmt('translation.alert.export_error',{msg: error.message},'Błąd podczas eksportu: {msg}'));
    }
}

// Export selected report formats from the toolbar (HTML / DOC / TXT)
// UI-only helper; backend endpoint may be wired later.
async function exportSelectedReports() {
    const selected = Array.from(document.querySelectorAll('input[name="tr_report_fmt"]:checked'))
        .map(el => el.value);

    if (selected.length === 0) {
        alert(tr('translation.alert.choose_report_format','Wybierz przynajmniej jeden format raportu (HTML / DOC / TXT).'));
        return;
    }

    // Map UI values to backend export formats
    const mapFmt = (v) => (v === 'doc' ? 'docx' : v);

    for (const v of selected) {
        // eslint-disable-next-line no-await-in-loop
        await exportAs(mapFmt(v));
    }
}

// Presets
function applyPreset(preset) {
    const presets = {
        'business': {
            mode: 'accurate',
            languages: ['english'],
            summary: true,
            detail: 7
        },
        'transcripts': {
            mode: 'fast',
            languages: ['english', 'russian'],
            summary: false,
            detail: 5
        },
        'scientific': {
            mode: 'accurate',
            languages: ['english'],
            summary: true,
            detail: 9
        }
    };
    
    const config = presets[preset];
    if (!config) return;
    
    // Set mode
    const modeRadio = document.querySelector(`input[name="translation_mode"][value="${config.mode}"]`);
    if (modeRadio) {
        modeRadio.checked = true;
        modeRadio.dispatchEvent(new Event('change'));
    }
    
    // Set languages
    const checkboxes = document.querySelectorAll('.lang-checkboxes input[type="checkbox"]');
    checkboxes.forEach(cb => {
        cb.checked = config.languages.includes(cb.value);
    });
    updateLanguageSelection();
    
    // Set summary
    document.getElementById('generate_summary').checked = config.summary;
    document.getElementById('generate_summary').dispatchEvent(new Event('change'));
    
    // Set detail
    document.getElementById('summary_detail').value = config.detail;
    
    alert(trFmt('translation.alert.preset_loaded',{preset},'Preset załadowany: {preset}'));
}


// ============================================================================
// TTS (Text-to-Speech) Integration
// ============================================================================

var _ttsVoiceMap = null;
var _ttsStatus = null;
var _ttsCurrentAudio = null;
var _ttsCurrentBtn = null;   // button that triggered current playback

var _TTS_ENGINE_NAMES = { piper: 'Piper', mms: 'MMS (Meta)', kokoro: 'Kokoro' };

/** Fetch TTS voice map + status once, populate engine selector */
async function _ttsInit() {
    if (_ttsVoiceMap !== null) return;
    try {
        const [voices, status] = await Promise.all([
            fetch('/api/tts/voices').then(r => r.ok ? r.json() : {}),
            fetch('/api/tts/status').then(r => r.ok ? r.json() : {}),
        ]);
        _ttsVoiceMap = voices || {};
        _ttsStatus = status || {};
    } catch(e) {
        _ttsVoiceMap = {};
        _ttsStatus = {};
    }

    // Populate engine selector with only installed engines
    const sel = document.getElementById('tts-engine-select');
    const box = document.getElementById('tts-engine-box');
    if (sel && _ttsHasAnyEngine()) {
        sel.innerHTML = '';
        const order = ['piper', 'kokoro', 'mms'];
        for (const eng of order) {
            if (_ttsEngineInstalled(eng)) {
                const opt = document.createElement('option');
                opt.value = eng;
                opt.textContent = _TTS_ENGINE_NAMES[eng] || eng;
                sel.appendChild(opt);
            }
        }
        if (box) box.style.display = 'inline-flex';

        // Show source TTS button
        const srcBtn = document.getElementById('tts-input-btn');
        if (srcBtn) srcBtn.style.display = '';
    }
}

function _ttsEngineInstalled(eng) {
    if (!_ttsStatus) return false;
    if (eng === 'mms') return _ttsStatus.mms && _ttsStatus.mms.installed;
    return _ttsStatus[eng] && _ttsStatus[eng].installed;
}

function _ttsHasAnyEngine() {
    return _ttsEngineInstalled('piper') || _ttsEngineInstalled('mms') || _ttsEngineInstalled('kokoro');
}

/** Pick voice for a language using user-selected engine.
 *  Falls back to other engines if selected one lacks the language. */
function _ttsPickVoice(lang) {
    if (!_ttsVoiceMap || !_ttsStatus) return null;

    const langEntry = _ttsVoiceMap[lang];
    if (!langEntry) return null;

    const warn = document.getElementById('tts-engine-warn');
    const sel = document.getElementById('tts-engine-select');
    const chosen = sel ? sel.value : '';

    // Try user-selected engine first
    if (chosen && langEntry[chosen] && _ttsEngineInstalled(chosen)) {
        if (warn) warn.style.display = 'none';
        return { engine: chosen, voice: langEntry[chosen], lang: lang };
    }

    // Selected engine doesn't have this language - try fallback
    const order = ['piper', 'kokoro', 'mms'];
    for (const eng of order) {
        const voice = langEntry[eng];
        if (!voice || !_ttsEngineInstalled(eng)) continue;
        // Show warning about fallback
        if (warn && chosen) {
            warn.textContent = (_TTS_ENGINE_NAMES[chosen] || chosen) +
                ' nie obsługuje tego języka. Użyto: ' + (_TTS_ENGINE_NAMES[eng] || eng);
            warn.style.display = '';
        }
        return { engine: eng, voice: voice, lang: lang };
    }

    return null;
}

/** Stop any currently playing TTS audio */
function _ttsStop() {
    if (_ttsCurrentAudio) {
        _ttsCurrentAudio.pause();
        _ttsCurrentAudio.currentTime = 0;
        _ttsCurrentAudio = null;
    }
    if (_ttsCurrentBtn) {
        _ttsCurrentBtn.classList.remove('playing', 'loading');
        _ttsCurrentBtn = null;
    }
    // Also clear all tab btn playing states
    document.querySelectorAll('.tts-tab-btn.playing, .tts-speak-btn.playing').forEach(
        el => el.classList.remove('playing')
    );
}

/** Toggle TTS: if playing from the same button, stop; otherwise start new */
async function _ttsSpeak(lang, source, triggerBtn) {
    // If the same button is already playing → stop
    if (_ttsCurrentAudio && _ttsCurrentBtn === triggerBtn) {
        _ttsStop();
        return;
    }

    // Stop any previous playback
    _ttsStop();

    await _ttsInit();

    const pick = _ttsPickVoice(lang);
    if (!pick) {
        alert('TTS: brak zainstalowanego silnika dla języka "' + lang + '". Zainstaluj silnik w Ustawieniach TTS.');
        return;
    }

    // Get text
    let text = '';
    if (source === 'input') {
        const el = document.getElementById('input-text');
        text = el ? el.value.trim() : '';
    } else {
        const el = document.getElementById('output-text');
        text = el ? el.value.trim() : '';
    }
    if (!text) return;

    // Limit text length
    if (text.length > 2000) text = text.substring(0, 2000);

    // Show loading state
    const btn = triggerBtn || (source === 'input'
        ? document.getElementById('tts-input-btn')
        : document.getElementById('tts-output-btn'));
    if (btn) btn.classList.add('loading');
    _ttsCurrentBtn = btn;

    try {
        const res = await fetch('/api/tts/synthesize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                engine: pick.engine,
                voice: pick.voice,
                text: text,
                lang: lang,
            }),
        });

        if (!res.ok) {
            console.error('TTS error:', await res.text());
            return;
        }

        const data = await res.json();

        if (data.status === 'cached' && data.audio_url) {
            if (btn) btn.classList.remove('loading');
            _ttsPlayUrl(data.audio_url, btn);
            return;
        }

        // Poll task until done
        if (data.task_id) {
            const audioUrl = data.audio_url;
            while (true) {
                await new Promise(r => setTimeout(r, 600));
                // If user stopped during polling, abort
                if (_ttsCurrentBtn !== btn) return;
                const tsk = await fetch('/api/tasks/' + data.task_id).then(r => r.ok ? r.json() : null);
                if (!tsk) continue;
                if (tsk.status === 'done') {
                    if (btn) btn.classList.remove('loading');
                    _ttsPlayUrl(audioUrl, btn);
                    return;
                }
                if (tsk.status === 'error') {
                    console.error('TTS task failed');
                    return;
                }
            }
        }
    } catch(e) {
        console.error('TTS error:', e);
    } finally {
        if (btn) btn.classList.remove('loading');
    }
}

function _ttsPlayUrl(url, btn) {
    const audio = new Audio(url);
    _ttsCurrentAudio = audio;
    _ttsCurrentBtn = btn;

    if (btn) btn.classList.add('playing');

    audio.onended = () => {
        _ttsCurrentAudio = null;
        _ttsCurrentBtn = null;
        if (btn) btn.classList.remove('playing');
    };
    audio.onerror = () => {
        _ttsCurrentAudio = null;
        _ttsCurrentBtn = null;
        if (btn) btn.classList.remove('playing');
    };

    audio.play().catch(e => {
        console.error('Audio playback error:', e);
        _ttsCurrentAudio = null;
        _ttsCurrentBtn = null;
        if (btn) btn.classList.remove('playing');
    });
}

// Init TTS on page load
document.addEventListener('DOMContentLoaded', () => {
    _ttsInit();

    // Bind source text TTS button (toggle play/stop)
    const srcBtn = document.getElementById('tts-input-btn');
    if (srcBtn) {
        srcBtn.addEventListener('click', () => {
            const srcLang = document.getElementById('source_lang');
            const lang = srcLang ? srcLang.value : 'english';
            _ttsSpeak(lang, 'input', srcBtn);
        });
    }

    // Bind output text TTS button (toggle play/stop)
    const outBtn = document.getElementById('tts-output-btn');
    if (outBtn) {
        outBtn.addEventListener('click', () => {
            const activeLang = _trGetActiveOutputLang ? _trGetActiveOutputLang() : 'english';
            _ttsSpeak(activeLang, 'output', outBtn);
        });
    }
});