"use strict";

// ASR Settings page JS
// - Task progress at the top
// - No logs here (all logs are in /logs)

function qs(id){ return document.getElementById(id); }
function sleep(ms){ return new Promise(r=>setTimeout(r, ms)); }

let ASR_STATUS = null;
let ASR_MODELS_STATE = null;
let ASR_CURRENT_TASK_ID = null;
let ASR_ACTIVE = { engine: "pyannote", id: "" };

function setTaskLogsLink(taskId){
  const a = qs("asr_task_open_logs");
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
  const bar = qs("asr_task_bar");
  if(!bar) return;
  const p = Math.max(0, Math.min(100, parseInt(pct || 0, 10)));
  bar.style.width = p + "%";
}

function setTaskUI(t){
  const st = qs("asr_task_status");
  const pct = qs("asr_task_pct");
  if(st) st.textContent = t ? (t.status || "—") : "—";
  if(pct) pct.textContent = (t ? (t.progress || 0) : 0) + "%";
  setBar(t ? t.progress : 0);
}

function _pkgLine(info){
  if(info && info.installed) return `✅ installed (${info.version || "unknown"})`;
  return "❌ not installed";
}

async function refreshStatus(){
  try{
    ASR_STATUS = await api("/api/asr/status");
    const s = ASR_STATUS || {};

    const ws = qs("asr_whisper_status");
    const nmAsr = qs("asr_nemo_asr_status");
    const nmDiar = qs("asr_nemo_diar_status");
    const pa = qs("asr_pyannote_status");

    if(ws) ws.textContent = _pkgLine(s.whisper);
    if(nmAsr) nmAsr.textContent = _pkgLine(s.nemo);
    if(nmDiar) nmDiar.textContent = _pkgLine(s.nemo);
    if(pa) pa.textContent = _pkgLine(s.pyannote);
    return s;
  }catch(e){
    console.warn("ASR status failed", e);
    return null;
  }
}


function _tSafe(key, fallback){
  try{ if(typeof t === 'function') return t(key); }catch(e){}
  return fallback;
}

function notInstalledSuffix(){
  return _tSafe('asr.model_not_installed_suffix', ' (niezainstalowany)');
}

async function refreshModelStates(force){
  try{
    const url = force ? '/api/asr/models_state?refresh=1' : '/api/asr/models_state';
    ASR_MODELS_STATE = await api(url);
    return ASR_MODELS_STATE;
  }catch(e){
    console.warn('ASR models_state failed', e);
    ASR_MODELS_STATE = null;
    return null;
  }
}

function updateSelectLabels(engine){
  const map = {
    pyannote: 'asr_pyannote_select',
    whisper: 'asr_whisper_select',
    nemo: 'asr_nemo_select',
    nemo_diar: 'asr_nemo_diar_select',
  };
  const sel = qs(map[engine]);
  if(!sel) return;
  const st = (ASR_MODELS_STATE && ASR_MODELS_STATE[engine]) ? ASR_MODELS_STATE[engine] : null;
  const suff = notInstalledSuffix();
  for(const opt of Array.from(sel.options || [])){
    const v = opt.value || '';
    if(!v) continue;
    const ok = st ? !!st[v] : false;
    opt.textContent = v + (ok ? '' : suff);
  }
}

function updateAllSelectLabels(){
  ['whisper','nemo','pyannote','nemo_diar'].forEach(updateSelectLabels);
}

function enginePkgInstalled(engine){
  if(!ASR_STATUS) return false;
  const key = (engine === 'nemo_diar') ? 'nemo' : engine;
  const info = ASR_STATUS[key];
  return !!(info && info.installed);
}

function modelCached(engine, id){
  if(!id) return false;
  const st = (ASR_MODELS_STATE && ASR_MODELS_STATE[engine]) ? ASR_MODELS_STATE[engine] : null;
  return !!(st && st[id]);
}

function updateInstallButton(engine){
  const btnMap = {
    pyannote: 'asr_pyannote_install_btn',
    whisper: 'asr_whisper_install_btn',
    nemo: 'asr_nemo_install_btn',
    nemo_diar: 'asr_nemo_diar_install_btn',
  };
  const btn = qs(btnMap[engine]);
  if(!btn) return;

  const id = getSelected(engine);
  const pkgOk = enginePkgInstalled(engine);
  const cached = modelCached(engine, id);

  if(id && pkgOk && cached){
    btn.style.display = 'none';
    setInline(engine, _tSafe('asr.model_installed_inline', '✅ zainstalowany'));
  }else{
    btn.style.display = 'inline-flex';
    // keep existing inline text (vram etc) but if empty, show simple state
    if(id && cached && !pkgOk){
      setInline(engine, '⚠️ Zainstaluj silnik (pakiet)');
    }
  }
}

