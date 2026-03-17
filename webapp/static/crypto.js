/**
 * Crypto Analysis Module — CryptoManager
 *
 * Lazy-initialized when the Crypto tab is first clicked.
 * Handles CSV upload, results rendering, Chart.js charts,
 * Cytoscape.js flow graph, and LLM narrative streaming.
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
  /*  Render results                                                    */
  /* ------------------------------------------------------------------ */

  function _renderResults(r) {
    _hide("crypto_empty_state");
    _show("crypto_results");

    _renderSummary(r);
    _renderRisk(r);
    _renderAlerts(r);
    _renderReviewTable(r);
    _renderCharts(r);
    _renderSmallCharts(r);
    _renderGraph(r);
    _renderWallets(r);
  }

  /* -- Summary (light fields like AML/GSM) ----------------------------- */

  function _renderSummary(r) {
    const token = Object.keys(r.tokens || {})[0] || "BTC";

    // Info rows (like AML bank info)
    const infoGrid = document.getElementById("crypto_info_grid");
    if (infoGrid) {
      let html = "";
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
      if (r.elapsed_sec) html += `<div class="small muted" style="margin-top:4px">Czas analizy: ${r.elapsed_sec.toFixed(1)}s</div>`;
      infoGrid.innerHTML = html;
    }

    // Stat cards (like GSM)
    const cards = [];
    if (r.tx_count) cards.push(["Transakcje", r.tx_count]);
    if (r.wallet_count) cards.push(["Portfele", r.wallet_count]);
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
  /*  Transaction Review & Classification                               */
  /* ------------------------------------------------------------------ */

  function _renderReviewTable(r) {
    const txs = r.transactions || [];
    const totalCount = r.transactions_total || txs.length;

    _renderReviewStats(txs);
    _filterAndRenderReview(txs);
  }

  function _renderReviewStats(txs) {
    const counts = { neutral: 0, legitimate: 0, suspicious: 0, monitoring: 0, unclassified: 0 };
    for (const tx of txs) {
      const cls = _txClassifications[tx.hash || tx.id] || _autoClassify(tx);
      if (counts[cls] != null) counts[cls]++;
      else counts.unclassified++;
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

  function _filterAndRenderReview(txs) {
    const search = (QS("#crypto_rv_search") || {}).value || "";
    const filterCls = (QS("#crypto_rv_filter_class") || {}).value || "";
    const filterRisk = (QS("#crypto_rv_filter_risk") || {}).value || "";
    const searchLow = search.toLowerCase();

    const filtered = txs.filter(tx => {
      // Classification filter
      const cls = _txClassifications[tx.hash || tx.id] || _autoClassify(tx);
      if (filterCls && cls !== filterCls) return false;

      // Risk filter
      if (filterRisk) {
        const tags = tx.risk_tags || [];
        const score = tx.risk_score || 0;
        let riskLevel = "low";
        if (score >= 70 || tags.includes("sanctioned")) riskLevel = "critical";
        else if (score >= 50 || tags.includes("mixer")) riskLevel = "high";
        else if (score >= 25 || tags.includes("high_value")) riskLevel = "medium";
        if (riskLevel !== filterRisk) return false;
      }

      // Text search
      if (searchLow) {
        const haystack = [tx.from, tx.to, tx.hash, tx.token, tx.tx_type, ...(tx.risk_tags || [])].join(" ").toLowerCase();
        if (!haystack.includes(searchLow)) return false;
      }

      return true;
    });

    _text("crypto_rv_tx_count", `${filtered.length} z ${txs.length} transakcji`);

    const wrap = document.getElementById("crypto_rv_table_wrap");
    if (!wrap) return;

    const show = filtered.slice(0, 200);
    let html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
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

      html += `<tr style="background:${meta.bg}">
        <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16))}</td>
        <td style="font-family:monospace;font-size:10px" title="${_esc(tx.from || "")}">${_esc(_shorten(tx.from || "\u2014"))}</td>
        <td style="font-family:monospace;font-size:10px" title="${_esc(tx.to || "")}">${_esc(_shorten(tx.to || "\u2014"))}</td>
        <td style="text-align:right">${_fmtCrypto(tx.amount, "")}</td>
        <td>${_esc(tx.token || "")}</td>
        <td>${_esc(tx.tx_type || "")}</td>
        <td style="color:${tagColor};font-size:11px">${_esc(tags || "\u2014")}</td>
        <td style="white-space:nowrap">`;

      // Classification buttons
      for (const [key, m] of Object.entries(CLS_META)) {
        const isActive = cls === key;
        html += `<button class="crypto-rv-cls-btn${isActive ? " active" : ""}" data-tx="${_esc(txId)}" data-cls="${key}" style="color:${m.color};${isActive ? "background:" + m.bg : ""}" title="${m.label}">${m.label.charAt(0)}</button>`;
      }

      html += `</td></tr>`;
    }

    html += "</tbody></table>";
    if (show.length < filtered.length) {
      html += `<div class="small muted" style="margin-top:4px">Pokazano ${show.length} z ${filtered.length}</div>`;
    }

    wrap.innerHTML = html;

    // Bind classification buttons
    wrap.querySelectorAll(".crypto-rv-cls-btn").forEach(btn => {
      btn.onclick = () => {
        const txId = btn.dataset.tx;
        const cls = btn.dataset.cls;
        _txClassifications[txId] = cls;
        _renderReviewTable(_lastResult);
      };
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Charts — main (dropdown selector like AML)                        */
  /* ------------------------------------------------------------------ */

  async function _renderCharts(r) {
    try { await _ensureChartJS(); } catch (e) { console.warn("[Crypto] Chart.js load failed:", e); return; }

    // Render the currently selected chart
    const chartKey = (QS("#crypto_chart_select") || {}).value || "balance_timeline";
    _renderMainChart(r, chartKey);
  }

  function _renderMainChart(r, chartKey) {
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
      if (isTimeline && data.labels && data.labels.length > 30) {
        zoomBar.style.display = "";
      } else {
        zoomBar.style.display = "none";
      }
    }

    if (chartKey === "balance_timeline") {
      _renderBalanceTimeline(canvas, data);
    } else if (chartKey === "monthly_volume") {
      _renderBarChart(canvas, data, ["rgba(34,197,94,0.7)", "rgba(239,68,68,0.7)"]);
    } else if (chartKey === "daily_tx_count") {
      _renderBarChart(canvas, data, ["rgba(139,92,246,0.7)"]);
    } else if (chartKey === "top_counterparties") {
      _renderCounterpartiesChart(canvas, data);
    }
  }

  function _renderBalanceTimeline(canvas, data) {
    if (!data || !data.labels || !data.labels.length) return;

    const labels = data.labels;
    _mainChartInstance = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [{
          label: data.label || "Saldo",
          data: data.data,
          borderColor: "#3b82f6",
          backgroundColor: "rgba(59,130,246,0.1)",
          fill: true,
          tension: 0.3,
          pointRadius: labels.length > 50 ? 0 : 2,
          pointHoverRadius: 6,
          pointHitRadius: 10,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false, axis: "x" },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function(items) {
                return items[0] ? items[0].label : "";
              },
              label: function(ctx) {
                return "Saldo: " + _fmtCrypto(ctx.parsed.y, "");
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              maxRotation: 45,
              autoSkip: true,
              maxTicksLimit: _adaptiveTickCount(labels.length),
            },
          },
          y: { beginAtZero: false },
        },
        elements: {
          point: { radius: labels.length > 50 ? 0 : 2, hoverRadius: 6, hitRadius: 10 },
        },
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

  function _renderCounterpartiesChart(canvas, data) {
    if (!data || !data.labels) return;

    _mainChartInstance = new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [{ label: "Wolumen", data: data.data, backgroundColor: "rgba(59,130,246,0.7)" }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: "y",
        plugins: { legend: { display: false } },
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

  async function _renderSmallCharts(r) {
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
      const doughnutColors = ["#3b82f6", "#22c55e", "#f97316", "#ef4444", "#8b5cf6", "#06b6d4", "#eab308"];
      _smallChartInstances.types = new Chart(typesCanvas, {
        type: "doughnut",
        data: {
          labels: types.labels,
          datasets: [{ data: types.data, backgroundColor: types.labels.map((_, i) => doughnutColors[i % doughnutColors.length]) }],
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

  /* ------------------------------------------------------------------ */
  /*  Wallets table                                                     */
  /* ------------------------------------------------------------------ */

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
  /*  Cytoscape.js flow graph                                           */
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
          _renderMainChart(_lastResult, chartSelect.value);
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
    const refilter = () => { if (_lastResult) _filterAndRenderReview(_lastResult.transactions || []); };
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
