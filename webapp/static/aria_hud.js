/**
 * A.R.I.A. HUD — Analytical Response & Intelligence Assistant
 * Frontend logic: chat, TTS, context injection
 */
(function () {
  'use strict';

  /* ---- Hint chips ---- */
  const ARIA_HINTS = [
    { label: 'Mówcy',       query: 'Ilu mówców wykryto w nagraniu?' },
    { label: 'Eksport',     query: 'Jak wyeksportować transkrypt do pliku?' },
    { label: 'Języki',      query: 'Jakie języki obsługuje transkrypcja?' },
    { label: 'Jakość',      query: 'Jak poprawić jakość diaryzacji?' },
    { label: 'Tłumaczenie', query: 'Jak uruchomić tłumaczenie offline?' },
  ];

  /* ---- State ---- */
  const AriaHUD = {
    open: false,
    busy: false,
    ttsEnabled: true,
    messages: [],         // { role: 'user'|'assistant', content: '...' }
    currentAudio: null,
    sessionId: null,
    msgCount: 0,

    // DOM refs (set in init)
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

    AriaHUD.sessionId = _genSessionId();

    // Set session ID in status line
    var sesEl = document.getElementById('aria-st-ses');
    if (sesEl) sesEl.textContent = 'SES:' + AriaHUD.sessionId;

    // Event listeners
    AriaHUD.$trigger.addEventListener('click', toggle);
    document.getElementById('aria-close')?.addEventListener('click', () => setOpen(false));
    AriaHUD.$sendBtn?.addEventListener('click', sendMessage);
    AriaHUD.$ttsBtn?.addEventListener('click', toggleTTS);

    AriaHUD.$input?.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    // Auto-resize textarea
    AriaHUD.$input?.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 80) + 'px';
    });

    // Build hint chips
    _buildHints();

    // Check ARIA status
    _checkStatus();

    // Add system welcome message
    _addSystemMsg('A.R.I.A. online — gotowa do analizy.');
  }

  /* ---- Session ID ---- */
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
    if (state && AriaHUD.$input) {
      setTimeout(() => AriaHUD.$input.focus(), 300);
    }
  }

  /* ---- Context ---- */
  function getPageContext() {
    return {
      module: document.body?.dataset?.ariaModule || document.querySelector('[data-aria-module]')?.dataset?.ariaModule || 'unknown',
      filename: document.querySelector('[data-aria-filename]')?.dataset?.ariaFilename || null,
      speakers: parseInt(document.querySelector('[data-aria-speakers]')?.dataset?.ariaSpeakers) || null,
      segments: parseInt(document.querySelector('[data-aria-segments]')?.dataset?.ariaSegments) || null,
    };
  }

  /* ---- Send message ---- */
  async function sendMessage() {
    if (AriaHUD.busy) return;
    const text = (AriaHUD.$input?.value || '').trim();
    if (!text) return;

    // Clear input
    AriaHUD.$input.value = '';
    AriaHUD.$input.style.height = 'auto';

    // Hide hints after first message
    if (AriaHUD.$hints) {
      AriaHUD.$hints.style.display = 'none';
    }

    // Add user message
    AriaHUD.messages.push({ role: 'user', content: text });
    AriaHUD.msgCount++;
    _addMsgBubble('user', text);
    _updateStatusLine();

    // Show typing indicator
    AriaHUD.busy = true;
    _setBusy(true);
    const typingEl = _showTyping();

    try {
      const res = await fetch('/api/aria/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: AriaHUD.messages,
          context: getPageContext(),
          session_id: AriaHUD.sessionId,
        }),
      });

      const data = await res.json();
      const reply = data.reply || 'Brak odpowiedzi.';

      // Remove typing indicator
      if (typingEl) typingEl.remove();

      // Add assistant message
      AriaHUD.messages.push({ role: 'assistant', content: reply });
      AriaHUD.msgCount++;
      _addMsgBubble(data.error ? 'error' : 'assistant', reply);

      if (data.model) {
        _setStatusModel(data.model);
      }

      // TTS
      if (AriaHUD.ttsEnabled && !data.error) {
        speakText(reply);
      }
    } catch (err) {
      if (typingEl) typingEl.remove();
      _addMsgBubble('error', 'Błąd połączenia: ' + (err.message || 'unknown'));
    } finally {
      AriaHUD.busy = false;
      _setBusy(false);
      _updateStatusLine();
    }
  }

  /* ---- TTS ---- */
  async function speakText(text) {
    if (!AriaHUD.ttsEnabled) return;

    // Stop previous
    stopSpeech();

    setAriaWaveMode(true);

    try {
      const res = await fetch('/api/aria/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text }),
      });

      if (!res.ok) {
        setAriaWaveMode(false);
        return;
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
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

      audio.play().catch(() => {
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
    if (!AriaHUD.ttsEnabled) {
      stopSpeech();
    }
    _updateTTSButton();
  }

  function _updateTTSButton() {
    if (!AriaHUD.$ttsBtn) return;
    AriaHUD.$ttsBtn.classList.toggle('active', AriaHUD.ttsEnabled);
    AriaHUD.$ttsBtn.classList.toggle('muted', !AriaHUD.ttsEnabled);
    AriaHUD.$ttsBtn.title = AriaHUD.ttsEnabled ? 'TTS aktywny — kliknij aby wyłączyć' : 'TTS wyłączony — kliknij aby włączyć';
    AriaHUD.$ttsBtn.innerHTML = AriaHUD.ttsEnabled ? '&#128266;' : '&#128263;';
  }

  /* ---- DOM helpers ---- */

  function _addMsgBubble(role, content) {
    if (!AriaHUD.$messages) return;
    var div = document.createElement('div');
    div.className = 'aria-msg ' + role;
    div.textContent = content;
    AriaHUD.$messages.appendChild(div);
    AriaHUD.$messages.scrollTop = AriaHUD.$messages.scrollHeight;
  }

  function _addSystemMsg(text) {
    if (!AriaHUD.$messages) return;
    var div = document.createElement('div');
    div.className = 'aria-msg system';
    div.textContent = text;
    AriaHUD.$messages.appendChild(div);
  }

  function _showTyping() {
    if (!AriaHUD.$messages) return null;
    var div = document.createElement('div');
    div.className = 'aria-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    AriaHUD.$messages.appendChild(div);
    AriaHUD.$messages.scrollTop = AriaHUD.$messages.scrollHeight;
    return div;
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
      // Shorten model name
      var short = model.replace(/:latest$/, '');
      if (short.length > 16) short = short.substring(0, 16) + '…';
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
        if (AriaHUD.$input) {
          AriaHUD.$input.value = h.query;
        }
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
      // Update TTS button state based on availability
      if (!data.piper_installed || !data.voice_model) {
        AriaHUD.ttsEnabled = false;
        _updateTTSButton();
      } else {
        _updateTTSButton();
      }
    } catch (e) {
      if (AriaHUD.$statusDot) AriaHUD.$statusDot.classList.add('offline');
    }
  }

  /* ---- Boot ---- */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose for external use
  window.AriaHUD = AriaHUD;
  window.AriaHUD.toggle = toggle;
  window.AriaHUD.setOpen = setOpen;

})();
