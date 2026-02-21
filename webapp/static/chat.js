/**
 * chat.js — Chat LLM module for AISTATEweb
 * Conversational interface with locally installed Ollama models.
 *
 * Background-job flow (routed through GPU Resource Manager):
 *   1. POST /api/chat/send  — enqueues task in GPU RM queue
 *   2. GET  /api/chat/follow/{conv_id}  — SSE stream for live display
 *   3. GET  /api/chat/result/{conv_id}  — poll completed/partial result on reload
 */

/* global applyI18n, i18n */

(function () {
  "use strict";

  // ---------- State ----------
  let _model = "";
  let _messages = []; // {role, content}
  let _streaming = false;
  let _abortCtrl = null;

  // Conversation history (in-memory, persisted to localStorage)
  const STORAGE_KEY = "aistate_chat_history";
  let _conversations = []; // [{id, title, model, messages, ts, pendingJobId}]
  let _activeConvId = null;

  // ---------- DOM refs ----------
  const $ = (sel) => document.querySelector(sel);
  const $id = (id) => document.getElementById(id);

  // ---------- Init ----------
  async function initChat() {
    _loadConversations();
    _bindEvents();
    await _loadModels();
    _renderHistory();
    // Restore last active conversation so it survives tab switches
    await _restoreLastActive();
  }

  // ---------- Models ----------
  async function _loadModels() {
    const sel = $id("chat_model");
    if (!sel) return;
    sel.innerHTML = '<option value="">…</option>';

    try {
      const r = await fetch("/api/chat/models");
      const data = await r.json();
      if (data.status === "offline") {
        sel.innerHTML = '<option value="">' + _t("chat.ollama_offline") + "</option>";
        _setStatus(_t("chat.ollama_offline"));
        return;
      }
      const models = data.models || [];
      if (models.length === 0) {
        sel.innerHTML = '<option value="">' + _t("chat.no_models") + "</option>";
        return;
      }
      sel.innerHTML = "";
      for (const m of models) {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        sel.appendChild(opt);
      }
      // restore last used model
      const last = localStorage.getItem("aistate_chat_model");
      if (last && models.includes(last)) {
        sel.value = last;
      }
      _model = sel.value;
      _setStatus(_t("chat.ready"));
    } catch (e) {
      sel.innerHTML = '<option value="">' + _t("chat.load_error") + "</option>";
      _setStatus(_t("chat.load_error"));
    }
  }

  // ---------- Events ----------
  function _bindEvents() {
    const sel = $id("chat_model");
    if (sel) sel.addEventListener("change", () => {
      _model = sel.value;
      localStorage.setItem("aistate_chat_model", _model);
    });

    const sendBtn = $id("chat_send_btn");
    if (sendBtn) sendBtn.addEventListener("click", _onSend);

    const stopBtn = $id("chat_stop_btn");
    if (stopBtn) stopBtn.addEventListener("click", _onStop);

    const newBtn = $id("chat_new_btn");
    if (newBtn) newBtn.addEventListener("click", _onNewConversation);

    const input = $id("chat_input");
    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          _onSend();
        }
      });
      // Auto-resize
      input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 200) + "px";
      });
    }

    const tempSlider = $id("chat_temperature");
    const tempVal = $id("chat_temp_val");
    if (tempSlider && tempVal) {
      tempSlider.addEventListener("input", () => {
        tempVal.textContent = tempSlider.value;
      });
    }
  }

  // ---------- Send message ----------
  async function _onSend() {
    if (_streaming) return;

    // Require active project before chatting
    try { await requireProjectId("chat"); } catch(e) { return; }

    const input = $id("chat_input");
    const text = (input ? input.value : "").trim();
    if (!text) return;

    const sel = $id("chat_model");
    _model = sel ? sel.value : "";
    if (!_model) {
      showToast(_t("chat.select_model"), 'warning');
      return;
    }

    // Add user message
    _messages.push({ role: "user", content: text });
    _renderMessage("user", text);
    if (input) {
      input.value = "";
      input.style.height = "auto";
    }

    // Hide welcome
    const welcome = $id("chat_welcome");
    if (welcome) welcome.style.display = "none";

    // Create / update conversation
    if (!_activeConvId) {
      _activeConvId = "conv_" + Date.now();
      _conversations.unshift({
        id: _activeConvId,
        title: text.substring(0, 60),
        model: _model,
        messages: [],
        ts: Date.now(),
      });
    }

    // Save immediately so user message survives tab switch
    _saveActiveConversation();

    // Stream response via background job
    _streaming = true;
    _toggleButtons(true);

    const systemPrompt = ($id("chat_system_prompt") || {}).value || "";
    const temperature = parseFloat(($id("chat_temperature") || {}).value || "0.7");

    const assistantEl = _renderMessage("assistant", "");
    const contentEl = assistantEl.querySelector(".chat-msg-content");

    _abortCtrl = new AbortController();
    let fullContent = "";

    try {
      // 1. Start background job on server (goes through GPU RM queue)
      const sendResp = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conv_id: _activeConvId,
          model: _model,
          messages: _messages,
          system: systemPrompt,
          temperature: temperature,
        }),
      });
      const sendData = await sendResp.json();
      if (sendData.status !== "started" && sendData.status !== "queued") {
        throw new Error(sendData.error || "Failed to start chat job");
      }

      // Mark conversation as having a pending server job
      const conv = _conversations.find((c) => c.id === _activeConvId);
      if (conv) conv.pendingJobId = _activeConvId;
      _saveActiveConversation();

      // Show queued indicator
      if (sendData.status === "queued") {
        contentEl.innerHTML = '<span class="chat-typing">' + _t("chat.queued") + "</span>";
      }

      // 2. Follow SSE stream
      fullContent = await _followSSE(_activeConvId, contentEl, _abortCtrl.signal);

      // Save final assistant message
      _messages.push({ role: "assistant", content: fullContent });
      // Clear pending flag
      if (conv) delete conv.pendingJobId;
      _saveActiveConversation();

    } catch (e) {
      if (e.name === "AbortError") {
        // User pressed Stop or navigated away — server keeps generating
        // Save what we have so far; on reload we'll poll for the rest
        if (fullContent) {
          _messages.push({ role: "assistant", content: fullContent });
        }
        _saveActiveConversation();
      } else {
        contentEl.innerHTML = '<span class="chat-error">[ERROR] ' + _esc(String(e)) + "</span>";
        // Save partial on error too
        if (fullContent) {
          _messages.push({ role: "assistant", content: fullContent });
          const conv = _conversations.find((c) => c.id === _activeConvId);
          if (conv) delete conv.pendingJobId;
          _saveActiveConversation();
        }
      }
    } finally {
      _streaming = false;
      _abortCtrl = null;
      _toggleButtons(false);
    }
  }

  /**
   * Follow SSE stream from /api/chat/follow/{convId}.
   * Returns the accumulated full content string.
   */
  async function _followSSE(convId, contentEl, signal) {
    const response = await fetch(
      "/api/chat/follow/" + encodeURIComponent(convId),
      { signal }
    );

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullContent = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const obj = JSON.parse(line.slice(6));
          // Queued keepalive — show waiting indicator
          if (obj.queued) {
            contentEl.innerHTML = '<span class="chat-typing">' + _t("chat.queued") + "</span>";
            continue;
          }
          if (obj.chunk) {
            fullContent += obj.chunk;
            contentEl.innerHTML = _renderMarkdown(fullContent);
            _scrollToBottom();
          }
          if (obj.done) {
            // Check for server-side error
            if (obj.error && !fullContent) {
              contentEl.innerHTML = '<span class="chat-error">[ERROR] ' + _esc(obj.error) + "</span>";
            }
            return fullContent;
          }
        } catch (_) { /* skip parse errors */ }
      }
    }

    return fullContent;
  }

  function _onStop() {
    if (_abortCtrl) {
      _abortCtrl.abort();
    }
  }

  function _onNewConversation() {
    _messages = [];
    _activeConvId = null;
    try { localStorage.removeItem(STORAGE_KEY + "_active"); } catch (_) {}
    const msgs = $id("chat_messages");
    if (msgs) msgs.innerHTML = "";
    const welcome = $id("chat_welcome");
    if (welcome) welcome.style.display = "";
    _renderHistory();
  }

  // ---------- Rendering ----------
  function _renderMessage(role, content) {
    const container = $id("chat_messages");
    if (!container) return null;

    const div = document.createElement("div");
    div.className = "chat-msg chat-msg-" + role;

    const avatar = document.createElement("div");
    avatar.className = "chat-msg-avatar";
    avatar.textContent = role === "user" ? "\u{1F464}" : "\u{1F916}";

    const body = document.createElement("div");
    body.className = "chat-msg-body";

    const roleLabel = document.createElement("div");
    roleLabel.className = "chat-msg-role small";
    roleLabel.textContent = role === "user" ? _t("chat.you") : _model;

    const contentDiv = document.createElement("div");
    contentDiv.className = "chat-msg-content";
    contentDiv.innerHTML = content ? _renderMarkdown(content) : '<span class="chat-typing"></span>';

    body.appendChild(roleLabel);
    body.appendChild(contentDiv);
    div.appendChild(avatar);
    div.appendChild(body);
    container.appendChild(div);

    _scrollToBottom();
    return div;
  }

  function _scrollToBottom() {
    const container = $id("chat_messages");
    if (container) container.scrollTop = container.scrollHeight;
  }

  function _toggleButtons(streaming) {
    const sendBtn = $id("chat_send_btn");
    const stopBtn = $id("chat_stop_btn");
    if (sendBtn) sendBtn.style.display = streaming ? "none" : "";
    if (stopBtn) stopBtn.style.display = streaming ? "" : "none";
  }

  function _setStatus(text) {
    const el = $id("chat_status_line");
    if (el) el.textContent = text;
  }

  // ---------- Conversation persistence ----------
  function _loadConversations() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) _conversations = JSON.parse(raw);
    } catch (_) {
      _conversations = [];
    }
  }

  function _saveConversations() {
    try {
      // Keep max 50 conversations
      if (_conversations.length > 50) _conversations.length = 50;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(_conversations));
    } catch (_) { /* storage full */ }
  }

  function _saveActiveConversation() {
    if (!_activeConvId) return;
    const conv = _conversations.find((c) => c.id === _activeConvId);
    if (conv) {
      conv.messages = _messages.slice();
      conv.model = _model;
      conv.ts = Date.now();
    }
    _saveConversations();
    // Persist active conversation id so it survives page navigation
    try { localStorage.setItem(STORAGE_KEY + "_active", _activeConvId); } catch (_) {}
    _renderHistory();
  }

  async function _restoreLastActive() {
    try {
      const lastId = localStorage.getItem(STORAGE_KEY + "_active");
      if (lastId && _conversations.find((c) => c.id === lastId)) {
        _loadConversation(lastId);
        // Check if there's a pending server-side job to recover
        await _recoverPendingJob(lastId);
      }
    } catch (_) {}
  }

  /**
   * If a conversation has a pendingJobId, poll the server for the completed response.
   * This recovers from tab switches / page reloads.
   */
  async function _recoverPendingJob(convId) {
    const conv = _conversations.find((c) => c.id === convId);
    if (!conv || !conv.pendingJobId) return;

    try {
      const r = await fetch("/api/chat/result/" + encodeURIComponent(conv.pendingJobId));
      const data = await r.json();

      if (data.status === "not_found") {
        delete conv.pendingJobId;
        _saveActiveConversation();
        return;
      }

      if (data.status === "done" || data.status === "error") {
        // Job completed while we were away — update messages
        const content = data.content || "";
        if (content) {
          const lastMsg = _messages[_messages.length - 1];
          if (lastMsg && lastMsg.role === "assistant") {
            lastMsg.content = content;
          } else {
            _messages.push({ role: "assistant", content: content });
          }
          _activeConvId = convId;
          _reRenderMessages();
        }
        delete conv.pendingJobId;
        _saveActiveConversation();
        return;
      }

      if (data.status === "running" || data.status === "queued") {
        // Job still running or queued — reconnect SSE to follow it live
        _streaming = true;
        _toggleButtons(true);

        // Show what we have so far
        let fullContent = data.content || "";
        const assistantEl = _renderMessage("assistant", fullContent || "");
        const contentEl = assistantEl.querySelector(".chat-msg-content");
        if (fullContent) {
          contentEl.innerHTML = _renderMarkdown(fullContent);
        } else if (data.status === "queued") {
          contentEl.innerHTML = '<span class="chat-typing">' + _t("chat.queued") + "</span>";
        }

        _abortCtrl = new AbortController();

        try {
          fullContent = await _followSSE(conv.pendingJobId, contentEl, _abortCtrl.signal);

          // Done — merge full content
          const lastMsg = _messages[_messages.length - 1];
          if (lastMsg && lastMsg.role === "assistant") {
            lastMsg.content = fullContent;
          } else {
            _messages.push({ role: "assistant", content: fullContent });
          }
          delete conv.pendingJobId;
          _saveActiveConversation();
        } catch (e) {
          // Disconnected again — save partial
          if (fullContent) {
            const lastMsg = _messages[_messages.length - 1];
            if (lastMsg && lastMsg.role === "assistant") {
              lastMsg.content = fullContent;
            } else {
              _messages.push({ role: "assistant", content: fullContent });
            }
            _saveActiveConversation();
          }
        } finally {
          _streaming = false;
          _abortCtrl = null;
          _toggleButtons(false);
        }
      }
    } catch (e) {
      // Network error — keep pendingJobId for next reload
      console.warn("Chat recovery failed:", e);
    }
  }

  function _reRenderMessages() {
    const container = $id("chat_messages");
    if (container) container.innerHTML = "";
    const welcome = $id("chat_welcome");
    if (welcome) welcome.style.display = _messages.length ? "none" : "";
    for (const m of _messages) {
      _renderMessage(m.role, m.content);
    }
  }

  function _renderHistory() {
    const list = $id("chat_history_list");
    if (!list) return;

    if (_conversations.length === 0) {
      list.innerHTML = '<div class="small" data-i18n="chat.no_conversations">' + _t("chat.no_conversations") + "</div>";
      return;
    }

    list.innerHTML = "";
    for (const conv of _conversations) {
      const item = document.createElement("div");
      item.className = "chat-history-item" + (conv.id === _activeConvId ? " active" : "");

      const title = document.createElement("div");
      title.className = "chat-history-title";
      title.textContent = conv.title || _t("chat.untitled");
      title.addEventListener("click", () => _loadConversation(conv.id));

      const meta = document.createElement("div");
      meta.className = "chat-history-meta small";
      meta.textContent = conv.model + " \u00B7 " + new Date(conv.ts).toLocaleString();

      const delBtn = document.createElement("button");
      delBtn.className = "chat-history-del";
      delBtn.textContent = "\u00D7";
      delBtn.title = _t("chat.delete");
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        _deleteConversation(conv.id);
      });

      item.appendChild(title);
      item.appendChild(meta);
      item.appendChild(delBtn);
      list.appendChild(item);
    }
  }

  function _loadConversation(id) {
    const conv = _conversations.find((c) => c.id === id);
    if (!conv) return;

    _activeConvId = id;
    _messages = (conv.messages || []).slice();
    _model = conv.model || "";

    // Update model selector
    const sel = $id("chat_model");
    if (sel && _model) sel.value = _model;

    _reRenderMessages();
    _renderHistory();
  }

  function _deleteConversation(id) {
    _conversations = _conversations.filter((c) => c.id !== id);
    if (_activeConvId === id) {
      _onNewConversation();
    }
    _saveConversations();
    try { localStorage.removeItem(STORAGE_KEY + "_active"); } catch (_) {}
    _renderHistory();
  }

  // ---------- Helpers ----------
  function _esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function _renderMarkdown(text) {
    // Simple markdown: bold, italic, code blocks, inline code, line breaks
    let html = _esc(text);
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="chat-code"><code>$2</code></pre>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // Italic
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
    // Line breaks
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function _t(key) {
    // i18n helper: use global i18n if available, else return key
    if (typeof i18n === "function") return i18n(key);
    if (typeof window._i18n_data === "object" && window._i18n_data[key]) return window._i18n_data[key];
    // Fallback defaults
    const defaults = {
      "chat.title": "Chat LLM",
      "chat.ready": "Gotowy",
      "chat.ollama_offline": "Ollama offline",
      "chat.no_models": "Brak modeli",
      "chat.load_error": "B\u0142\u0105d \u0142adowania",
      "chat.select_model": "Wybierz model.",
      "chat.you": "Ty",
      "chat.no_conversations": "Brak rozm\u00F3w",
      "chat.untitled": "Bez tytu\u0142u",
      "chat.delete": "Usu\u0144",
      "chat.queued": "\u23F3 W kolejce GPU\u2026",
    };
    return defaults[key] || key;
  }

  // Save conversation on page unload (tab switch / close) so nothing is lost
  window.addEventListener("beforeunload", () => {
    if (_activeConvId) {
      _saveActiveConversation();
    }
  });

  // Expose
  window.initChat = initChat;
})();