function updateAllInstallButtons(){
  ['whisper','nemo','pyannote','nemo_diar'].forEach(updateInstallButton);
}

function getSelected(engine){
  const map = {
    pyannote: "asr_pyannote_select",
    whisper: "asr_whisper_select",
    nemo: "asr_nemo_select",
    nemo_diar: "asr_nemo_diar_select",
  };
  const el = qs(map[engine]);
  return el ? (el.value || "") : "";
}

function setInline(engine, txt){
  const map = {
    pyannote: "asr_pyannote_inline",
    whisper: "asr_whisper_inline",
    nemo: "asr_nemo_inline",
    nemo_diar: "asr_nemo_diar_inline",
  };
  const el = qs(map[engine]);
  if(el) el.textContent = txt || "—";
}

function setCacheCmd(engine, value){
  const map = {
    pyannote: "asr_pyannote_cache_cmd",
    whisper: "asr_whisper_cache_cmd",
    nemo: "asr_nemo_cache_cmd",
    nemo_diar: "asr_nemo_diar_cache_cmd",
  };
  const el = qs(map[engine]);
  if(!el) return;

  if(engine === "pyannote") el.textContent = `Pipeline.from_pretrained('${value || "..."}')`;
  else if(engine === "whisper") el.textContent = `whisper.load_model('${value || "..."}')`;
  else if(engine === "nemo") el.textContent = `ASRModel.from_pretrained('${value || "..."}')`;
  else if(engine === "nemo_diar"){
    const v = String(value||"").toLowerCase();
    if(v.includes("titanet")) el.textContent = `EncDecSpeakerLabelModel.from_pretrained('${value || "..."}')`;
    else el.textContent = `NeuralDiarizer.from_pretrained('${value || "..."}')`;
  }
}

function esc(s){
  return String(s || "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#39;");
}

function uiLang(){
  try{ return (typeof getUiLang === "function") ? getUiLang() : "pl"; }catch(e){ return "pl"; }
}

function pickTxt(v){
  if(!v) return "";
  if(typeof v === "object" && (v.pl || v.en)){
    const lang = uiLang();
    return v[lang] || v.en || v.pl || "";
  }
  return String(v);
}


function pickArr(v){
  if(!v) return [];
  if(typeof v === "object" && (v.pl || v.en)){
    const lang = uiLang();
    return v[lang] || v.en || v.pl || [];
  }
  return Array.isArray(v) ? v : [];
}

function offlineCls(v){
  const s = String(v||"").toLowerCase();
  if(s.includes("✅") || s.includes("yes") || s.includes("tak")) return "offline-yes";
  if(s.includes("❌") || s.includes("no") || s.includes("nie")) return "offline-no";
  return "offline-yes";
}

function renderRichCard(rich){
  if(!rich) return "";
  const offlineTxt = pickTxt(rich.offline);
  const badge = offlineCls(offlineTxt);
  const rec = pickTxt(rich.recommended) || "";
  const recHtml = esc(rec).replace(/\n/g, "<br>");
  const useTitle = pickTxt(rich.use_cases_title) || "Use cases:";
  const featTitle = pickTxt(rich.features_title) || "Features:";
  const recTitle = pickTxt(rich.recommended_title) || "Recommended:";
  const use = pickArr(rich.use_cases);
  const feat = pickArr(rich.features);
  const plq = pickTxt(rich.pl_quality) || "";
  const analysisTime = pickTxt(rich.analysis_time) || "";

  const rows = [
    ["VRAM", rich.vram],
    ["Min GPU", rich.min_gpu],
    ["Optimal GPU", rich.optimal_gpu],
    ["RAM", rich.ram],
    ["Speed", rich.speed],
    ["Analysis time", analysisTime],
    ["Quality", rich.quality],
    ["Polish quality", plq],
    ["Russian/Ukrainian quality", rich.ru_uk_quality],
    ["Max speakers", rich.max_speakers],
    ["Languages", rich.languages],
    ["Architecture", rich.architecture],
    ["Model size", rich.model_size],
  ];

  let kv = '<div class="asr-kv">';
  for(const [k,v] of rows){
    if(v === undefined || v === null) continue;
    const vv = String(v).trim();
    if(!vv) continue;
    kv += `<div class="kv-h">${esc(k)}</div><div>${esc(vv)}</div>`;
  }
  kv += "</div>";

  let reco = '';
  if(rec){
    reco = `<div class="asr-reco"><div class="title">${esc(recTitle)}</div>` +
           `<div>${recHtml}</div>` +
           `<div style="margin-top:8px;"><span class="asr-badge ${badge}">OFFLINE</span> <span class="asr-offline-strong">${esc(offlineTxt)}</span></div>` +
           `</div>`;
  }else if(offlineTxt){
    reco = `<div style="margin-top:10px;"><span class="asr-badge ${badge}">OFFLINE</span> <span class="asr-offline-strong">${esc(offlineTxt)}</span></div>`;
  }

  let list = '';
  if(feat && feat.length){
    list += `<div style="margin-top:10px;"><strong>${esc(featTitle)}</strong></div>` +
            `<ul class="asr-list">` + feat.map(x=>`<li>${esc(x)}</li>`).join('') + `</ul>`;
  }
  if(use && use.length){
    list += `<div style="margin-top:10px;"><strong>${esc(useTitle)}</strong></div>` +
            `<ul class="asr-list">` + use.map(x=>`<li>${esc(x)}</li>`).join('') + `</ul>`;
  }

  const modelLine = rich.model ? `<div class="small" style="margin-bottom:6px;"><code>${esc(rich.model)}</code></div>` : '';
  return modelLine + kv + reco + list;
}

