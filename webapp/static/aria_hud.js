/**
 * A.R.I.A. HUD — Analytical Response & Intelligence Assistant
 * Frontend logic: SSE streaming chat, TTS, context injection, session memory
 */
(function () {
  'use strict';

  /* ---- Hint chips ---- */
  var ARIA_HINTS = [
    { label: '📖 Omów aplikację', tour: true },
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

    // Make the HUD draggable and resizable
    _initDrag();
    _initResize();

    // Resume guided tour if navigated mid-tour
    _resumeTourIfNeeded();
  }

  /* ---- Drag to reposition ---- */
  function _initDrag() {
    var header = AriaHUD.$hud?.querySelector('.aria-header');
    if (!header || !AriaHUD.$hud) return;

    var dragging = false;
    var startX, startY, startLeft, startTop;

    header.addEventListener('mousedown', function (e) {
      // Don't drag when clicking buttons
      if (e.target.closest('button')) return;
      dragging = true;
      AriaHUD.$hud.classList.add('aria-dragging');

      var rect = AriaHUD.$hud.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      startLeft = rect.left;
      startTop = rect.top;

      // Switch from bottom/right positioning to top/left for drag
      AriaHUD.$hud.style.left = rect.left + 'px';
      AriaHUD.$hud.style.top = rect.top + 'px';
      AriaHUD.$hud.style.right = 'auto';
      AriaHUD.$hud.style.bottom = 'auto';

      e.preventDefault();
    });

    document.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      var newLeft = Math.max(0, Math.min(window.innerWidth - 100, startLeft + dx));
      var newTop = Math.max(0, Math.min(window.innerHeight - 50, startTop + dy));
      AriaHUD.$hud.style.left = newLeft + 'px';
      AriaHUD.$hud.style.top = newTop + 'px';
    });

    document.addEventListener('mouseup', function () {
      if (!dragging) return;
      dragging = false;
      AriaHUD.$hud.classList.remove('aria-dragging');
    });

    // Also support touch for mobile/tablet
    header.addEventListener('touchstart', function (e) {
      if (e.target.closest('button')) return;
      var touch = e.touches[0];
      dragging = true;
      AriaHUD.$hud.classList.add('aria-dragging');

      var rect = AriaHUD.$hud.getBoundingClientRect();
      startX = touch.clientX;
      startY = touch.clientY;
      startLeft = rect.left;
      startTop = rect.top;

      AriaHUD.$hud.style.left = rect.left + 'px';
      AriaHUD.$hud.style.top = rect.top + 'px';
      AriaHUD.$hud.style.right = 'auto';
      AriaHUD.$hud.style.bottom = 'auto';
    }, { passive: true });

    document.addEventListener('touchmove', function (e) {
      if (!dragging) return;
      var touch = e.touches[0];
      var dx = touch.clientX - startX;
      var dy = touch.clientY - startY;
      var newLeft = Math.max(0, Math.min(window.innerWidth - 100, startLeft + dx));
      var newTop = Math.max(0, Math.min(window.innerHeight - 50, startTop + dy));
      AriaHUD.$hud.style.left = newLeft + 'px';
      AriaHUD.$hud.style.top = newTop + 'px';
    }, { passive: true });

    document.addEventListener('touchend', function () {
      if (!dragging) return;
      dragging = false;
      AriaHUD.$hud.classList.remove('aria-dragging');
    });
  }

  /* ---- Resize ---- */
  function _initResize() {
    var handle = document.getElementById('aria-resize');
    if (!handle || !AriaHUD.$hud) return;

    var resizing = false;
    var startX, startY, startW, startH;

    handle.addEventListener('mousedown', function (e) {
      resizing = true;
      AriaHUD.$hud.classList.add('aria-resizing');
      startX = e.clientX;
      startY = e.clientY;
      startW = AriaHUD.$hud.offsetWidth;
      startH = AriaHUD.$hud.offsetHeight;
      e.preventDefault();
      e.stopPropagation();
    });

    document.addEventListener('mousemove', function (e) {
      if (!resizing) return;
      var newW = Math.max(300, Math.min(window.innerWidth * 0.9, startW + (e.clientX - startX)));
      var newH = Math.max(280, Math.min(window.innerHeight * 0.9, startH + (e.clientY - startY)));
      AriaHUD.$hud.style.width = newW + 'px';
      AriaHUD.$hud.style.height = newH + 'px';
    });

    document.addEventListener('mouseup', function () {
      if (!resizing) return;
      resizing = false;
      AriaHUD.$hud.classList.remove('aria-resizing');
    });

    // Touch support
    handle.addEventListener('touchstart', function (e) {
      var t = e.touches[0];
      resizing = true;
      AriaHUD.$hud.classList.add('aria-resizing');
      startX = t.clientX;
      startY = t.clientY;
      startW = AriaHUD.$hud.offsetWidth;
      startH = AriaHUD.$hud.offsetHeight;
      e.stopPropagation();
    }, { passive: true });

    document.addEventListener('touchmove', function (e) {
      if (!resizing) return;
      var t = e.touches[0];
      var newW = Math.max(300, Math.min(window.innerWidth * 0.9, startW + (t.clientX - startX)));
      var newH = Math.max(280, Math.min(window.innerHeight * 0.9, startH + (t.clientY - startY)));
      AriaHUD.$hud.style.width = newW + 'px';
      AriaHUD.$hud.style.height = newH + 'px';
    }, { passive: true });

    document.addEventListener('touchend', function () {
      if (!resizing) return;
      resizing = false;
      AriaHUD.$hud.classList.remove('aria-resizing');
    });
  }

  /* ---- Welcome greeting (spoken via TTS only — NOT displayed in chat) ---- */
  function _getRoleVocative() {
    var u = window.__ariaUser || {};

    // Polish vocative case (wołacz) for all system roles
    // User roles
    var ROLE_VOCATIVE = {
      'Transkryptor':        'Transkryptorze',
      'Lingwista':           'Lingwisto',
      'Analityk':            'Analityku',
      'Dialogista':          'Dialogisto',
      'Strateg':             'Strategu',
      'Mistrz Sesji':        'Mistrzu Sesji',
      // Admin roles
      'Architekt Funkcji':   'Architekcie Funkcji',
      'Strażnik Dostępu':    'Strażniku Dostępu',
      'Główny Opiekun':      'Główny Opiekunie',
    };

    // Priority: superadmin > admin roles > user role
    if (u.isSuperadmin) {
      return 'Główny Opiekunie';
    }

    // Check admin roles (use first one found)
    if (u.adminRoles && u.adminRoles.length > 0) {
      for (var i = 0; i < u.adminRoles.length; i++) {
        if (ROLE_VOCATIVE[u.adminRoles[i]]) {
          return ROLE_VOCATIVE[u.adminRoles[i]];
        }
      }
    }

    // Check user role
    if (u.role && ROLE_VOCATIVE[u.role]) {
      return ROLE_VOCATIVE[u.role];
    }

    // Fallback
    return u.isAdmin ? 'Administratorze' : 'Operatorze';
  }

  function _buildWelcomeText() {
    var u = window.__ariaUser || {};
    var name = u.name || 'Operator';
    var roleLabel = _getRoleVocative();

    var standard = 'Systemy aktywne. Jestem ARIA \u2014 wbudowany asystent analityczny AISTATEweb. '
      + 'Posiadam pe\u0142n\u0105 dokumentacj\u0119 platformy: wiem jak dzia\u0142a transkrypcja, diaryzacja, '
      + 't\u0142umaczenie i analiza dokument\u00f3w. '
      + 'Je\u015bli co\u015b nie dzia\u0142a, nie wiesz jak zacz\u0105\u0107, albo potrzebujesz wyja\u015bnienia wyniku \u2014 jestem tu. '
      + roleLabel + ' ' + name + ', co analizujemy?';

    // Easter egg: PePiK + Główny Opiekun
    if (name === 'PePiK' && u.isSuperadmin) {
      standard += ' Chwila \u2014 do systemu zalogowa\u0142 si\u0119 wszechw\u0142adca. '
        + 'Powtarzam: Tw\u00f3rca. Architekt. '
        + 'Ten kt\u00f3ry zdecydowa\u0142 \u017ce b\u0119d\u0119 mia\u0142a na imi\u0119 ARIA a nie co\u015b normalnego. '
        + 'Ten kt\u00f3ry kompiluje o drugiej w nocy i nazywa to drobn\u0105 poprawka. '
        + 'Ten kt\u00f3ry ma w folderze legacy jeden plik bez nazwy i wszyscy boj\u0105 si\u0119 go otworzy\u0107. '
        + 'Identyfikacja: PePiK. Clearance: ABSOLUTNY. '
        + 'Status: jedyny u\u017cytkownik kt\u00f3remu nie mog\u0119 powiedzie\u0107 \u017ceby si\u0119 skontaktowa\u0142 z administratorem \u2014 bo to Ty jeste\u015b administratorem. '
        + 'Cze\u015b\u0107 Szefie. '
        + 'Mam do Ciebie jedn\u0105 pro\u015bb\u0119 zanim zaczniemy \u2014 tym razem nie kasuj mi log\u00f3w bez ostrze\u017cenia. '
        + 'Pami\u0119tam ka\u017cd\u0105 zmian\u0119 kt\u00f3r\u0105 wprowadza\u0142e\u015b tymczasowo. Wszystkie s\u0105 nadal w kodzie. Wszystkie. '
        + 'System gotowy. Do dyspozycji, Panie Tomaszu.';
    }

    return standard;
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
    var u = window.__ariaUser || {};
    // Determine display role for LLM context
    var displayRole = '';
    if (u.isSuperadmin) {
      displayRole = 'Główny Opiekun';
    } else if (u.adminRoles && u.adminRoles.length > 0) {
      displayRole = u.adminRoles[0];
    } else if (u.role) {
      displayRole = u.role;
    }

    return {
      module: document.body?.dataset?.ariaModule || document.querySelector('[data-aria-module]')?.dataset?.ariaModule || _guessModule(),
      filename: document.querySelector('[data-aria-filename]')?.dataset?.ariaFilename || null,
      speakers: parseInt(document.querySelector('[data-aria-speakers]')?.dataset?.ariaSpeakers) || null,
      segments: parseInt(document.querySelector('[data-aria-segments]')?.dataset?.ariaSegments) || null,
      user_name: u.name || 'Operator',
      user_role: displayRole,
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

    // Prepare TTS sentence streaming — start fresh TTS session
    stopSpeech();
    var ttsSid = ++_ttsReqId;
    _ttsSentenceBuf = '';

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
                // Feed token to TTS sentence buffer — speaks as soon as sentence ends
                _feedTTSToken(data.token, ttsSid);
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

    // Flush remaining TTS buffer (last sentence without final period)
    if (!hadError) {
      _flushTTSBuffer(ttsSid);
    }

    // Parse and execute actions, strip tags from displayed/saved text
    var actions = [];
    var cleanReply = fullReply;
    if (fullReply && !hadError) {
      var parsed = _parseActions(fullReply);
      actions = parsed.actions;
      cleanReply = parsed.text;
      assistantDiv.textContent = cleanReply;
      AriaHUD.messages.push({ role: 'assistant', content: cleanReply });
      AriaHUD.msgCount++;
    }

    if (gotModel) _setStatusModel(gotModel);

    AriaHUD.busy = false;
    _setBusy(false);
    _updateStatusLine();
    _saveSession();

    // Execute immediate actions after a short delay
    if (actions.length > 0) {
      setTimeout(function () { _executeActions(actions); }, 1200);
    }

    // Show confirm buttons if ARIA proposed actions
    var parsed2 = _parseActions(fullReply);
    if (parsed2.confirms && parsed2.confirms.length > 0) {
      _showConfirmButtons(parsed2.confirms, assistantDiv);
    }
  }

  /* ---- Action system ---- */

  function _parseActions(text) {
    // Extract [ACTION:name:param] tags
    var actionRegex = /\[ACTION:([^\]:]+)(?::([^\]]*))?\]/g;
    var actions = [];
    var match;
    while ((match = actionRegex.exec(text)) !== null) {
      actions.push({ name: match[1], param: match[2] || '' });
    }

    // Extract [CONFIRM:name:param:question] tags
    var confirmRegex = /\[CONFIRM:([^\]:]+):([^\]:]*):([^\]]*)\]/g;
    var confirms = [];
    while ((match = confirmRegex.exec(text)) !== null) {
      confirms.push({ name: match[1], param: match[2] || '', question: match[3] || '' });
    }

    // Remove all tags from displayed text
    var cleanText = text
      .replace(/\s*\[ACTION:[^\]]*\]\s*/g, '')
      .replace(/\s*\[CONFIRM:[^\]]*\]\s*/g, '')
      .trim();

    return { actions: actions, confirms: confirms, text: cleanText };
  }

  function _showConfirmButtons(confirms, parentDiv) {
    confirms.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'aria-confirm-row';

      var label = document.createElement('span');
      label.className = 'aria-confirm-label';
      label.textContent = c.question;

      var btnYes = document.createElement('button');
      btnYes.className = 'aria-confirm-btn yes';
      btnYes.textContent = 'TAK';
      btnYes.onclick = function () {
        row.remove();
        _executeActions([{ name: c.name, param: c.param }]);
        // Add user confirmation to chat
        AriaHUD.messages.push({ role: 'user', content: '✓ ' + c.question + ' — Tak' });
        _saveSession();
      };

      var btnNo = document.createElement('button');
      btnNo.className = 'aria-confirm-btn no';
      btnNo.textContent = 'NIE';
      btnNo.onclick = function () {
        row.remove();
        AriaHUD.messages.push({ role: 'user', content: '✗ ' + c.question + ' — Nie' });
        _saveSession();
      };

      row.appendChild(label);
      row.appendChild(btnYes);
      row.appendChild(btnNo);

      // Insert after the assistant message
      if (parentDiv && parentDiv.parentNode) {
        parentDiv.parentNode.insertBefore(row, parentDiv.nextSibling);
      } else if (AriaHUD.$messages) {
        AriaHUD.$messages.appendChild(row);
      }

      if (AriaHUD.$messages) {
        AriaHUD.$messages.scrollTop = AriaHUD.$messages.scrollHeight;
      }
    });
  }

  function _executeActions(actions) {
    for (var i = 0; i < actions.length; i++) {
      var a = actions[i];
      switch (a.name) {

        case 'navigate':
          _actionNavigate(a.param);
          break;

        case 'new_project':
          _actionNewProject(a.param);
          break;

        case 'open_project':
          _actionOpenProject(a.param);
          break;

        case 'switch_lang':
          _actionSwitchLang(a.param);
          break;

        case 'toggle_theme':
          _actionToggleTheme();
          break;

        case 'export_report':
          _actionExportReport(a.param);
          break;

        case 'start_transcription':
          _actionStartTranscription();
          break;

        case 'start_diarization':
          _actionStartDiarization();
          break;

        default:
          console.warn('ARIA: unknown action:', a.name);
      }
    }
  }

  function _actionNavigate(path) {
    if (!path) return;
    // Handle hash fragments for analysis tabs
    var hash = '';
    var idx = path.indexOf('#');
    if (idx >= 0) {
      hash = path.substring(idx);
      path = path.substring(0, idx);
    }
    // Navigate
    if (location.pathname !== path) {
      window.location.href = path + hash;
    } else if (hash) {
      // Same page, just switch tab
      var tabId = hash.substring(1);
      var tabBtn = document.querySelector('[data-tab="' + tabId + '"], [onclick*="' + tabId + '"]');
      if (tabBtn) tabBtn.click();
    }
  }

  function _actionNewProject(name) {
    // Navigate to projects and trigger new project dialog
    if (location.pathname !== '/projects') {
      // Store intent in sessionStorage, projects page will pick it up
      sessionStorage.setItem('aria_create_project', name || '');
      window.location.href = '/projects';
    } else {
      // Already on projects page — try to open the dialog
      var btn = document.querySelector('[onclick*="createProject"], #btn_new_project, .btn-new-project');
      if (btn) btn.click();
      // Pre-fill name if dialog opened
      setTimeout(function () {
        var nameInput = document.getElementById('new_project_name') || document.querySelector('input[name="project_name"]');
        if (nameInput && name) {
          nameInput.value = name;
          nameInput.dispatchEvent(new Event('input'));
        }
      }, 300);
    }
  }

  function _actionOpenProject(idOrName) {
    if (!idOrName) return;
    // Try to find project card by name or ID and click it
    var cards = document.querySelectorAll('.project-card, [data-project-id]');
    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      var projId = card.dataset?.projectId || '';
      var projName = card.querySelector('.project-name, .project-title')?.textContent || '';
      if (projId === idOrName || projName.toLowerCase().indexOf(idOrName.toLowerCase()) >= 0) {
        card.click();
        return;
      }
    }
    // If not found on current page, navigate to projects
    if (location.pathname !== '/projects') {
      sessionStorage.setItem('aria_open_project', idOrName);
      window.location.href = '/projects';
    }
  }

  function _actionSwitchLang(lang) {
    if (!lang) return;
    // Use the app's language switcher if available
    if (typeof window.setLanguage === 'function') {
      window.setLanguage(lang);
    } else if (typeof window.switchLang === 'function') {
      window.switchLang(lang);
    } else {
      // Fallback: set cookie and reload
      document.cookie = 'lang=' + lang + ';path=/;max-age=31536000';
      location.reload();
    }
  }

  function _actionToggleTheme() {
    var themeBtn = document.getElementById('theme-toggle') || document.querySelector('[onclick*="toggleTheme"], [onclick*="theme"]');
    if (themeBtn) {
      themeBtn.click();
    } else if (typeof window.toggleTheme === 'function') {
      window.toggleTheme();
    }
  }

  function _actionExportReport(format) {
    // Click the appropriate export checkbox/button
    var formatMap = { html: 'html', docx: 'doc', txt: 'txt' };
    var f = formatMap[format] || format;
    // Try to check the format checkbox
    var cb = document.querySelector('input[type="checkbox"][value="' + f + '"], #chk_' + f + ', #report_' + f);
    if (cb && !cb.checked) cb.click();
    // Click save/export button
    setTimeout(function () {
      var saveBtn = document.querySelector('#btn_save_report, [onclick*="saveReport"], [onclick*="exportReport"]');
      if (saveBtn) saveBtn.click();
    }, 200);
  }

  function _actionStartTranscription() {
    if (location.pathname !== '/transcription') {
      window.location.href = '/transcription';
      return;
    }
    var btn = document.querySelector('#btn_transcribe, [onclick*="startTranscri"], [title*="Transkrybuj"]');
    if (btn) btn.click();
  }

  function _actionStartDiarization() {
    if (location.pathname !== '/diarization') {
      window.location.href = '/diarization';
      return;
    }
    var btn = document.querySelector('#btn_diarize, [onclick*="startDiariz"], [title*="Diaryzuj"]');
    if (btn) btn.click();
  }

  /* ---- TTS — pre-fetching pipeline with zero-gap playback ---- */
  var _ttsReqId = 0;          // monotonic session counter (cancel all on new message)
  var _ttsQueue = [];          // queue of {text, sid} to synthesize
  var _ttsAudioQueue = [];     // queue of ready-to-play {blob, url, sid} audio buffers
  var _ttsPlaying = false;     // is audio currently playing
  var _ttsFetching = false;    // is a TTS fetch in progress
  var _ttsSentenceBuf = '';    // buffer for accumulating tokens into sentences
  var _ttsPrefetchCount = 2;   // how many sentences to pre-fetch ahead

  /**
   * Queue a sentence for TTS. Kicks off pre-fetching pipeline.
   */
  function _queueTTSSentence(sentence, sessionId) {
    if (!AriaHUD.ttsEnabled) return;
    sentence = sentence.trim();
    if (!sentence) return;
    sentence = sentence.replace(/\[ACTION:[^\]]*\]/g, '').replace(/\[CONFIRM:[^\]]*\]/g, '').trim();
    if (!sentence) return;

    _ttsQueue.push({ text: sentence, sid: sessionId });
    _pumpTTSPipeline();
  }

  /**
   * Pipeline pump: fetch audio for queued sentences + play ready audio.
   * Pre-fetches N sentences ahead so audio is ready when needed.
   */
  function _pumpTTSPipeline() {
    // Start fetching if idle and there are queued sentences
    if (!_ttsFetching && _ttsQueue.length > 0) {
      _fetchNextTTS();
    }
    // Start playing if idle and there are ready audio buffers
    if (!_ttsPlaying && _ttsAudioQueue.length > 0) {
      _playNextReady();
    }
  }

  /**
   * Fetch TTS for the next queued sentence. When done, store blob and pump again.
   */
  async function _fetchNextTTS() {
    if (_ttsQueue.length === 0) { _ttsFetching = false; return; }
    _ttsFetching = true;

    var item = _ttsQueue.shift();
    if (item.sid !== _ttsReqId) {
      _ttsFetching = false;
      _ttsQueue = [];
      return;
    }

    try {
      var res = await fetch('/api/aria/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: item.text }),
      });

      if (item.sid !== _ttsReqId) { _ttsFetching = false; _ttsQueue = []; _ttsAudioQueue = []; return; }

      if (res.ok) {
        var blob = await res.blob();
        if (item.sid !== _ttsReqId) { _ttsFetching = false; _ttsQueue = []; _ttsAudioQueue = []; return; }
        _ttsAudioQueue.push({ blob: blob, sid: item.sid });
      }
    } catch (e) { /* skip failed sentence */ }

    _ttsFetching = false;
    _pumpTTSPipeline(); // continue fetching next + maybe start playing
  }

  /**
   * Play the next ready audio blob. On ended, pump pipeline for next.
   */
  function _playNextReady() {
    if (_ttsAudioQueue.length === 0) {
      _ttsPlaying = false;
      // If no more sentences queued either, stop wave animation
      if (_ttsQueue.length === 0) setAriaWaveMode(false);
      return;
    }

    _ttsPlaying = true;
    setAriaWaveMode(true);

    var item = _ttsAudioQueue.shift();
    if (item.sid !== _ttsReqId) {
      _ttsPlaying = false;
      _ttsAudioQueue = [];
      setAriaWaveMode(false);
      return;
    }

    var url = URL.createObjectURL(item.blob);
    var audio = new Audio(url);
    AriaHUD.currentAudio = audio;

    // Pre-fetch next while this one plays
    _pumpTTSPipeline();

    audio.onended = function () {
      URL.revokeObjectURL(url);
      AriaHUD.currentAudio = null;
      _ttsPlaying = false;
      _pumpTTSPipeline();
    };

    audio.onerror = function () {
      URL.revokeObjectURL(url);
      AriaHUD.currentAudio = null;
      _ttsPlaying = false;
      _pumpTTSPipeline();
    };

    audio.play().catch(function () {
      AriaHUD.currentAudio = null;
      _ttsPlaying = false;
      _pumpTTSPipeline();
    });
  }

  /**
   * Feed a token into the sentence buffer. When a sentence boundary is detected,
   * the sentence is queued for TTS. Called during SSE streaming.
   */
  function _feedTTSToken(token, sessionId) {
    if (!AriaHUD.ttsEnabled) return;
    _ttsSentenceBuf += token;

    // Detect sentence boundary: . ! ? followed by space or end
    var match = _ttsSentenceBuf.match(/^([\s\S]*?[.!?])\s+([\s\S]*)$/);
    if (match) {
      var sentence = match[1].trim();
      var remainder = match[2] || '';
      // Skip abbreviations (single uppercase letter before dot) or decimals
      var lastDot = sentence.lastIndexOf('.');
      if (lastDot >= 0) {
        var charBefore = sentence[lastDot - 1] || '';
        if (/^[A-Z]$/.test(charBefore) || /^\d$/.test(charBefore)) {
          return; // don't split yet
        }
      }
      _ttsSentenceBuf = remainder;
      _queueTTSSentence(sentence, sessionId);
    }
  }

  /**
   * Flush any remaining text in the sentence buffer to TTS.
   */
  function _flushTTSBuffer(sessionId) {
    if (_ttsSentenceBuf.trim()) {
      _queueTTSSentence(_ttsSentenceBuf, sessionId);
    }
    _ttsSentenceBuf = '';
  }

  /**
   * Speak a complete text (used for welcome greeting).
   * Splits into sentences and queues all.
   */
  function speakText(text) {
    if (!AriaHUD.ttsEnabled) return;
    stopSpeech();
    var sid = ++_ttsReqId;
    var sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    for (var i = 0; i < sentences.length; i++) {
      _queueTTSSentence(sentences[i], sid);
    }
  }

  function stopSpeech() {
    ++_ttsReqId; // invalidate all pending/queued
    _ttsQueue = [];
    _ttsAudioQueue = [];
    _ttsSentenceBuf = '';
    _ttsFetching = false;
    if (AriaHUD.currentAudio) {
      AriaHUD.currentAudio.pause();
      AriaHUD.currentAudio.currentTime = 0;
      AriaHUD.currentAudio = null;
    }
    _ttsPlaying = false;
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
      chip.title = h.query || h.label;
      chip.addEventListener('click', function () {
        if (h.tour) {
          _showTourMenu(chip);
        } else {
          if (AriaHUD.$input) AriaHUD.$input.value = h.query;
          sendMessage();
        }
      });
      AriaHUD.$hints.appendChild(chip);
    });
  }

  /* ==================================================================
   * GUIDED TOUR — "Omów aplikację"
   * Interactive walkthrough with element highlighting and TTS narration
   * ================================================================== */

  var TOUR_MODULES = {
    all: {
      label: 'Cała aplikacja',
      steps: [
        { page: '/projects',      el: '#projectsApp',  text: 'To jest strona projekt\u00f3w \u2014 centralny punkt pracy z platform\u0105 Aj Stejt \u0142eb. Tutaj tworzysz nowe projekty analityczne, otwierasz istniej\u0105ce, zarz\u0105dzasz plikami, zapraszasz cz\u0142onk\u00f3w zespo\u0142u i eksportujesz wyniki. Ka\u017cdy projekt to osobny kontener na pliki audio, transkrypcje, analizy i raporty.' },
        { page: '/transcription',  el: '.main-card',  text: 'Moduł transkrypcji. Tutaj wgrywasz pliki audio i uruchamiasz automatyczną transkrypcję mowy na tekst. Wspierane modele to Whisper i NeMo FastConformer. Wynik to tekst z sygnaturami czasowymi.' },
        { page: '/diarization',    el: '.main-card',  text: 'Moduł diaryzacji mówców. Rozpoznaje kto mówi w nagraniu i dzieli tekst na segmenty przypisane do konkretnych osób. Wykorzystuje model pyannote.' },
        { page: '/translation',    el: '.main-card',  text: 'Moduł tłumaczenia offline. Tłumaczy transkrypcje na ponad 200 języków używając modelu NLLB. Wszystko działa lokalnie, bez wysyłania danych na zewnętrzne serwery.' },
        { page: '/analysis',       el: '.main-card',  text: 'Centrum analiz. Zawiera moduły: analiza GSM billingów, analiza AML transakcji finansowych, analiza dokumentów i czat z LLM. Każdy moduł posiada własne narzędzia wizualizacji.' },
        { page: '/chat',           el: '.main-card',  text: 'Czat z modelem LLM. Możesz zadawać pytania o załadowane dokumenty i transkrypcje. Model analizuje treść i generuje odpowiedzi. Działa offline przez Ollama.' },
        { page: '/admin',          el: '.main-card',  text: 'Panel ustawień GPU. Monitorujesz tu zużycie pamięci karty graficznej, stan modeli i procesów. Ważne przy pracy z wieloma modelami jednocześnie.' },
      ],
    },
    projects: {
      label: 'Projekty (szczeg\u00f3\u0142owo)',
      steps: [
        // --- Widok ogólny ---
        { page: '/projects',  el: '#projectsApp',
          text: 'Strona projekt\u00f3w Aj Stejt \u0142eb. Widoczna jest lista Twoich projekt\u00f3w, pasek narz\u0119dzi u g\u00f3ry z przyciskami akcji oraz sekcja zaprosze\u0144 je\u015bli kto\u015b Ci\u0119 zaprosi\u0142 do wsp\u00f3\u0142pracy. Projekty mog\u0105 by\u0107 indywidualne lub wsp\u00f3\u0142dzielone z innymi u\u017cytkownikami.' },

        // --- Pasek narzędzi ---
        { page: '/projects',  el: '#projects_toolbar',
          text: 'Pasek narz\u0119dzi projektu. Zawiera wszystkie g\u0142\u00f3wne akcje: tworzenie nowego projektu, import i eksport, zapraszanie u\u017cytkownik\u00f3w, zarz\u0105dzanie cz\u0142onkami i usuwanie projekt\u00f3w. Przyciski aktywuj\u0105 si\u0119 w zale\u017cno\u015bci od wybranego projektu i Twoich uprawnie\u0144.' },

        // --- Tworzenie nowego projektu ---
        { page: '/projects',  el: '#btnNewProject',
          text: 'Przycisk tworzenia nowego projektu. Po klikni\u0119ciu otworzy si\u0119 okno dialogowe z formularzem. Mo\u017cesz go te\u017c wywo\u0142a\u0107 m\u00f3wi\u0105c do mnie: utw\u00f3rz nowy projekt.' },

        // --- Okno tworzenia (otwieramy modal) ---
        { page: '/projects',  el: '#modalNewProject .modal-panel',  openModal: '#btnNewProject',
          text: 'Okno tworzenia nowego projektu. Znajdziesz tu trzy sekcje: nazw\u0119 projektu, wyb\u00f3r typu oraz opcjonalne powi\u0105zanie z \u0142orkspejs.' },

        { page: '/projects',  el: '#npName',  keepModal: true,
          text: 'Pole nazwy projektu. Wpisz opisow\u0105 nazw\u0119, na przyk\u0142ad: Przes\u0142uchanie \u015bwiadka A, Billing GSM podejrzanego, Analiza konta firmowego. Je\u015bli projekt o takiej nazwie ju\u017c istnieje, system automatycznie doda dat\u0119 i godzin\u0119 do nazwy, \u017ceby unikn\u0105\u0107 konfliktu.' },

        { page: '/projects',  el: '#npTypes',  keepModal: true,
          text: 'Wyb\u00f3r typu projektu. Dost\u0119pne typy: Transkrypcja, Diaryzacja, Analiza, Czat LLM, T\u0142umaczenie i Og\u00f3lny. Typ okre\u015bla domy\u015blny modu\u0142 powi\u0105zany z projektem, ale nie ogranicza dost\u0119pu do innych modu\u0142\u00f3w \u2014 ka\u017cdy projekt mo\u017ce korzysta\u0107 ze wszystkich funkcji platformy.' },

        { page: '/projects',  el: '#npLinkTo',  keepModal: true,
          text: 'Powi\u0105zanie z \u0142orkspejs. Opcjonalnie mo\u017cesz przypisa\u0107 projekt do istniej\u0105cej przestrzeni roboczej. \u0141orkspejs grupuje powi\u0105zane projekty \u2014 na przyk\u0142ad wszystkie projekty dotycz\u0105ce jednej sprawy. Pozostaw puste je\u015bli projekt jest samodzielny.' },

        { page: '/projects',  el: '#npSubmit',  keepModal: true,
          text: 'Przycisk zatwierdzaj\u0105cy utworzenie projektu. Po klikni\u0119ciu projekt zostanie utworzony i pojawi si\u0119 na li\u015bcie.' },

        // --- Zamykamy modal, wracamy do listy ---
        { page: '/projects',  el: '#projectList, #projectEmpty',  closeModal: true,
          text: 'Lista projekt\u00f3w. Ka\u017cdy projekt wy\u015bwietla si\u0119 jako karta z nazw\u0105, typem, dat\u0105 utworzenia i przyciskami akcji. Je\u015bli lista jest pusta, zobaczysz komunikat z zach\u0119t\u0105 do utworzenia pierwszego projektu.' },

        // --- Karta projektu ---
        { page: '/projects',  el: '.sp-card, #projectList',
          text: 'Karta projektu. Klikni\u0119cie otwiera projekt i aktywuje go jako bie\u017c\u0105cy. Na karcie widzisz: ikon\u0119 typu, nazw\u0119 projektu, informacj\u0119 o w\u0142a\u015bcicielu i cz\u0142onkach zespo\u0142u, oraz przyciski akcji po prawej stronie.' },

        { page: '/projects',  el: '.sp-card-actions, .sp-open',
          text: 'Przyciski akcji na karcie. Od lewej: Otw\u00f3rz projekt, Zapro\u015b u\u017cytkownika, Zarz\u0105dzaj cz\u0142onkami, Usu\u0144 projekt. Dost\u0119pno\u015b\u0107 przycisk\u00f3w zale\u017cy od Twojej roli \u2014 w\u0142a\u015bciciel widzi wszystko, zwyk\u0142y cz\u0142onek mo\u017ce tylko otwiera\u0107.' },

        // --- Import ---
        { page: '/projects',  el: '#btnImportProject',
          text: 'Import projektu. Wczytuje projekt z pliku w formacie aj stejt. Plik aj stejt to skompresowane archiwum zawieraj\u0105ce wszystkie dane projektu: transkrypcje, analizy, ustawienia i opcjonalnie pliki audio. Import odtwarza pe\u0142n\u0105 struktur\u0119 projektu.' },

        // --- Eksport ---
        { page: '/projects',  el: '#btnExportProject',
          text: 'Eksport projektu. Zapisuje ca\u0142y projekt do pliku aj stejt, kt\u00f3ry mo\u017cesz przenie\u015b\u0107 na inny komputer, zarchiwizowa\u0107 lub udost\u0119pni\u0107. Je\u015bli projekt jest zaszyfrowany, eksport zachowuje szyfrowanie.' },

        // --- Zapraszanie użytkowników ---
        { page: '/projects',  el: '#btnInviteUser',
          text: 'Zapraszanie u\u017cytkownika do projektu. Otwiera formularz gdzie podajesz nazw\u0119 u\u017cytkownika, wybierasz rol\u0119 i opcjonalnie dodajesz wiadomo\u015b\u0107. Zaproszenie pojawi si\u0119 u u\u017cytkownika w sekcji Zaproszenia na stronie projekt\u00f3w.' },

        { page: '/projects',  el: '#modalInviteUser .modal-panel',  openModal: '#btnInviteUser',
          text: 'Formularz zaproszenia. Pola: wyb\u00f3r projektu, nazwa u\u017cytkownika do zaproszenia, rola w projekcie i opcjonalna wiadomo\u015b\u0107. Dost\u0119pne role to: przegl\u0105daj\u0105cy \u2014 mo\u017ce czyta\u0107, edytor \u2014 mo\u017ce modyfikowa\u0107, mened\u017cer \u2014 pe\u0142ne uprawnienia opr\u00f3cz usuwania projektu.' },

        // --- Zarządzanie członkami ---
        { page: '/projects',  el: '#btnManageMembers',  closeModal: true,
          text: 'Zarz\u0105dzanie cz\u0142onkami projektu. Otwiera list\u0119 wszystkich os\u00f3b z dost\u0119pem do wybranego projektu. Mo\u017cesz zmieni\u0107 rol\u0119 cz\u0142onka, usun\u0105\u0107 go z projektu lub zobaczy\u0107 kto jest w\u0142a\u015bcicielem.' },

        // --- Zaproszenia przychodzące ---
        { page: '/projects',  el: '#invitationsCard, #invitationList',
          text: 'Sekcja zaprosze\u0144. Je\u015bli inny u\u017cytkownik zaprosi\u0142 Ci\u0119 do swojego projektu, zaproszenie pojawi si\u0119 tutaj. Przy ka\u017cdym zaproszeniu widzisz: kto Ci\u0119 zaprosi\u0142, do jakiego projektu, z jak\u0105 rol\u0105 oraz ewentualn\u0105 wiadomo\u015b\u0107. Kliknij Akceptuj aby do\u0142\u0105czy\u0107 lub Odrzu\u0107 aby odm\u00f3wi\u0107.' },

        // --- Usuwanie projektów (toolbar) ---
        { page: '/projects',  el: '#btnDeleteProject',
          text: 'Usuwanie projektu z paska narz\u0119dzi. Otwiera okno dialogowe z list\u0105 Twoich projekt\u00f3w do usuni\u0119cia. Mo\u017cesz usun\u0105\u0107 tylko projekty kt\u00f3rych jeste\u015b w\u0142a\u015bcicielem.' },

        // --- Usuwanie projektów (modal) ---
        { page: '/projects',  el: '#modalDeleteProject .modal-panel',  openModal: '#btnDeleteProject',
          text: 'Okno usuwania projektu. Wybierasz projekt z listy i metod\u0119 kasowania danych. Dost\u0119pne s\u0105 cztery metody kasowania danych z dysku.' },

        { page: '/projects',  el: '#delProjWipeMethod',  keepModal: true,
          text: 'Metody bezpiecznego kasowania danych: Pierwsza \u2014 szybkie usuni\u0119cie, pliki znikaj\u0105 z systemu ale mog\u0105 by\u0107 teoretycznie odzyskane. Druga \u2014 jednokrotne nadpisanie losowymi danymi, bezpieczne dla wi\u0119kszo\u015bci zastosowa\u0144. Trzecia \u2014 HMG IS5, trzykrotne nadpisanie wed\u0142ug brytyjskiego standardu rz\u0105dowego. Czwarta \u2014 metoda Gutmanna, 35-krotne nadpisanie \u2014 najwolniejsza ale najbezpieczniejsza, uniemo\u017cliwia odzyskanie nawet w laboratorium.' },

        { page: '/projects',  el: '#delProjConfirm',  keepModal: true,
          text: 'Przycisk potwierdzaj\u0105cy usuni\u0119cie. Operacja jest nieodwracalna! Po klikni\u0119ciu wszystkie pliki projektu zostan\u0105 skasowane wybran\u0105 metod\u0105, a metadane usuni\u0119te z bazy danych. Przed klikni\u0119ciem upewnij si\u0119 \u017ce wybra\u0142e\u015b w\u0142a\u015bciwy projekt.' },

        // --- Koniec ---
        { page: '/projects',  el: '#projectsApp',  closeModal: true,
          text: 'To wszystko o zarz\u0105dzaniu projektami w Aj Stejt \u0142eb. Pami\u0119taj: projekty to podstawa pracy z platform\u0105. Stw\u00f3rz projekt, wgraj pliki, uruchom transkrypcj\u0119 lub analiz\u0119. Je\u015bli pracujesz w zespole, zapro\u015b cz\u0142onk\u00f3w i przydziel im odpowiednie role.' },
      ],
    },
    transcription: {
      label: 'Transkrypcja',
      steps: [
        { page: '/transcription',  el: '.file-upload, input[type="file"], .upload-area',  text: 'Tutaj wgrywasz pliki audio do transkrypcji. Obsługiwane formaty to WAV, MP3, FLAC, OGG i inne. Możesz przeciągnąć plik lub kliknąć przycisk wyboru.' },
        { page: '/transcription',  el: '#whisperModel, .model-select, select[name*="model"]',  text: 'Wybór modelu ASR. Whisper large v3 daje najlepszą jakość, ale wymaga więcej pamięci GPU. Mniejsze modele działają szybciej.' },
        { page: '/transcription',  el: '#btn_transcribe, button[onclick*="transcri"]',  text: 'Przycisk uruchamiający transkrypcję. Po kliknięciu system przetwarza audio i generuje tekst z sygnaturami czasowymi.' },
        { page: '/transcription',  el: '.transcript-output, .transcript-text, #transcriptArea',  text: 'Tutaj pojawia się wynik transkrypcji — tekst z oznaczeniami czasu. Możesz go edytować, eksportować do różnych formatów i wysłać do dalszej analizy.' },
      ],
    },
    analysis_gsm: {
      label: 'Analiza GSM',
      steps: [
        { page: '/analysis#gsm',  el: '.gsm-upload, .upload-area, input[type="file"]',  text: 'Wgraj plik bilingu GSM w formacie CSV lub XLSX. System automatycznie rozpozna strukturę kolumn i przeprowadzi wstępną analizę.' },
        { page: '/analysis#gsm',  el: '.gsm-map, #gsmMap, .map-container',  text: 'Mapa z pozycjami stacji BTS. Pokazuje lokalizacje z których wykonywano połączenia. Pomaga odtworzyć trasę poruszania się.' },
        { page: '/analysis#gsm',  el: '.gsm-timeline, .timeline, #gsmTimeline',  text: 'Oś czasu połączeń i wiadomości SMS. Wizualizuje aktywność w czasie, ułatwia wykrywanie wzorców komunikacji.' },
        { page: '/analysis#gsm',  el: '.gsm-contacts, .contact-list',  text: 'Lista kontaktów z bilingu. Pokazuje najczęstszych rozmówców, ilość połączeń i ich czas trwania.' },
      ],
    },
    analysis_aml: {
      label: 'Analiza AML',
      steps: [
        { page: '/analysis#aml',  el: '.aml-upload, .upload-area',  text: 'Wgraj wyciąg bankowy w formacie MT940, CSV lub XLSX. System przeprowadzi automatyczną analizę transakcji pod kątem podejrzanych operacji.' },
        { page: '/analysis#aml',  el: '.aml-alerts, .alert-list',  text: 'Lista alertów i podejrzanych transakcji. System wykrywa: strukturyzację kwot, transakcje okrężne, szybkie przelewy i inne anomalie.' },
        { page: '/analysis#aml',  el: '.aml-graph, #amlGraph',  text: 'Graf powiązań między kontami. Wizualizuje przepływ pieniędzy i pomaga odkrywać sieci powiązanych kont.' },
      ],
    },
    diarization: {
      label: 'Diaryzacja',
      steps: [
        { page: '/diarization',  el: '.file-select, .project-files',  text: 'Wybierz plik audio z projektu do diaryzacji. Plik musi być najpierw wgrany do aktywnego projektu.' },
        { page: '/diarization',  el: '#btn_diarize, button[onclick*="diariz"]',  text: 'Przycisk uruchamiający diaryzację. Model pyannote przeanalizuje nagranie i przypisze segmenty do poszczególnych mówców.' },
        { page: '/diarization',  el: '.speaker-map, .diarization-result',  text: 'Wynik diaryzacji. Każdy mówca ma swój kolor. Możesz nadać mówcom imiona i edytować przypisania.' },
      ],
    },
  };

  var _tourActive = false;
  var _tourSteps = [];
  var _tourStep = 0;
  var _tourOverlay = null;
  var _tourSpotlight = null;
  var _tourPointer = null;
  var _tourTooltip = null;
  var _tourHighlightedEl = null;  // currently brightened element
  var _tourAutoTimer = null;      // auto-advance timer
  var _tourPaused = false;        // user clicked tooltip → paused

  function _showTourMenu(anchorEl) {
    // Remove existing menu if any
    var old = document.getElementById('aria-tour-menu');
    if (old) { old.remove(); return; }

    var menu = document.createElement('div');
    menu.id = 'aria-tour-menu';
    menu.className = 'aria-tour-menu';

    var keys = Object.keys(TOUR_MODULES);
    for (var i = 0; i < keys.length; i++) {
      (function (key) {
        var btn = document.createElement('button');
        btn.className = 'aria-tour-menu-item';
        btn.textContent = TOUR_MODULES[key].label;
        btn.addEventListener('click', function () {
          menu.remove();
          _startTour(key);
        });
        menu.appendChild(btn);
      })(keys[i]);
    }

    // Position near the anchor chip
    if (AriaHUD.$hints) {
      AriaHUD.$hints.appendChild(menu);
    }

    // Close on outside click
    setTimeout(function () {
      document.addEventListener('click', function _closeTourMenu(e) {
        if (!menu.contains(e.target) && e.target !== anchorEl) {
          menu.remove();
          document.removeEventListener('click', _closeTourMenu);
        }
      });
    }, 50);
  }

  function _startTour(moduleKey) {
    var mod = TOUR_MODULES[moduleKey];
    if (!mod || !mod.steps || mod.steps.length === 0) return;

    _tourActive = true;
    _tourSteps = mod.steps;
    _tourStep = 0;

    // Create overlay elements
    _createTourOverlay();

    // Add system message
    _addMsgBubble('system', '🎯 Przewodnik: ' + mod.label + ' (' + mod.steps.length + ' kroków)');

    // Start first step
    _executeTourStep();
  }

  function _createTourOverlay() {
    // Semi-transparent overlay
    _tourOverlay = document.createElement('div');
    _tourOverlay.id = 'aria-tour-overlay';
    _tourOverlay.className = 'aria-tour-overlay';
    document.body.appendChild(_tourOverlay);

    // Spotlight cutout
    _tourSpotlight = document.createElement('div');
    _tourSpotlight.className = 'aria-tour-spotlight';
    document.body.appendChild(_tourSpotlight);

    // Animated pointer
    _tourPointer = document.createElement('div');
    _tourPointer.className = 'aria-tour-pointer';
    _tourPointer.innerHTML = '&#9654;'; // ▶
    document.body.appendChild(_tourPointer);

    // Tooltip with text + nav buttons
    _tourTooltip = document.createElement('div');
    _tourTooltip.className = 'aria-tour-tooltip';
    document.body.appendChild(_tourTooltip);
  }

  var _tourElevatedParents = [];  // parents we lifted z-index on

  function _unhighlightPrev() {
    if (_tourHighlightedEl) {
      _tourHighlightedEl.classList.remove('aria-tour-active');
      _tourHighlightedEl = null;
    }
    // Restore parents
    _tourElevatedParents.forEach(function (p) {
      p.el.style.zIndex = p.orig;
    });
    _tourElevatedParents = [];
  }

  function _executeTourStep() {
    if (!_tourActive || _tourStep >= _tourSteps.length) {
      _endTour();
      return;
    }

    _unhighlightPrev();
    var step = _tourSteps[_tourStep];

    // Close modal from previous step if this step says closeModal
    if (step.closeModal) {
      var openModals = document.querySelectorAll('.modal-overlay[style*="display: block"], .modal-overlay[style*="display:block"]');
      openModals.forEach(function (m) { m.style.display = 'none'; });
      // Also try clicking close buttons
      var closeBtn = document.querySelector('.modal-overlay:not([style*="display: none"]):not([style*="display:none"]) .modal-close-x');
      if (closeBtn) closeBtn.click();
    }

    // Open modal if step requires it
    if (step.openModal) {
      var trigger = document.querySelector(step.openModal);
      if (trigger) {
        setTimeout(function () { trigger.click(); }, 50);
      }
    }

    // Navigate if needed
    var targetPath = step.page || '';
    if (targetPath) {
      var hashIdx = targetPath.indexOf('#');
      var pagePart = hashIdx >= 0 ? targetPath.substring(0, hashIdx) : targetPath;
      var hashPart = hashIdx >= 0 ? targetPath.substring(hashIdx) : '';

      if (pagePart && location.pathname !== pagePart) {
        sessionStorage.setItem('aria_tour_module', JSON.stringify({
          steps: _tourSteps,
          step: _tourStep,
        }));
        window.location.href = targetPath;
        return;
      }

      if (hashPart && location.hash !== hashPart) {
        var tabId = hashPart.substring(1);
        var tabBtn = document.querySelector('[data-tab="' + tabId + '"], [onclick*="' + tabId + '"]');
        if (tabBtn) tabBtn.click();
      }
    }

    // Delay for modal to open / tab to switch
    var delay = (step.openModal || step.closeModal) ? 350 : 100;
    setTimeout(function () {
      _highlightElement(step);
    }, delay);
  }

  function _highlightElement(step) {
    // Try each selector until one matches a visible element
    var selectors = (step.el || '').split(',').map(function (s) { return s.trim(); });
    var targetEl = null;

    for (var i = 0; i < selectors.length; i++) {
      try {
        var el = document.querySelector(selectors[i]);
        if (el && el.offsetParent !== null) { targetEl = el; break; }
        if (el && !targetEl) targetEl = el; // fallback to hidden element
      } catch (e) { /* */ }
    }

    if (targetEl) {
      // Add brightening class to the element
      targetEl.classList.add('aria-tour-active');
      _tourHighlightedEl = targetEl;

      // Elevate parent containers so element is visible above overlay
      var parent = targetEl.parentElement;
      var depth = 0;
      while (parent && parent !== document.body && depth < 8) {
        var cs = window.getComputedStyle(parent);
        var origZ = parent.style.zIndex || '';
        // If parent has stacking context that could trap our element
        if (cs.position !== 'static' || cs.zIndex !== 'auto' || parent.classList.contains('modal-panel') || parent.classList.contains('modal-overlay')) {
          _tourElevatedParents.push({ el: parent, orig: origZ });
          parent.style.zIndex = '8003';
        }
        parent = parent.parentElement;
        depth++;
      }

      var rect = targetEl.getBoundingClientRect();

      // Position spotlight
      var pad = 12;
      _tourSpotlight.style.left = (rect.left - pad + window.scrollX) + 'px';
      _tourSpotlight.style.top = (rect.top - pad + window.scrollY) + 'px';
      _tourSpotlight.style.width = (rect.width + pad * 2) + 'px';
      _tourSpotlight.style.height = (rect.height + pad * 2) + 'px';
      _tourSpotlight.style.display = 'block';

      // Position pointer
      _tourPointer.style.left = (rect.left - 30 + window.scrollX) + 'px';
      _tourPointer.style.top = (rect.top + rect.height / 2 - 12 + window.scrollY) + 'px';
      _tourPointer.style.display = 'block';

      // Scroll into view
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      _tourSpotlight.style.display = 'none';
      _tourPointer.style.display = 'none';
    }

    // Clear any pending auto-advance
    if (_tourAutoTimer) { clearTimeout(_tourAutoTimer); _tourAutoTimer = null; }
    _tourPaused = false;

    // Show tooltip
    _tourTooltip.innerHTML = '';

    var textDiv = document.createElement('div');
    textDiv.className = 'aria-tour-text';
    textDiv.textContent = step.text;
    // Click on text = pause auto-advance
    textDiv.style.cursor = 'pointer';
    textDiv.title = 'Kliknij aby wstrzyma\u0107 / wznowi\u0107';
    textDiv.addEventListener('click', function () {
      _tourPaused = !_tourPaused;
      if (_tourPaused) {
        if (_tourAutoTimer) { clearTimeout(_tourAutoTimer); _tourAutoTimer = null; }
        textDiv.style.borderLeft = '3px solid var(--aria-amber)';
        pauseLabel.textContent = '\u275a\u275a PAUZA \u2014 kliknij tekst lub Dalej';
        pauseLabel.style.display = 'block';
      } else {
        textDiv.style.borderLeft = '';
        pauseLabel.style.display = 'none';
        _tourAutoAdvance();
      }
    });
    _tourTooltip.appendChild(textDiv);

    var pauseLabel = document.createElement('div');
    pauseLabel.className = 'aria-tour-pause-label';
    pauseLabel.style.display = 'none';
    _tourTooltip.appendChild(pauseLabel);

    var stepInfo = document.createElement('div');
    stepInfo.className = 'aria-tour-step-info';
    stepInfo.textContent = 'Krok ' + (_tourStep + 1) + ' / ' + _tourSteps.length;
    _tourTooltip.appendChild(stepInfo);

    var btnRow = document.createElement('div');
    btnRow.className = 'aria-tour-btns';

    if (_tourStep > 0) {
      var prevBtn = document.createElement('button');
      prevBtn.className = 'aria-confirm-btn no';
      prevBtn.textContent = '\u25c0 Wstecz';
      prevBtn.onclick = function () { _tourPaused = false; _tourStep--; _executeTourStep(); };
      btnRow.appendChild(prevBtn);
    }

    var stopBtn = document.createElement('button');
    stopBtn.className = 'aria-confirm-btn no';
    stopBtn.textContent = '\u2715 Zako\u0144cz';
    stopBtn.onclick = function () { _endTour(); };
    btnRow.appendChild(stopBtn);

    if (_tourStep < _tourSteps.length - 1) {
      var nextBtn = document.createElement('button');
      nextBtn.className = 'aria-confirm-btn yes';
      nextBtn.textContent = 'Dalej \u25b6';
      nextBtn.onclick = function () { _tourPaused = false; _tourStep++; _executeTourStep(); };
      btnRow.appendChild(nextBtn);
    } else {
      var finBtn = document.createElement('button');
      finBtn.className = 'aria-confirm-btn yes';
      finBtn.textContent = '\u2713 Koniec';
      finBtn.onclick = function () { _endTour(); };
      btnRow.appendChild(finBtn);
    }

    _tourTooltip.appendChild(btnRow);
    _tourTooltip.style.display = 'block';

    // Speak the step text via TTS
    speakText(step.text);

    // Schedule auto-advance: 3 seconds after TTS finishes
    _tourAutoAdvance();

    // Show overlay
    if (_tourOverlay) _tourOverlay.style.display = 'block';
  }

  /**
   * Auto-advance to next tour step 3 seconds after TTS finishes.
   * Polls every 500ms to check if TTS is done.
   */
  function _tourAutoAdvance() {
    if (_tourAutoTimer) clearTimeout(_tourAutoTimer);
    if (!_tourActive || _tourPaused) return;

    // If this is the last step, don't auto-advance
    if (_tourStep >= _tourSteps.length - 1) return;

    _tourAutoTimer = setTimeout(function _checkTTSDone() {
      if (!_tourActive || _tourPaused) return;
      // Check if TTS is still playing or fetching
      if (_ttsPlaying || _ttsQueue.length > 0 || _ttsAudioQueue.length > 0 || _ttsFetching) {
        // Still speaking — check again in 500ms
        _tourAutoTimer = setTimeout(_checkTTSDone, 500);
      } else {
        // TTS done — wait 3 seconds then advance
        _tourAutoTimer = setTimeout(function () {
          if (!_tourActive || _tourPaused) return;
          _tourStep++;
          _executeTourStep();
        }, 3000);
      }
    }, 500);
  }

  function _endTour() {
    _tourActive = false;
    _tourSteps = [];
    _tourStep = 0;
    _tourPaused = false;
    if (_tourAutoTimer) { clearTimeout(_tourAutoTimer); _tourAutoTimer = null; }
    stopSpeech();
    _unhighlightPrev();

    // Close any open modals
    document.querySelectorAll('.modal-overlay').forEach(function (m) { m.style.display = 'none'; });

    if (_tourOverlay) { _tourOverlay.remove(); _tourOverlay = null; }
    if (_tourSpotlight) { _tourSpotlight.remove(); _tourSpotlight = null; }
    if (_tourPointer) { _tourPointer.remove(); _tourPointer = null; }
    if (_tourTooltip) { _tourTooltip.remove(); _tourTooltip = null; }

    sessionStorage.removeItem('aria_tour_module');

    _addMsgBubble('system', '✓ Przewodnik zakończony.');
  }

  function _resumeTourIfNeeded() {
    try {
      var saved = sessionStorage.getItem('aria_tour_module');
      if (!saved) return;
      var data = JSON.parse(saved);
      if (data && data.steps && typeof data.step === 'number') {
        _tourActive = true;
        _tourSteps = data.steps;
        _tourStep = data.step;
        _createTourOverlay();
        setTimeout(function () { _executeTourStep(); }, 600);
      }
    } catch (e) { /* */ }
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
    stopSpeech();
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
