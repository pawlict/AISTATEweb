/**
 * Crypto Analysis Module — CryptoManager
 *
 * Lazy-initialized when the Crypto tab is first clicked.
 * Handles CSV/PDF upload, results rendering, Chart.js charts,
 * Cytoscape.js flow graph, and LLM narrative streaming.
 *
 * Supports two display modes based on source_type:
 *   - "exchange"   — exchange statements (Binance, Kraken, …)
 *   - "blockchain" — on-chain data (WalletExplorer, Etherscan, …)
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                           */
  /* ------------------------------------------------------------------ */

  const QS = (sel) => document.querySelector(sel);
  const QSA = (sel) => document.querySelectorAll(sel);
  const _hide = (id) => { const el = document.getElementById(id); if (el) el.style.display = "none"; };
  const _show = (id, d) => { const el = document.getElementById(id); if (el) el.style.display = d || ""; };
  const _text = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };
  const _html = (id, h) => { const el = document.getElementById(id); if (el) el.innerHTML = h; };
  const _esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function _getProjectId() {
    try { return (new URLSearchParams(window.location.search)).get("project") || localStorage.getItem("aistate_current_project") || ""; }
    catch (_) { return ""; }
  }

  function _fmtCrypto(val, token) {
    if (val == null) return "\u2014";
    const n = Number(val);
    if (isNaN(n)) return String(val);
    // Use up to 8 decimals for crypto, trim trailing zeros
    const s = n.toFixed(8).replace(/\.?0+$/, "");
    return s + (token ? " " + token : "");
  }

  /* ------------------------------------------------------------------ */
  /*  State                                                             */
  /* ------------------------------------------------------------------ */

  let _lastResult = null;
  let _chartInstances = {};
  let _smallChartInstances = {};
  let _mainChartInstance = null;
  let _cyInstance = null;
  let _llmRunning = false;
  let _txClassifications = {}; // tx_hash -> classification
  let _chartZoom = { level: 1, activeKey: null };

  /* Classification metadata */
  const CLS_META = {
    neutral:    { label: "Neutralny",  color: "#60a5fa", bg: "rgba(96,165,250,.08)" },
    legitimate: { label: "Poprawny",   color: "#15803d", bg: "rgba(21,128,61,.08)" },
    suspicious: { label: "Podejrzany", color: "#dc2626", bg: "rgba(220,38,38,.08)" },
    monitoring: { label: "Obserwacja", color: "#ea580c", bg: "rgba(234,88,12,.08)" },
  };

  const RISK_COLORS = { critical: "#ef4444", high: "#f97316", medium: "#eab308", low: "#22c55e", unknown: "#94a3b8" };

  /* ------------------------------------------------------------------ */
  /*  Lazy-load external libraries                                      */
  /* ------------------------------------------------------------------ */

  function _loadScript(url) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${url}"]`)) { resolve(); return; }
      const s = document.createElement("script");
      s.src = url;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  async function _ensureChartJS() {
    if (window.Chart) return;
    await _loadScript("https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js");
  }

  async function _ensureCytoscape() {
    if (window.cytoscape) return;
    await _loadScript("https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js");
  }

  /* ------------------------------------------------------------------ */
  /*  LLM model loading (shared pattern with GSM)                       */
  /* ------------------------------------------------------------------ */

  async function _loadModels() {
    const sel = QS("#crypto_model_deep");
    if (!sel) return;
    try {
      const resp = await fetch("/api/models/list");
      if (!resp.ok) return;
      const data = await resp.json();
      const models = data.models || [];
      sel.innerHTML = "";
      if (!models.length) {
        sel.innerHTML = '<option value="">Brak modeli</option>';
        return;
      }
      for (const m of models) {
        const opt = document.createElement("option");
        opt.value = m.id || m.name || "";
        opt.textContent = m.display_name || m.name || m.id || "?";
        sel.appendChild(opt);
      }
      sel.disabled = false;
    } catch (e) {
      console.warn("[Crypto] Failed to load models:", e);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  File upload                                                       */
  /* ------------------------------------------------------------------ */

  async function _uploadFile(file) {
    _hide("crypto_empty_state");
    _hide("crypto_results");
    _show("crypto_progress");
    _text("crypto_status", "Analizowanie...");
    const bar = QS("#crypto_bar");
    if (bar) bar.style.width = "30%";

    const fd = new FormData();
    fd.append("file", file);
    fd.append("project_id", _getProjectId());

    try {
      const resp = await fetch("/api/crypto/analyze", { method: "POST", body: fd });
      const data = await resp.json();

      if (data.status === "ok" && data.result) {
        if (bar) bar.style.width = "100%";
        _text("crypto_status", "Gotowe");
        _lastResult = data.result;
        _txClassifications = {};
        _renderResults(data.result);
        setTimeout(() => _hide("crypto_progress"), 1500);
      } else {
        _text("crypto_status", "Błąd: " + (data.errors || []).join("; "));
        if (bar) bar.style.width = "0%";
      }
    } catch (e) {
      console.error("[Crypto] Upload error:", e);
      _text("crypto_status", "Błąd: " + e.message);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Auto-load from project                                            */
  /* ------------------------------------------------------------------ */

  async function _loadFromProject() {
    const pid = _getProjectId();
    if (!pid) return;
    try {
      const resp = await fetch(`/api/crypto/detail?project_id=${encodeURIComponent(pid)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.status === "ok" && data.result) {
        _lastResult = data.result;
        _txClassifications = {};
        _hide("crypto_empty_state");
        _renderResults(data.result);
      }
    } catch (e) {
      console.warn("[Crypto] Auto-load failed:", e);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Render results — dual mode                                        */
  /* ------------------------------------------------------------------ */

  function _renderResults(r) {
    _hide("crypto_empty_state");
    _show("crypto_results");

    const isExchange = (r.source_type === "exchange");

    _renderSummary(r, isExchange);
    _renderRisk(r);
    _renderAlerts(r);

    if (isExchange) {
      _renderExchangeMeta(r);
      _renderTokenBreakdown(r);
      _hide("crypto_wallets_card");
    } else {
      _hide("crypto_exchange_meta_card");
      _hide("crypto_token_breakdown_card");
    }

    _renderReviewTable(r, isExchange);
    _renderAnomalies(r, isExchange);
    _renderCharts(r, isExchange);
    _renderSmallCharts(r, isExchange);
    _renderGraph(r);
    if (!isExchange) _renderWallets(r);
  }

  /* -- Summary (light fields like AML/GSM) ----------------------------- */

  function _renderSummary(r, isExchange) {
    // Info rows (like AML bank info)
    const infoGrid = document.getElementById("crypto_info_grid");
    if (infoGrid) {
      let html = "";
      if (isExchange) {
        const em = r.exchange_meta || {};
        if (em.exchange_name || r.source) html += `<div class="crypto-info-row"><b>Giełda:</b> ${_esc(em.exchange_name || r.source)}</div>`;
        if (r.filename) html += `<div class="crypto-info-row"><b>Plik:</b> ${_esc(r.filename)}</div>`;
        const dateFrom = (r.date_from || "").slice(0, 10);
        const dateTo = (r.date_to || "").slice(0, 10);
        if (dateFrom || dateTo) html += `<div class="crypto-info-row"><b>Okres:</b> ${_esc(dateFrom)} \u2014 ${_esc(dateTo)}</div>`;
        if (em.crypto_tokens && em.crypto_tokens.length) html += `<div class="crypto-info-row"><b>Tokeny krypto:</b> ${_esc(em.crypto_tokens.join(", "))}</div>`;
        if (em.fiat_tokens && em.fiat_tokens.length) html += `<div class="crypto-info-row"><b>Waluty fiat:</b> ${_esc(em.fiat_tokens.join(", "))}</div>`;
        if (em.account_types && em.account_types.length) html += `<div class="crypto-info-row"><b>Konta:</b> ${_esc(em.account_types.join(", "))}</div>`;
        html += '<div class="crypto-info-stats">';
        if (r.total_received != null) html += `<span><b>Wpłaty (dep.):</b> ${(r.total_received || 0).toFixed(4)}</span>`;
        if (r.total_sent != null) html += `<span><b>Wypłaty (wd.):</b> ${(r.total_sent || 0).toFixed(4)}</span>`;
        html += '</div>';
      } else {
        const token = Object.keys(r.tokens || {})[0] || "BTC";
        if (r.source) html += `<div class="crypto-info-row"><b>Źródło:</b> ${_esc(r.source)}</div>`;
        if (r.chain) html += `<div class="crypto-info-row"><b>Blockchain:</b> ${_esc(r.chain)}</div>`;
        if (r.filename) html += `<div class="crypto-info-row"><b>Plik:</b> ${_esc(r.filename)}</div>`;
        const dateFrom = (r.date_from || "").slice(0, 10);
        const dateTo = (r.date_to || "").slice(0, 10);
        if (dateFrom || dateTo) html += `<div class="crypto-info-row"><b>Okres:</b> ${_esc(dateFrom)} \u2014 ${_esc(dateTo)}</div>`;
        html += '<div class="crypto-info-stats">';
        if (r.total_received != null) html += `<span><b>Wpłaty:</b> ${_fmtCrypto(r.total_received, token)}</span>`;
        if (r.total_sent != null) html += `<span><b>Wypłaty:</b> ${_fmtCrypto(r.total_sent, token)}</span>`;
        html += '</div>';
      }
      if (r.elapsed_sec) html += `<div class="small muted" style="margin-top:4px">Czas analizy: ${r.elapsed_sec.toFixed(1)}s</div>`;
      infoGrid.innerHTML = html;
    }

    // Stat cards (like GSM)
    const cards = [];
    if (r.tx_count) cards.push(["Transakcje", r.tx_count]);
    if (!isExchange && r.wallet_count) cards.push(["Portfele", r.wallet_count]);
    if (r.counterparty_count) cards.push(["Kontrahenci", r.counterparty_count]);
    const tokenCount = Object.keys(r.tokens || {}).length;
    if (tokenCount) cards.push(["Tokeny", tokenCount]);

    const grid = document.getElementById("crypto_summary_grid");
    if (grid) {
      let html = "";
      for (const [label, val] of cards) {
        html += `<div class="crypto-stat-card">
          <div class="crypto-stat-value">${_esc(String(val))}</div>
          <div class="crypto-stat-label">${_esc(label)}</div>
        </div>`;
      }
      grid.innerHTML = html;
    }
  }

  /* -- Exchange metadata ---------------------------------------------- */

  function _renderExchangeMeta(r) {
    const tokens = r.tokens || {};
    if (!Object.keys(tokens).length) { _hide("crypto_exchange_meta_card"); return; }
    _show("crypto_exchange_meta_card");

    let html = '<table class="data-table" style="width:100%;font-size:13px"><thead><tr>' +
      "<th>Token</th><th>Wpływy</th><th>Wypływy</th><th>Saldo netto</th><th>TX</th>" +
      "</tr></thead><tbody>";
    const sorted = Object.entries(tokens).sort((a, b) => b[1].count - a[1].count);
    for (const [tok, s] of sorted) {
      const net = (s.received || 0) - (s.sent || 0);
      const netColor = net >= 0 ? "#22c55e" : "#ef4444";
      html += `<tr>
        <td style="font-weight:600">${_esc(tok)}</td>
        <td style="text-align:right">${(s.received || 0).toFixed(4)}</td>
        <td style="text-align:right">${(s.sent || 0).toFixed(4)}</td>
        <td style="text-align:right;color:${netColor};font-weight:600">${net >= 0 ? "+" : ""}${net.toFixed(4)}</td>
        <td style="text-align:center">${s.count}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    _html("crypto_exchange_meta_body", html);
  }

  /* -- Token breakdown chart card ------------------------------------- */

  function _renderTokenBreakdown(r) {
    _show("crypto_token_breakdown_card");
    // Actual chart is rendered in _renderCharts
  }

  /* -- Risk assessment ----------------------------------------------- */

  function _renderRisk(r) {
    const score = r.risk_score || 0;
    let color = "#22c55e"; // green
    let label = "Niskie";
    if (score >= 70) { color = "#ef4444"; label = "Krytyczne"; }
    else if (score >= 50) { color = "#f97316"; label = "Wysokie"; }
    else if (score >= 25) { color = "#eab308"; label = "Średnie"; }

    let html = `<div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
      <div style="font-size:36px;font-weight:700;color:${color}">${score.toFixed(1)}<span style="font-size:16px;color:var(--text-muted)">/100</span></div>
      <div style="font-size:18px;font-weight:600;color:${color}">${label}</div>
    </div>`;

    if (r.risk_reasons && r.risk_reasons.length) {
      html += '<ul style="margin:0;padding-left:20px">';
      for (const reason of r.risk_reasons) {
        html += `<li style="margin-bottom:4px">${_esc(reason)}</li>`;
      }
      html += "</ul>";
    }
    _html("crypto_risk_body", html);
  }

  /* -- Alerts -------------------------------------------------------- */

  function _renderAlerts(r) {
    const alerts = r.alerts || [];
    if (!alerts.length) { _hide("crypto_alerts_card"); return; }
    _show("crypto_alerts_card");

    let html = "";
    for (const a of alerts) {
      const c = RISK_COLORS[a.risk] || "#94a3b8";
      html += `<div style="padding:8px 12px;margin-bottom:6px;border-left:3px solid ${c};background:${a.risk === "critical" ? "rgba(239,68,68,.06)" : a.risk === "high" ? "rgba(249,115,22,.06)" : "var(--bg-secondary,#f1f5f9)"};border-radius:4px">
        <strong style="color:${c}">${_esc(a.pattern || "?")}</strong>: ${_esc(a.description || "")}
      </div>`;
    }
    _html("crypto_alerts_body", html);
  }

  /* ------------------------------------------------------------------ */
  /*  Transaction Review & Classification (per-record like AML)         */
  /* ------------------------------------------------------------------ */

  function _renderReviewTable(r, isExchange) {
    const txs = r.transactions || [];

    _renderReviewStats(txs);
    _filterAndRenderReview(txs, isExchange);
  }

  function _renderReviewStats(txs) {
    const counts = { neutral: 0, legitimate: 0, suspicious: 0, monitoring: 0 };
    for (const tx of txs) {
      const cls = _txClassifications[tx.hash || tx.id] || _autoClassify(tx);
      if (counts[cls] != null) counts[cls]++;
    }
    const total = txs.length || 1;

    // Stats bar
    const bar = document.getElementById("crypto_rv_stats_bar");
    if (bar) {
      let html = "";
      for (const [key, meta] of Object.entries(CLS_META)) {
        const pct = (counts[key] / total * 100).toFixed(1);
        if (counts[key] > 0) {
          html += `<div style="width:${pct}%;background:${meta.color};transition:width .3s" title="${meta.label}: ${counts[key]}"></div>`;
        }
      }
      bar.innerHTML = html;
    }

    // Legend
    const legend = document.getElementById("crypto_rv_stats_legend");
    if (legend) {
      let html = '<div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px">';
      for (const [key, meta] of Object.entries(CLS_META)) {
        html += `<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${meta.color};margin-right:4px"></span>${meta.label}: ${counts[key]}</span>`;
      }
      html += '</div>';
      legend.innerHTML = html;
    }
  }

  function _autoClassify(tx) {
    const tags = tx.risk_tags || [];
    if (tags.includes("sanctioned") || tags.includes("mixer")) return "suspicious";
    if (tags.includes("high_value") || tags.includes("privacy_coin")) return "monitoring";
    const score = tx.risk_score || 0;
    if (score >= 70) return "suspicious";
    if (score >= 40) return "monitoring";
    return "neutral";
  }

  /** Classify a single transaction (DOM-only update, like AML review.js) */
  function _classifyTx(txId, classification) {
    if (!txId) return;
    _txClassifications[txId] = classification;

    // Update just this row's buttons (no re-render)
    const btnsDiv = document.querySelector(`.crypto-rv-cls-btns[data-txid="${txId}"]`);
    if (btnsDiv) {
      btnsDiv.querySelectorAll(".crypto-rv-cls-btn").forEach(b => {
        const k = b.dataset.cls;
        const m = CLS_META[k];
        if (k === classification) {
          b.classList.add("active");
          b.style.background = m ? m.bg : "";
        } else {
          b.classList.remove("active");
          b.style.background = "";
        }
      });

      // Update row background
      const row = btnsDiv.closest("tr");
      if (row) {
        const m = CLS_META[classification];
        row.style.background = m ? m.bg : "";
      }
    }

    // Update stats bar (lightweight)
    if (_lastResult) {
      _renderReviewStats(_lastResult.transactions || []);
    }
  }

  function _filterAndRenderReview(txs, isExchange) {
    const search = (QS("#crypto_rv_search") || {}).value || "";
    const filterCls = (QS("#crypto_rv_filter_class") || {}).value || "";
    const filterRisk = (QS("#crypto_rv_filter_risk") || {}).value || "";
    const searchLow = search.toLowerCase();

    const filtered = txs.filter(tx => {
      const cls = _txClassifications[tx.hash || tx.id] || _autoClassify(tx);
      if (filterCls && cls !== filterCls) return false;

      if (filterRisk) {
        const tags = tx.risk_tags || [];
        const score = tx.risk_score || 0;
        let riskLevel = "low";
        if (score >= 70 || tags.includes("sanctioned")) riskLevel = "critical";
        else if (score >= 50 || tags.includes("mixer")) riskLevel = "high";
        else if (score >= 25 || tags.includes("high_value")) riskLevel = "medium";
        if (riskLevel !== filterRisk) return false;
      }

      if (searchLow) {
        const haystack = [tx.from, tx.to, tx.hash, tx.token, tx.tx_type, tx.category, ...(tx.risk_tags || [])].join(" ").toLowerCase();
        if (!haystack.includes(searchLow)) return false;
      }

      return true;
    });

    _text("crypto_rv_tx_count", `${filtered.length} z ${txs.length} transakcji`);

    const wrap = document.getElementById("crypto_rv_table_wrap");
    if (!wrap) return;

    const show = filtered.slice(0, 200);
    let html;

    if (isExchange) {
      html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
        "<th>Data</th><th>Konto</th><th>Operacja</th><th>Token</th><th>Kwota</th><th>Typ</th><th>Tagi</th><th>Klasyfikacja</th>" +
        "</tr></thead><tbody>";
      for (const tx of show) {
        const txId = tx.hash || tx.id || "";
        const cls = _txClassifications[txId] || _autoClassify(tx);
        const meta = CLS_META[cls] || CLS_META.neutral;
        const tags = (tx.risk_tags || []).join(", ");
        const tagColor = tags.includes("privacy_coin") ? "#f97316" :
          tags.includes("meme_coin") ? "#eab308" :
            tags.includes("withdrawal") ? "#3b82f6" :
              tags.includes("high_value_fiat") ? "#ef4444" : "";
        const raw = tx.raw || {};
        const amt = tx.amount || 0;
        const rawChange = raw.change || "";
        const isNeg = rawChange && String(rawChange).trim().startsWith("-");
        const amtColor = isNeg ? "#ef4444" : "#22c55e";

        html += `<tr style="background:${meta.bg}" data-txid="${_esc(txId)}">
          <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16).replace("T", " "))}</td>
          <td>${_esc(raw.account || "\u2014")}</td>
          <td>${_esc(tx.category || raw.operation || tx.tx_type || "\u2014")}</td>
          <td style="font-weight:600">${_esc(tx.token || "")}</td>
          <td style="text-align:right;color:${amtColor};font-weight:500">${isNeg ? "-" : "+"}${amt.toFixed(4)}</td>
          <td>${_esc(tx.tx_type || "")}</td>
          <td style="color:${tagColor};font-size:11px">${_esc(tags || "\u2014")}</td>
          <td style="white-space:nowrap">
            <div class="crypto-rv-cls-btns" data-txid="${_esc(txId)}">`;

        for (const [key, m] of Object.entries(CLS_META)) {
          const isActive = cls === key;
          html += `<button class="crypto-rv-cls-btn${isActive ? " active" : ""}" data-cls="${key}" style="color:${m.color};${isActive ? "background:" + m.bg : ""}" title="${m.label}">${m.label.charAt(0)}</button>`;
        }

        html += `</div></td></tr>`;
      }
    } else {
      html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
        "<th>Data</th><th>Od</th><th>Do</th><th>Kwota</th><th>Token</th><th>Typ</th><th>Ryzyko</th><th>Klasyfikacja</th>" +
        "</tr></thead><tbody>";
      for (const tx of show) {
        const txId = tx.hash || tx.id || "";
        const cls = _txClassifications[txId] || _autoClassify(tx);
        const meta = CLS_META[cls] || CLS_META.neutral;
        const tags = (tx.risk_tags || []).join(", ");
        const tagColor = tags.includes("sanctioned") ? "#ef4444" :
          tags.includes("mixer") ? "#f97316" :
            tags.includes("high_value") ? "#eab308" : "";

        html += `<tr style="background:${meta.bg}" data-txid="${_esc(txId)}">
          <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16))}</td>
          <td style="font-family:monospace;font-size:10px" title="${_esc(tx.from || "")}">${_esc(_shorten(tx.from || "\u2014"))}</td>
          <td style="font-family:monospace;font-size:10px" title="${_esc(tx.to || "")}">${_esc(_shorten(tx.to || "\u2014"))}</td>
          <td style="text-align:right">${_fmtCrypto(tx.amount, "")}</td>
          <td>${_esc(tx.token || "")}</td>
          <td>${_esc(tx.tx_type || "")}</td>
          <td style="color:${tagColor};font-size:11px">${_esc(tags || "\u2014")}</td>
          <td style="white-space:nowrap">
            <div class="crypto-rv-cls-btns" data-txid="${_esc(txId)}">`;

        for (const [key, m] of Object.entries(CLS_META)) {
          const isActive = cls === key;
          html += `<button class="crypto-rv-cls-btn${isActive ? " active" : ""}" data-cls="${key}" style="color:${m.color};${isActive ? "background:" + m.bg : ""}" title="${m.label}">${m.label.charAt(0)}</button>`;
        }

        html += `</div></td></tr>`;
      }
    }

    html += "</tbody></table>";
    if (show.length < filtered.length) {
      html += `<div class="small muted" style="margin-top:4px">Pokazano ${show.length} z ${filtered.length}</div>`;
    }

    wrap.innerHTML = html;

    // Bind classification buttons — per-record DOM update (like AML)
    wrap.querySelectorAll(".crypto-rv-cls-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const txId = btn.closest(".crypto-rv-cls-btns").getAttribute("data-txid");
        const cls = btn.dataset.cls;
        _classifyTx(txId, cls);
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Anomalies (like GSM, dedicated to crypto)                         */
  /* ------------------------------------------------------------------ */

  const _CRYPTO_ANOMALY_CATS = [
    { type: "deposits_withdrawals",  label: "Wpłaty i wypłaty środków",         desc: "Wpłaty na giełdę / z zewnątrz i wypłaty na zewnątrz giełdy — chronologicznie" },
    { type: "high_value_tx",         label: "Transakcje dużej wartości",         desc: "Pojedyncze transakcje przekraczające istotny próg wartości" },
    { type: "rapid_movement",        label: "Szybkie przerzuty środków",         desc: "Wpłata + wypłata w krótkim czasie — potencjalne pranie pieniędzy" },
    { type: "round_amounts",         label: "Okrągłe kwoty",                     desc: "Transakcje na równe, okrągłe kwoty (100, 1000, 5000 itd.)" },
    { type: "privacy_coins",         label: "Privacy coins / mikser",            desc: "Transakcje z użyciem Monero (XMR), Zcash (ZEC), Tornado Cash lub podejrzanych adresów" },
    { type: "inactivity_gap",        label: "Brak aktywności",                    desc: "Okresy bez żadnej transakcji (przerwy w aktywności)" },
    { type: "burst_activity",        label: "Nagły wzrost aktywności",            desc: "Nietypowo duża liczba transakcji w krótkim oknie czasowym" },
    { type: "new_token",             label: "Nowe / nieznane tokeny",             desc: "Transakcje z tokenami pojawiającymi się po raz pierwszy lub tokenami niskiej kapitalizacji" },
    { type: "cross_chain",           label: "Transfery cross-chain / bridge",     desc: "Operacje pomiędzy różnymi blockchainami lub przez mosty kryptowalutowe" },
    { type: "sanctioned_addr",       label: "Adresy sankcjonowane",               desc: "Interakcje z adresami znajdującymi się na listach sankcji (OFAC, EU)" },
  ];

  function _renderAnomalies(r, isExchange) {
    const card = document.getElementById("crypto_anomalies_card");
    const body = document.getElementById("crypto_anomalies_body");
    if (!card || !body) return;

    const txs = r.transactions || [];
    if (!txs.length) { card.style.display = "none"; return; }
    card.style.display = "";

    // Detect anomalies from transaction data
    const detected = _detectCryptoAnomalies(r, txs, isExchange);

    const VISIBLE = 5;

    let html = '<div style="display:flex;flex-direction:column;gap:10px">';
    for (const cat of _CRYPTO_ANOMALY_CATS) {
      const items = detected[cat.type] || [];
      const hasItems = items.length > 0;
      const sev = hasItems ? _anomalySeverity(cat.type, items) : "ok";
      const sevColor = sev === "critical" ? "#dc2626" : sev === "warning" ? "#f97316" : sev === "info" ? "#3b82f6" : "#22c55e";
      const sevIcon = sev === "critical" ? "\u2757" : sev === "warning" ? "\u26A0" : sev === "info" ? "\u2139" : "\u2713";

      html += `<div class="gsm-anomaly-card" data-anomaly-type="${cat.type}" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;border-left:3px solid ${sevColor};transition:background .15s,box-shadow .15s">`;

      // Top bar
      html += `<div class="gsm-anomaly-bar" style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:rgba(${sev === 'critical' ? '220,38,38' : sev === 'warning' ? '249,115,22' : sev === 'info' ? '59,130,246' : '34,197,94'},.04)">`;
      html += `<span style="color:${sevColor};font-size:15px;flex-shrink:0">${sevIcon}</span>`;
      html += `<div style="flex:1;min-width:0">`;
      html += `<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap"><b>${cat.label}</b>`;
      if (!hasItems) {
        html += ` <span class="muted">\u2014 brak</span>`;
      } else {
        html += ` <span class="muted">(${items.length})</span>`;
      }
      html += `</div>`;
      html += `<div class="small muted" style="margin-top:1px;line-height:1.3">${cat.desc}</div>`;
      html += `</div>`;
      html += `</div>`;

      // Items body
      if (hasItems) {
        const needCollapse = items.length > VISIBLE;
        const collapsedH = VISIBLE * 24;
        html += `<div class="crypto-anom-items" data-type="${cat.type}" style="padding:4px 12px 8px;font-size:12px;line-height:1.8;${needCollapse ? 'max-height:' + collapsedH + 'px;overflow:hidden;' : ''}transition:max-height .25s ease">`;
        for (const item of items) {
          const ic = item.severity === "critical" ? "#dc2626" : item.severity === "warning" ? "#f97316" : "#3b82f6";
          html += `<div style="border-left:3px solid ${ic};padding:2px 8px;margin-bottom:2px;background:rgba(${item.severity === "critical" ? "220,38,38" : item.severity === "warning" ? "249,115,22" : "59,130,246"},.04);border-radius:4px">${item.html || _esc(item.text || "")}</div>`;
        }
        html += '</div>';
        if (needCollapse) {
          html += `<div style="text-align:center;padding:2px"><button class="crypto-anom-toggle small muted" data-type="${cat.type}" style="border:none;background:none;cursor:pointer;text-decoration:underline">Rozwiń (${items.length})</button></div>`;
        }
      }

      html += '</div>';
    }
    html += '</div>';
    body.innerHTML = html;

    // Bind expand/collapse
    body.querySelectorAll(".crypto-anom-toggle").forEach(btn => {
      btn.onclick = () => {
        const type = btn.dataset.type;
        const container = body.querySelector(`.crypto-anom-items[data-type="${type}"]`);
        if (!container) return;
        const isExpanded = container.dataset.expanded === "1";
        if (isExpanded) {
          container.style.maxHeight = (VISIBLE * 24) + "px";
          container.style.overflow = "hidden";
          container.dataset.expanded = "0";
          btn.textContent = `Rozwiń (${container.children.length})`;
        } else {
          container.style.maxHeight = container.scrollHeight + "px";
          container.style.overflow = "visible";
          container.dataset.expanded = "1";
          btn.textContent = "Zwiń";
        }
      };
    });
  }

  function _anomalySeverity(type, items) {
    if (type === "sanctioned_addr" || type === "privacy_coins") return items.length ? "critical" : "ok";
    if (type === "rapid_movement" || type === "high_value_tx") return items.length > 3 ? "warning" : items.length ? "info" : "ok";
    return items.length ? "info" : "ok";
  }

  function _detectCryptoAnomalies(r, txs, isExchange) {
    const result = {};

    // 1. Deposits & Withdrawals (chronological in/out from/to exchange)
    {
      const items = [];
      for (const tx of txs) {
        const type = (tx.tx_type || "").toLowerCase();
        const cat = (tx.category || "").toLowerCase();
        const isDeposit = type.includes("deposit") || cat.includes("deposit") || type === "receive" || type === "incoming";
        const isWithdraw = type.includes("withdraw") || cat.includes("withdraw") || type === "send" || type === "outgoing";
        if (isDeposit || isWithdraw) {
          const dir = isDeposit ? "\u2B07 Wpłata" : "\u2B06 Wypłata";
          const color = isDeposit ? "#22c55e" : "#ef4444";
          items.push({
            text: `${(tx.timestamp || "").slice(0, 16)} | ${dir} | ${_fmtCrypto(tx.amount, tx.token || "")}${tx.to ? " → " + _shorten(tx.to) : ""}${tx.from ? " ← " + _shorten(tx.from) : ""}`,
            html: `<span style="color:${color};font-weight:600">${dir}</span> ${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — <b>${_fmtCrypto(tx.amount, tx.token || "")}</b>${tx.to && !isDeposit ? ' → <code style="font-size:10px">' + _esc(_shorten(tx.to)) + '</code>' : ''}${tx.from && isDeposit ? ' ← <code style="font-size:10px">' + _esc(_shorten(tx.from)) + '</code>' : ''}`,
            severity: "info",
          });
        }
      }
      result.deposits_withdrawals = items;
    }

    // 2. High value transactions
    {
      const amounts = txs.map(tx => Math.abs(tx.amount || 0)).filter(a => a > 0);
      const mean = amounts.reduce((s, v) => s + v, 0) / (amounts.length || 1);
      const threshold = Math.max(mean * 5, 1000);
      result.high_value_tx = txs.filter(tx => Math.abs(tx.amount || 0) > threshold).map(tx => ({
        text: `${(tx.timestamp || "").slice(0, 16)} | ${_fmtCrypto(tx.amount, tx.token)} | ${tx.tx_type || ""}`,
        html: `${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — <b style="color:#ef4444">${_fmtCrypto(tx.amount, tx.token || "")}</b> (${_esc(tx.tx_type || "")})`,
        severity: "warning",
      }));
    }

    // 3. Rapid movement (deposit + withdrawal within 30min)
    {
      const items = [];
      const sorted = [...txs].sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || ""));
      for (let i = 0; i < sorted.length; i++) {
        const tx = sorted[i];
        const type = (tx.tx_type || "").toLowerCase();
        const cat = (tx.category || "").toLowerCase();
        const isDeposit = type.includes("deposit") || cat.includes("deposit") || type === "receive";
        if (!isDeposit) continue;
        const depositTime = new Date((tx.timestamp || "").replace(" ", "T"));
        if (isNaN(depositTime)) continue;
        // Look for withdrawal within 30min after
        for (let j = i + 1; j < sorted.length; j++) {
          const tx2 = sorted[j];
          const type2 = (tx2.tx_type || "").toLowerCase();
          const cat2 = (tx2.category || "").toLowerCase();
          const isWd = type2.includes("withdraw") || cat2.includes("withdraw") || type2 === "send";
          if (!isWd) continue;
          const wdTime = new Date((tx2.timestamp || "").replace(" ", "T"));
          if (isNaN(wdTime)) continue;
          const diffMin = (wdTime - depositTime) / 60000;
          if (diffMin > 0 && diffMin <= 30) {
            items.push({
              html: `Wpłata ${_fmtCrypto(tx.amount, tx.token)} → Wypłata ${_fmtCrypto(tx2.amount, tx2.token)} w ciągu <b>${Math.round(diffMin)} min</b> (${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))})`,
              severity: "warning",
            });
          }
          if (diffMin > 30) break;
        }
      }
      result.rapid_movement = items;
    }

    // 4. Round amounts
    {
      result.round_amounts = txs.filter(tx => {
        const a = Math.abs(tx.amount || 0);
        return a >= 100 && a === Math.round(a) && (a % 100 === 0 || a % 50 === 0);
      }).map(tx => ({
        html: `${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — <b>${_fmtCrypto(tx.amount, tx.token || "")}</b> (${_esc(tx.tx_type || "")})`,
        severity: "info",
      }));
    }

    // 5. Privacy coins / mixer
    {
      const privacyTokens = new Set(["XMR", "ZEC", "DASH", "SCRT"]);
      const mixerTags = ["mixer", "tornado", "privacy_coin"];
      result.privacy_coins = txs.filter(tx => {
        if (privacyTokens.has((tx.token || "").toUpperCase())) return true;
        return (tx.risk_tags || []).some(t => mixerTags.includes(t));
      }).map(tx => ({
        html: `${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — <b style="color:#dc2626">${_esc(tx.token || "?")}</b> ${_fmtCrypto(tx.amount, "")} (${_esc(tx.tx_type || "")})`,
        severity: "critical",
      }));
    }

    // 6. Inactivity gaps (>24h)
    {
      const sorted = [...txs].sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || ""));
      const items = [];
      for (let i = 1; i < sorted.length; i++) {
        const prev = new Date((sorted[i - 1].timestamp || "").replace(" ", "T"));
        const curr = new Date((sorted[i].timestamp || "").replace(" ", "T"));
        if (isNaN(prev) || isNaN(curr)) continue;
        const gapH = (curr - prev) / 3600000;
        if (gapH >= 24) {
          items.push({
            html: `<b>${Math.round(gapH)}h</b> przerwy: ${_esc((sorted[i-1].timestamp||"").slice(0,16).replace("T"," "))} → ${_esc((sorted[i].timestamp||"").slice(0,16).replace("T"," "))}`,
            severity: "info",
          });
        }
      }
      result.inactivity_gap = items;
    }

    // 7. Burst activity (>10 tx in 1h window)
    {
      const sorted = [...txs].sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || ""));
      const items = [];
      for (let i = 0; i < sorted.length; i++) {
        const t0 = new Date((sorted[i].timestamp || "").replace(" ", "T"));
        if (isNaN(t0)) continue;
        let count = 1;
        for (let j = i + 1; j < sorted.length; j++) {
          const t1 = new Date((sorted[j].timestamp || "").replace(" ", "T"));
          if (isNaN(t1) || (t1 - t0) > 3600000) break;
          count++;
        }
        if (count >= 10) {
          items.push({
            html: `<b>${count} transakcji</b> w ciągu 1h od ${_esc((sorted[i].timestamp||"").slice(0,16).replace("T"," "))}`,
            severity: "warning",
          });
          i += count - 1; // skip ahead
        }
      }
      result.burst_activity = items;
    }

    // 8. New / unknown tokens
    {
      const knownTokens = new Set(["BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "MATIC", "AVAX", "LINK", "DAI", "BUSD", "EUR", "USD", "PLN", "GBP"]);
      const unknownTxs = txs.filter(tx => tx.token && !knownTokens.has(tx.token.toUpperCase()));
      const byToken = {};
      for (const tx of unknownTxs) {
        const tok = tx.token.toUpperCase();
        if (!byToken[tok]) byToken[tok] = { count: 0, total: 0 };
        byToken[tok].count++;
        byToken[tok].total += Math.abs(tx.amount || 0);
      }
      result.new_token = Object.entries(byToken).map(([tok, d]) => ({
        html: `Token <b>${_esc(tok)}</b>: ${d.count} transakcji, wolumen ${d.total.toFixed(4)}`,
        severity: "info",
      }));
    }

    // 9. Cross-chain / bridge
    {
      const bridgeKeywords = ["bridge", "cross-chain", "swap", "wrap", "unwrap"];
      result.cross_chain = txs.filter(tx => {
        const haystack = [tx.tx_type, tx.category, ...(tx.risk_tags || [])].join(" ").toLowerCase();
        return bridgeKeywords.some(kw => haystack.includes(kw));
      }).map(tx => ({
        html: `${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — ${_esc(tx.tx_type || tx.category || "")} — ${_fmtCrypto(tx.amount, tx.token || "")}`,
        severity: "info",
      }));
    }

    // 10. Sanctioned addresses
    {
      result.sanctioned_addr = txs.filter(tx => (tx.risk_tags || []).includes("sanctioned")).map(tx => ({
        html: `<b style="color:#dc2626">SANCTIONED</b> ${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — ${_esc(tx.from || "")} → ${_esc(tx.to || "")} — ${_fmtCrypto(tx.amount, tx.token || "")}`,
        severity: "critical",
      }));
    }

    return result;
  }

  /* ------------------------------------------------------------------ */
  /*  Charts — main (dropdown selector like AML) + dual mode            */
  /* ------------------------------------------------------------------ */

  const PALETTE = ["#3b82f6", "#22c55e", "#f97316", "#ef4444", "#8b5cf6", "#06b6d4", "#eab308",
                   "#ec4899", "#14b8a6", "#a855f7", "#f43f5e", "#84cc16"];

  async function _renderCharts(r, isExchange) {
    try { await _ensureChartJS(); } catch (e) { console.warn("[Crypto] Chart.js load failed:", e); return; }

    // Update dropdown options based on mode
    const chartSelect = QS("#crypto_chart_select");
    if (chartSelect) {
      const opts = isExchange
        ? [["balance_timeline","Saldo w czasie"],["monthly_volume","Wolumen miesięczny"],["daily_tx_count","Aktywność dzienna"],["fiat_flow","Przepływy fiatowe"],["token_breakdown","Wolumen per token"],["top_operations","Rozkład operacji"]]
        : [["balance_timeline","Saldo w czasie"],["monthly_volume","Wolumen miesięczny"],["daily_tx_count","Aktywność dzienna"],["top_counterparties","Top kontrahenci"]];

      chartSelect.innerHTML = "";
      for (const [val, label] of opts) {
        const o = document.createElement("option");
        o.value = val;
        o.textContent = label;
        chartSelect.appendChild(o);
      }
    }

    const chartKey = (chartSelect || {}).value || "balance_timeline";
    _renderMainChart(r, chartKey, isExchange);
  }

  function _renderMainChart(r, chartKey, isExchange) {
    const charts = r.charts || {};
    const container = document.getElementById("crypto_chart_container");
    if (!container) return;

    // Destroy previous
    if (_mainChartInstance) { try { _mainChartInstance.destroy(); } catch (_) {} _mainChartInstance = null; }

    container.innerHTML = '<canvas id="crypto_chart_main"></canvas>';
    const canvas = QS("#crypto_chart_main");
    if (!canvas) return;

    const data = charts[chartKey];
    if (!data) {
      container.innerHTML = '<div class="small muted" style="padding:20px">Brak danych wykresu</div>';
      return;
    }

    const isTimeline = (chartKey === "balance_timeline");

    // Zoom controls
    const zoomBar = document.getElementById("crypto_chart_zoom_bar");
    if (zoomBar) {
      zoomBar.style.display = (isTimeline && data.labels && data.labels.length > 30) ? "" : "none";
    }

    if (chartKey === "balance_timeline") {
      _renderBalanceTimeline(canvas, data, isExchange);
    } else if (chartKey === "monthly_volume") {
      _renderBarChart(canvas, data, ["rgba(34,197,94,0.7)", "rgba(239,68,68,0.7)"]);
    } else if (chartKey === "daily_tx_count") {
      _renderBarChart(canvas, data, ["rgba(139,92,246,0.7)"]);
    } else if (chartKey === "top_counterparties") {
      _renderHorizontalBarChart(canvas, data);
    } else if (chartKey === "fiat_flow") {
      _renderFiatFlowChart(canvas, data);
    } else if (chartKey === "token_breakdown") {
      _renderHorizontalBarChart(canvas, data);
    } else if (chartKey === "top_operations") {
      _renderDoughnutChart(canvas, data);
    }
  }

  function _renderBalanceTimeline(canvas, data, isExchange) {
    if (!data || !data.labels || !data.labels.length) return;

    const labels = data.labels;
    let datasets;
    let scales = {};

    if (isExchange && data.datasets && data.datasets.length) {
      // Exchange: multi-token balance lines
      // Detect if tokens have vastly different scales → use normalized % view
      const maxPerToken = data.datasets.map(ds => {
        const vals = (ds.data || []).map(v => Math.abs(v || 0));
        return Math.max(...vals, 0.0001);
      });
      const globalMax = Math.max(...maxPerToken);
      const globalMin = Math.min(...maxPerToken);
      const needsNormalization = globalMax > 0 && globalMin > 0 && (globalMax / globalMin) > 50;

      if (needsNormalization) {
        // Normalize each token to % of its own max for visibility
        datasets = data.datasets.map((ds, i) => {
          const tokenMax = maxPerToken[i] || 1;
          return {
            label: ds.token + " (%)",
            data: (ds.data || []).map(v => ((v || 0) / tokenMax) * 100),
            _rawData: ds.data,
            _tokenMax: tokenMax,
            _token: ds.token,
            borderColor: PALETTE[i % PALETTE.length],
            backgroundColor: PALETTE[i % PALETTE.length] + "22",
            fill: false,
            tension: 0.3,
            pointRadius: labels.length > 50 ? 0 : 2,
            pointHoverRadius: 6,
            pointHitRadius: 10,
          };
        });
        scales = {
          x: { ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: _adaptiveTickCount(labels.length) } },
          y: {
            beginAtZero: true,
            max: 105,
            title: { display: true, text: "% maksimum tokena" },
            ticks: { callback: v => v + "%" },
          },
        };
      } else {
        datasets = data.datasets.map((ds, i) => ({
          label: ds.token,
          data: ds.data,
          borderColor: PALETTE[i % PALETTE.length],
          backgroundColor: PALETTE[i % PALETTE.length] + "22",
          fill: false,
          tension: 0.3,
          pointRadius: labels.length > 50 ? 0 : 2,
          pointHoverRadius: 6,
          pointHitRadius: 10,
        }));
        scales = {
          x: { ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: _adaptiveTickCount(labels.length) } },
          y: { beginAtZero: false },
        };
      }
    } else {
      // Blockchain: single balance line
      datasets = [{
        label: data.label || "Saldo",
        data: data.data,
        borderColor: "#3b82f6",
        backgroundColor: "rgba(59,130,246,0.1)",
        fill: true,
        tension: 0.3,
        pointRadius: labels.length > 50 ? 0 : 2,
        pointHoverRadius: 6,
        pointHitRadius: 10,
      }];
      scales = {
        x: { ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: _adaptiveTickCount(labels.length) } },
        y: { beginAtZero: false },
      };
    }

    _mainChartInstance = new Chart(canvas, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false, axis: "x" },
        plugins: {
          legend: { display: datasets.length > 1 },
          tooltip: {
            callbacks: {
              title: function(items) { return items[0] ? items[0].label : ""; },
              label: function(ctx) {
                const ds = ctx.dataset;
                // If normalized, show real value in tooltip
                if (ds._rawData) {
                  const realVal = ds._rawData[ctx.dataIndex];
                  return ds._token + ": " + _fmtCrypto(realVal, "") + " (" + ctx.parsed.y.toFixed(1) + "%)";
                }
                return (ds.label || "Saldo") + ": " + _fmtCrypto(ctx.parsed.y, "");
              },
            },
          },
        },
        scales,
      },
    });

    _applyTimelineZoom();
  }

  function _renderBarChart(canvas, data, colors) {
    if (!data || !data.labels) return;

    const datasets = [];
    if (data.received && data.sent) {
      datasets.push({ label: "Otrzymane", data: data.received, backgroundColor: colors[0] || "rgba(34,197,94,0.7)" });
      datasets.push({ label: "Wysłane", data: data.sent, backgroundColor: colors[1] || "rgba(239,68,68,0.7)" });
    } else if (data.data) {
      datasets.push({ label: data.label || "Wartość", data: data.data, backgroundColor: colors[0] || "rgba(139,92,246,0.7)" });
    }

    _mainChartInstance = new Chart(canvas, {
      type: "bar",
      data: { labels: data.labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: datasets.length > 1 } },
        scales: {
          x: { ticks: { maxRotation: 45 } },
          y: { beginAtZero: true },
        },
      },
    });
  }

  function _renderHorizontalBarChart(canvas, data) {
    if (!data || !data.labels) return;

    _mainChartInstance = new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [{
          label: "Wolumen",
          data: data.data,
          backgroundColor: data.labels.map((_, i) => PALETTE[i % PALETTE.length]),
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: "y",
        plugins: { legend: { display: false } },
      },
    });
  }

  function _renderFiatFlowChart(canvas, data) {
    if (!data || !data.labels) return;

    _mainChartInstance = new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [
          { label: "Wpłaty fiat", data: data.deposits, backgroundColor: "rgba(34,197,94,0.7)" },
          { label: "Wypłaty fiat", data: data.withdrawals, backgroundColor: "rgba(239,68,68,0.7)" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true } },
        scales: {
          x: { ticks: { maxRotation: 45 } },
          y: { beginAtZero: true },
        },
      },
    });
  }

  function _renderDoughnutChart(canvas, data) {
    if (!data || !data.labels) return;

    _mainChartInstance = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: data.labels,
        datasets: [{
          data: data.data,
          backgroundColor: data.labels.map((_, i) => PALETTE[i % PALETTE.length]),
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } } },
      },
    });
  }

  function _adaptiveTickCount(labelCount) {
    if (labelCount > 200) return 15;
    if (labelCount > 100) return 20;
    if (labelCount > 50) return 25;
    return labelCount;
  }

  /* -- Zoom for balance timeline ------------------------------------- */

  function _applyTimelineZoom() {
    const container = document.getElementById("crypto_chart_container");
    if (!container) return;
    if (_chartZoom.level <= 1) {
      container.style.width = "";
      container.style.minWidth = "100%";
    } else {
      container.style.width = (_chartZoom.level * 100) + "%";
      container.style.minWidth = (_chartZoom.level * 100) + "%";
    }
    if (_mainChartInstance) _mainChartInstance.resize();
  }

  function _chartZoomStep(delta) {
    _chartZoom.level = Math.max(1, Math.min(10, _chartZoom.level + delta));
    _applyTimelineZoom();
  }

  /* -- Small charts (3 side by side) --------------------------------- */

  async function _renderSmallCharts(r, isExchange) {
    try { await _ensureChartJS(); } catch (e) { return; }

    const charts = r.charts || {};

    // Destroy old small charts
    for (const key of Object.keys(_smallChartInstances)) {
      try { _smallChartInstances[key].destroy(); } catch (_) {}
    }
    _smallChartInstances = {};

    const smallOpts = {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } },
    };

    // 1. TX type distribution (doughnut)
    const types = charts.tx_type_distribution;
    const typesCanvas = QS("#crypto_chart_types");
    if (types && types.labels && types.labels.length && typesCanvas) {
      _smallChartInstances.types = new Chart(typesCanvas, {
        type: "doughnut",
        data: {
          labels: types.labels,
          datasets: [{ data: types.data, backgroundColor: types.labels.map((_, i) => PALETTE[i % PALETTE.length]) }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } } },
        },
      });
    }

    // 2. Monthly volume (small bar)
    const vol = charts.monthly_volume;
    const volCanvas = QS("#crypto_chart_volume_small");
    if (vol && vol.labels && vol.labels.length && volCanvas) {
      const ds = [];
      if (vol.received && vol.sent) {
        ds.push({ label: "Otr.", data: vol.received, backgroundColor: "rgba(34,197,94,0.7)" });
        ds.push({ label: "Wys.", data: vol.sent, backgroundColor: "rgba(239,68,68,0.7)" });
      }
      _smallChartInstances.volume = new Chart(volCanvas, {
        type: "bar",
        data: { labels: vol.labels, datasets: ds },
        options: { ...smallOpts, scales: { x: { ticks: { maxRotation: 45, font: { size: 9 } } }, y: { beginAtZero: true } } },
      });
    }

    // 3. Daily TX count (small bar)
    const daily = charts.daily_tx_count;
    const dailyCanvas = QS("#crypto_chart_daily_small");
    if (daily && daily.labels && daily.labels.length && dailyCanvas) {
      _smallChartInstances.daily = new Chart(dailyCanvas, {
        type: "bar",
        data: {
          labels: daily.labels,
          datasets: [{ label: "TX", data: daily.data, backgroundColor: "rgba(139,92,246,0.7)" }],
        },
        options: { ...smallOpts, scales: { x: { ticks: { maxRotation: 45, font: { size: 9 } } }, y: { beginAtZero: true } } },
      });
    }
  }

  function _destroyAllCharts() {
    if (_mainChartInstance) { try { _mainChartInstance.destroy(); } catch (_) {} _mainChartInstance = null; }
    for (const key of Object.keys(_smallChartInstances)) {
      try { _smallChartInstances[key].destroy(); } catch (_) {}
    }
    _smallChartInstances = {};
  }

  /* -- Wallets table (blockchain only) -------------------------------- */

  function _renderWallets(r) {
    const wallets = r.wallets || [];
    if (!wallets.length) { _hide("crypto_wallets_card"); return; }
    _show("crypto_wallets_card");

    let html = '<table class="data-table" style="width:100%;font-size:13px"><thead><tr>' +
      "<th>Adres</th><th>Etykieta</th><th>TX</th><th>Otrzymane</th><th>Wysłane</th><th>Ryzyko</th>" +
      "</tr></thead><tbody>";
    for (const w of wallets.slice(0, 50)) {
      const rc = RISK_COLORS[w.risk_level] || "#94a3b8";
      html += `<tr>
        <td style="font-family:monospace;font-size:11px" title="${_esc(w.address)}">${_esc(_shorten(w.address))}</td>
        <td>${_esc(w.label || "\u2014")}</td>
        <td>${w.tx_count}</td>
        <td>${_fmtCrypto(w.total_received, "")}</td>
        <td>${_fmtCrypto(w.total_sent, "")}</td>
        <td style="color:${rc};font-weight:600">${_esc(w.risk_level)}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    if (wallets.length > 50) html += `<div class="small" style="margin-top:4px;color:var(--text-muted)">Pokazano 50 z ${wallets.length}</div>`;
    _html("crypto_wallets_body", html);
  }

  /* ------------------------------------------------------------------ */
  /*  Cytoscape.js flow graph (blockchain only)                         */
  /* ------------------------------------------------------------------ */

  async function _renderGraph(r) {
    const graphData = r.graph;
    if (!graphData || !graphData.nodes || !graphData.nodes.length) {
      _hide("crypto_graph_card");
      return;
    }
    _show("crypto_graph_card");

    try {
      await _ensureCytoscape();
    } catch (e) {
      console.warn("[Crypto] Cytoscape load failed:", e);
      return;
    }

    if (_cyInstance) { try { _cyInstance.destroy(); } catch (_) {} }

    const container = QS("#crypto_graph_container");
    if (!container) return;

    const elements = [];

    // Nodes
    for (const node of graphData.nodes) {
      const d = node.data;
      const color = RISK_COLORS[d.risk_level] || "#64748b";
      let shape = "ellipse";
      if (d.type === "mixer") shape = "diamond";
      else if (d.type === "exchange") shape = "round-rectangle";

      elements.push({
        group: "nodes",
        data: {
          id: d.id,
          label: d.label || d.id.slice(0, 10),
          color: color,
          shape: shape,
          size: Math.max(20, Math.min(60, 20 + (d.tx_count || 0) * 2)),
        },
      });
    }

    // Edges
    for (const edge of graphData.edges) {
      const d = edge.data;
      elements.push({
        group: "edges",
        data: {
          source: d.source,
          target: d.target,
          label: _fmtCrypto(d.amount, d.token || ""),
          width: Math.max(1, Math.min(6, d.count || 1)),
          color: d.risk ? "#ef4444" : "#475569",
        },
      });
    }

    _cyInstance = cytoscape({
      container: container,
      elements: elements,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "label": "data(label)",
            "color": "#e2e8f0",
            "font-size": "10px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            "width": "data(size)",
            "height": "data(size)",
            "shape": "data(shape)",
            "border-width": 1,
            "border-color": "#334155",
          },
        },
        {
          selector: "edge",
          style: {
            "line-color": "data(color)",
            "target-arrow-color": "data(color)",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "width": "data(width)",
            "label": "data(label)",
            "font-size": "8px",
            "color": "#94a3b8",
            "text-rotation": "autorotate",
            "text-margin-y": -8,
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        nodeRepulsion: 8000,
        idealEdgeLength: 120,
        nodeOverlap: 30,
      },
    });
  }

  /* ------------------------------------------------------------------ */
  /*  LLM narrative streaming                                           */
  /* ------------------------------------------------------------------ */

  async function _generateLLM() {
    if (_llmRunning) return;
    if (!_lastResult) return;

    _llmRunning = true;
    _show("crypto_llm_progress");
    _text("crypto_llm_progress_text", "Generowanie...");
    _html("crypto_llm_text", "");
    const bar = QS("#crypto_llm_bar");
    if (bar) bar.style.width = "5%";

    const model = (QS("#crypto_model_deep") || {}).value || "";
    const pid = _getProjectId();

    const params = new URLSearchParams({ model, project_id: pid });

    try {
      const resp = await fetch(`/api/crypto/llm-stream?${params}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let chunks = 0;
      const textEl = QS("#crypto_llm_text");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const lines = buf.split("\n");
        buf = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));

            if (ev.error) {
              if (textEl) textEl.innerHTML += `<div style="color:#ef4444">${_esc(ev.error)}</div>`;
              break;
            }

            if (ev.chunk && textEl) {
              chunks++;
              textEl.innerHTML += ev.chunk
                .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                .replace(/\n/g, "<br>");

              const pct = Math.min(95, 5 + 90 * (1 - 1 / (1 + chunks * 0.02)));
              if (bar) bar.style.width = pct + "%";
            }

            if (ev.done) {
              if (bar) bar.style.width = "100%";
              _text("crypto_llm_progress_text", "Gotowe");
              _text("crypto_llm_status", `${chunks} fragmentów`);
              setTimeout(() => _hide("crypto_llm_progress"), 2000);
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      _text("crypto_llm_progress_text", `Błąd: ${e.message}`);
      console.error("[Crypto] LLM stream error:", e);
    } finally {
      _llmRunning = false;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Utility                                                           */
  /* ------------------------------------------------------------------ */

  function _shorten(addr) {
    if (!addr) return "\u2014";
    if (addr.length > 18) return addr.slice(0, 8) + "\u2026" + addr.slice(-6);
    return addr;
  }

  /* ------------------------------------------------------------------ */
  /*  Event binding                                                     */
  /* ------------------------------------------------------------------ */

  function _bind() {
    // File upload
    const fileInput = QS("#crypto_file_input");
    const uploadBtn = QS("#crypto_add_file_toolbar_btn");

    if (uploadBtn) {
      uploadBtn.onclick = () => { if (fileInput) fileInput.click(); };
    }

    if (fileInput) {
      fileInput.onchange = () => {
        if (fileInput.files && fileInput.files.length > 0) {
          _uploadFile(fileInput.files[0]);
          fileInput.value = "";
        }
      };
    }

    // LLM generate
    const genBtn = QS("#crypto_generate_btn");
    if (genBtn) {
      genBtn.onclick = () => _generateLLM();
    }

    // Chart selector (dropdown)
    const chartSelect = QS("#crypto_chart_select");
    if (chartSelect) {
      chartSelect.onchange = () => {
        if (_lastResult) {
          _chartZoom.level = 1;
          const isEx = _lastResult.source_type === "exchange";
          _renderMainChart(_lastResult, chartSelect.value, isEx);
        }
      };
    }

    // Zoom controls
    const zoomIn = document.getElementById("crypto_chart_zoom_in");
    const zoomOut = document.getElementById("crypto_chart_zoom_out");
    const zoomReset = document.getElementById("crypto_chart_zoom_reset");
    if (zoomIn) zoomIn.onclick = () => _chartZoomStep(0.5);
    if (zoomOut) zoomOut.onclick = () => _chartZoomStep(-0.5);
    if (zoomReset) zoomReset.onclick = () => { _chartZoom.level = 1; _applyTimelineZoom(); };

    // Review filters
    const rvSearch = QS("#crypto_rv_search");
    const rvFilterCls = QS("#crypto_rv_filter_class");
    const rvFilterRisk = QS("#crypto_rv_filter_risk");
    const refilter = () => {
      if (_lastResult) _filterAndRenderReview(_lastResult.transactions || [], _lastResult.source_type === "exchange");
    };
    if (rvSearch) rvSearch.oninput = refilter;
    if (rvFilterCls) rvFilterCls.onchange = refilter;
    if (rvFilterRisk) rvFilterRisk.onchange = refilter;
  }

  /* ------------------------------------------------------------------ */
  /*  Public Manager (lazy init)                                        */
  /* ------------------------------------------------------------------ */

  window.CryptoManager = {
    _initialized: false,
    async init() {
      if (this._initialized) return;
      this._initialized = true;
      _bind();
      _loadModels();

      // Auto-load saved analysis
      try {
        await _loadFromProject();
      } catch (e) {
        console.warn("[Crypto] Auto-load failed:", e);
      }
    },
  };
})();
