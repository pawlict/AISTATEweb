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

  /* ---- TTS — sentence-level streaming queue ---- */
  var _ttsReqId = 0;      // monotonic session counter (cancel all on new message)
  var _ttsQueue = [];      // queue of sentence strings to speak
  var _ttsPlaying = false; // is audio currently playing from queue
  var _ttsSentenceBuf = ''; // buffer for accumulating tokens into sentences

  /**
   * Queue a sentence for TTS playback. Starts playing immediately if idle.
   */
  function _queueTTSSentence(sentence, sessionId) {
    if (!AriaHUD.ttsEnabled) return;
    sentence = sentence.trim();
    if (!sentence) return;
    // Strip action/confirm tags from TTS
    sentence = sentence.replace(/\[ACTION:[^\]]*\]/g, '').replace(/\[CONFIRM:[^\]]*\]/g, '').trim();
    if (!sentence) return;

    _ttsQueue.push({ text: sentence, sid: sessionId });
    if (!_ttsPlaying) {
      _playNextFromQueue();
    }
  }

  /**
   * Play next sentence from queue. Chains: play → onended → playNext.
   */
  async function _playNextFromQueue() {
    if (_ttsQueue.length === 0) {
      _ttsPlaying = false;
      setAriaWaveMode(false);
      return;
    }

    _ttsPlaying = true;
    setAriaWaveMode(true);

    var item = _ttsQueue.shift();
    // If session changed (new message started or stopSpeech called), drop
    if (item.sid !== _ttsReqId) {
      _ttsPlaying = false;
      _ttsQueue = [];
      setAriaWaveMode(false);
      return;
    }

    try {
      var res = await fetch('/api/aria/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: item.text }),
      });

      if (item.sid !== _ttsReqId) { _ttsPlaying = false; _ttsQueue = []; setAriaWaveMode(false); return; }
      if (!res.ok) { _playNextFromQueue(); return; }

      var blob = await res.blob();
      if (item.sid !== _ttsReqId) { _ttsPlaying = false; _ttsQueue = []; setAriaWaveMode(false); return; }

      var url = URL.createObjectURL(blob);
      var audio = new Audio(url);
      AriaHUD.currentAudio = audio;

      audio.onended = function () {
        URL.revokeObjectURL(url);
        AriaHUD.currentAudio = null;
        _playNextFromQueue();
      };

      audio.onerror = function () {
        URL.revokeObjectURL(url);
        AriaHUD.currentAudio = null;
        _playNextFromQueue();
      };

      audio.play().catch(function () {
        AriaHUD.currentAudio = null;
        _playNextFromQueue();
      });
    } catch (e) {
      _playNextFromQueue();
    }
  }

  /**
   * Feed a token into the sentence buffer. When a sentence boundary is detected,
   * the sentence is queued for TTS. Called during SSE streaming.
   */
  function _feedTTSToken(token, sessionId) {
    if (!AriaHUD.ttsEnabled) return;
    _ttsSentenceBuf += token;

    // Detect sentence boundary: ends with . ! ? followed by optional whitespace or end of token
    // But skip dots in abbreviations like "A.R.I.A." or numbers like "3.5"
    var match = _ttsSentenceBuf.match(/^([\s\S]*?[.!?])\s+([\s\S]*)$/);
    if (match) {
      var sentence = match[1].trim();
      var remainder = match[2] || '';
      // Skip if it looks like an abbreviation (single letter before dot) or decimal number
      var lastDot = sentence.lastIndexOf('.');
      if (lastDot >= 0) {
        var charBefore = sentence[lastDot - 1] || '';
        // e.g. "A." or "3." — skip boundary
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
    // Split by sentence boundaries
    var sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    for (var i = 0; i < sentences.length; i++) {
      _queueTTSSentence(sentences[i], sid);
    }
  }

  function stopSpeech() {
    ++_ttsReqId; // invalidate all pending/queued
    _ttsQueue = [];
    _ttsSentenceBuf = '';
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
        { page: '/projects',      el: '.workspace-card, .project-card, #projectGrid',  text: 'To jest strona projektów. Tutaj tworzysz nowe projekty analityczne, otwierasz istniejące i zarządzasz plikami. Każdy projekt to osobny kontener na pliki audio, transkrypcje, analizy i raporty.' },
        { page: '/transcription',  el: '#btn_transcribe, .transcription-controls, .main-card',  text: 'Moduł transkrypcji. Tutaj wgrywasz pliki audio i uruchamiasz automatyczną transkrypcję mowy na tekst. Wspierane modele to Whisper i NeMo FastConformer. Wynik to tekst z sygnaturami czasowymi.' },
        { page: '/diarization',    el: '#btn_diarize, .diarization-controls, .main-card',  text: 'Moduł diaryzacji mówców. Rozpoznaje kto mówi w nagraniu i dzieli tekst na segmenty przypisane do konkretnych osób. Wykorzystuje model pyannote.' },
        { page: '/translation',    el: '.translation-controls, .main-card',  text: 'Moduł tłumaczenia offline. Tłumaczy transkrypcje na ponad 200 języków używając modelu NLLB. Wszystko działa lokalnie, bez wysyłania danych na zewnętrzne serwery.' },
        { page: '/analysis',       el: '.analysis-tabs, .tab-bar, .main-card',  text: 'Centrum analiz. Zawiera moduły: analiza GSM, analiza AML transakcji finansowych, analiza dokumentów i czat z LLM. Każdy moduł posiada własne narzędzia wizualizacji.' },
        { page: '/chat',           el: '.chat-container, .main-card',  text: 'Czat z modelem LLM. Możesz zadawać pytania o załadowane dokumenty i transkrypcje. Model analizuje treść i generuje odpowiedzi. Działa offline przez Ollama.' },
        { page: '/admin',          el: '.gpu-status, .main-card',  text: 'Panel ustawień GPU. Monitorujesz tu zużycie pamięci karty graficznej, stan modeli i procesów. Ważne przy pracy z wieloma modelami jednocześnie.' },
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

  function _executeTourStep() {
    if (!_tourActive || _tourStep >= _tourSteps.length) {
      _endTour();
      return;
    }

    var step = _tourSteps[_tourStep];

    // Navigate if needed
    var currentPath = location.pathname + location.hash;
    var targetPath = step.page || '';
    var needsNav = false;

    if (targetPath) {
      var hashIdx = targetPath.indexOf('#');
      var pagePart = hashIdx >= 0 ? targetPath.substring(0, hashIdx) : targetPath;
      var hashPart = hashIdx >= 0 ? targetPath.substring(hashIdx) : '';

      if (pagePart && location.pathname !== pagePart) {
        needsNav = true;
        // Store tour state so it resumes after navigation
        sessionStorage.setItem('aria_tour_module', JSON.stringify({
          steps: _tourSteps,
          step: _tourStep,
        }));
        window.location.href = targetPath;
        return;
      }

      // If same page but different hash (tab), click the tab
      if (hashPart && location.hash !== hashPart) {
        var tabId = hashPart.substring(1);
        var tabBtn = document.querySelector('[data-tab="' + tabId + '"], [onclick*="' + tabId + '"]');
        if (tabBtn) tabBtn.click();
      }
    }

    // Find and highlight element
    setTimeout(function () {
      _highlightElement(step);
    }, needsNav ? 500 : 100);
  }

  function _highlightElement(step) {
    // Try each selector (comma-separated) until one matches
    var selectors = (step.el || '').split(',').map(function (s) { return s.trim(); });
    var targetEl = null;

    for (var i = 0; i < selectors.length; i++) {
      try { targetEl = document.querySelector(selectors[i]); } catch (e) { /* */ }
      if (targetEl) break;
    }

    if (targetEl) {
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

    // Show tooltip
    _tourTooltip.innerHTML = '';

    var textDiv = document.createElement('div');
    textDiv.className = 'aria-tour-text';
    textDiv.textContent = step.text;
    _tourTooltip.appendChild(textDiv);

    var stepInfo = document.createElement('div');
    stepInfo.className = 'aria-tour-step-info';
    stepInfo.textContent = 'Krok ' + (_tourStep + 1) + ' / ' + _tourSteps.length;
    _tourTooltip.appendChild(stepInfo);

    var btnRow = document.createElement('div');
    btnRow.className = 'aria-tour-btns';

    if (_tourStep > 0) {
      var prevBtn = document.createElement('button');
      prevBtn.className = 'aria-confirm-btn no';
      prevBtn.textContent = '◀ Wstecz';
      prevBtn.onclick = function () { _tourStep--; _executeTourStep(); };
      btnRow.appendChild(prevBtn);
    }

    var stopBtn = document.createElement('button');
    stopBtn.className = 'aria-confirm-btn no';
    stopBtn.textContent = '✕ Zakończ';
    stopBtn.onclick = function () { _endTour(); };
    btnRow.appendChild(stopBtn);

    if (_tourStep < _tourSteps.length - 1) {
      var nextBtn = document.createElement('button');
      nextBtn.className = 'aria-confirm-btn yes';
      nextBtn.textContent = 'Dalej ▶';
      nextBtn.onclick = function () { _tourStep++; _executeTourStep(); };
      btnRow.appendChild(nextBtn);
    } else {
      var finBtn = document.createElement('button');
      finBtn.className = 'aria-confirm-btn yes';
      finBtn.textContent = '✓ Koniec';
      finBtn.onclick = function () { _endTour(); };
      btnRow.appendChild(finBtn);
    }

    _tourTooltip.appendChild(btnRow);
    _tourTooltip.style.display = 'block';

    // Speak the step text via TTS
    speakText(step.text);

    // Show overlay
    if (_tourOverlay) _tourOverlay.style.display = 'block';
  }

  function _endTour() {
    _tourActive = false;
    _tourSteps = [];
    _tourStep = 0;
    stopSpeech();

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
