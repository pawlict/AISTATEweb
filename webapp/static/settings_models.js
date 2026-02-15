/* AISTATEweb – Model settings (Ollama)
 *
 * Renders model selectors in Settings tab and persists global selection.
 * Supports groups:
 *   quick, deep, vision, translation, financial, specialized
 */

(function(){
  "use strict";

  const $ = (id) => document.getElementById(id);

  async function http(url, opts){
    const r = await fetch(url, opts || {});
    if (!r.ok){
      let msg = "";
      try{ msg = (await r.json())?.detail || ""; }catch{ msg = await r.text(); }
      throw new Error(msg || ("HTTP " + r.status));
    }
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("application/json")) return await r.json();
    return await r.text();
  }

  function esc(s){
    return String(s ?? "").replace(/[&<>"']/g, (c)=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function tr(key, fallback){
    try{
      const v = (typeof window.t === "function") ? window.t(key) : null;
      return v || fallback || key;
    }catch{
      return fallback || key;
    }
  }

  function notify(msg, kind){
    if (typeof window.notify === "function") return window.notify(msg, kind);
    console[(kind === "error") ? "error" : "log"](msg);
  }

  const GROUPS = ["quick","deep","vision","translation","financial","specialized"];
  const UI = {
    quick: {
      select: "llm_quick_select",
      installBtn: "llm_quick_install_btn",
      warn: "llm_quick_warn",
      infoName: "llm_quick_info_name",
      infoBody: "llm_quick_info_body",
      infoWarning: "llm_quick_info_warning",
    },
    deep: {
      select: "llm_deep_select",
      installBtn: "llm_deep_install_btn",
      warn: "llm_deep_warn",
      infoName: "llm_deep_info_name",
      infoBody: "llm_deep_info_body",
      infoWarning: "llm_deep_info_warning",
    },
    vision: {
      select: "llm_vision_select",
      installBtn: "llm_vision_install_btn",
      warn: "llm_vision_warn",
      infoName: "llm_vision_info_name",
      infoBody: "llm_vision_info_body",
      infoWarning: "llm_vision_info_warning",
    },
    translation: {
      select: "llm_translation_select",
      installBtn: "llm_translation_install_btn",
      warn: "llm_translation_warn",
      infoName: "llm_translation_info_name",
      infoBody: "llm_translation_info_body",
      infoWarning: "llm_translation_info_warning",
    },
    financial: {
      select: "llm_financial_select",
      installBtn: "llm_financial_install_btn",
      warn: "llm_financial_warn",
      infoName: "llm_financial_info_name",
      infoBody: "llm_financial_info_body",
      infoWarning: "llm_financial_info_warning",
    },
    specialized: {
      select: "llm_specialized_select",
      installBtn: "llm_specialized_install_btn",
      warn: "llm_specialized_warn",
      infoName: "llm_specialized_info_name",
      infoBody: "llm_specialized_info_body",
      infoWarning: "llm_specialized_info_warning",
    },
  };

  function analysisTimeSummary(perf, group){
    if (!perf) return "";
    const at = perf.analysis_time;
    if (!at) return "";
    if (typeof at === "string") return at;
    if (typeof at !== "object") return "";
    if (at[group]) return String(at[group]);

    // Fallback: build a short summary from known keys
    const keysPref = {
      quick: ["quick","instant","summary"],
      deep: ["deep","protocol","complex","structured","fast_deep"],
      vision: ["ocr","document","invoice","tables","complex_tables"],
      translation: ["translation","cyrillic","premium"],
      financial: ["financial","balance","balance_check","anomaly","extraction","scoring"],
      specialized: ["legal","contract","reasoning","complex"],
    };
    const order = keysPref[group] || Object.keys(at);
    const parts = [];
    for (const k of order){
      if (at[k]) parts.push(`${k}: ${at[k]}`);
      if (parts.length >= 3) break;
    }
    return parts.join(" • ");
  }

  function setInfo(group, info){
    const cfg = UI[group];
    if (!cfg) return;
    const nameEl = $(cfg.infoName);
    const bodyEl = $(cfg.infoBody);
    const warnEl = $(cfg.infoWarning);
    if (!nameEl || !bodyEl) return;

    if (!info){
      nameEl.textContent = "—";
      bodyEl.textContent = "";
      if (warnEl){ warnEl.style.display = "none"; warnEl.textContent = ""; }
      return;
    }

    const hw = info.hardware || {};
    const perf = info.performance || {};
    const at = analysisTimeSummary(perf, group);
    const quality = perf.quality_stars;
    const plq = perf.polish_quality_stars;
    const cases = Array.isArray(info.use_cases) ? info.use_cases : [];

    nameEl.textContent = info.display_name || info.id || "";

    const lines = [];
    lines.push(`<div class="llm-mini-grid">`);
    lines.push(`  <div><b>${esc(tr("settings.llm_hw_vram","VRAM"))}:</b> ${esc(hw.vram || "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_hw_min_gpu","Min GPU"))}:</b> ${esc(hw.min_gpu || "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_hw_opt_gpu","Optimal GPU"))}:</b> ${esc(hw.optimal_gpu || "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_hw_ram","RAM"))}:</b> ${esc(hw.ram || "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_perf_speed","Speed"))}:</b> ${esc(perf.speed_tokens_sec ? (perf.speed_tokens_sec + " tok/s") : "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_perf_time","Analysis time"))}:</b> ${esc(at || "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_perf_quality","Quality"))}:</b> ${esc(quality != null ? ("★".repeat(Number(quality)) || String(quality)) : "?")}</div>`);
    lines.push(`  <div><b>${esc(tr("settings.llm_perf_pl","Polish quality"))}:</b> ${esc(plq != null ? ("★".repeat(Number(plq)) || String(plq)) : "?")}</div>`);
    lines.push(`</div>`);

    if (info.requires_multi_gpu){
      lines.push(`<div class="llm-mini-rec">${aiIcon('warning',12)} Multi-GPU required</div>`);
    }

    if (cases.length){
      lines.push(`<div class="llm-mini-rec"><b>${esc(tr("settings.llm_use_cases","Use cases"))}:</b></div>`);
      lines.push(`<ul class="llm-mini-cases">`);
      for (const c of cases.slice(0, 10)){
        lines.push(`<li class="llm-mini-case">${esc(c)}</li>`);
      }
      lines.push(`</ul>`);
    }

    if (info.recommendation){
      lines.push(`<div class="llm-mini-rec"><b>${esc(tr("settings.llm_recommended","Recommended"))}:</b> ${esc(info.recommendation)}</div>`);
    }

    bodyEl.innerHTML = lines.join("\n");

    const w = String(info.warning || "").trim();
    if (warnEl){
      if (w){
        warnEl.style.display = "block";
        warnEl.textContent = w;
      }else{
        warnEl.style.display = "none";
        warnEl.textContent = "";
      }
    }
  }

  function setStatusDot(online){
    const dot = $("llm_status_dot");
    if (!dot) return;
    dot.classList.toggle("online", !!online);
    dot.classList.toggle("offline", !online);
  }

  const State = {
    online: false,
    list: {
      quick: [],
      deep: [],
      vision: [],
      translation: [],
      financial: [],
      specialized: [],
    },
    custom: {
      quick: [],
      deep: [],
      vision: [],
      translation: [],
      financial: [],
      specialized: [],
    },
    installed: new Map(),
    selected: {
      quick: null,
      deep: null,
      vision: null,
      translation: null,
      financial: null,
      specialized: null,
    },
    defaults: {},
    _saveTimer: null,

    async init(){
      const btn = $("llm_refresh_btn");
      if (btn) btn.addEventListener("click", () => this.refresh(true));

      // Hook install buttons
      for (const g of GROUPS){
        const cfg = UI[g];
        if (!cfg) continue;
        const b = $(cfg.installBtn);
        if (b) b.addEventListener("click", () => this.install(g));
      }

      this.bindCustomUI();

      await this.refresh(true);
    },

    _customBound: false,

    bindCustomUI(){
      if (this._customBound) return;
      this._customBound = true;

      const addBtn = $("llm_custom_add_btn");
      const input = $("llm_custom_model_id");
      const groupSel = $("llm_custom_group");
      const listEl = $("llm_custom_list");

      const runAdd = async () => {
        const group = groupSel ? (groupSel.value || "deep") : "deep";
        const modelId = input ? String(input.value || "").trim() : "";
        const msgEl = $("llm_custom_msg");
        if (!modelId){
          if (msgEl) msgEl.textContent = tr("settings.llm_custom_missing","Podaj nazwę modelu.");
          return;
        }
        try{
          if (msgEl) msgEl.textContent = tr("settings.llm_custom_adding","Dodaję…");
          await http("/api/models/custom", {
            method: "POST",
            headers: {"Content-Type":"application/json"},
            body: JSON.stringify({ group, model_id: modelId })
          });

          if (input) input.value = "";
          if (msgEl) msgEl.innerHTML = aiIcon('success',12) + ' ' + tr("settings.llm_custom_added","Dodano");

          // Refresh selectors so the new model appears, then auto-select it for the chosen group
          await this.refresh(false);

          const cfg = UI[group];
          const sel = cfg ? $(cfg.select) : null;
          this.selected[group] = modelId;
          if (sel) sel.value = modelId;

          this.updateInstallUI(group);
          this.updateInfo(group);
          this.scheduleSave();
          this.renderCustomList();
        }catch(e){
          const msgEl2 = $("llm_custom_msg");
          if (msgEl2) msgEl2.textContent = (tr("settings.llm_custom_error","Błąd") + ": " + (e?.message || e));
        }
      };

      if (addBtn) addBtn.addEventListener("click", (ev) => { ev.preventDefault(); runAdd(); });
      if (input) input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter"){
          ev.preventDefault();
          runAdd();
        }
      });

      // Remove (event delegation)
      if (listEl){
        listEl.addEventListener("click", async (ev) => {
          const t = ev.target;
          if (!t) return;
          const btn = t.closest ? t.closest("button[data-action='remove-custom']") : null;
          if (!btn) return;
          ev.preventDefault();
          const group = btn.getAttribute("data-group") || "deep";
          const modelId = decodeURIComponent(btn.getAttribute("data-model") || "");
          if (!modelId) return;

          try{
            await http("/api/models/custom/remove", {
              method: "POST",
              headers: {"Content-Type":"application/json"},
              body: JSON.stringify({ group, model_id: modelId })
            });

            // If current selection removed, reset to default by clearing override
            if (this.selected[group] === modelId){
              this.selected[group] = null;
              this.scheduleSave();
            }
            await this.refresh(false);
          }catch(e){
            const msgEl = $("llm_custom_msg");
            if (msgEl) msgEl.textContent = (tr("settings.llm_custom_error","Błąd") + ": " + (e?.message || e));
          }
        });
      }
    },

    renderCustomList(){
      const el = $("llm_custom_list");
      if (!el) return;

      const custom = this.custom || {};
      const groups = GROUPS.slice();

      const parts = [];
      for (const g of groups){
        const arr = Array.isArray(custom[g]) ? custom[g] : [];
        if (!arr.length) continue;

        const label = tr(`settings.llm_group_${g}`, g);
        const items = arr.map(mid => {
          const safe = String(mid).replace(/</g,"&lt;").replace(/>/g,"&gt;");
          const enc = encodeURIComponent(String(mid));
          return `<span style="display:inline-flex; align-items:center; gap:6px; margin-right:10px; margin-top:6px;">
            <code style="font-size:12px;">${safe}</code>
            <button class="btn mini" type="button" data-action="remove-custom" data-group="${g}" data-model="${enc}">${aiIcon("delete",12)}</button>
          </span>`;
        }).join("");

        parts.push(`<div style="margin-top:6px;"><b>${label}:</b> ${items}</div>`);
      }

      if (!parts.length){
        el.innerHTML = `<span class="muted">${tr("settings.llm_custom_empty","Brak własnych modeli.")}</span>`;
      }else{
        el.innerHTML = parts.join("");
      }
    },

    scheduleSave(){
      clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => this.save(), 500);
    },

    async refresh(showMsg){
      const msg = $("llm_refresh_msg");
      if (showMsg && msg) msg.textContent = tr("settings.llm_refreshing", "Refreshing…");

      // Status
      try{
        const st = await http("/api/ollama/status");
        this.online = st.status === "online";
        setStatusDot(this.online);
        const label = this.online ? tr("settings.llm_online","Online") : tr("settings.llm_offline","Offline");
        const txt = $("llm_status_text");
        if (txt) txt.textContent = `${label} · ${st.version || "?"}`;
        const url = $("llm_status_url");
        if (url) url.textContent = (st.url || st.base_url || "").toString();
      }catch(e){
        this.online = false;
        setStatusDot(false);
        const txt = $("llm_status_text");
        if (txt) txt.textContent = tr("settings.llm_offline","Offline");
      }

      // Recommended list
      try{
        const res = await http("/api/models/list");
        for (const g of GROUPS){
          this.list[g] = Array.isArray(res?.[g]) ? res[g] : [];
        }
        this.custom = (res && typeof res.custom_models === "object" && res.custom_models) ? res.custom_models : this.custom;

        // Build installed map from all groups
        this.installed.clear();
        for (const g of GROUPS){
          for (const it of (this.list[g] || [])){
            if (it?.id) this.installed.set(it.id, !!it.installed);
          }
        }
      }catch(e){
        notify(e.message, "error");
      }

      // Current selection
      try{
        const cur = await http("/api/settings/models");
        // Backend may return {quick,deep,...} or {models:{...},defaults:{...}}.
        const models = (cur && typeof cur === "object" && cur.models && typeof cur.models === "object") ? cur.models : cur;
        this.defaults = (cur && typeof cur === "object" && cur.defaults && typeof cur.defaults === "object") ? cur.defaults : {};
        for (const g of GROUPS){
          const v = models?.[g];
          this.selected[g] = v ? String(v) : null;
        }
      }catch{
        // keep existing selected
      }

      this.ensureDefaults();
      this.renderSelects();
      for (const g of GROUPS){
        this.updateInstallUI(g);
        this.updateInfo(g);
      }

      this.renderCustomList();

      if (showMsg && msg) msg.innerHTML = aiIcon('success',12) + ' ' + tr("settings.llm_loaded", "Updated");
    },

    ensureDefaults(){
      // Pick defaults if nothing selected (priority: backend default -> list default -> first option)
      for (const g of GROUPS){
        const arr = this.list[g] || [];
        const isValid = (id) => !!id && arr.some(x => x?.id === id);

        if (isValid(this.selected[g])) continue;

        const backendDefault = this.defaults?.[g];
        if (isValid(backendDefault)){
          this.selected[g] = backendDefault;
          continue;
        }

        const flagged = arr.find(x => x?.default);
        if (flagged?.id){
          this.selected[g] = flagged.id;
          continue;
        }

        if (arr[0]?.id) this.selected[g] = arr[0].id;
      }
    },

    renderSelects(){
      const placeholder = tr("settings.llm_select_placeholder", "Select a model…");
      const notInstalled = tr("settings.llm_not_installed", "not installed");

      const build = (sel, items, chosenId) => {
        if (!sel) return;
        sel.innerHTML = "";
        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = placeholder;
        sel.appendChild(opt0);

        for (const it of (items || [])){
          const opt = document.createElement("option");
          opt.value = it.id;
          const vram = it.vram ? ` · ${it.vram}` : "";
          const speed = it.speed ? ` · ${it.speed}` : "";
          const warn = it.warning ? " (!)" : "";
          const inst = it.installed ? "" : ` (${notInstalled})`;
          opt.textContent = `${it.display_name || it.id}${inst}${vram}${speed}${warn}`;
          if (it.id === chosenId) opt.selected = true;
          sel.appendChild(opt);
        }
      };

      for (const g of GROUPS){
        const cfg = UI[g];
        const sel = cfg ? $(cfg.select) : null;
        if (!sel) continue;
        build(sel, this.list[g], this.selected[g]);

        // Remove old listeners by cloning (simple + safe)
        const cloned = sel.cloneNode(true);
        sel.parentNode.replaceChild(cloned, sel);
        cloned.addEventListener("change", (ev) => {
          this.selected[g] = ev.target.value || null;
          this.updateInstallUI(g);
          this.updateInfo(g);
          this.scheduleSave();
        });
      }
    },

    async save(){
      const payload = {};
      for (const g of GROUPS) payload[g] = this.selected[g];
      try{
        await http("/api/settings/models", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify(payload)
        });
      }catch(e){
        notify(`Save models failed: ${e.message}`, "error");
      }
    },

    updateInstallUI(group){
      const cfg = UI[group];
      if (!cfg) return;
      const modelId = this.selected[group];
      const btn = $(cfg.installBtn);
      const warn = $(cfg.warn);
      if (!btn || !warn) return;

      if (!modelId){
        btn.style.display = "none";
        warn.textContent = "";
        return;
      }

      const installed = !!this.installed.get(modelId);
      if (installed){
        btn.style.display = "none";
        warn.textContent = "";
      }else{
        btn.style.display = "inline-flex";
        btn.disabled = !this.online;
        warn.textContent = tr("settings.llm_install_hint", "To install: ollama pull {model}").replace("{model}", modelId);
      }
    },

    async updateInfo(group){
      const modelId = this.selected[group];
      if (!modelId){
        setInfo(group, null);
        return;
      }
      // quick loading
      setInfo(group, { id: modelId, display_name: modelId, performance: { analysis_time: { [group]: "Loading…" } }, hardware: {}, use_cases: [] });

      let info = null;
      try{
        info = await http(`/api/models/info/${encodeURIComponent(modelId)}?category=${encodeURIComponent(group)}`);
      }catch{
        try{ info = await http(`/api/models/info/${encodeURIComponent(modelId)}`); }catch{ info = null; }
      }
      if (info) info.id = modelId;
      setInfo(group, info);
    },

    async install(group){
      const cfg = UI[group];
      const modelId = this.selected[group];
      if (!cfg || !modelId) return;

      const btn = $(cfg.installBtn);
      const msgEl = $("llm_refresh_msg");
      if (btn){ btn.disabled = true; btn.innerHTML = aiIcon('loading',12) + " Installing\u2026"; }
      if (msgEl) msgEl.textContent = `Installing ${modelId}…`;

      try{
        await http("/api/ollama/install", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ model: modelId, scope: group })
        });

        const start = Date.now();
        const timeout = 30 * 60 * 1000;
        while (Date.now() - start < timeout){
          await new Promise(r => setTimeout(r, 2000));
          const st = await http(`/api/ollama/install/status?model=${encodeURIComponent(modelId)}`);
          if (st?.status === "done"){
            if (msgEl) msgEl.innerHTML = aiIcon('success',12) + ` Installed (${modelId})`;
            notify(`Installed: ${modelId}`, "success");
            await this.refresh(false);
            return;
          }
          if (st?.status === "error") throw new Error(st.error || "install error");
          if (msgEl){
            const p = (typeof st.progress === "number") ? st.progress : null;
            const stage = st.stage || "";
            msgEl.textContent = `Installing ${modelId}… ${p != null ? (p + "%") : ""} ${stage}`.trim();
          }
        }
        throw new Error("install timeout");
      }catch(e){
        if (msgEl) msgEl.textContent = `Install error: ${e.message}`;
        notify(`Install failed: ${e.message}`, "error");
      }finally{
        if (btn){ btn.innerHTML = aiIcon('install',12) + ' ' + tr("settings.llm_install","Install"); btn.disabled = false; }
        this.updateInstallUI(group);
      }
    }
  };

  window.ModelSettings = {
    init: async () => {
      await State.init();
    }
  };

  document.addEventListener("DOMContentLoaded", () => {
    // Settings page calls ModelSettings.init() explicitly, but keep as a fallback.
    if (window.ModelSettings && typeof window.ModelSettings.init === "function"){
      window.ModelSettings.init().catch(()=>{});
    }
  });
})();