function whisperVram(model){
  const m = String(model||"").toLowerCase();
  const map = {
    "tiny":"~1 GB",
    "base":"~1 GB",
    "small":"~2 GB",
    "medium":"~5 GB",
    "large":"~10 GB",
    "turbo":"~6 GB",
    "large-v2":"~10 GB",
    "large-v3":"~10 GB",
  };
  return map[m] || "~(depends on model)";
}

function nemoVram(model){
  const s = String(model||"").toLowerCase();
  if(s.includes("small")) return "~4–6 GB";
  if(s.includes("multilingual")) return "~10–12 GB";
  if(s.includes("large")) return "~8–12 GB";
  return "~(zależne od modelu)";
}

// Rich per-model metadata (minimal + optimal GPU, accuracy, offline capability).
// Values are intentionally short and practical.
const ASR_MODEL_INFO = {
  whisper: {
    _default: {
      functionality: {pl: "Transkrypcja audio (segment-level).", en: "Audio transcription (segment-level)."},
      accuracy: {pl: "Zależna od rozmiaru modelu.", en: "Depends on model size."},
      offline: {pl: "Tak (po pobraniu modelu).", en: "Yes (after the model is downloaded)."},
      ram: "8–16 GB",
      disk: "~1–10 GB cache",
      notes: {pl: "Klasyczny Whisper (bez alignera).", en: "Classic Whisper (no aligner)."},
    },
    tiny:   { vram: whisperVram("tiny"),   min_gpu: "2 GB VRAM",  optimal_gpu: "4+ GB VRAM",  accuracy: {pl:"Niska (najszybszy)", en:"Low (fastest)"} },
    base:   { vram: whisperVram("base"),   min_gpu: "2 GB VRAM",  optimal_gpu: "4+ GB VRAM",  accuracy: {pl:"Niska/średnia", en:"Low/medium"} },
    small:  { vram: whisperVram("small"),  min_gpu: "4 GB VRAM",  optimal_gpu: "6+ GB VRAM",  accuracy: {pl:"Średnia", en:"Medium"} },
    medium: { vram: whisperVram("medium"), min_gpu: "6 GB VRAM",  optimal_gpu: "8–12 GB VRAM",accuracy: {pl:"Wysoka", en:"High"} },
    large:  { vram: whisperVram("large"),  min_gpu: "10 GB VRAM", optimal_gpu: "12–16 GB VRAM",accuracy: {pl:"Bardzo wysoka", en:"Very high"} },
    "large-v2": { vram: whisperVram("large-v2"), min_gpu: "10 GB VRAM", optimal_gpu: "12–16 GB VRAM", accuracy: {pl:"Bardzo wysoka", en:"Very high"} },
    "large-v3": { vram: whisperVram("large-v3"), min_gpu: "10 GB VRAM", optimal_gpu: "12–16 GB VRAM", accuracy: {pl:"Bardzo wysoka (najlepszy)", en:"Very high (best)"} },
    turbo: {
      vram: whisperVram("turbo"),
      min_gpu: "8 GB VRAM",
      optimal_gpu: "10–12 GB VRAM",
      accuracy: {pl:"Wysoka (minimalnie niższa niż large‑v3)", en:"High (slightly below large‑v3)"},
      notes: {pl:"Turbo jest zoptymalizowany pod transkrypcję (nie do tłumaczeń).", en:"Turbo is optimized for transcription (not for translation)."},
    },
  },

  nemo: {
    _default: {
      functionality: {pl: "ASR NVIDIA NeMo (lokalne modele ASR).", en: "NVIDIA NeMo ASR (local ASR models)."},
      accuracy: {pl: "Zależna od modelu.", en: "Model-dependent."},
      offline: {pl: "✅ Offline po pobraniu wag.", en: "✅ Offline after weights are downloaded."},
      ram: "8–16 GB",
      disk: "~0.1–4 GB cache",
      notes: {pl:"Tryb offline dotyczy inferencji; pobranie wymaga internetu.", en:"Offline refers to inference; downloading requires internet."},
    },

    "nvidia/stt_multilingual_fastconformer_hybrid_large_pc": {
      offline: {pl: "✅ Całkowicie offline po pobraniu (~4GB download)", en: "✅ Fully offline after download (~4GB download)"},
      rich: {
        model: "stt_multilingual_fastconformer_hybrid_large_pc",
        vram: "4-6GB",
        min_gpu: "RTX 3060 12GB",
        optimal_gpu: "RTX 4070 12GB / RTX 4090 24GB",
        ram: "16GB",
        speed: "RTF 0.15 (~6x faster than realtime)",
        analysis_time: {pl: "1min audio = ~10 sekund", en: "1min audio = ~10 seconds"},
        quality: "★★★★★",
        pl_quality: "★★★★★",
        languages: "100+ (PL, EN, DE, ES, FR, RU, UK, CS, SK...)",
        architecture: "Hybrid (CTC + Transducer)",
        model_size: "~1.1B parameters",
        use_cases_title: {pl: "Use cases:", en: "Use cases:"},
        use_cases: {
          pl: [
            "Wielojęzyczna transkrypcja (automatyczne rozpoznawanie języka)",
            "Transkrypcja spotkań międzynarodowych",
            "Podcasts/wywiady w wielu językach",
            "Profesjonalna transkrypcja polska (najlepsza jakość)",
            "Mixed-language content (przełączanie PL↔EN w jednym nagraniu)",
            "Produkcyjna transkrypcja z wysoką dokładnością",
          ],
          en: [
            "Multilingual transcription (automatic language detection)",
            "International meeting transcription",
            "Multilingual podcasts/interviews",
            "Professional Polish transcription (best quality)",
            "Mixed-language content (switching PL↔EN within one recording)",
            "Production-grade transcription with high accuracy",
          ]
        },
        recommended_title: {pl: "Recommended:", en: "Recommended:"},
        recommended: {
          pl: `⭐ NAJLEPSZY WYBÓR dla AISTATEweb. Świetna jakość na polskim,
obsługuje 100+ języków out-of-the-box, nowoczesna architektura (2023),
idealny balans prędkość/jakość. Twoje RTX 4090 x2 obsłużą bez problemu.`,
          en: `⭐ BEST CHOICE for AISTATEweb. Excellent Polish quality,
supports 100+ languages out-of-the-box, modern architecture (2023),
ideal speed/quality balance. Your dual RTX 4090 will handle it easily.`,
        },
        offline: {pl: "✅ Całkowicie offline po pobraniu (~4GB download)", en: "✅ Fully offline after download (~4GB download)"},
      }
    },

    "nvidia/stt_en_conformer_transducer_large": {
      offline: {pl: "✅ Całkowicie offline po pobraniu (~500MB download)", en: "✅ Fully offline after download (~500MB download)"},
      rich: {
        model: "stt_en_conformer_transducer_large",
        vram: "2-3GB",
        min_gpu: "RTX 2060 6GB",
        optimal_gpu: "RTX 3060 8GB",
        ram: "8GB",
        speed: "RTF 0.3 (~3x faster than realtime)",
        analysis_time: {pl: "1min audio = ~20 sekund", en: "1min audio = ~20 seconds"},
        quality: "★★★★★",
        pl_quality: {pl: "⚠️ N/A (English only)", en: "⚠️ N/A (English only)"},
        languages: "EN only",
        architecture: "RNN-Transducer (with Language Model)",
        model_size: "~120M parameters",
        use_cases_title: {pl: "Use cases:", en: "Use cases:"},
        use_cases: {
          pl: [
            "Profesjonalna transkrypcja angielska (najwyższa dokładność)",
            "Techniczne/medyczne nagrania EN (świetnie z terminologią)",
            "Podcasty/audiobooki angielskie",
            "Business meetings w języku angielskim",
            "Gdy potrzebujesz max jakości dla EN (lepsze niż CTC)",
            "Content creation (YouTube, kursy online)",
          ],
          en: [
            "Professional English transcription (highest accuracy)",
            "Technical/medical EN recordings (strong terminology)",
            "English podcasts/audiobooks",
            "Business meetings in English",
            "When you need max EN quality (better than CTC)",
            "Content creation (YouTube, online courses)",
          ]
        },
        recommended_title: {pl: "Recommended:", en: "Recommended:"},
        recommended: {
          pl: `Doskonały dla czystego angielskiego contentu. Model językowy
poprawia dokładność przy trudnych słowach/akcentach. Wolniejszy niż CTC
ale znacznie dokładniejszy.`,
          en: `Excellent for pure English content. The language model
improves accuracy on hard words/accents. Slower than CTC
but significantly more accurate.`,
        },
        offline: {pl: "✅ Całkowicie offline po pobraniu (~500MB download)", en: "✅ Fully offline after download (~500MB download)"},
      }
    },

    "nvidia/stt_en_conformer_ctc_small": {
      offline: {pl: "✅ Całkowicie offline po pobraniu (~60MB download)", en: "✅ Fully offline after download (~60MB download)"},
      rich: {
        model: "stt_en_conformer_ctc_small",
        vram: "1-2GB",
        min_gpu: "GTX 1660 6GB",
        optimal_gpu: "RTX 2060 6GB",
        ram: "4GB",
        speed: "RTF 0.08 (~12x faster than realtime)",
        analysis_time: {pl: "1min audio = ~5 sekund", en: "1min audio = ~5 seconds"},
        quality: "★★★☆☆",
        pl_quality: {pl: "⚠️ N/A (English only)", en: "⚠️ N/A (English only)"},
        languages: "EN only",
        architecture: "CTC (no Language Model)",
        model_size: "~14M parameters",
        use_cases_title: {pl: "Use cases:", en: "Use cases:"},
        use_cases: {
          pl: [
            "Ultra-szybka transkrypcja angielska (real-time capable)",
            "Live transcription/subtitling",
            "Quick preview nagrań (przed deep analysis)",
            "Słabe GPU / limited VRAM",
            "Batch processing dużej ilości plików",
            "Embedded systems / edge devices",
            "Gdy prędkość > dokładność",
          ],
          en: [
            "Ultra-fast English transcription (real-time capable)",
            "Live transcription/subtitling",
            "Quick preview (before deep analysis)",
            "Weak GPU / limited VRAM",
            "Batch processing large volumes",
            "Embedded systems / edge devices",
            "When speed > accuracy",
          ]
        },
        recommended_title: {pl: "Recommended:", en: "Recommended:"},
        recommended: {
          pl: `Idealny dla real-time lub gdy masz ograniczone zasoby GPU.
Błyskawiczny ale niższa dokładność niż Transducer. Świetny do szybkiego
"pierwszego przejścia" przez materiał.`,
          en: `Ideal for real-time or limited GPU resources.
Blazing fast but less accurate than Transducer. Great for a quick
"first pass" over the material.`,
        },
        offline: {pl: "✅ Całkowicie offline po pobraniu (~60MB download)", en: "✅ Fully offline after download (~60MB download)"},
      }
    },
  },


  // NeMo diarization (MSDD diarization + speaker embeddings)
  nemo_diar: {
    _default: {
      functionality: {pl: "Diaryzacja mówców (speaker diarization) w NeMo.", en: "Speaker diarization in NeMo."},
      accuracy: {pl: "Wysoka (MSDD), zależna od modelu.", en: "High (MSDD), model-dependent."},
      offline: {pl: "✅ Offline po pobraniu wag.", en: "✅ Offline after weights are downloaded."},
      ram: "8–16 GB",
      disk: "~0.2–2 GB cache",
      notes: {pl: "Zalecane jako stabilna alternatywa dla pyannote (bez HF tokena).", en: "Recommended as a stable alternative to pyannote (no HF token)."},
    },

    diar_msdd_telephonic: {
      rich: {
        model: "diar_msdd_telephonic",
        vram: "3-4GB",
        min_gpu: "RTX 3060 8GB",
        optimal_gpu: "RTX 4070 12GB / RTX 4090 24GB",
        ram: "16GB",
        speed: "RTF 0.3 (~3x faster than realtime)",
        analysis_time: {pl: "1min audio = ~20 sekund", en: "1min audio = ~20 seconds"},
        quality: "★★★★★",
        pl_quality: "★★★★★",
        ru_uk_quality: "★★★★★",
        max_speakers: "10+ (auto-detect)",
        languages: {pl: "✅ WSZYSTKIE (language-agnostic)", en: "✅ ALL (language-agnostic)"},
        architecture: "MSDD (Multi-Scale Diarization Decoder)",
        model_size: "~1.5GB",
        features_title: {pl: "Funkcje:", en: "Features:"},
        features: {
          pl: [
            "MSDD (Multi-Scale Diarization Decoder)",
            "Najlepsza jakość dla overlapping speech",
            "Automatyczna detekcja liczby mówców",
            "Stabilne GPU (brak hanging jak pyannote!)",
            "Działa doskonale z językami PL/RU/UK/BY",
          ],
          en: [
            "MSDD (Multi-Scale Diarization Decoder)",
            "Best quality for overlapping speech",
            "Automatic speaker count detection",
            "Stable on GPU (no hanging like pyannote)",
            "Excellent for PL/RU/UK/BY speech",
          ],
        },
        use_cases_title: {pl: "Use cases:", en: "Use cases:"},
        use_cases: {
          pl: [
            "Profesjonalna diaryzacja wielojęzyczna",
            "Międzynarodowe spotkania (PL+EN+RU mix)",
            "Overlapping speech",
            "2-10+ mówców",
            "Trudne warunki akustyczne",
          ],
          en: [
            "Professional multilingual diarization",
            "International meetings (PL+EN+RU mix)",
            "Overlapping speech",
            "2-10+ speakers",
            "Hard acoustic conditions",
          ],
        },
        recommended_title: {pl: "Recommended:", en: "Recommended:"},
        recommended: {
          pl: "⭐⭐⭐ NAJLEPSZY WYBÓR dla Twoich języków! Świetna jakość, stabilne, działa z każdym językiem. ZAMIEŃ pyannote na to!",
          en: "⭐⭐⭐ BEST CHOICE for your languages! Great quality, stable, language-agnostic. Replace pyannote with this.",
        },
        offline: {pl: "✅ Całkowicie offline (~1.5GB)", en: "✅ Fully offline (~1.5GB)"},
      }
    },

    titanet_large: {
      rich: {
        model: "titanet_large",
        vram: "2-3GB",
        min_gpu: "RTX 2060 6GB",
        optimal_gpu: "RTX 3060 8GB",
        ram: "8GB",
        speed: "RTF 0.2 (~5x faster than realtime)",
        analysis_time: {pl: "1min audio = ~12 sekund", en: "1min audio = ~12 seconds"},
        quality: "★★★★☆",
        pl_quality: "★★★★☆",
        ru_uk_quality: "★★★★☆",
        max_speakers: {pl: "2-5 (najlepiej do 5)", en: "2-5 (best up to 5)"},
        languages: {pl: "✅ WSZYSTKIE (language-agnostic)", en: "✅ ALL (language-agnostic)"},
        architecture: {pl: "Embeddings (speaker recognition)", en: "Embeddings (speaker recognition)"},
        model_size: "~500MB",
        features_title: {pl: "Funkcje:", en: "Features:"},
        features: {
          pl: [
            "Szybki",
            "Prostsza architektura (embeddings)",
            "Dobry dla małych grup (2-5 osób)",
            "Lekki",
          ],
          en: [
            "Fast",
            "Simpler architecture (embeddings)",
            "Great for small groups (2-5 people)",
            "Lightweight",
          ],
        },
        use_cases_title: {pl: "Use cases:", en: "Use cases:"},
        use_cases: {
          pl: [
            "Spotkania 1:1 lub małe grupy (max 5 osób)",
            "Gdy masz przewidywalną liczbę mówców",
            "Szybka diaryzacja dla prostych przypadków",
          ],
          en: [
            "1:1 meetings or small groups (max 5 people)",
            "When the speaker count is predictable",
            "Fast diarization for simpler cases",
          ],
        },
        recommended_title: {pl: "Recommended:", en: "Recommended:"},
        recommended: {
          pl: "★★★ OK jeśli wiesz że masz max 5 osób. Jeśli więcej lub overlapping speech → użyj MSDD.",
          en: "★★★ OK if you know it's max 5 speakers. For more or overlapping speech → use MSDD.",
        },
        offline: {pl: "✅ Całkowicie offline (~500MB)", en: "✅ Fully offline (~500MB)"},
      }
    },
  },


  pyannote: {
    _default: {
      functionality: {pl: "Diaryzacja mówców (speaker diarization).", en: "Speaker diarization."},
      accuracy: {pl: "Zależna od pipeline; 3.1 zwykle najlepszy.", en: "Pipeline-dependent; 3.1 is usually best."},
      offline: {pl: "❌ Wymaga tokena HF i połączenia z HuggingFace do pobrania/uruchomienia pipeline. Po zbuforowaniu może działać offline, ale token/akceptacja licencji nadal są wymagane.", en: "❌ Requires an HF token and an internet connection to download/run the pipeline from HuggingFace. After caching it may run offline, but token/license acceptance is still required."},
      vram: "~4–8 GB",
      min_gpu: "4–6 GB VRAM",
      optimal_gpu: "8–12 GB VRAM",
      ram: "8–16 GB",
      disk: "~1–5 GB cache",
    },
    "pyannote/speaker-diarization-3.1": { accuracy: {pl:"Bardzo wysoka", en:"Very high"}, notes: {pl:"Wymaga zaakceptowania licencji na HF.", en:"Requires accepting the HF model license."} },
    "pyannote/speaker-diarization-community-1": { accuracy: {pl:"Średnia", en:"Medium"}, notes: {pl:"Community (często mniej dokładny, ale wygodny).", en:"Community (often less accurate, but convenient)."} },
    "pyannote/speaker-diarization": { accuracy: {pl:"Średnia/wysoka (legacy)", en:"Medium/high (legacy)"}, notes: {pl:"Starszy pipeline (2.x/legacy).", en:"Older pipeline (2.x/legacy)."} },
  },
};

