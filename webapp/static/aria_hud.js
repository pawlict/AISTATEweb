/**
 * A.R.I.A. HUD — Analytical Response & Intelligence Assistant
 * Frontend logic: SSE streaming chat, TTS, context injection, session memory
 */
(function () {
  'use strict';

  /* ---- Hint chips ---- */
  var ARIA_HINTS = [
    { label: 'Jak transkrybować?', query: 'Jak uruchomić transkrypcję pliku audio?' },
    { label: 'Mówcy',             query: 'Jak działa diaryzacja mówców?' },
    { label: 'Analiza GSM',       query: 'Jak wczytać i analizować billing GSM?' },
    { label: 'Tłumaczenie',       query: 'Jak uruchomić tłumaczenie offline?' },
    { label: 'Szyfrowanie',       query: 'Jak zaszyfrować projekt?' },
  ];

  /* ---- State ---- */
  var AriaHUD = {
    open: false,
    busy: false,
    ttsEnabled: true,
    messages: [],
    currentAudio: null,
    sessionId: null,
    msgCount: 0,
    greeted: false,

    $trigger: null,
    $hud: null,
    $messages: null,
    $hints: null,
    $input: null,
    $sendBtn: null,
    $ttsBtn: null,
    $statusMsgCount: null,
    $statusModel: null,
    $statusState: null,
    $statusDot: null,
  };

  /* ---- Session Storage Keys ---- */
  var SS_MESSAGES  = 'aria_hud_messages';
  var SS_SESSION   = 'aria_hud_session';
  var SS_TTS       = 'aria_hud_tts';
  var SS_GREETED   = 'aria_hud_greeted';

  /* ---- Init ---- */
  function init() {
    AriaHUD.$trigger       = document.getElementById('aria-trigger');
    AriaHUD.$hud           = document.getElementById('aria-hud');
    AriaHUD.$messages      = document.getElementById('aria-messages');
    AriaHUD.$hints         = document.getElementById('aria-hints');
    AriaHUD.$input         = document.getElementById('aria-input');
    AriaHUD.$sendBtn       = document.getElementById('aria-send');
    AriaHUD.$ttsBtn        = document.getElementById('aria-tts-toggle');
    AriaHUD.$statusMsgCount = document.getElementById('aria-st-msg');
    AriaHUD.$statusModel   = document.getElementById('aria-st-model');
    AriaHUD.$statusState   = document.getElementById('aria-st-state');
    AriaHUD.$statusDot     = document.getElementById('aria-status-dot');

    if (!AriaHUD.$trigger || !AriaHUD.$hud) return;

    _restoreSession();

    var sesEl = document.getElementById('aria-st-ses');
    if (sesEl) sesEl.textContent = 'SES:' + AriaHUD.sessionId;

    AriaHUD.$trigger.addEventListener('click', toggle);
    document.getElementById('aria-close')?.addEventListener('click', function () { setOpen(false); });
    AriaHUD.$sendBtn?.addEventListener('click', sendMessage);
    AriaHUD.$ttsBtn?.addEventListener('click', toggleTTS);

    AriaHUD.$input?.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    AriaHUD.$input?.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 80) + 'px';
    });

    if (AriaHUD.messages.length === 0) {
      _buildHints();
    } else {
      if (AriaHUD.$hints) AriaHUD.$hints.style.display = 'none';
    }

    _checkStatus();
    _updateTTSButton();
    _updateStatusLine();
  }

  /* ---- Welcome greeting (spoken via TTS only — NOT displayed in chat) ---- */
  function _buildWelcomeText() {
    var u = window.__ariaUser || {};
    var name = u.name || 'Operator';
    var role = u.role || 'user';

    var ROLE_MAP = {
      admin:       'Administratorze',
      superadmin:  'Superadministratorze',
      analyst:     'Analityku',
      user:        'Operatorze',
      viewer:      'Obserwatorze',
    };
    var roleLabel = ROLE_MAP[role] || 'Operatorze';

    return 'Systemy aktywne. Jestem A.R.I.A. \u2014 wbudowany asystent analityczny AISTATEweb. '
      + 'Posiadam pe\u0142n\u0105 dokumentacj\u0119 platformy: wiem jak dzia\u0142a transkrypcja, diaryzacja, '
      + 't\u0142umaczenie i analiza dokument\u00f3w. '
      + 'Je\u015bli co\u015b nie dzia\u0142a, nie wiesz jak zacz\u0105\u0107, albo potrzebujesz wyja\u015bnienia wyniku \u2014 jestem tu. '
      + roleLabel + ' ' + name + ', co analizujemy?';
  }

  function _playWelcomeGreeting() {
    if (AriaHUD.greeted || !AriaHUD.ttsEnabled) return;
    AriaHUD.greeted = true;
    try { sessionStorage.setItem(SS_GREETED, 'true'); } catch (e) { /* */ }
    // Speak the welcome — no text bubble in chat
    speakText(_buildWelcomeText());
  }

  /* ---- Session persistence ---- */
  function _restoreSession() {
    try {
      var savedSession = sessionStorage.getItem(SS_SESSION);
      var savedMessages = sessionStorage.getItem(SS_MESSAGES);
      var savedTTS = sessionStorage.getItem(SS_TTS);
      var savedGreeted = sessionStorage.getItem(SS_GREETED);

      AriaHUD.sessionId = savedSession || _genSessionId();
      AriaHUD.greeted = savedGreeted === 'true';

      if (savedMessages) {
        AriaHUD.messages = JSON.parse(savedMessages);
        AriaHUD.msgCount = AriaHUD.messages.length;
        AriaHUD.messages.forEach(function (m) {
          _addMsgBubble(m.role, m.content, true);
        });
      }

      if (savedTTS !== null) {
        AriaHUD.ttsEnabled = savedTTS === 'true';
      }
    } catch (e) { /* ignore */ }
  }

  function _saveSession() {
    try {
      sessionStorage.setItem(SS_SESSION, AriaHUD.sessionId);
      sessionStorage.setItem(SS_MESSAGES, JSON.stringify(AriaHUD.messages));
      sessionStorage.setItem(SS_TTS, String(AriaHUD.ttsEnabled));
    } catch (e) { /* ignore */ }
  }

  function _genSessionId() {
    return Math.random().toString(36).substring(2, 10).toUpperCase();
  }

  /* ---- Toggle panel ---- */
  function toggle() {
    setOpen(!AriaHUD.open);
  }

  function setOpen(state) {
    AriaHUD.open = state;
    if (AriaHUD.$hud) {
      AriaHUD.$hud.classList.toggle('hidden', !state);
    }
    if (state) {
      if (AriaHUD.$input) {
        setTimeout(function () { AriaHUD.$input.focus(); }, 300);
      }
      // Play spoken welcome on first open this session
      if (!AriaHUD.greeted) {
        setTimeout(_playWelcomeGreeting, 500);
      }
    }
  }

  /* ---- Context ---- */
  function getPageContext() {
    return {
      module: document.body?.dataset?.ariaModule || document.querySelector('[data-aria-module]')?.dataset?.ariaModule || _guessModule(),
      filename: document.querySelector('[data-aria-filename]')?.dataset?.ariaFilename || null,
      speakers: parseInt(document.querySelector('[data-aria-speakers]')?.dataset?.ariaSpeakers) || null,
      segments: parseInt(document.querySelector('[data-aria-segments]')?.dataset?.ariaSegments) || null,
    };
  }

  function _guessModule() {
    var path = location.pathname;
    if (path.indexOf('/transcription') >= 0) return 'transkrypcja';
    if (path.indexOf('/diarization') >= 0) return 'diaryzacja';
    if (path.indexOf('/analysis') >= 0) return 'analiza';
    if (path.indexOf('/chat') >= 0) return 'chat_llm';
    if (path.indexOf('/translation') >= 0) return 'tłumaczenie';
    if (path.indexOf('/projects') >= 0) return 'projekty';
    if (path.indexOf('/admin') >= 0) return 'ustawienia_gpu';
    if (path.indexOf('/llm-settings') >= 0) return 'ustawienia_llm';
    if (path.indexOf('/asr-settings') >= 0) return 'ustawienia_asr';
    if (path.indexOf('/tts-settings') >= 0) return 'ustawienia_tts';
    if (path.indexOf('/info') >= 0) return 'info';
    if (path.indexOf('/logs') >= 0) return 'logi';
    return 'unknown';
  }

  /* ---- Send message (SSE streaming) ---- */
  async function sendMessage() {
    if (AriaHUD.busy) return;
    var text = (AriaHUD.$input?.value || '').trim();
    if (!text) return;

    AriaHUD.$input.value = '';
    AriaHUD.$input.style.height = 'auto';

    if (AriaHUD.$hints) {
      AriaHUD.$hints.style.display = 'none';
    }

    AriaHUD.messages.push({ role: 'user', content: text });
    AriaHUD.msgCount++;
    _addMsgBubble('user', text);
    _saveSession();
    _updateStatusLine();

    AriaHUD.busy = true;
    _setBusy(true);

    var assistantDiv = document.createElement('div');
    assistantDiv.className = 'aria-msg assistant';
    assistantDiv.textContent = '';
    if (AriaHUD.$messages) {
      AriaHUD.$messages.appendChild(assistantDiv);
      AriaHUD.$messages.scrollTop = AriaHUD.$messages.scrollHeight;
    }

    var fullReply = '';
    var gotModel = '';
    var hadError = false;

    try {
      var res = await fetch('/api/aria/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: AriaHUD.messages,
          context: getPageContext(),
          session_id: AriaHUD.sessionId,
        }),
      });

      if (!res.ok) {
        var errData = await res.json().catch(function () { return {}; });
        fullReply = errData.error || 'Błąd połączenia z ARIA.';
        hadError = true;
        assistantDiv.className = 'aria-msg error';
        assistantDiv.textContent = fullReply;
      } else {
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
          var result = await reader.read();
          if (result.done) break;

          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (!line.startsWith('data: ')) continue;
            try {
              var data = JSON.parse(line.substring(6));
              if (data.error) {
                fullReply = data.error;
                hadError = true;
                assistantDiv.className = 'aria-msg error';
                assistantDiv.textContent = fullReply;
                break;
              }
              if (data.token) {
                fullReply += data.token;
                assistantDiv.textContent = fullReply;
                if (AriaHUD.$messages) {
                  AriaHUD.$messages.scrollTop = AriaHUD.$messages.scrollHeight;
                }
              }
              if (data.model) gotModel = data.model;
              if (data.done) break;
            } catch (e) { /* ignore */ }
          }
        }
      }
    } catch (err) {
      fullReply = 'Błąd połączenia: ' + (err.message || 'unknown');
      hadError = true;
      assistantDiv.className = 'aria-msg error';
      assistantDiv.textContent = fullReply;
    }

    if (fullReply && !hadError) {
      AriaHUD.messages.push({ role: 'assistant', content: fullReply });
      AriaHUD.msgCount++;
    }

    if (gotModel) _setStatusModel(gotModel);

    AriaHUD.busy = false;
    _setBusy(false);
    _updateStatusLine();
    _saveSession();

    if (AriaHUD.ttsEnabled && !hadError && fullReply) {
      speakText(fullReply);
    }
  }

  /* ---- TTS ---- */
  async function speakText(text) {
    if (!AriaHUD.ttsEnabled) return;
    stopSpeech();
    setAriaWaveMode(true);

    try {
      var res = await fetch('/api/aria/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text }),
      });

      if (!res.ok) {
        setAriaWaveMode(false);
        return;
      }

      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      var audio = new Audio(url);
      AriaHUD.currentAudio = audio;

      audio.onended = function () {
        setAriaWaveMode(false);
        URL.revokeObjectURL(url);
        AriaHUD.currentAudio = null;
      };

      audio.onerror = function () {
        setAriaWaveMode(false);
        URL.revokeObjectURL(url);
        AriaHUD.currentAudio = null;
      };

      audio.play().catch(function () {
        setAriaWaveMode(false);
        AriaHUD.currentAudio = null;
      });
    } catch (e) {
      setAriaWaveMode(false);
    }
  }

  function stopSpeech() {
    if (AriaHUD.currentAudio) {
      AriaHUD.currentAudio.pause();
      AriaHUD.currentAudio.currentTime = 0;
      AriaHUD.currentAudio = null;
    }
    setAriaWaveMode(false);
  }

  function setAriaWaveMode(active) {
    var logo = document.getElementById('aria-logo-group');
    var wave = document.getElementById('aria-wave-group');
    if (logo) logo.style.display = active ? 'none' : 'block';
    if (wave) wave.style.display = active ? 'block' : 'none';
  }

  function toggleTTS() {
    AriaHUD.ttsEnabled = !AriaHUD.ttsEnabled;
    if (!AriaHUD.ttsEnabled) stopSpeech();
    _updateTTSButton();
    _saveSession();
  }

  function _updateTTSButton() {
    if (!AriaHUD.$ttsBtn) return;
    AriaHUD.$ttsBtn.classList.toggle('active', AriaHUD.ttsEnabled);
    AriaHUD.$ttsBtn.classList.toggle('muted', !AriaHUD.ttsEnabled);
    AriaHUD.$ttsBtn.title = AriaHUD.ttsEnabled ? 'TTS aktywny — kliknij aby wyłączyć' : 'TTS wyłączony — kliknij aby włączyć';
    AriaHUD.$ttsBtn.innerHTML = AriaHUD.ttsEnabled ? '&#128266;' : '&#128263;';
  }

  /* ---- DOM helpers ---- */
  function _addMsgBubble(role, content, silent) {
    if (!AriaHUD.$messages) return;
    var div = document.createElement('div');
    div.className = 'aria-msg ' + role;
    div.textContent = content;
    if (!silent) div.style.animation = 'ariaFadeIn 0.2s ease';
    AriaHUD.$messages.appendChild(div);
    AriaHUD.$messages.scrollTop = AriaHUD.$messages.scrollHeight;
  }

  function _setBusy(busy) {
    if (AriaHUD.$sendBtn) AriaHUD.$sendBtn.disabled = busy;
    if (AriaHUD.$statusState) {
      AriaHUD.$statusState.textContent = busy ? 'PROCESSING' : 'READY';
    }
  }

  function _updateStatusLine() {
    if (AriaHUD.$statusMsgCount) {
      AriaHUD.$statusMsgCount.textContent = 'MSG:' + AriaHUD.msgCount;
    }
  }

  function _setStatusModel(model) {
    if (AriaHUD.$statusModel) {
      var short = model.replace(/:latest$/, '');
      if (short.length > 16) short = short.substring(0, 16) + '\u2026';
      AriaHUD.$statusModel.textContent = 'MDL:' + short;
    }
  }

  function _buildHints() {
    if (!AriaHUD.$hints) return;
    AriaHUD.$hints.innerHTML = '';
    ARIA_HINTS.forEach(function (h) {
      var chip = document.createElement('button');
      chip.className = 'aria-hint-chip';
      chip.textContent = h.label;
      chip.title = h.query;
      chip.addEventListener('click', function () {
        if (AriaHUD.$input) AriaHUD.$input.value = h.query;
        sendMessage();
      });
      AriaHUD.$hints.appendChild(chip);
    });
  }

  async function _checkStatus() {
    try {
      var res = await fetch('/api/aria/status');
      var data = await res.json();
      if (AriaHUD.$statusDot) {
        AriaHUD.$statusDot.classList.toggle('offline', !data.ollama);
      }
      if (data.ollama && AriaHUD.$statusState) {
        AriaHUD.$statusState.textContent = 'READY';
      }
      if (!data.piper_installed || !data.voice_model) {
        AriaHUD.ttsEnabled = false;
        _updateTTSButton();
      }
    } catch (e) {
      if (AriaHUD.$statusDot) AriaHUD.$statusDot.classList.add('offline');
    }
  }

  /* ---- Clear history ---- */
  function clearHistory() {
    AriaHUD.messages = [];
    AriaHUD.msgCount = 0;
    AriaHUD.greeted = false;
    AriaHUD.sessionId = _genSessionId();
    if (AriaHUD.$messages) AriaHUD.$messages.innerHTML = '';
    _buildHints();
    if (AriaHUD.$hints) AriaHUD.$hints.style.display = '';
    _updateStatusLine();
    _saveSession();
    try { sessionStorage.removeItem(SS_GREETED); } catch (e) { /* */ }
    setTimeout(_playWelcomeGreeting, 300);
    var sesEl = document.getElementById('aria-st-ses');
    if (sesEl) sesEl.textContent = 'SES:' + AriaHUD.sessionId;
  }

  /* ---- Boot ---- */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.AriaHUD = AriaHUD;
  window.AriaHUD.toggle = toggle;
  window.AriaHUD.setOpen = setOpen;
  window.AriaHUD.clearHistory = clearHistory;

})();
