/* global api, t, showNotification */

(() => {
  const $ = (id) => document.getElementById(id);

  // ---- tiny safe helpers ----
  const _t = (k) => (typeof t === "function" ? t(k) : k);
  const notify = (msg, type="info") => {
    if (typeof showNotification === "function") return showNotification(msg, type);
    console.log(`[${type}] ${msg}`);
  };

  async function http(url, opts){
    // Prefer project helper if present
    if (typeof api === "function") return api(url, opts);
    const r = await fetch(url, opts);
    const txt = await r.text();
    let data = null;
    try { data = JSON.parse(txt); } catch { data = txt; }
    if (!r.ok) throw new Error((data && data.detail) ? data.detail : `HTTP ${r.status}`);
    return data;
  }

  function esc(s){
    return String(s ?? "")
      .replaceAll("&","&amp;")
      .replaceAll("<","&lt;")
      .replaceAll(">","&gt;")
      .replaceAll('"',"&quot;")
      .replaceAll("'","&#039;");
  }

  function stars(n){
    const v = Math.max(0, Math.min(5, Number(n || 0)));
    return "★".repeat(v) + "☆".repeat(5 - v);
  }

  function setStatus(online, text, url){
    const dot = $("llm_status_dot");
    const msg = $("llm_status_text");
    const urlEl = $("llm_status_url");
    if (dot){
      dot.classList.remove("online","offline");
      dot.classList.add(online ? "online" : "offline");
    }
    if (msg) msg.textContent = text || (online ? _t("settings.llm_online") : _t("settings.llm_offline"));
    if (urlEl) urlEl.textContent = url || "";
  }

  function setInfo(kind, info){
    // Supports right-side panels (preferred)
    const nameId = kind === "quick" ? "llm_quick_info_name" : "llm_deep_info_name";
    const bodyId = kind === "quick" ? "llm_quick_info_body" : "llm_deep_info_body";
    const warnId = kind === "quick" ? "llm_quick_info_warning" : "llm_deep_info_warning";

    const nameEl = $(nameId);
    const bodyEl = $(bodyId);
    const warnEl = $(warnId);

    if (!nameEl || !bodyEl) return;

    if (!info){
      nameEl.textContent = "—";
      bodyEl.innerHTML = `<div class="small muted">${esc(_t("settings.llm_select_placeholder"))}</div>`;
      if (warnEl) warnEl.style.display = "none";
      return;
    }

    const hw = info.hardware || {};
    const perf = info.performance || {};
    const useCases = Array.isArray(info.use_cases) ? info.use_cases : [];
    const rec = info.recommendation || "";
    const warn = info.warning || "";

    nameEl.textContent = info.display_name || info.id || "—";

    // Compact 2-column grid + list + recommendation (fits small box)
    const listHtml = useCases.length
      ? `<div class="llm-info-section-title">🎯 ${esc(_t("settings.llm_use_cases") || "Use cases")}</div>
         <ul class="llm-ul">${useCases.slice(0, 8).map(x => `<li>${esc(x)}</li>`).join("")}</ul>`
      : "";

    const bodyHtml = `
      <div class="llm-info-grid">
        <div>
          <div class="llm-info-section-title">📊 ${esc(_t("settings.llm_hw") || "Hardware")}</div>
          <ul class="llm-ul">
            <li>VRAM: <b>${esc(hw.vram || "?")}</b></li>
            <li>${esc(_t("settings.llm_min_gpu") || "Min GPU")}: <b>${esc(hw.min_gpu || "?")}</b></li>
            <li>${esc(_t("settings.llm_opt_gpu") || "Optimal GPU")}: <b>${esc(hw.optimal_gpu || "?")}</b></li>
            <li>RAM: <b>${esc(hw.ram || "?")}</b></li>
          </ul>
        </div>
        <div>
          <div class="llm-info-section-title">⚡ ${esc(_t("settings.llm_perf") || "Performance")}</div>
          <ul class="llm-ul">
            <li>${esc(_t("settings.llm_analysis_time") || "Analysis time")}: <b>${esc(perf.analysis_time || "?")}</b></li>
            <li>${esc(_t("settings.llm_quality") || "Quality")}: <b>${esc(stars(perf.quality_stars || 0))}</b></li>
            <li>${esc(_t("settings.llm_polish_quality") || "Polish quality")}: <b>${esc(stars(perf.polish_quality_stars || 0))}</b></li>
          </ul>
        </div>
      </div>

      ${listHtml}

      ${rec ? `<div class="llm-reco"><div class="llm-info-section-title">💡 ${esc(_t("settings.llm_reco") || "Recommendation")}</div>
      <div>${esc(rec)}</div></div>` : ``}
    `;

    bodyEl.innerHTML = bodyHtml;

    if (warnEl){
      if (warn){
        warnEl.textContent = `⚠️ ${warn}`;
        warnEl.style.display = "block";
      }else{
        warnEl.style.display = "none";
      }
    }
  }

  const State = {
    online: false,
    list: { quick: [], deep: [] },
    selected: { quick: null, deep: null },
    installed: new Map(),
    _saveTimer: null,

    async init(){
      const qSel = $("llm_quick_select");
      const dSel = $("llm_deep_select");
      if (!qSel || !dSel) return; // page doesn't have this section

      // events
      qSel.addEventListener("change", async () => {
        this.selected.quick = qSel.value || null;
        await this.updateInfo("quick");
        this.updateInstallUI("quick");
        this.scheduleSave();
      });

      dSel.addEventListener("change", async () => {
        this.selected.deep = dSel.value || null;
        await this.updateInfo("deep");
        this.updateInstallUI("deep");
        this.scheduleSave();
      });

      const refreshBtn = $("llm_refresh_btn");
      if (refreshBtn) refreshBtn.addEventListener("click", () => this.refresh(true));

      const qi = $("llm_quick_install_btn");
      if (qi) qi.addEventListener("click", () => this.install("quick"));

      const di = $("llm_deep_install_btn");
      if (di) di.addEventListener("click", () => this.install("deep"));

      await this.refresh(false);
    },

    async refresh(showToast){
      const msgEl = $("llm_refresh_msg");
      if (msgEl) msgEl.textContent = _t("settings.llm_refreshing") || "Refreshing…";

      // status
      try{
        const st = await http("/api/ollama/status");
        this.online = st && st.status === "online";
        const url = st.url || "http://127.0.0.1:11434";
        const count = st.models_count ?? 0;
        setStatus(this.online, this.online ? `Online (${count})` : "Offline", url);
      }catch(e){
        this.online = false;
        setStatus(false, "Offline", "");
      }

      // list
      try{
        // keep it compatible (some backends accept lang, some not)
        try{
          this.list = await http("/api/models/list");
        }catch{
          this.list = await http("/api/models/list?lang=pl");
        }
      }catch(e){
        this.list = { quick: [], deep: [] };
      }

      // installed map
      this.installed.clear();
      for (const m of (this.list.quick || [])) this.installed.set(m.id, !!m.installed);
      for (const m of (this.list.deep || [])) this.installed.set(m.id, !!m.installed);

      // selected
      try{
        const cur = await http("/api/settings/models");
        this.selected.quick = cur.quick || null;
        this.selected.deep = cur.deep || null;
      }catch{
        this.selected.quick = null;
        this.selected.deep = null;
      }

      this.renderSelects();
      await this.updateInfo("quick");
      await this.updateInfo("deep");
      this.updateInstallUI("quick");
      this.updateInstallUI("deep");

      if (msgEl) msgEl.textContent = _t("settings.llm_loaded") || "Updated ✅";
      if (showToast) notify("✅ Models refreshed", "success");
    },

    renderSelects(){
      const qSel = $("llm_quick_select");
      const dSel = $("llm_deep_select");
      if (!qSel || !dSel) return;

      const build = (sel, arr, selectedId) => {
        sel.innerHTML = "";
        const ph = document.createElement("option");
        ph.value = "";
        ph.textContent = _t("settings.llm_select_placeholder") || "Select model…";
        sel.appendChild(ph);

        (arr || []).forEach(m => {
          const opt = document.createElement("option");
          opt.value = m.id;

          // Do NOT disable not-installed (user can select and click Install)
          const ni = m.installed ? "" : " (not installed)";
          const vram = m.vram ? ` • ${m.vram}` : "";
          const speed = m.speed ? ` • ${m.speed}` : "";
          const rec = m.default ? " • Recommended" : "";

          opt.textContent = `${m.display_name || m.id}${ni}${vram}${speed}${rec}`;
          if (m.id === selectedId) opt.selected = true;
          sel.appendChild(opt);
        });
      };

      build(qSel, this.list.quick, this.selected.quick);
      build(dSel, this.list.deep, this.selected.deep);
    },

    scheduleSave(){
      clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => this.save(), 500);
    },

    async save(){
      const payload = { quick: this.selected.quick, deep: this.selected.deep };
      try{
        await http("/api/settings/models", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify(payload)
        });
      }catch(e){
        notify(`❌ Save models failed: ${e.message}`, "error");
      }
    },

    async updateInfo(kind){
      const modelId = this.selected[kind];
      if (!modelId){
        setInfo(kind, null);
        return;
      }
      // show loading quickly
      setInfo(kind, { display_name: modelId, hardware:{}, performance:{ analysis_time: "Loading…" }, use_cases:[], recommendation:"" });

      // fetch info (prefer category)
      let info = null;
      try{
        info = await http(`/api/models/info/${encodeURIComponent(modelId)}?category=${encodeURIComponent(kind)}&lang=pl`);
      }catch{
        try{
          info = await http(`/api/models/info/${encodeURIComponent(modelId)}?category=${encodeURIComponent(kind)}`);
        }catch{
          try{
            info = await http(`/api/models/info/${encodeURIComponent(modelId)}`);
          }catch{
            info = null;
          }
        }
      }
      if (info) info.id = modelId;
      setInfo(kind, info);
    },

    updateInstallUI(kind){
      const modelId = this.selected[kind];
      const btn = $(kind === "quick" ? "llm_quick_install_btn" : "llm_deep_install_btn");
      const warn = $(kind === "quick" ? "llm_quick_warn" : "llm_deep_warn");
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
        warn.textContent = `To install: ollama pull ${modelId}`;
      }
    },

    async install(kind){
      const modelId = this.selected[kind];
      if (!modelId) return;

      const btn = $(kind === "quick" ? "llm_quick_install_btn" : "llm_deep_install_btn");
      const msgEl = $("llm_refresh_msg");
      if (btn){
        btn.disabled = true;
        btn.textContent = "⏳ Installing…";
      }
      if (msgEl) msgEl.textContent = `Installing ${modelId}…`;

      try{
        // include scope for logging (backend accepts extra keys)
        await http("/api/ollama/install", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ model: modelId, scope: kind })
        });

        // poll
        const start = Date.now();
        const timeout = 30 * 60 * 1000;

        while (Date.now() - start < timeout){
          await new Promise(r => setTimeout(r, 2000));
          const st = await http(`/api/ollama/install/status?model=${encodeURIComponent(modelId)}`);

          if (st.status === "done"){
            if (msgEl) msgEl.textContent = `Installed ✅ (${modelId})`;
            notify(`✅ Installed: ${modelId}`, "success");
            await this.refresh(false);
            break;
          }
          if (st.status === "error"){
            throw new Error(st.error || "install error");
          }
        }
      }catch(e){
        if (msgEl) msgEl.textContent = `Install error: ${e.message}`;
        notify(`❌ Install failed: ${e.message}`, "error");
      }finally{
        if (btn){
          btn.textContent = "⬇️ Install";
          btn.disabled = false;
        }
        this.updateInstallUI(kind);
      }
    }
  };

  document.addEventListener("DOMContentLoaded", () => {
    State.init();
  });
})();