function infoFor(engine, id){
  const e = String(engine||"").toLowerCase();
  const key = String(id||"").trim();
  const db = ASR_MODEL_INFO[e] || {};
  const base = db._default || {};
  const specific = (key && db[key]) ? db[key] : (key && db[key.toLowerCase()]) ? db[key.toLowerCase()] : {};

  const namePrefix = (e === "pyannote") ? "pyannote"
    : (e === "nemo") ? "NeMo ASR"
    : (e === "nemo_diar") ? "NeMo Diarization"
    : "Whisper";
  return {
    name: `${namePrefix} — ${key || "—"}`
    , rich: specific.rich || null,
    functionality: pickTxt(specific.functionality || base.functionality),
    accuracy: pickTxt(specific.accuracy || base.accuracy),
    offline: pickTxt(specific.offline || base.offline),
    vram: specific.vram || base.vram || (e === "whisper" ? whisperVram(key) : (e === "nemo" ? nemoVram(key) : "—")),
    min_gpu: specific.min_gpu || base.min_gpu || "—",
    optimal_gpu: specific.optimal_gpu || base.optimal_gpu || "—",
    ram: specific.ram || base.ram || "—",
    disk: specific.disk || base.disk || "—",
    notes: pickTxt(specific.notes || base.notes) || "",
  };
}

