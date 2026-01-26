// Translation Module - Frontend Logic

let currentTaskId = null;
let currentResults = {};
let currentLanguages = [];

// Installed NLLB models as reported by /api/nllb/models_state
// { fast: [modelId...], accurate: [modelId...] }
let NLLB_INSTALLED = { fast: [], accurate: [] };

function _byId(id){ return document.getElementById(id); }

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

    // Populate model selector from NLLB Settings (installed models)
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
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/api/translation/progress/${currentTaskId}`);
            const data = await response.json();
            
            // Update progress bar
            const progressFill = document.getElementById('progress-fill');
            const progressText = document.getElementById('progress-text');
            const progressStatus = document.getElementById('progress-status');
            
            progressFill.style.width = data.progress + '%';
            progressText.textContent = data.progress + '%';
            progressStatus.textContent = data.status;
            
            // Check if completed
            if (data.status === 'completed') {
                clearInterval(interval);
                displayResults(data);
            } else if (data.status === 'failed') {
                clearInterval(interval);
                throw new Error(data.error || 'Translation failed');
            }
            
        } catch (error) {
            clearInterval(interval);
            console.error('Progress monitoring error:', error);
            alert(trFmt('translation.alert.progress_error',{msg: error.message},'Błąd: {msg}'));
            resetUI();
        }
    }, 1000);
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
        tab.textContent = getLangFlag(lang) + ' ' + getLangName(lang);
        tab.onclick = () => switchLanguageTab(lang);
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
}

// Switch language tab
function switchLanguageTab(lang) {
    // Update tab active state
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => {
        if (tab.textContent.includes(getLangName(lang))) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
    
    // Display translation for this language
    document.getElementById('output-text').value = currentResults[lang] || '';
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
    const activeTab = document.querySelector('.tab.active');
    if (!activeTab) return;
    
    const lang = Object.keys(currentResults).find(l => 
        activeTab.textContent.includes(getLangName(l))
    );
    
    if (lang) {
        currentResults[lang] = document.getElementById('output-text').value;
        alert(tr('translation.alert.saved','Zmiany zapisane ✅'));
    }
}

// Reset output
function resetOutput() {
    if (confirm(tr('translation.confirm.reset','Czy na pewno chcesz zresetować wyniki?'))) {
        document.getElementById('output-container').classList.add('hidden');
        document.getElementById('summary-container').classList.add('hidden');
        currentResults = {};
        currentTaskId = null;
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