/**
 * tts_settings.js — TTS Settings admin page logic
 *
 * Handles engine installation, voice download, status checks, and test playback.
 */
(function () {
  "use strict";

  /* ---- state ---- */
  var TTS_STATUS = null;
  var TTS_MODELS_STATE = null;
  var TTS_CURRENT_TASK_ID = null;
  var TTS_POLL_TIMER = null;

  /* ---- helpers ---- */
  function qs(id) { return document.getElementById(id); }

  function _tSafe(key, fallback) {
    try { if (typeof t === "function") { var v = t(key); if (v && v !== key) return v; } } catch (e) {}
    return fallback || key;
  }

  async function api(path, opts) {
    try {
      var r = await fetch(path, opts || {});
      if (!r.ok) {
        var err = await r.text();
        console.error("API error:", path, r.status, err);
        return null;
      }
      return await r.json();
    } catch (e) {
      console.error("API fetch error:", path, e);
      return null;
    }
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* ---- task progress UI ---- */
  function setTaskUI(task) {
    var st = qs("tts_task_status");
    var pct = qs("tts_task_pct");
    var bar = qs("tts_task_bar");
    var logsBtn = qs("tts_task_open_logs");

    if (!task) {
      st.textContent = "—";
      pct.textContent = "0%";
      bar.style.width = "0%";
      logsBtn.style.display = "none";
      return;
    }

    var s = String(task.status || "running");
    st.textContent = s === "done" ? _tSafe("common.done", "Gotowe") :
                     s === "error" ? _tSafe("common.error", "Błąd") :
                     s === "queued" ? _tSafe("common.queued", "W kolejce") :
                     _tSafe("common.running", "W toku...");
    var p = Math.max(0, Math.min(100, parseInt(task.progress) || 0));
    pct.textContent = p + "%";
    bar.style.width = p + "%";
    logsBtn.style.display = "inline-flex";
  }

  /* ---- run a task and poll ---- */
  async function runTask(path, payload) {
    var res = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res || !res.task_id) {
      setTaskUI({ status: "error", progress: 0 });
      return null;
    }

    TTS_CURRENT_TASK_ID = res.task_id;
    setTaskUI({ status: "running", progress: 0 });

    // Poll until done
    while (true) {
      await sleep(700);
      var tsk = await api("/api/tasks/" + TTS_CURRENT_TASK_ID);
      if (!tsk) continue;
      setTaskUI(tsk);
      if (tsk.status === "done" || tsk.status === "error") {
        return tsk;
      }
    }
  }

  /* ---- resume interrupted task ---- */
  async function resumeTaskIfAny() {
    try {
      var tasks = await api("/api/tasks");
      if (!tasks || !Array.isArray(tasks)) return;

      for (var i = 0; i < tasks.length; i++) {
        var t = tasks[i];
        if (t.kind && String(t.kind).startsWith("tts_") && t.status === "running") {
          TTS_CURRENT_TASK_ID = t.task_id;
          setTaskUI({ status: "running", progress: t.progress || 0 });

          // Resume polling
          while (true) {
            await sleep(700);
            var tsk = await api("/api/tasks/" + TTS_CURRENT_TASK_ID);
            if (!tsk) continue;
            setTaskUI(tsk);
            if (tsk.status === "done" || tsk.status === "error") {
              await refreshAll();
              return;
            }
          }
        }
      }
    } catch (e) { /* ignore */ }
  }

  /* ---- status refresh ---- */
  async function refreshStatus() {
    TTS_STATUS = await api("/api/tts/status");
    if (!TTS_STATUS) return;

    // Piper status
    var ps = qs("tts_piper_status");
    if (TTS_STATUS.piper && TTS_STATUS.piper.installed) {
      ps.innerHTML = aiIcon('success',12) + " piper " + (TTS_STATUS.piper.version || "");
    } else {
      ps.innerHTML = aiIcon('error',12) + " " + _tSafe("tts.not_installed", "Niezainstalowany");
    }

    // MMS status
    var ms = qs("tts_mms_status");
    if (TTS_STATUS.mms && TTS_STATUS.mms.installed) {
      var tv = TTS_STATUS.mms.transformers ? TTS_STATUS.mms.transformers.version : "";
      ms.innerHTML = aiIcon('success',12) + " transformers " + (tv || "");
    } else {
      ms.innerHTML = aiIcon('error',12) + " " + _tSafe("tts.not_installed", "Niezainstalowany");
    }

    // Kokoro status
    var ks = qs("tts_kokoro_status");
    if (TTS_STATUS.kokoro && TTS_STATUS.kokoro.installed) {
      ks.innerHTML = aiIcon('success',12) + " kokoro " + (TTS_STATUS.kokoro.version || "");
    } else {
      ks.innerHTML = aiIcon('error',12) + " " + _tSafe("tts.not_installed", "Niezainstalowany");
    }
  }

  async function refreshModels() {
    TTS_MODELS_STATE = await api("/api/tts/models_state?refresh=1");
    updateInstallButtons();
  }

  function _isVoiceDownloaded(engine, voiceId) {
    if (!TTS_MODELS_STATE) return false;
    // Build possible marker keys for this engine/voice
    for (var k in TTS_MODELS_STATE) {
      var m = TTS_MODELS_STATE[k];
      if (m.engine !== engine || !m.downloaded) continue;
      // Piper: marker key is "piper_{voiceId}", voice field matches
      if (m.voice === voiceId) return true;
      // MMS: marker key contains model_id or lang_code
      if (m.model_id === voiceId) return true;
      // Kokoro: single model, key is "kokoro"
      if (engine === "kokoro" && k === "kokoro") return true;
    }
    return false;
  }

  function updateInstallButtons() {
    var engines = ["piper", "mms", "kokoro"];

    engines.forEach(function (eng) {
      var btn = qs("tts_" + eng + "_install_btn");
      var inl = qs("tts_" + eng + "_inline");
      if (!btn || !inl) return;

      var installed = TTS_STATUS && TTS_STATUS[eng] &&
        (TTS_STATUS[eng].installed || (eng === "mms" && TTS_STATUS.mms && TTS_STATUS.mms.installed));

      // Check voice downloads
      var voiceSelect = qs("tts_" + eng + "_voice");
      var selectedVoice = voiceSelect ? voiceSelect.value : "";
      var voiceDownloaded = false;

      if (TTS_MODELS_STATE && installed) {
        for (var k in TTS_MODELS_STATE) {
          if (TTS_MODELS_STATE[k].engine === eng && TTS_MODELS_STATE[k].downloaded) {
            voiceDownloaded = true;
            break;
          }
        }
      }

      if (installed && voiceDownloaded) {
        inl.innerHTML = aiIcon('success',12) + " " + _tSafe("tts.ready", "Gotowy");
      } else if (installed) {
        inl.innerHTML = aiIcon('warning',12) + " " + _tSafe("tts.no_voice", "Silnik OK, pobierz głos");
      } else {
        inl.innerHTML = aiIcon('error',12) + " " + _tSafe("tts.not_installed", "Niezainstalowany");
      }

      // Mark individual voice options as installed / not installed
      if (voiceSelect) {
        var opts = voiceSelect.options;
        for (var i = 0; i < opts.length; i++) {
          var opt = opts[i];
          var origLabel = opt.getAttribute("data-orig-label");
          if (!origLabel) {
            // Save original label on first pass
            origLabel = opt.textContent;
            opt.setAttribute("data-orig-label", origLabel);
          }
          if (!installed) {
            opt.textContent = origLabel;
            continue;
          }
          var dl = _isVoiceDownloaded(eng, opt.value);
          opt.textContent = dl ? origLabel : origLabel + " (" + _tSafe("tts.voice_not_downloaded", "niezainstalowany") + ")";
        }
      }
    });
  }

  async function refreshAll() {
    await refreshStatus();
    await refreshModels();
    updateInstallButtons();
  }

  /* ---- install & download ---- */
  async function installAndDownload(engine) {
    var voiceSelect = qs("tts_" + engine + "_voice");
    var voice = voiceSelect ? voiceSelect.value : "";

    var engineInstalled = TTS_STATUS && TTS_STATUS[engine] &&
      (TTS_STATUS[engine].installed || (engine === "mms" && TTS_STATUS.mms && TTS_STATUS.mms.installed));

    // Step 1: Install engine deps if needed
    if (!engineInstalled) {
      var t1 = await runTask("/api/tts/install", { engine: engine });
      if (!t1 || t1.status === "error") {
        await refreshAll();
        return;
      }
    }

    // Step 2: Download voice/model
    var payload = { engine: engine };
    if (voice) payload.voice = voice;
    var t2 = await runTask("/api/tts/predownload", payload);

    await refreshAll();
  }

  /* ---- test playback ---- */
  async function testVoice(engine) {
    var voiceSelect = qs("tts_" + engine + "_voice");
    var textInput = qs("tts_" + engine + "_test_text");

    var voice = voiceSelect ? voiceSelect.value : "";
    var text = textInput ? textInput.value.trim() : "";

    if (!text) {
      showToast(_tSafe("tts.test_no_text", "Wpisz tekst testowy"), 'warning');
      return;
    }

    var testBtn = qs("tts_" + engine + "_test_btn");
    if (testBtn) testBtn.disabled = true;

    try {
      var res = await api("/api/tts/synthesize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          engine: engine,
          voice: voice,
          text: text,
          lang: engine === "kokoro" ? _guessKokoroLang(voice) : "",
        }),
      });

      if (!res) {
        showToast(_tSafe("tts.test_error", "Błąd syntezy"), 'error');
        return;
      }

      // If cached, play immediately
      if (res.status === "cached" && res.audio_url) {
        _playAudio(res.audio_url);
        return;
      }

      // Otherwise poll until done, then play
      if (res.task_id) {
        TTS_CURRENT_TASK_ID = res.task_id;
        setTaskUI({ status: "running", progress: 0 });

        while (true) {
          await sleep(700);
          var tsk = await api("/api/tasks/" + TTS_CURRENT_TASK_ID);
          if (!tsk) continue;
          setTaskUI(tsk);
          if (tsk.status === "done") {
            if (res.audio_url) _playAudio(res.audio_url);
            break;
          }
          if (tsk.status === "error") break;
        }
      }
    } finally {
      if (testBtn) testBtn.disabled = false;
    }
  }

  function _guessKokoroLang(voice) {
    if (!voice) return "a";
    var prefix = voice.charAt(0);
    var map = { a: "english", b: "german", e: "spanish", f: "french", h: "hindi", i: "italian", j: "japanese", k: "korean", z: "chinese" };
    return map[prefix] || "english";
  }

  function _playAudio(url) {
    var audio = new Audio(url);
    audio.play().catch(function (e) {
      console.error("Audio playback error:", e);
    });
  }

  /* ---- bind UI ---- */
  function bindUI() {
    // Install buttons
    ["piper", "mms", "kokoro"].forEach(function (eng) {
      var btn = qs("tts_" + eng + "_install_btn");
      if (btn) btn.addEventListener("click", function () { installAndDownload(eng); });

      var testBtn = qs("tts_" + eng + "_test_btn");
      if (testBtn) testBtn.addEventListener("click", function () { testVoice(eng); });
    });
  }

  /* ---- init ---- */
  document.addEventListener("DOMContentLoaded", async function () {
    setTaskUI(null);
    bindUI();
    await resumeTaskIfAny();
    await refreshAll();
  });

})();