function boxIds(engine){
  const map = {
    pyannote: { name: "asr_info_name_pyannote", body: "asr_info_body_pyannote", warn: "asr_info_warning_pyannote" },
    whisper:  { name: "asr_info_name_whisper",  body: "asr_info_body_whisper",  warn: "asr_info_warning_whisper" },
    nemo:     { name: "asr_info_name_nemo",     body: "asr_info_body_nemo",     warn: "asr_info_warning_nemo" },
    nemo_diar:{ name: "asr_info_name_nemo_diar",body: "asr_info_body_nemo_diar",warn: "asr_info_warning_nemo_diar" },
  };
  return map[String(engine||"").toLowerCase()] || null;
}


function renderInfo(engine, id){
  const ids = boxIds(engine);
  if(!ids) return;

  const boxName = qs(ids.name);
  const boxBody = qs(ids.body);
  const boxWarn = qs(ids.warn);

  const info = infoFor(engine, id);
  if(boxName) boxName.textContent = info.name || "—";

  if(boxBody){
    if(info.rich){
      boxBody.innerHTML = renderRichCard(info.rich) || "";
    }else{
      const rows = [
        {k: t("asr.info.functionality"), v: info.functionality},
        {k: t("asr.info.accuracy"), v: info.accuracy},
        {k: t("asr.info.offline"), v: info.offline, kind: "offline"},
        {k: t("asr.info.vram_estimate"), v: info.vram},
        {k: t("asr.info.min_gpu"), v: info.min_gpu},
        {k: t("asr.info.optimal_gpu"), v: info.optimal_gpu},
        {k: t("asr.info.ram"), v: info.ram},
        {k: t("asr.info.disk"), v: info.disk},
      ];
      if(info.notes) rows.push({k: t("asr.info.notes"), v: info.notes});

      let html = `<div class="asr-kv">`;
      for(const r of rows){
        const vv = String(r.v || "—").trim() || "—";
        if(r.kind === "offline"){
          const cls = offlineCls(vv);
          html += `<div class="kv-h">${esc(r.k)}</div><div><span class="asr-badge ${cls}">OFFLINE</span> <span class="asr-offline-strong">${esc(vv)}</span></div>`;
        }else{
          html += `<div class="kv-h">${esc(r.k)}</div><div>${esc(vv)}</div>`;
        }
      }
      html += `</div>`;
      boxBody.innerHTML = html;
    }
  }

  if(boxWarn){
    boxWarn.style.display = "none";
    boxWarn.textContent = "";
    if(String(engine) === "pyannote" && ASR_STATUS && ASR_STATUS.hf_token_present === false){
      boxWarn.style.display = "block";
      boxWarn.textContent = "⚠️ pyannote: Brak tokena HuggingFace w Ustawieniach (HF token).";
    }
  }
}


