/**
 * analyst_notes.js — Unified analyst notes system for GSM & AML analysis.
 *
 * Provides:
 *  - Panel toggle (collapse / expand)
 *  - Global note (auto-save)
 *  - Item notes (add / edit / delete) with tags & navigation
 *  - Ctrl+M shortcut to add note from context
 *  - Modal editor
 *
 * Usage:
 *   const mgr = new AnalystNotesManager({ mode: "gsm"|"aml", projectId, ... });
 *   await mgr.init();
 */

/* global aiIcon */
/* eslint-disable no-unused-vars */

"use strict";

// ────────── Tag definitions ──────────
const ANALYST_TAGS = {
  neutral:    { label: "Neutralny",  labelEn: "Neutral",    color: "#60a5fa", bg: "rgba(96,165,250,.12)" },
  legitimate: { label: "Poprawny",   labelEn: "Legitimate", color: "#15803d", bg: "rgba(21,128,61,.10)" },
  suspicious: { label: "Podejrzany", labelEn: "Suspicious", color: "#dc2626", bg: "rgba(220,38,38,.10)" },
  monitoring: { label: "Obserwacja", labelEn: "Monitoring", color: "#ea580c", bg: "rgba(234,88,12,.10)" },
  custom1:    { label: "Własny 1",   labelEn: "Custom 1",   color: "#ffff00", bg: "rgba(255,255,0,.15)", custom: true },
  custom2:    { label: "Własny 2",   labelEn: "Custom 2",   color: "#7fff00", bg: "rgba(127,255,0,.15)", custom: true },
  custom3:    { label: "Własny 3",   labelEn: "Custom 3",   color: "#b8860b", bg: "rgba(184,134,11,.15)", custom: true },
  custom4:    { label: "Własny 4",   labelEn: "Custom 4",   color: "#6366f1", bg: "rgba(99,102,241,.12)", custom: true },
};

// ────────── Ref-type → icon mapping ──────────
const _REF_ICONS = {
  gsm_record:         "/static/icons/komunikacja/phone.svg",
  gsm_heatmap:        "/static/icons/wizualizacja/chart_bar.svg",
  gsm_bts:            "/static/icons/inne/pin.svg",
  gsm_contact:        "/static/icons/uzytkownicy/user.svg",
  gsm_anomaly:        "/static/icons/status/warning.svg",
  gsm_device:         "/static/icons/komunikacja/phone.svg",
  gsm_special_number: "/static/icons/komunikacja/phone.svg",
  aml_transaction:    "/static/icons/dokumenty/doc_txt.svg",
  aml_account:        "/static/icons/bezpieczenstwo/shield.svg",
  aml_alert:          "/static/icons/status/warning.svg",
  aml_graph_node:     "/static/icons/wizualizacja/chart_bar.svg",
  crypto_transaction: "/static/icons/dokumenty/doc_txt.svg",
  crypto_anomaly:     "/static/icons/status/warning.svg",
  crypto_wallet:      "/static/icons/bezpieczenstwo/shield.svg",
  crypto_token:       "/static/icons/inne/pin.svg",
  // Transcription & Diarization
  tr_block:           "/static/icons/dokumenty/doc_txt.svg",
  di_block:           "/static/icons/dokumenty/doc_txt.svg",
};

// ────────── Helper: note icon path (filled vs empty) ──────────
function _noteIconSrc(hasNote) {
  return hasNote ? "/static/icons/pliki/notes_filled.svg" : "/static/icons/pliki/notes.svg";
}

// ────────── Helper: short unique ID ──────────
function _noteId() {
  return "nm_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6);
}

// ────────── Helper: truncate label ──────────
function _trunc(s, max) {
  if (!s) return "";
  return s.length > max ? s.slice(0, max) + "\u2026" : s;
}

// ────────── Helper: escape HTML ──────────
function _esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}


class AnalystNotesManager {