function renderAllInfos(){
  ["whisper","nemo","pyannote","nemo_diar"].forEach(eng=>{
    renderInfo(eng, getSelected(eng));
  });
}

function updateEngine(engine){
  const id = getSelected(engine);
  setInline(engine, id ? `Selected: ${id}` : "—");
  setCacheCmd(engine, id);
}

function setActive(engine){
  const id = getSelected(engine);
  ASR_ACTIVE = { engine, id };
  updateEngine(engine);
  renderInfo(engine, id);
}

async function runTask(path, payload){
  const res = await api(path, {
    method: "POST",
    headers: {"content-type":"application/json"},
    body: JSON.stringify(payload || {}),
    keepalive: true
  });

  ASR_CURRENT_TASK_ID = res.task_id;

  // Allow quick navigation to Logs for this task.
  setTaskLogsLink(ASR_CURRENT_TASK_ID);

  // Persist task so progress can be resumed after changing tabs/pages.
  try{
    if(window.AISTATE && typeof AISTATE.setTaskId === "function"){
      AISTATE.setTaskId("asr", ASR_CURRENT_TASK_ID);
    }
    if(window.AISTATE){ AISTATE.lastTaskId = ASR_CURRENT_TASK_ID; }
  }catch(e){}

  setTaskUI({status:"running", progress:0});

  while(true){
    const tsk = await api(`/api/tasks/${ASR_CURRENT_TASK_ID}`);
    setTaskUI(tsk);
    if(tsk.status === "done" || tsk.status === "error"){
      try{ if(window.AISTATE && typeof AISTATE.setTaskId === "function") AISTATE.setTaskId("asr", ""); }catch(e){}
      setTaskLogsLink(ASR_CURRENT_TASK_ID);
      return tsk;
    }
    await sleep(700);
  }
}

async function resumeAsrTaskIfAny(){
  try{
    const tid = (window.AISTATE && typeof AISTATE.getTaskId === "function") ? AISTATE.getTaskId("asr") : "";
    if(!tid) return;
    ASR_CURRENT_TASK_ID = tid;
    setTaskLogsLink(tid);

    const tsk = await api(`/api/tasks/${tid}`);
    setTaskUI(tsk);

    if(tsk.status === "running" || tsk.status === "queued"){
      // keep polling until it finishes
      while(true){
        const cur = await api(`/api/tasks/${tid}`);
        setTaskUI(cur);
        if(cur.status === "done" || cur.status === "error") break;
        await sleep(700);
      }
    }

    try{ if(window.AISTATE && typeof AISTATE.setTaskId === "function") AISTATE.setTaskId("asr", ""); }catch(e){}
  }catch(e){
    try{ if(window.AISTATE && typeof AISTATE.setTaskId === "function") AISTATE.setTaskId("asr", ""); }catch(_e){}
  }
}

async function ensureAndDownload(engine){
  const id = getSelected(engine);
  if(!id){
    setInline(engine, "⚠️ Wybierz model/pipeline przed instalacją.");
    return;
  }

  const st = await refreshStatus() || {};
  const compInfo = st[engine];
  const component = (engine === "nemo_diar") ? "nemo" : engine;

  // 1) Ensure package installed
  if(!compInfo || !compInfo.installed){
    const t1 = await runTask("/api/asr/install", {component});
    if(t1.status === "error"){
      await refreshStatus();
      return;
    }
  }

  // 2) Download/cache model/pipeline
  const payload = {engine};
  if(engine === "pyannote") payload.pipeline = id;
  else payload.model = id;

  await runTask("/api/asr/predownload", payload);

  // 3) Refresh
  await refreshStatus();
  await refreshModelStates(true);
  updateAllSelectLabels();
  updateAllInstallButtons();
  renderAllInfos();
}