  /**
   * @param {Object} opts
   * @param {string} opts.mode          - "gsm" or "aml"
   * @param {string} opts.projectId     - project ID
   * @param {Function} [opts.onNavigate]- callback(ref) when "Przejdź" is clicked
   * @param {Function} [opts.getContext]- callback() → {label, icon, ref} for Ctrl+M context
   */
  constructor(opts) {
    this.mode = opts.mode;             // "gsm" | "aml"
    this.projectId = opts.projectId;
    this.onNavigate = opts.onNavigate || null;
    this.getContext = opts.getContext || null;
    this.onNoteChange = opts.onNoteChange || null;

    this.notes = { global: "", items: [], customTagNames: {} };
    this._saveTimer = null;
    this._initialized = false;

    // DOM references (set in init)
    this._panel = null;
    this._toggleBtn = null;
    this._collapseBtn = null;
    this._globalTa = null;
    this._notesList = null;
    this._countBadge = null;
    this._tagFilter = null;
  }

  // ────────── Initialization ──────────

  async init() {
    if (this._initialized) return;
    this._initialized = true;

    const m = this.mode;
    this._panel       = document.getElementById(`${m}_analyst_panel`);
    this._toggleBtn   = document.getElementById(`${m}_panel_toggle`);
    this._collapseBtn = document.getElementById(`${m}_panel_collapse`);
    this._globalTa    = document.getElementById(`${m}_analyst_global_note`);
    this._notesList   = document.getElementById(`${m}_notes_list`);
    this._countBadge  = document.getElementById(`${m}_notes_count`);
    this._tagFilter   = document.getElementById(`${m}_tag_filter_select`);

    if (!this._panel) return;

    // Restore collapse state
    const collapsed = localStorage.getItem(`aistate_analyst_panel_${m}`) !== "open";
    if (collapsed) {
      this._panel.classList.add("collapsed");
    } else {
      this._panel.classList.remove("collapsed");
    }

    // Toggle events
    this._toggleBtn?.addEventListener("click", () => this._expand());
    this._collapseBtn?.addEventListener("click", () => this._collapse());

    // Global note auto-save
    this._globalTa?.addEventListener("input", () => {
      this.notes.global = this._globalTa.value;
      this._scheduleSave();
      if (this.onNoteChange) this.onNoteChange(null);
    });

    // Tag filter
    this._tagFilter?.addEventListener("change", () => this._renderItems());

    // Ctrl+M shortcut
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "m") {
        // Only handle if our tab is active
        const tab = document.querySelector(".analysis-tab.active");
        if (!tab) return;
        const activeMode = tab.getAttribute("data-tab");
        if (activeMode !== this.mode) return;

        e.preventDefault();
        e.stopPropagation();
        this.openNoteModal();
      }
    });

    // Modal events (shared — only bind once)
    if (!window._analystNoteModalBound) {
      window._analystNoteModalBound = true;
      this._bindModalEvents();
    }

    // Load notes from server
    await this._load();
  }

  // ────────── Panel collapse/expand ──────────

  _expand() {
    this._panel.classList.remove("collapsed");
    localStorage.setItem(`aistate_analyst_panel_${this.mode}`, "open");
  }

  _collapse() {
    this._panel.classList.add("collapsed");
    localStorage.setItem(`aistate_analyst_panel_${this.mode}`, "collapsed");
  }

  // ────────── Load & Save ──────────

  async _load() {
    if (!this.projectId) return;
    try {
      const r = await fetch(`/api/projects/${this.projectId}/notes/${this.mode}`);
      if (r.ok) {
        const data = await r.json();
        this.notes.global = data.global || "";
        this.notes.items = Array.isArray(data.items) ? data.items : [];
        this.notes.customTagNames = data.customTagNames || {};
        // Apply saved custom tag names to ANALYST_TAGS
        for (const [key, name] of Object.entries(this.notes.customTagNames)) {
          if (ANALYST_TAGS[key] && ANALYST_TAGS[key].custom) {
            ANALYST_TAGS[key].label = name;
          }
        }
        this._syncCustomTagUI();
      }
    } catch (e) {
      console.warn("AnalystNotes: load error", e);
    }
    if (this._globalTa) this._globalTa.value = this.notes.global;
    this._renderItems();
    // Notify after initial load so icons update
    if (this.onNoteChange && (this.notes.global || this.notes.items.length)) {
      this.onNoteChange(null);
    }
  }

  _scheduleSave() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this._save(), 1000);
  }

  async _save() {
    if (!this.projectId) return;
    try {
      await fetch(`/api/projects/${this.projectId}/notes/${this.mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: this.notes }),
      });
    } catch (e) {
      console.warn("AnalystNotes: save error", e);
    }
  }

  // ────────── Render item notes list ──────────

  _renderItems() {
    if (!this._notesList) return;

    const filterTag = this._tagFilter?.value || "";
    let items = this.notes.items;
    if (filterTag) {
      items = items.filter(it => it.tags && it.tags.includes(filterTag));
    }

    // Update count badge
    if (this._countBadge) {
      this._countBadge.textContent = String(this.notes.items.length);
    }

    if (!items.length) {
      this._notesList.innerHTML = `<div class="analyst-panel-empty">${
        this.notes.items.length ? "Brak notatek z wybranym tagiem." : "Brak notatek. Użyj Ctrl+M aby dodać."
      }</div>`;
      return;
    }

    let html = "";
    for (const it of items) {
      const iconSrc = _REF_ICONS[it.ref?.type] || "/static/icons/pliki/notes.svg";
      const tagsHtml = (it.tags || []).map(t => {
        const td = ANALYST_TAGS[t];
        if (!td) return "";
        const lbl = (td.custom && this.notes.customTagNames[t]) ? this.notes.customTagNames[t] : td.label;
        return `<span class="analyst-tag-badge" data-tag="${t}">${_esc(lbl)}</span>`;
      }).join("");

      html += `<div class="analyst-note-item" data-note-id="${_esc(it.id)}">
        <div class="analyst-note-item-header">
          <img src="${iconSrc}" alt="" width="14" height="14" draggable="false">
          <span class="analyst-note-item-label" title="${_esc(it.label)}">${_esc(_trunc(it.label, 50))}</span>
        </div>
        ${it.text ? `<div class="analyst-note-item-preview">${_esc(_trunc(it.text, 80))}</div>` : ""}
        <div class="analyst-note-item-footer">
          ${tagsHtml}
          <div class="analyst-note-item-actions">
            ${it.ref?.type ? `<button data-action="goto" title="Przejdź do elementu">&#8595; Przejdź</button>` : ""}
            <button data-action="edit" title="Edytuj">Edytuj</button>
            <button data-action="delete" class="danger" title="Usuń">Usuń</button>
          </div>
        </div>
      </div>`;
    }
    this._notesList.innerHTML = html;

    // Bind item actions
    this._notesList.querySelectorAll(".analyst-note-item").forEach(el => {
      const noteId = el.getAttribute("data-note-id");
      el.querySelectorAll("button[data-action]").forEach(btn => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const action = btn.getAttribute("data-action");
          if (action === "edit") this._editNote(noteId);
          else if (action === "delete") this._deleteNote(noteId);
          else if (action === "goto") this._navigateTo(noteId);
        });
      });
      // Click on item body → edit
      el.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        this._editNote(noteId);
      });
    });
  }

  // ────────── Custom tag name sync ──────────

  /** Sync custom tag names to modal buttons & filter dropdowns */
  _syncCustomTagUI() {
    for (const [key, def] of Object.entries(ANALYST_TAGS)) {
      if (!def.custom) continue;
      const name = this.notes.customTagNames[key] || def.label;
      // Update modal button label
      const btn = document.querySelector(`#analyst_note_tags .analyst-tag-btn[data-tag="${key}"] .analyst-tag-label`);
      if (btn) btn.textContent = name;
      // Update filter dropdown options
      document.querySelectorAll(`select option[value="${key}"]`).forEach(opt => {
        opt.textContent = name;
      });
    }
  }

  /** Rename a custom tag and persist */
  renameCustomTag(tagKey, newName) {
    if (!ANALYST_TAGS[tagKey] || !ANALYST_TAGS[tagKey].custom) return;
    newName = (newName || "").trim();
    if (!newName) newName = ANALYST_TAGS[tagKey].labelEn || tagKey;
    this.notes.customTagNames[tagKey] = newName;
    ANALYST_TAGS[tagKey].label = newName;
    this._syncCustomTagUI();
    this._renderItems(); // re-render badges with new name
    this._scheduleSave();
  }

  // ────────── Note CRUD ──────────

  addNote(label, icon, text, tags, ref) {
    const item = {
      id: _noteId(),
      label: label || "",
      icon: icon || "",
      text: text || "",
      tags: tags || [],
      ref: ref || {},
      created: new Date().toISOString(),
      modified: new Date().toISOString(),
    };
    this.notes.items.push(item);
    this._renderItems();
    this._scheduleSave();
    if (this.onNoteChange) this.onNoteChange(item);
    return item;
  }

  updateNote(noteId, text, tags) {
    const item = this.notes.items.find(it => it.id === noteId);
    if (!item) return;
    item.text = text || "";
    item.tags = tags || [];
    item.modified = new Date().toISOString();
    this._renderItems();
    this._scheduleSave();
    if (this.onNoteChange) this.onNoteChange(item);
  }

  _deleteNote(noteId) {
    const deleted = this.notes.items.find(it => it.id === noteId);
    this.notes.items = this.notes.items.filter(it => it.id !== noteId);
    this._renderItems();
    this._scheduleSave();
    if (this.onNoteChange) this.onNoteChange(deleted || null);
  }

  _editNote(noteId) {
    const item = this.notes.items.find(it => it.id === noteId);
    if (!item) return;
    this.openNoteModal(item);
  }

  _navigateTo(noteId) {
    const item = this.notes.items.find(it => it.id === noteId);
    if (!item || !item.ref || !this.onNavigate) return;
    this.onNavigate(item.ref);
  }

  // Find note by ref
  findNoteByRef(refType, refKey, refValue) {
    return this.notes.items.find(it =>
      it.ref?.type === refType && it.ref?.[refKey] === refValue
    );
  }

  // ────────── Modal ──────────

  openNoteModal(existingItem) {
    const overlay = document.getElementById("analyst_note_overlay");
    if (!overlay) return;

    // Sync custom tag names in modal buttons
    this._syncCustomTagUI();

    // Store current manager on overlay for modal events
    overlay._manager = this;
    overlay._editingId = existingItem?.id || null;

    const titleEl = document.getElementById("analyst_note_modal_title");
    const labelEl = document.getElementById("analyst_note_element_label");
    const textEl  = document.getElementById("analyst_note_text");
    const deleteBtn = document.getElementById("analyst_note_delete");

    if (existingItem) {
      titleEl.textContent = "Edytuj notatkę";
      labelEl.textContent = existingItem.label || "";
      textEl.value = existingItem.text || "";
      deleteBtn.style.display = "";

      // Set active tags
      document.querySelectorAll("#analyst_note_tags .analyst-tag-btn").forEach(btn => {
        const tag = btn.getAttribute("data-tag");
        btn.classList.toggle("active", (existingItem.tags || []).includes(tag));
      });
    } else {
      titleEl.textContent = "Nowa notatka";
      textEl.value = "";
      deleteBtn.style.display = "none";

      // Clear tags
      document.querySelectorAll("#analyst_note_tags .analyst-tag-btn").forEach(btn => {
        btn.classList.remove("active");
      });

      // Get context from active analysis
      let ctx = null;
      if (this.getContext) {
        try { ctx = this.getContext(); } catch (e) { /* ignore */ }
      }
      if (ctx) {
        labelEl.textContent = ctx.label || "";
        overlay._pendingRef = ctx.ref || {};
        overlay._pendingIcon = ctx.icon || "";
        overlay._pendingLabel = ctx.label || "";
      } else {
        labelEl.textContent = "";
        overlay._pendingRef = {};
        overlay._pendingIcon = "";
        overlay._pendingLabel = "";
      }
    }

    overlay.style.display = "flex";
    textEl.focus();
  }

  _bindModalEvents() {
    const overlay = document.getElementById("analyst_note_overlay");
    if (!overlay) return;

    const close = () => { overlay.style.display = "none"; };

    // Close button
    document.getElementById("analyst_note_close")?.addEventListener("click", close);
    document.getElementById("analyst_note_cancel")?.addEventListener("click", close);

    // Backdrop click
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });

    // Tag toggle buttons
    document.querySelectorAll("#analyst_note_tags .analyst-tag-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        // Don't toggle if clicking on edit input
        if (e.target.classList.contains("analyst-tag-edit-input")) return;
        btn.classList.toggle("active");
      });
    });

    // Inline custom tag name editing — double-click on label to rename
    document.querySelectorAll("#analyst_note_tags .analyst-tag-label[data-editable]").forEach(lbl => {
      lbl.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        e.preventDefault();
        const tagKey = lbl.closest(".analyst-tag-btn").getAttribute("data-tag");
        const currentName = lbl.textContent;
        // Replace label with input
        const input = document.createElement("input");
        input.type = "text";
        input.className = "analyst-tag-edit-input";
        input.value = currentName;
        input.style.width = Math.max(60, currentName.length * 7 + 16) + "px";
        lbl.style.display = "none";
        lbl.parentNode.insertBefore(input, lbl.nextSibling);
        input.focus();
        input.select();

        const commit = () => {
          const val = input.value.trim();
          if (val && val !== currentName) {
            lbl.textContent = val;
            // Find the active manager and rename
            const overlay = document.getElementById("analyst_note_overlay");
            const mgr = overlay?._manager;
            if (mgr) mgr.renameCustomTag(tagKey, val);
          }
          lbl.style.display = "";
          if (input.parentNode) input.remove();
        };
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", (ke) => {
          if (ke.key === "Enter") { ke.preventDefault(); input.blur(); }
          if (ke.key === "Escape") { input.value = currentName; input.blur(); }
        });
      });
    });

    // Save
    document.getElementById("analyst_note_save")?.addEventListener("click", () => {
      this._modalSave(overlay);
    });

    // Delete
    document.getElementById("analyst_note_delete")?.addEventListener("click", () => {
      const mgr = overlay._manager;
      if (mgr && overlay._editingId) {
        mgr._deleteNote(overlay._editingId);
      }
      close();
    });

    // Ctrl+Enter to save
    document.getElementById("analyst_note_text")?.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        this._modalSave(overlay);
      }
    });

    // Escape to close
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.style.display !== "none") {
        close();
      }
    });
  }

  _modalSave(overlay) {
    const mgr = overlay._manager;
    if (!mgr) return;

    const text = document.getElementById("analyst_note_text")?.value?.trim() || "";
    const tags = [];
    document.querySelectorAll("#analyst_note_tags .analyst-tag-btn.active").forEach(btn => {
      tags.push(btn.getAttribute("data-tag"));
    });

    // Must have text or at least one tag
    if (!text && !tags.length) return;

    if (overlay._editingId) {
      mgr.updateNote(overlay._editingId, text, tags);
    } else {
      mgr.addNote(
        overlay._pendingLabel || "",
        overlay._pendingIcon || "",
        text,
        tags,
        overlay._pendingRef || {}
      );
    }

    overlay.style.display = "none";
  }

  // ────────── Public: check if element has note (for marker icons) ──────────

  hasNote(refType, refKey, refValue) {
    return this.notes.items.some(it =>
      it.ref?.type === refType && it.ref?.[refKey] === refValue
    );
  }

  getNoteForRef(refType, refKey, refValue) {
    return this.notes.items.find(it =>
      it.ref?.type === refType && it.ref?.[refKey] === refValue
    ) || null;
  }

  // ────────── Public: open note for specific element ──────────

  openNoteForElement(label, icon, ref) {
    // Check if note already exists for this ref
    const existing = this.notes.items.find(it =>
      it.ref?.type === ref?.type &&
      JSON.stringify(it.ref) === JSON.stringify(ref)
    );

    if (existing) {
      this.openNoteModal(existing);
    } else {
      const overlay = document.getElementById("analyst_note_overlay");
      if (!overlay) return;
      overlay._manager = this;
      overlay._editingId = null;
      overlay._pendingRef = ref || {};
      overlay._pendingIcon = icon || "";
      overlay._pendingLabel = label || "";

      const titleEl = document.getElementById("analyst_note_modal_title");
      const labelEl = document.getElementById("analyst_note_element_label");
      const textEl  = document.getElementById("analyst_note_text");
      const deleteBtn = document.getElementById("analyst_note_delete");

      titleEl.textContent = "Nowa notatka";
      labelEl.textContent = label || "";
      textEl.value = "";
      deleteBtn.style.display = "none";

      document.querySelectorAll("#analyst_note_tags .analyst-tag-btn").forEach(btn => {
        btn.classList.remove("active");
      });

      overlay.style.display = "flex";
      textEl.focus();
    }
  }

  // ────────── Public: update project ID (when project changes) ──────────

  async setProject(projectId) {
    this.projectId = projectId;
    this.notes = { global: "", items: [], customTagNames: {} };
    if (this._globalTa) this._globalTa.value = "";
    this._renderItems();
    if (projectId) {
      await this._load();
    }
  }
}

// Export for use in gsm.js and aml.js
window.AnalystNotesManager = AnalystNotesManager;
window.ANALYST_TAGS = ANALYST_TAGS;