function bindUI(){
  const selects = [
    qs("asr_pyannote_select"),
    qs("asr_whisper_select"),
    qs("asr_nemo_select"),
    qs("asr_nemo_diar_select"),
  ].filter(Boolean);

  selects.forEach(sel=>{
    const eng = sel.getAttribute("data-engine") || "";
    sel.addEventListener("change", ()=>{ if(eng){ setActive(eng); renderInfo(eng, getSelected(eng)); updateInstallButton(eng); } });
    sel.addEventListener("click", ()=>{ if(eng){ setActive(eng); renderInfo(eng, getSelected(eng)); updateInstallButton(eng); } });
  });

  const btns = [
    qs("asr_pyannote_install_btn"),
    qs("asr_whisper_install_btn"),
    qs("asr_nemo_install_btn"),
    qs("asr_nemo_diar_install_btn"),
  ].filter(Boolean);

  btns.forEach(btn=>{
    btn.addEventListener("click", async ()=>{
      const eng = btn.getAttribute("data-engine") || "";
      if(!eng) return;
      setActive(eng);
      try{
        await ensureAndDownload(eng);
      }catch(e){
        setInline(eng, `❌ ${String(e.message || e)}`);
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", async ()=>{
  setTaskUI(null);
  await resumeAsrTaskIfAny();
  await refreshStatus();
  await refreshModelStates(true);
  updateAllSelectLabels();

  ["whisper","nemo","pyannote","nemo_diar"].forEach(updateEngine);

  // Default active: transcription group first
  setActive("whisper");
  updateAllInstallButtons();
  renderAllInfos();
  bindUI();
});
