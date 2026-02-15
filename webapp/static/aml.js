// AML Analysis UI module (AISTATEweb)
// Depends on /static/app.js helpers: api(), AISTATE

(function(){
  "use strict";

  const QS  = (sel, root=document) => root.querySelector(sel);
  const QSA = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  function _esc(s){
    const d = document.createElement("div");
    d.textContent = String(s || "");
    return d.innerHTML;
  }

  function _fmtAmount(v, currency){
    if(v == null || v === "") return "\u2014";
    const n = Number(v);
    if(isNaN(n)) return String(v);
    return n.toLocaleString("pl-PL", {minimumFractionDigits:2, maximumFractionDigits:2}) + " " + (currency || "PLN");
  }

  function _fmtDate(iso){
    if(!iso) return "";
    return String(iso).replace("T"," ").replace("Z","").slice(0,16);
  }

  async function _api(url, opts){
    return await api(url, opts);
  }
  async function _safeApi(url, opts){
    try{ return await api(url, opts); }catch(e){ return null; }
  }

  // ============================================================
  // STATE
  // ============================================================

  const St = {
    analyzing: false,
    lastResult: null,     // from POST /api/aml/analyze
    detail: null,         // from GET /api/aml/detail/{id}
    statementId: null,
    caseId: null,
    history: [],
    cyInstance: null,      // Cytoscape.js instance
    chartInstance: null,   // Chart.js instance
    chartsData: {},        // all chart datasets
    allTransactions: [],   // current transactions for filtering
    cyLoaded: false,
    chartjsLoaded: false,
    llmRunning: false,
    // Batch upload state
    batchMode: false,
    batchFiles: [],        // [{file, name, status, statementId, error, preview}]
    batchIdx: -1,          // current file index being processed
    batchCaseId: "",       // shared case_id for batch
    batchResults: [],      // statement IDs of successfully processed files
  };

  // ============================================================
  // UPLOAD & ANALYZE
  // ============================================================

  function _showUpload(){
    _show("aml_upload_zone");
    _hide("aml_progress_card");
    _hide("aml_results");
    if(!St.batchMode) _hide("aml_batch_panel");
    const histCard = QS("#aml_history_card");
    if(histCard && St.history.length) _show("aml_history_card");
  }

  function _showProgress(text){
    _hide("aml_upload_zone");
    _show("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    if(!St.batchMode) _hide("aml_batch_panel");
    const el = QS("#aml_prog_text");
    if(el) el.textContent = text || "Przetwarzanie PDF...";
    const bar = QS("#aml_prog_bar");
    if(bar) bar.style.width = "0%";
  }

  function _showResults(){
    _hide("aml_upload_zone");
    _hide("aml_progress_card");
    _show("aml_results");
    _hide("aml_history_card");
    _hide("aml_batch_panel");
  }

  function _showBatchPanel(){
    _hide("aml_upload_zone");
    _hide("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    _show("aml_batch_panel");
  }

  function _showError(msg){
    _hide("aml_progress_card");
    _show("aml_upload_zone");
    const inner = QS("#aml_drop_area");
    if(inner){
      const errDiv = inner.querySelector(".aml-error");
      if(errDiv) errDiv.remove();
      const d = document.createElement("div");
      d.className = "small aml-error";
      d.style.color = "var(--danger)";
      d.style.marginTop = "10px";
      d.textContent = msg;
      inner.appendChild(d);
      setTimeout(()=> d.remove(), 8000);
    }
  }

  async function _uploadAndAnalyze(file){
    if(!file || St.analyzing) return;
    if(!file.name.toLowerCase().endsWith(".pdf")){
      _showError("Tylko pliki PDF sa obslugiwane.");
      return;
    }

    St.analyzing = true;
    _showProgress("Analiza AML...");

    const fd = new FormData();
    fd.append("file", file, file.name);

    let pct = 0;
    const bar = QS("#aml_prog_bar");
    const progText = QS("#aml_prog_text");
    const progTimer = setInterval(()=>{
      pct = Math.min(pct + Math.random() * 8, 90);
      if(bar) bar.style.width = pct + "%";
    }, 800);

    const stages = [
      "Parsowanie transakcji...",
      "Klasyfikacja regul...",
      "Detekcja anomalii...",
      "Budowa grafu...",
      "Generowanie raportu..."
    ];
    let stageIdx = 0;
    const stageTimer = setInterval(()=>{
      stageIdx++;
      if(stageIdx < stages.length && progText){
        progText.textContent = stages[stageIdx];
      }
    }, 2500);

    try{
      const controller = new AbortController();
      const timeoutId = setTimeout(()=> controller.abort(), 120000);

      let result;
      try {
        result = await _api("/api/aml/analyze", {method:"POST", body:fd, signal: controller.signal});
      } finally {
        clearTimeout(timeoutId);
      }

      clearInterval(progTimer);
      clearInterval(stageTimer);

      if(result && result.status === "ok"){
        St.lastResult = result;
        St.statementId = result.statement_id;
        St.caseId = result.case_id;

        await _loadDetail(result.statement_id);
        _renderResults();
        _showResults();

        if(window.ReviewManager && result.statement_id){
          ReviewManager.loadForStatement(result.statement_id);
        }
      } else {
        clearInterval(progTimer);
        clearInterval(stageTimer);
        let errMsg = result && result.error ? String(result.error) : "Blad analizy";
        if(errMsg === "no_transactions"){
          errMsg = "Nie znaleziono transakcji w dokumencie.";
        }
        _showError(errMsg);
      }
    } catch(e) {
      clearInterval(progTimer);
      clearInterval(stageTimer);
      _showError("Blad: " + String(e.message || e));
    } finally {
      St.analyzing = false;
    }
  }

  /** Run AML pipeline for a file that's already uploaded (used by batch processing). */
  async function _runPipelineForFile(file, caseId){
    const fd = new FormData();
    fd.append("file", file, file.name);
    if(caseId) fd.append("case_id", caseId);

    const controller = new AbortController();
    const timeoutId = setTimeout(()=> controller.abort(), 120000);

    try {
      return await _api("/api/aml/analyze", {method:"POST", body:fd, signal: controller.signal});
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // ============================================================
  // LOAD DATA
  // ============================================================

  async function _loadDetail(statementId){
    const data = await _safeApi("/api/aml/detail/" + encodeURIComponent(statementId));
    if(data && data.statement){
      St.detail = data;
      St.statementId = statementId;
      St.caseId = data.statement.case_id;
      St.allTransactions = data.transactions || [];
    }
    return data;
  }

  async function _loadHistory(){
    const data = await _safeApi("/api/aml/history?limit=20");
    if(data && Array.isArray(data.items)){
      St.history = data.items;
    }
    _renderHistory();
  }

  // ============================================================
  // RENDER RESULTS
  // ============================================================

  function _renderResults(){
    if(!St.detail && !St.lastResult) return;

    const result = St.lastResult || {};
    const detail = St.detail || {};
    const stmt = detail.statement || {};
    const risk = detail.risk || {};
    const transactions = detail.transactions || [];
    const graph = detail.graph || {nodes:[], edges:[], stats:{}};

    // Risk score
    const score = risk.total_score != null ? risk.total_score : (result.risk_score || 0);
    _renderRiskGauge(score);

    // Bank info (merged with header fields: salda, IBAN, period, currency)
    _renderBankInfo(stmt, result);

    // Alerts
    const alerts = risk.score_breakdown && risk.score_breakdown.alerts
      ? risk.score_breakdown.alerts
      : (result.alerts || []);
    _renderAlerts(alerts);

    // Note: ReviewManager is loaded by the caller (single-file or batch flow)
    // to avoid race conditions — do NOT call loadForStatement here.

    // Charts
    const charts = detail.charts || result.charts || {};
    St.chartsData = charts;
    _renderChart("balance_timeline");

    // ML anomalies
    const mlAnomalies = detail.ml_anomalies || [];
    _renderMlAnomalies(mlAnomalies, transactions);

    // Graph
    _renderGraph(graph);

    // LLM section
    _setupLlmSection(detail.has_llm_prompt || result.has_llm_prompt);
  }

  function _renderRiskGauge(score){
    const s = Math.max(0, Math.min(100, Math.round(score)));
    const numEl = QS("#aml_risk_number");
    const labelEl = QS("#aml_risk_label");
    const arcEl = QS("#aml_gauge_arc");
    const card = QS("#aml_risk_card");

    if(numEl) numEl.textContent = s;

    let level = "Niski", color = "#15803d";
    if(s >= 60){ level = "Wysoki"; color = "#b91c1c"; }
    else if(s >= 30){ level = "Sredni"; color = "#d97706"; }

    if(labelEl) labelEl.textContent = level + " (" + s + "/100)";
    if(arcEl){
      const dashLen = (s / 100) * 157;
      arcEl.setAttribute("stroke-dasharray", dashLen + " 157");
      arcEl.setAttribute("stroke", color);
    }
    if(card) card.style.setProperty("--gauge-color", color);
  }

  function _renderBankInfo(stmt, result){
    const grid = QS("#aml_info_grid");
    if(!grid) return;
    const bank = stmt.bank_name || result.bank_name || "";
    const holder = stmt.account_holder || "";
    const iban = stmt.account_number || "";
    const period = [stmt.period_from, stmt.period_to].filter(Boolean).join(" \u2014 ");
    const cur = stmt.currency || "PLN";
    const txCount = (result.transaction_count || St.allTransactions.length) || 0;
    const prevClosing = stmt.previous_closing_balance;
    const availBal = stmt.available_balance;

    let html = "";
    if(bank) html += `<div class="aml-info-row"><b>Bank:</b> ${_esc(bank)}</div>`;
    if(holder) html += `<div class="aml-info-row"><b>Wlasciciel:</b> ${_esc(holder)}</div>`;
    if(iban) html += `<div class="aml-info-row"><b>IBAN:</b> <span style="font-family:monospace">${_esc(iban)}</span></div>`;
    if(period) html += `<div class="aml-info-row"><b>Okres:</b> ${_esc(period)}</div>`;
    if(cur && cur !== "PLN") html += `<div class="aml-info-row"><b>Waluta:</b> ${_esc(cur)}</div>`;

    // Balances grid
    html += '<div class="aml-info-stats">';
    if(stmt.opening_balance != null) html += `<span><b>Saldo otw.:</b> ${_fmtAmount(stmt.opening_balance, cur)}</span>`;
    if(stmt.closing_balance != null) html += `<span><b>Saldo konc.:</b> ${_fmtAmount(stmt.closing_balance, cur)}</span>`;
    if(availBal != null) html += `<span><b>Saldo dost.:</b> ${_fmtAmount(availBal, cur)}</span>`;
    if(prevClosing != null) html += `<span><b>Saldo konc. poprz.:</b> ${_fmtAmount(prevClosing, cur)}</span>`;
    html += '</div>';

    // Summary stats
    html += `<div class="small muted" style="margin-top:4px">Transakcje: ${txCount}`;
    if(result.pipeline_time_s) html += ` | Czas analizy: ${result.pipeline_time_s}s`;
    html += `</div>`;

    grid.innerHTML = html;
  }

  function _renderAlerts(alerts){
    const list = QS("#aml_alerts_list");
    const countEl = QS("#aml_alerts_count");
    if(!list) return;

    if(countEl) countEl.textContent = alerts.length;

    if(!alerts.length){
      list.innerHTML = '<div class="small muted">Brak alertow.</div>';
      return;
    }

    const sevOrder = {critical:0, high:1, medium:2, low:3};
    const sorted = [...alerts].sort((a,b)=> (sevOrder[a.severity]||9) - (sevOrder[b.severity]||9));

    list.innerHTML = sorted.map(a => {
      const sevClass = a.severity === "high" || a.severity === "critical" ? "aml-alert-high" :
                       a.severity === "medium" ? "aml-alert-medium" : "aml-alert-low";
      return `<div class="aml-alert ${sevClass}">
        <div class="aml-alert-head">
          <span class="aml-alert-type">${_esc(a.alert_type)}</span>
          <span class="aml-alert-severity">${_esc(a.severity)}</span>
          <span class="aml-alert-score">+${a.score_delta || 0}</span>
        </div>
        <div class="small">${_esc(a.explain || "")}</div>
      </div>`;
    }).join("");
  }

  // ============================================================
  // CHARTS (Chart.js) — with zoom, scroll & gap detection
  // ============================================================

  // Zoom state for balance_timeline
  const _chartZoom = {
    level: 1,          // 1 = fit-to-width, >1 = zoomed in
    minLevel: 1,
    maxLevel: 10,
    pxPerPoint: 0,     // base px per data point (computed)
    activeKey: null,    // currently rendered chart key
    wheelBound: false,  // whether Ctrl+wheel listener is attached
  };

  function _ensureChartJs(cb){
    if(window.Chart){
      St.chartjsLoaded = true;
      cb();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js";
    script.onload = ()=>{
      St.chartjsLoaded = true;
      cb();
    };
    script.onerror = ()=>{
      const container = QS("#aml_chart_container");
      if(container) container.innerHTML = '<div class="small muted" style="padding:20px">Nie udalo sie zaladowac Chart.js</div>';
    };
    document.head.appendChild(script);
  }

  /** Build a Chart.js annotation-like box plugin for drawing gap zones. */
  function _gapBoxPlugin(gaps, labels){
    if(!gaps || !gaps.length) return null;
    return {
      id: "gapZones",
      beforeDraw(chart){
        const ctx = chart.ctx;
        const xScale = chart.scales.x;
        const yScale = chart.scales.y;
        if(!xScale || !yScale) return;

        const top = yScale.top;
        const bottom = yScale.bottom;

        ctx.save();
        for(const gap of gaps){
          const idx = gap.after_index;
          if(idx < 0 || idx >= labels.length - 1) continue;

          // Pixel positions: right edge of idx, left edge of idx+1
          const x1 = xScale.getPixelForValue(idx);
          const x2 = xScale.getPixelForValue(idx + 1);
          const gapX = x1;
          const gapW = x2 - x1;
          if(gapW < 2) continue;

          // Hashed background
          ctx.fillStyle = "rgba(217,119,6,0.08)";
          ctx.fillRect(gapX, top, gapW, bottom - top);

          // Dashed borders
          ctx.strokeStyle = "rgba(217,119,6,0.35)";
          ctx.lineWidth = 1;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          ctx.moveTo(gapX, top);
          ctx.lineTo(gapX, bottom);
          ctx.moveTo(gapX + gapW, top);
          ctx.lineTo(gapX + gapW, bottom);
          ctx.stroke();
          ctx.setLineDash([]);

          // Label at top
          const label = gap.from_date + " \u2014 " + gap.to_date;
          ctx.font = "10px sans-serif";
          ctx.fillStyle = "rgba(217,119,6,0.7)";
          ctx.textAlign = "center";
          ctx.fillText(label, gapX + gapW / 2, top + 12);
        }
        ctx.restore();
      }
    };
  }

  /** Apply zoom level to balance_timeline chart container width. */
  function _applyTimelineZoom(){
    const container = QS("#aml_chart_container");
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    if(!container || !scrollWrap) return;

    const data = St.chartsData[_chartZoom.activeKey];
    if(!data) return;

    const pointCount = (data.labels || []).length;
    const wrapWidth = scrollWrap.clientWidth;

    if(pointCount <= 1 || _chartZoom.level <= 1){
      container.style.width = "";
      container.style.minWidth = "100%";
      return;
    }

    // Base: fit all points in visible width
    _chartZoom.pxPerPoint = wrapWidth / pointCount;
    const targetWidth = Math.max(wrapWidth, pointCount * _chartZoom.pxPerPoint * _chartZoom.level);
    container.style.width = Math.round(targetWidth) + "px";
    container.style.minWidth = Math.round(targetWidth) + "px";

    // Resize chart if it exists
    if(St.chartInstance){
      St.chartInstance.resize();
    }
  }

  /** Bind Alt+wheel zoom on the scroll wrapper (once). */
  function _bindChartZoomWheel(){
    if(_chartZoom.wheelBound) return;
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    if(!scrollWrap) return;
    _chartZoom.wheelBound = true;

    scrollWrap.addEventListener("wheel", (e)=>{
      // Only zoom when left Alt is held (not AltGr which sets both ctrlKey+altKey)
      if(!e.altKey || e.ctrlKey) return;
      // Only for timeline-like scrollable charts
      if(_chartZoom.activeKey !== "balance_timeline" && _chartZoom.activeKey !== "monthly_trend") return;

      e.preventDefault();
      e.stopPropagation();

      const oldLevel = _chartZoom.level;
      const delta = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      _chartZoom.level = Math.max(_chartZoom.minLevel, Math.min(_chartZoom.maxLevel, _chartZoom.level * delta));

      if(Math.abs(_chartZoom.level - oldLevel) < 0.001) return;

      // Preserve scroll position around mouse cursor
      const rect = scrollWrap.getBoundingClientRect();
      const mouseXRatio = (e.clientX - rect.left + scrollWrap.scrollLeft) /
                          (scrollWrap.scrollWidth || 1);

      _applyTimelineZoom();

      // Restore scroll to keep mouse pointer at same data position
      requestAnimationFrame(()=>{
        const newScrollX = mouseXRatio * scrollWrap.scrollWidth - (e.clientX - rect.left);
        scrollWrap.scrollLeft = Math.max(0, newScrollX);
      });
    }, {passive: false});
  }

  /** Render gap legend below the chart. */
  function _renderGapLegend(gaps){
    const legend = QS("#aml_chart_gap_legend");
    if(!legend) return;
    if(!gaps || !gaps.length){
      legend.style.display = "none";
      legend.innerHTML = "";
      return;
    }
    legend.style.display = "";
    let html = '<span class="gap-item"><span class="gap-swatch"></span> Brakujace okresy:</span>';
    for(const g of gaps){
      html += `<span class="gap-item" style="font-weight:500">${_esc(g.from_date)} \u2014 ${_esc(g.to_date)} (${g.days} dni)</span>`;
    }
    legend.innerHTML = html;
  }

  function _renderChart(chartKey){
    const data = St.chartsData[chartKey];
    const container = QS("#aml_chart_container");
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    const hint = QS("#aml_chart_hint");
    const gapLegend = QS("#aml_chart_gap_legend");

    if(!data){
      if(container) container.innerHTML = '<div class="small muted" style="padding:20px">Brak danych wykresu</div>';
      if(gapLegend) gapLegend.style.display = "none";
      return;
    }

    const isTimeline = (chartKey === "balance_timeline" || chartKey === "monthly_trend");

    // Show/hide zoom hint
    if(hint) hint.style.display = isTimeline ? "" : "none";

    // Reset zoom for non-timeline charts
    if(!isTimeline){
      _chartZoom.level = 1;
      _chartZoom.activeKey = null;
      if(container){
        container.style.width = "";
        container.style.minWidth = "100%";
      }
    } else {
      _chartZoom.activeKey = chartKey;
      // Keep zoom if switching between timeline types, reset otherwise
      if(_chartZoom.level < 1) _chartZoom.level = 1;
    }

    _ensureChartJs(()=>{
      if(!container) return;

      // Ensure canvas exists
      container.innerHTML = '<canvas id="aml_chart_canvas"></canvas>';
      const canvas = QS("#aml_chart_canvas");
      if(!canvas) return;

      // Destroy previous chart
      if(St.chartInstance){
        St.chartInstance.destroy();
        St.chartInstance = null;
      }

      const gaps = data.gaps || [];
      const labels = data.labels || [];
      const datasets = data.datasets || [];

      // Show gaps legend for balance_timeline
      if(chartKey === "balance_timeline"){
        _renderGapLegend(gaps);
      } else {
        if(gapLegend){ gapLegend.style.display = "none"; gapLegend.innerHTML = ""; }
      }

      const chartConfig = {
        type: data.type || "bar",
        data: {
          labels: labels,
          datasets: datasets,
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: datasets.length > 1 },
          },
        },
        plugins: [],
      };

      // Special options for specific chart types
      if(data.options && data.options.indexAxis){
        chartConfig.options.indexAxis = data.options.indexAxis;
      }
      if(data.type === "line"){
        chartConfig.options.elements = { point: { radius: 1 } };
      }
      // Dual y-axis for channel distribution
      if(datasets.some(ds => ds.yAxisID === "y1")){
        chartConfig.options.scales = {
          y: { type: "linear", display: true, position: "left" },
          y1: { type: "linear", display: true, position: "right", grid: { drawOnChartArea: false } },
        };
      }

      // Register gap-zone plugin for balance_timeline
      if(chartKey === "balance_timeline" && gaps.length > 0){
        const gapPlugin = _gapBoxPlugin(gaps, labels);
        if(gapPlugin) chartConfig.plugins.push(gapPlugin);
      }

      St.chartInstance = new Chart(canvas, chartConfig);

      // Apply zoom (sets container width, triggers resize)
      if(isTimeline){
        _applyTimelineZoom();
        _bindChartZoomWheel();
      }
    });
  }

  // ============================================================
  // ML ANOMALIES
  // ============================================================

  function _renderMlAnomalies(anomalies, transactions){
    const list = QS("#aml_ml_list");
    const countEl = QS("#aml_ml_count");
    if(!list) return;

    const flagged = anomalies.filter(a => a.is_anomaly);
    if(countEl) countEl.textContent = flagged.length;

    if(!flagged.length){
      list.innerHTML = '<div class="small muted">Brak wykrytych anomalii ML.</div>';
      return;
    }

    // Build tx lookup
    const txMap = {};
    for(const tx of (transactions || [])){
      txMap[tx.id] = tx;
    }

    const sorted = [...flagged].sort((a,b) => (b.anomaly_score || 0) - (a.anomaly_score || 0));

    list.innerHTML = sorted.slice(0, 20).map(a => {
      const tx = txMap[a.tx_id] || {};
      const scorePct = Math.round((a.anomaly_score || 0) * 100);
      const barColor = scorePct >= 70 ? "#b91c1c" : scorePct >= 40 ? "#d97706" : "#2563eb";
      return `<div class="aml-ml-row">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span class="small" style="font-family:monospace">${_esc((a.tx_id || "").slice(0,8))}...</span>
          <span class="small" style="font-weight:600;color:${barColor}">${scorePct}%</span>
        </div>
        <div style="background:var(--border);border-radius:4px;height:4px;margin:4px 0">
          <div style="background:${barColor};height:100%;border-radius:4px;width:${scorePct}%"></div>
        </div>
        <div class="small muted">${_esc(tx.booking_date || "")} | ${_esc((tx.counterparty_raw || "").slice(0,30))} | ${_fmtAmount(tx.amount, "PLN")}</div>
      </div>`;
    }).join("");
  }

  // ============================================================
  // LLM ANALYSIS
  // ============================================================

  function _setupLlmSection(hasPrompt){
    const btn = QS("#aml_llm_run_btn");
    const status = QS("#aml_llm_status");
    if(!btn) return;

    if(hasPrompt){
      btn.disabled = false;
      if(status) status.textContent = 'Kliknij "Generuj analize" aby uzyskac profesjonalny raport AML od modelu LLM (wymaga Ollama).';
    } else {
      btn.disabled = true;
      if(status) status.textContent = "Brak danych do analizy LLM. Uruchom najpierw analize AML.";
    }
  }

  async function _runLlmAnalysis(){
    if(!St.statementId || St.llmRunning) return;
    St.llmRunning = true;

    const btn = QS("#aml_llm_run_btn");
    const status = QS("#aml_llm_status");
    const resultDiv = QS("#aml_llm_result");
    const textDiv = QS("#aml_llm_text");
    const progressDiv = QS("#aml_llm_progress");
    const progBar = QS("#aml_llm_prog_bar");
    const progText = QS("#aml_llm_prog_text");

    if(btn) btn.disabled = true;
    if(status) status.style.display = "none";
    if(progressDiv) progressDiv.style.display = "";
    if(progBar) progBar.style.width = "5%";
    if(progText) progText.textContent = "Laczenie z Ollama...";
    if(resultDiv){ resultDiv.style.display = ""; }
    if(textDiv) textDiv.innerHTML = "";

    // Animated progress: slowly fills as text streams in
    let llmPct = 5;
    const progTimer = setInterval(()=>{
      llmPct = Math.min(llmPct + Math.random() * 3, 92);
      if(progBar) progBar.style.width = llmPct + "%";
    }, 1500);

    let fullText = "";
    let chunkCount = 0;

    try{
      const url = "/api/aml/llm-stream/" + encodeURIComponent(St.statementId);
      const response = await fetch(url);
      if(!response.ok) throw new Error("HTTP " + response.status);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if(progText) progText.textContent = "Generowanie analizy...";
      if(progBar) progBar.style.width = "15%";

      while(true){
        const {done, value} = await reader.read();
        if(done) break;

        buffer += decoder.decode(value, {stream: true});
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for(const line of lines){
          if(!line.startsWith("data: ")) continue;
          try{
            const obj = JSON.parse(line.slice(6));
            if(obj.error){
              throw new Error(obj.error);
            }
            if(obj.chunk){
              fullText += obj.chunk;
              chunkCount++;
              if(textDiv) textDiv.innerHTML = _formatLlmText(fullText);
              // Update progress based on chunks received
              const estPct = Math.min(15 + chunkCount * 0.5, 95);
              if(estPct > llmPct){
                llmPct = estPct;
                if(progBar) progBar.style.width = llmPct + "%";
              }
            }
            if(obj.done){
              break;
            }
          } catch(parseErr){
            if(parseErr.message && !parseErr.message.startsWith("Unexpected")){
              throw parseErr;
            }
          }
        }
      }

      clearInterval(progTimer);
      if(progBar) progBar.style.width = "100%";
      if(progText) progText.textContent = "Analiza zakonczona.";

      setTimeout(()=>{
        if(progressDiv) progressDiv.style.display = "none";
        if(status){
          status.textContent = "Analiza wygenerowana pomyslnie.";
          status.style.display = "";
        }
      }, 1200);

      if(fullText && textDiv){
        textDiv.innerHTML = _formatLlmText(fullText);
      }
      if(resultDiv) resultDiv.style.display = "";

    } catch(e) {
      clearInterval(progTimer);
      if(progressDiv) progressDiv.style.display = "none";
      if(status){
        status.textContent = "Blad: " + String(e.message || e);
        status.style.display = "";
      }
    } finally {
      St.llmRunning = false;
      if(btn) btn.disabled = false;
    }
  }

  function _formatLlmText(text){
    // Simple markdown-like formatting
    let html = _esc(text);
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h4 style="margin:12px 0 6px">$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 style="margin:16px 0 8px">$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2 style="margin:20px 0 10px">$1</h2>');
    // List items
    html = html.replace(/^- (.+)$/gm, '<li style="margin-left:20px">$1</li>');
    html = html.replace(/^\d+\. (.+)$/gm, '<li style="margin-left:20px">$1</li>');
    // Paragraphs (double newline)
    html = html.replace(/\n\n/g, "</p><p>");
    // Single newlines
    html = html.replace(/\n/g, "<br>");
    return "<p>" + html + "</p>";
  }

  // ============================================================
  // GRAPH (Cytoscape.js)
  // ============================================================

  function _ensureCytoscape(cb){
    if(window.cytoscape){
      St.cyLoaded = true;
      cb();
      return;
    }
    // Load from CDN
    const script = document.createElement("script");
    script.src = "https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js";
    script.onload = ()=>{
      St.cyLoaded = true;
      cb();
    };
    script.onerror = ()=>{
      const container = QS("#aml_graph_container");
      if(container) container.innerHTML = '<div class="small muted" style="padding:20px">Nie udalo sie zaladowac biblioteki Cytoscape.js</div>';
    };
    document.head.appendChild(script);
  }

  // ============================================================
  // GRAPH: classification-aware colors + multiple layouts
  // ============================================================

  // Classification → node color mapping
  const _CLASS_COLORS = {
    legitimate: "#15803d",   // green
    suspicious: "#dc2626",   // red
    monitoring: "#ea580c",   // orange
    neutral:    "#60a5fa",   // light blue
  };
  // Fallback: risk-level → color (when no classification available)
  const _RISK_COLORS = {
    high:   "#dc2626",
    medium: "#ea580c",
    low:    "#60a5fa",
    none:   "#60a5fa",
  };
  // Edge color mirrors the TARGET node color
  const _EDGE_BASE = "#94a3b8";
  const _TYPE_SHAPES = {ACCOUNT:"diamond", MERCHANT:"round-rectangle", CASH_NODE:"hexagon", PAYMENT_PROVIDER:"barrel"};

  // Layout configs
  const _LAYOUTS = {
    cose: {
      name:"cose", animate:true, animationDuration:400,
      nodeRepulsion:function(){return 8000;},
      idealEdgeLength:function(){return 120;},
      edgeElasticity:function(){return 100;},
      gravity:0.3, padding:30,
    },
    circle: {
      name:"circle", animate:true, animationDuration:400,
      padding:30, startAngle: 0,
    },
    grid: {
      name:"grid", animate:true, animationDuration:400,
      padding:30, rows:undefined, condense:true, avoidOverlap:true,
    },
    breadthfirst: {
      name:"breadthfirst", animate:true, animationDuration:400,
      directed:true, padding:30, spacingFactor:1.2,
      roots:"#account_own",
    },
    concentric: {
      name:"concentric", animate:true, animationDuration:400,
      padding:30, minNodeSpacing:40,
      concentric:function(node){
        // ACCOUNT at center, then by risk level (high=outer)
        if(node.data("type") === "ACCOUNT") return 100;
        const rl = node.data("riskLevel") || "none";
        return ({none:80, low:60, medium:40, high:20})[rl] || 50;
      },
      levelWidth:function(){ return 2; },
    },
  };

  function _nodeColor(ele){
    if(ele.data("type") === "ACCOUNT") return "#1f5aa6";
    const cls = ele.data("classStatus");
    if(cls && _CLASS_COLORS[cls]) return _CLASS_COLORS[cls];
    return _RISK_COLORS[ele.data("riskLevel")] || "#60a5fa";
  }
  function _edgeColor(ele){
    // Color edge by its target node color (muted)
    const tgt = ele.target();
    if(!tgt || !tgt.length) return _EDGE_BASE;
    const c = _nodeColor(tgt);
    // Lighten: mix with gray
    return c;
  }

  function _renderGraph(graphData){
    const container = QS("#aml_graph_container");
    if(!container) return;

    if(!graphData || !graphData.nodes || !graphData.nodes.length){
      container.innerHTML = '<div class="small muted" style="padding:20px">Brak danych grafu</div>';
      return;
    }

    _ensureCytoscape(()=>{
      const elements = [];

      for(const node of graphData.nodes){
        elements.push({
          data: {
            id: node.id,
            label: node.label || node.id,
            type: node.node_type || node.type || "COUNTERPARTY",
            riskLevel: node.risk_level || "none",
            classStatus: node.class_status || "",
          }
        });
      }

      for(const edge of graphData.edges){
        elements.push({
          data: {
            id: edge.id,
            source: edge.source || edge.source_id,
            target: edge.target || edge.target_id,
            label: _fmtAmount(edge.total_amount, "PLN") + " (" + (edge.tx_count||1) + "x)",
            edgeType: edge.edge_type || edge.type || "TRANSFER",
            amount: edge.total_amount || 0,
            classStatus: edge.class_status || "",
          }
        });
      }

      if(St.cyInstance){
        St.cyInstance.destroy();
      }

      St.cyInstance = cytoscape({
        container: container,
        elements: elements,
        style: [
          {
            selector: "node",
            style: {
              "label": "data(label)",
              "font-size": "11px",
              "text-wrap": "ellipsis",
              "text-max-width": "100px",
              "width": 40,
              "height": 40,
              "background-color": _nodeColor,
              "color": "#1e293b",
              "text-valign": "bottom",
              "text-margin-y": 6,
              "shape": function(ele){ return _TYPE_SHAPES[ele.data("type")] || "ellipse"; },
              "border-width": 2,
              "border-color": "rgba(0,0,0,.15)",
            }
          },
          {
            selector: "node[type='ACCOUNT']",
            style: {
              "background-color": "#1f5aa6",
              "width": 55,
              "height": 55,
              "font-weight": "bold",
              "font-size": "13px",
            }
          },
          {
            selector: "edge",
            style: {
              "width": function(ele){ return Math.min(1 + Math.sqrt(ele.data("amount")||1) / 20, 8); },
              "line-color": _edgeColor,
              "target-arrow-color": _edgeColor,
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              "label": "data(label)",
              "font-size": "9px",
              "color": "#64748b",
              "text-rotation": "autorotate",
              "text-margin-y": -8,
            }
          }
        ],
        layout: _LAYOUTS.cose,
        maxZoom: 3,
        minZoom: 0.3,
      });

      // --- Layout buttons ---
      const layoutBtns = QSA(".aml-graph-layout-btn");
      layoutBtns.forEach(btn=>{
        btn.onclick = ()=>{
          const layoutName = btn.getAttribute("data-layout");
          if(!layoutName || !_LAYOUTS[layoutName] || !St.cyInstance) return;
          // Highlight active button
          layoutBtns.forEach(b=>{ b.style.background=""; b.style.color=""; });
          btn.style.background = "var(--primary)";
          btn.style.color = "#fff";
          // Run layout
          St.cyInstance.layout(_LAYOUTS[layoutName]).run();
        };
      });

      // --- Risk filter ---
      const filterSel = QS("#aml_graph_risk_filter");
      if(filterSel){
        filterSel.onchange = ()=>{
          const val = filterSel.value;
          if(!val){
            St.cyInstance.elements().show();
          } else {
            St.cyInstance.nodes().forEach(n=>{
              if(n.data("riskLevel") === val || n.data("type") === "ACCOUNT"){
                n.show();
              } else {
                n.hide();
              }
            });
            St.cyInstance.edges().forEach(e=>{
              if(e.source().visible() && e.target().visible()){ e.show(); } else { e.hide(); }
            });
          }
        };
      }
    });
  }

  // ============================================================
  // TRANSACTIONS TABLE
  // ============================================================

  function _renderTransactions(transactions){
    St.allTransactions = transactions || [];
    _fillChannelFilter(transactions);
    _filterAndRenderTx();

    // Bind search & filter
    const search = QS("#aml_tx_search");
    if(search){
      search.oninput = ()=> _filterAndRenderTx();
    }
    const chFilter = QS("#aml_tx_channel_filter");
    if(chFilter){
      chFilter.onchange = ()=> _filterAndRenderTx();
    }
  }

  function _fillChannelFilter(transactions){
    const sel = QS("#aml_tx_channel_filter");
    if(!sel) return;
    const channels = new Set();
    for(const tx of transactions){
      if(tx.channel) channels.add(tx.channel);
    }
    sel.innerHTML = '<option value="">Kanal: wszystkie</option>';
    for(const ch of [...channels].sort()){
      sel.innerHTML += `<option value="${_esc(ch)}">${_esc(ch)}</option>`;
    }
  }

  function _filterAndRenderTx(){
    const searchVal = (QS("#aml_tx_search")?.value || "").toLowerCase().trim();
    const channelVal = QS("#aml_tx_channel_filter")?.value || "";

    let filtered = St.allTransactions;
    if(searchVal){
      filtered = filtered.filter(tx=>
        (tx.counterparty_raw || "").toLowerCase().includes(searchVal) ||
        (tx.title || "").toLowerCase().includes(searchVal) ||
        (tx.category || "").toLowerCase().includes(searchVal)
      );
    }
    if(channelVal){
      filtered = filtered.filter(tx => tx.channel === channelVal);
    }

    const countEl = QS("#aml_tx_count");
    if(countEl) countEl.textContent = filtered.length + " / " + St.allTransactions.length;

    const wrap = QS("#aml_tx_table_wrap");
    if(!wrap) return;

    if(!filtered.length){
      wrap.innerHTML = '<div class="small muted" style="padding:10px">Brak transakcji</div>';
      return;
    }

    let html = `<table class="aml-tx-table">
      <thead><tr>
        <th>Data</th><th>Kontrahent</th><th>Tytul</th><th>Kwota</th>
        <th>Kanal</th><th>Kategoria</th><th>Ryzyko</th>
      </tr></thead><tbody>`;

    for(const tx of filtered){
      const amt = Number(tx.amount || 0);
      const isDebit = tx.direction === "DEBIT" || amt < 0;
      const amtClass = isDebit ? "aml-tx-debit" : "aml-tx-credit";
      const absAmt = Math.abs(amt);
      const tags = Array.isArray(tx.risk_tags) ? tx.risk_tags : [];
      const riskBadge = tags.length
        ? `<span class="aml-tag">${tags.map(t=>_esc(t)).join(", ")}</span>`
        : (tx.risk_score > 0 ? `<span class="small muted">${tx.risk_score}</span>` : "");

      html += `<tr class="${tags.length ? 'aml-tx-risky' : ''}">
        <td class="aml-tx-date">${_esc(tx.booking_date || "")}</td>
        <td class="aml-tx-cp">${_esc((tx.counterparty_raw || "").slice(0,40))}</td>
        <td class="aml-tx-title">${_esc((tx.title || "").slice(0,50))}</td>
        <td class="aml-tx-amt ${amtClass}">${isDebit ? "-" : "+"}${absAmt.toLocaleString("pl-PL",{minimumFractionDigits:2, maximumFractionDigits:2})}</td>
        <td class="aml-tx-ch">${_esc(tx.channel || "")}</td>
        <td class="aml-tx-cat">${_esc(tx.category || "")}</td>
        <td>${riskBadge}</td>
      </tr>`;
    }

    html += "</tbody></table>";
    wrap.innerHTML = html;
  }

  // ============================================================
  // COUNTERPARTY MEMORY
  // ============================================================

  async function _loadMemory(){
    const list = QS("#aml_memory_list");
    if(!list) return;

    const data = await _safeApi("/api/memory?limit=100");
    if(!data || !data.counterparties || !data.counterparties.length){
      list.innerHTML = '<div class="small muted">Brak kontrahentow w pamieci.</div>';
      return;
    }

    list.innerHTML = data.counterparties.map(cp => {
      const labelClass = cp.label === "blacklist" ? "aml-cp-blacklist" :
                         cp.label === "whitelist" ? "aml-cp-whitelist" : "";
      return `<div class="aml-cp-row ${labelClass}">
        <span class="aml-cp-name">${_esc(cp.canonical_name)}</span>
        <span class="aml-cp-label">${_esc(cp.label || "neutral")}</span>
        <span class="small muted">${cp.times_seen || 0}x</span>
        <select class="aml-cp-select" data-id="${_esc(cp.id)}" title="Zmien etykiete">
          <option value="neutral" ${cp.label === "neutral" ? "selected" : ""}>neutral</option>
          <option value="whitelist" ${cp.label === "whitelist" ? "selected" : ""}>whitelist</option>
          <option value="blacklist" ${cp.label === "blacklist" ? "selected" : ""}>blacklist</option>
        </select>
      </div>`;
    }).join("");

    // Bind label changes
    QSA(".aml-cp-select", list).forEach(sel=>{
      sel.onchange = async ()=>{
        const cpId = sel.getAttribute("data-id");
        const label = sel.value;
        await _safeApi("/api/memory/" + encodeURIComponent(cpId), {
          method: "PATCH",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({label: label}),
        });
        await _loadMemory();
      };
    });
  }

  // ============================================================
  // HISTORY
  // ============================================================

  function _renderHistory(){
    const card = QS("#aml_history_card");
    const list = QS("#aml_history_list");
    const countEl = QS("#aml_history_count");
    if(!card || !list) return;

    if(!St.history.length){
      card.style.display = "none";
      return;
    }

    card.style.display = "";
    if(countEl) countEl.textContent = St.history.length + " analiz";

    list.innerHTML = St.history.map(item => {
      const score = item.risk_score != null ? Math.round(item.risk_score) : "?";
      const scoreColor = score >= 60 ? "var(--danger)" : score >= 30 ? "#d97706" : "var(--ok)";
      return `<div class="aml-history-item" data-sid="${_esc(item.statement_id)}" style="display:flex;align-items:center;gap:8px">
        <span class="aml-hist-bank" style="flex:1">${_esc(item.bank_name || "?")}</span>
        <span class="aml-hist-period">${_esc(item.period_from || "")} \u2014 ${_esc(item.period_to || "")}</span>
        <span class="aml-hist-score" style="color:${scoreColor}">${score}</span>
        <span class="aml-hist-tx small muted">${item.tx_count || 0} tx</span>
        <span class="aml-hist-date small muted">${_fmtDate(item.created_at)}</span>
        <button class="aml-hist-delete" data-sid="${_esc(item.statement_id)}" title="Usun analize" style="background:none;border:none;cursor:pointer;color:var(--danger,#b91c1c);font-size:16px;padding:2px 6px;border-radius:4px;opacity:0.5;line-height:1">&times;</button>
      </div>`;
    }).join("");

    // Bind clicks (open analysis)
    QSA(".aml-history-item", list).forEach(el=>{
      el.addEventListener("click", async (e)=>{
        // Ignore if delete button was clicked
        if(e.target.closest(".aml-hist-delete")) return;
        const sid = el.getAttribute("data-sid");
        if(!sid) return;
        _showProgress("Ladowanie analizy...");
        const detail = await _loadDetail(sid);
        _renderResults();
        _showResults();

        // Load Review & Classification (batch-aware via sibling statements)
        if(window.ReviewManager){
          const siblings = (detail && detail.sibling_statement_ids) || [];
          if(siblings.length > 1){
            await ReviewManager.loadForBatch(siblings);
          } else {
            await ReviewManager.loadForStatement(sid);
          }
        }
      });
    });

    // Bind delete buttons
    QSA(".aml-hist-delete", list).forEach(btn=>{
      btn.addEventListener("mouseenter", ()=> btn.style.opacity = "1");
      btn.addEventListener("mouseleave", ()=> btn.style.opacity = "0.5");
      btn.addEventListener("click", async (e)=>{
        e.stopPropagation();
        const sid = btn.getAttribute("data-sid");
        if(!sid) return;
        const ok = await showConfirm({title:'Usunięcie analizy',message:'Usunąć tę analizę? Operacja usunie wyciąg i wszystkie powiązane transakcje.',confirmText:'Usuń',type:'danger',warning:'Ta operacja jest nieodwracalna.'});
        if(!ok) return;
        const res = await _safeApi("/api/aml/history/" + encodeURIComponent(sid), {method:"DELETE"});
        if(res){
          // Remove from local state and re-render
          St.history = St.history.filter(h => h.statement_id !== sid);
          _renderHistory();
        }
      });
    });
  }

  // ============================================================
  // BIND UI EVENTS
  // ============================================================

  function _bindUpload(){
    const dropArea = QS("#aml_drop_area");
    const fileInput = QS("#aml_file_input");
    const uploadBtn = QS("#aml_upload_btn");

    if(uploadBtn && fileInput){
      uploadBtn.onclick = ()=> fileInput.click();
    }
    if(fileInput){
      fileInput.onchange = _fileInputDefaultHandler;
    }

    if(dropArea){
      dropArea.addEventListener("dragover", (e)=>{
        e.preventDefault();
        dropArea.classList.add("aml-dragover");
      });
      dropArea.addEventListener("dragleave", ()=>{
        dropArea.classList.remove("aml-dragover");
      });
      dropArea.addEventListener("drop", (e)=>{
        e.preventDefault();
        dropArea.classList.remove("aml-dragover");
        const files = e.dataTransfer && e.dataTransfer.files;
        if(!files || !files.length) return;
        if(files.length === 1){
          _uploadAndAnalyze(files[0]);
        } else {
          _startBatch(Array.from(files));
        }
      });
    }
  }

  function _bindActions(){
    const downloadBtn = QS("#aml_download_report");
    if(downloadBtn){
      downloadBtn.onclick = ()=>{
        if(St.statementId){
          window.open("/api/aml/report/" + encodeURIComponent(St.statementId), "_blank");
        }
      };
    }

    const newBtn = QS("#aml_new_analysis");
    if(newBtn){
      newBtn.onclick = ()=>{
        St.lastResult = null;
        St.detail = null;
        St.statementId = null;
        St.caseId = null;
        St.chartsData = {};
        if(St.chartInstance){ St.chartInstance.destroy(); St.chartInstance = null; }
        if(St.cyInstance){ St.cyInstance.destroy(); St.cyInstance = null; }
        _chartZoom.level = 1;
        _chartZoom.activeKey = null;
        const _cont = QS("#aml_chart_container");
        if(_cont){ _cont.style.width = ""; _cont.style.minWidth = "100%"; }
        const _gapL = QS("#aml_chart_gap_legend");
        if(_gapL){ _gapL.style.display = "none"; _gapL.innerHTML = ""; }
        _resetBatchState();
        _loadHistory();
        _showUpload();
      };
    }

    const memRefresh = QS("#aml_memory_refresh");
    if(memRefresh){
      memRefresh.onclick = ()=> _loadMemory();
    }

    // Chart selector
    const chartSel = QS("#aml_chart_select");
    if(chartSel){
      chartSel.onchange = ()=> _renderChart(chartSel.value);
    }

    // LLM analysis button
    const llmBtn = QS("#aml_llm_run_btn");
    if(llmBtn){
      llmBtn.onclick = ()=> _runLlmAnalysis();
    }
  }

  // Column mapping UI removed — replaced by direct PyMuPDF auto-parsing.


  // ============================================================
  // HELPERS
  // ============================================================

  function _show(id){ const el = QS("#" + id); if(el) el.style.display = ""; }
  function _hide(id){ const el = QS("#" + id); if(el) el.style.display = "none"; }

  // ============================================================
  // BATCH UPLOAD (multi-file)
  // ============================================================

  function _startBatch(files){
    // Filter to PDF only
    const pdfs = files.filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if(!pdfs.length){
      _showError("Nie znaleziono plikow PDF.");
      return;
    }

    St.batchMode = true;
    St.batchFiles = pdfs.map(f => ({
      file: f,
      name: f.name,
      status: "queued",   // queued | processing | done | error
      statementId: null,
      error: null,
    }));
    St.batchIdx = -1;
    St.batchCaseId = "";
    St.batchResults = [];

    _renderBatchPanel();
    _showBatchPanel();
    _processBatchNext();
  }

  async function _processBatchNext(){
    St.batchIdx++;
    if(St.batchIdx >= St.batchFiles.length){
      await _batchFinalize();
      return;
    }

    const entry = St.batchFiles[St.batchIdx];
    entry.status = "processing";
    _renderBatchPanel();

    try {
      const result = await _runPipelineForFile(entry.file, St.batchCaseId);

      if(result && result.status === "ok"){
        entry.status = "done";
        entry.statementId = result.statement_id;
        if(!St.batchCaseId && result.case_id){
          St.batchCaseId = result.case_id;
        }
        St.batchResults.push(result.statement_id);
      } else {
        entry.status = "error";
        let errMsg = result && result.error ? String(result.error) : "Blad analizy";
        if(errMsg === "no_transactions"){
          errMsg = "Nie znaleziono transakcji w dokumencie.";
        }
        entry.error = errMsg;
      }
    } catch(e){
      entry.status = "error";
      entry.error = String(e.message || e);
    }

    _renderBatchPanel();
    await _processBatchNext();
  }

  async function _batchFinalize(){
    _showBatchPanel();
    _renderBatchPanel();

    // Run cross-validation if we have at least 2 statements
    if(St.batchResults.length >= 2){
      const valPanel = QS("#aml_batch_validation");
      if(valPanel){
        valPanel.style.display = "";
        valPanel.innerHTML = '<div class="small muted">Walidacja krzyzowa...</div>';
      }

      try {
        const result = await _api("/api/aml/validate-batch", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({statement_ids: St.batchResults}),
        });

        if(result && result.status === "ok"){
          _renderBatchValidation(result);
        }
      } catch(e){
        if(valPanel) valPanel.innerHTML = `<div class="small" style="color:var(--danger)">Blad walidacji: ${_esc(e.message || e)}</div>`;
      }
    }

    // If we have any successful results, load the first one for St.detail
    if(St.batchResults.length > 0){
      const firstStmtId = St.batchResults[0];
      await _loadDetail(firstStmtId);
    }

    // Show "add more documents" dialog
    _showAddMoreDialog();
  }

  /** Show dialog asking if user wants to add more documents (e.g. from another bank). */
  function _showAddMoreDialog(){
    const panel = QS("#aml_batch_list");
    if(!panel) return;

    // Append the dialog after existing content
    const existingDialog = QS("#aml_batch_add_more");
    if(existingDialog) existingDialog.remove();

    const d = document.createElement("div");
    d.id = "aml_batch_add_more";
    d.style.cssText = "margin-top:12px;padding:12px 16px;background:var(--bg-alt,#f1f5f9);border-radius:8px;border:1px solid var(--border,#e2e8f0)";
    d.innerHTML = `
      <div style="font-weight:600;margin-bottom:8px">Chcesz dodac inne dokumenty (np. z innego banku)?</div>
      <div style="display:flex;gap:8px">
        <button class="btn" id="aml_batch_add_yes">Tak — dodaj kolejne pliki</button>
        <button class="btn btn-outline" id="aml_batch_add_no">Nie — przejdz do przegladu</button>
      </div>
    `;
    panel.parentNode.insertBefore(d, panel.nextSibling);

    QS("#aml_batch_add_yes").onclick = ()=>{
      d.remove();
      // Keep batch state, open file browser for additional files
      const fileInput = QS("#aml_file_input");
      if(fileInput){
        fileInput.onchange = ()=>{
          const files = fileInput.files;
          if(!files || !files.length) return;
          // Add new files to batch
          const pdfs = Array.from(files).filter(f => f.name.toLowerCase().endsWith(".pdf"));
          if(!pdfs.length) return;
          for(const f of pdfs){
            St.batchFiles.push({
              file: f,
              name: f.name,
              status: "queued",
              statementId: null,
              error: null,
            });
          }
          _renderBatchPanel();
          // Continue processing from current index (next unprocessed)
          St.batchIdx = St.batchFiles.length - pdfs.length - 1;
          _processBatchNext();
          fileInput.value = "";
          // Restore normal onchange for future single uploads
          fileInput.onchange = _fileInputDefaultHandler;
        };
        fileInput.click();
      }
    };

    QS("#aml_batch_add_no").onclick = async ()=>{
      d.remove();
      // Proceed to review all statements
      await _batchViewAllResults();
    };
  }

  /** Load and show all batch results in review. */
  async function _batchViewAllResults(){
    if(!St.batchResults.length) return;

    // Load detail for first statement (for risk/graph/charts)
    if(!St.detail){
      await _loadDetail(St.batchResults[0]);
    }

    _renderResults();
    _showResults();
    _hide("aml_batch_panel");

    // Load ALL statements in ReviewManager (await to ensure rendering completes)
    if(window.ReviewManager){
      if(St.batchResults.length > 1){
        await ReviewManager.loadForBatch(St.batchResults);
      } else {
        await ReviewManager.loadForStatement(St.batchResults[0]);
      }
    }
  }

  /** Default file input onchange handler (saved for restoring after batch add-more). */
  function _fileInputDefaultHandler(){
    const fileInput = QS("#aml_file_input");
    if(!fileInput) return;
    const files = fileInput.files;
    if(!files || !files.length) return;
    if(files.length === 1){
      _uploadAndAnalyze(files[0]);
    } else {
      _startBatch(Array.from(files));
    }
    fileInput.value = "";
  }

  function _renderBatchPanel(){
    const counterEl = QS("#aml_batch_counter");
    const listEl = QS("#aml_batch_list");
    if(!listEl) return;

    const done = St.batchFiles.filter(f => f.status === "done").length;
    const errs = St.batchFiles.filter(f => f.status === "error").length;
    const total = St.batchFiles.length;

    if(counterEl){
      counterEl.textContent = `${done} / ${total} przetworzonych` + (errs > 0 ? ` (${errs} bledow)` : "");
    }

    const _statusIcon = (status) => {
      switch(status){
        case "queued": return aiIcon("loading", 14);
        case "uploading": return aiIcon("export", 14);
        case "processing": return aiIcon("settings", 14);
        case "done": return aiIcon("success", 14);
        case "error": return aiIcon("error", 14);
        default: return aiIcon("info_circle", 14);
      }
    };
    const _statusLabel = (status) => {
      switch(status){
        case "queued": return "W kolejce";
        case "uploading": return "Przesylanie...";
        case "processing": return "Analiza...";
        case "done": return "Gotowe";
        case "error": return "Blad";
        default: return status;
      }
    };
    const _statusColor = (status) => {
      switch(status){
        case "done": return "var(--ok,#15803d)";
        case "error": return "var(--danger,#b91c1c)";
        case "processing":
        case "uploading":
        default: return "var(--text-muted,#94a3b8)";
      }
    };

    let html = "";
    for(let i = 0; i < St.batchFiles.length; i++){
      const f = St.batchFiles[i];
      const isActive = (i === St.batchIdx && f.status !== "done" && f.status !== "error");
      const bg = isActive ? "var(--bg-alt,#f1f5f9)" : "";
      html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;background:${bg}">
        <span style="font-size:14px">${_statusIcon(f.status)}</span>
        <span style="flex:1;font-size:13px;font-weight:${isActive ? "600" : "400"}">${_esc(f.name)}</span>
        <span class="small" style="color:${_statusColor(f.status)}">${_statusLabel(f.status)}</span>`;
      if(f.error){
        html += `<span class="small" style="color:var(--danger)" title="${_esc(f.error)}">${_esc(f.error.slice(0,40))}</span>`;
      }
      html += `</div>`;
    }

    // Progress bar
    const pct = total > 0 ? Math.round(((done + errs) / total) * 100) : 0;
    html += `<div style="margin-top:8px;background:var(--border,#e2e8f0);border-radius:4px;height:6px;overflow:hidden">
      <div style="width:${pct}%;height:100%;background:${errs > 0 ? "#d97706" : "var(--ok,#15803d)"};transition:width .3s"></div>
    </div>`;

    // If all done, show button to view results
    if(done + errs === total && done > 0){
      html += `<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" id="aml_batch_view_results">Przegladaj wyniki (${done} wyciag${done > 1 ? "ow" : ""})</button>
        <button class="btn btn-outline" id="aml_batch_new">Nowa analiza</button>
      </div>`;
    }

    listEl.innerHTML = html;

    // Bind view results button
    const viewBtn = QS("#aml_batch_view_results");
    if(viewBtn){
      viewBtn.onclick = ()=> _batchViewAllResults();
    }

    const newBtn = QS("#aml_batch_new");
    if(newBtn){
      newBtn.onclick = ()=>{
        _resetBatchState();
        _loadHistory();
        _showUpload();
      };
    }
  }

  function _renderBatchValidation(result){
    const panel = QS("#aml_batch_validation");
    if(!panel) return;

    const validations = result.validations || [];
    const summary = result.summary || {};

    let html = '<div style="border-top:1px solid var(--border,#e2e8f0);padding-top:8px">';
    html += `<div style="font-weight:600;margin-bottom:6px">Walidacja krzyzowa</div>`;

    // Summary
    html += `<div class="small" style="margin-bottom:6px">
      Wyciagi: ${summary.statement_count || 0} |
      Transakcje: ${summary.total_transactions || 0} |
      Okres: ${_esc(summary.period_from || "?")} \u2014 ${_esc(summary.period_to || "?")}
    </div>`;

    if(validations.length === 0){
      html += `<div style="color:var(--ok,#15803d);font-weight:500">\u2705 Wszystkie kontrole przeszly pomyslnie.</div>`;
    } else {
      for(const v of validations){
        const isErr = v.level === "error";
        const icon = isErr ? "\u274C" : "\u26A0\uFE0F";
        const color = isErr ? "var(--danger,#b91c1c)" : "#d97706";
        html += `<div style="display:flex;align-items:start;gap:6px;padding:4px 0;color:${color}">
          <span>${icon}</span>
          <span class="small">${_esc(v.message)}</span>
        </div>`;
      }
    }
    html += '</div>';
    panel.innerHTML = html;
    panel.style.display = "";
  }

  function _resetBatchState(){
    St.batchMode = false;
    St.batchFiles = [];
    St.batchIdx = -1;
    St.batchCaseId = "";
    St.batchResults = [];
    _hide("aml_batch_panel");
    const valPanel = QS("#aml_batch_validation");
    if(valPanel){ valPanel.style.display = "none"; valPanel.innerHTML = ""; }
  }

  // ============================================================
  // PUBLIC API
  // ============================================================

  /** Refresh graph with current classification colors (called after classify). */
  async function _refreshGraphColors(){
    if(!St.caseId || !St.cyInstance) return;
    try {
      const graph = await _safeApi("/api/aml/graph/" + encodeURIComponent(St.caseId));
      if(graph && graph.nodes){
        // Update node/edge data in place for smooth update
        const cy = St.cyInstance;
        for(const node of graph.nodes){
          const ele = cy.getElementById(node.id);
          if(ele.length){
            ele.data("classStatus", node.class_status || "");
          }
        }
        for(const edge of graph.edges){
          const ele = cy.getElementById(edge.id);
          if(ele.length){
            ele.data("classStatus", edge.class_status || "");
          }
        }
        // Force style recalculation
        cy.style().update();
      }
    } catch(e){
      console.warn("[AML] Graph color refresh failed:", e);
    }
  }

  const AmlManager = {
    _initialized: false,

    async init(){
      if(this._initialized) return;
      this._initialized = true;

      _bindUpload();
      _bindActions();
      await _loadHistory();
      _showUpload();
    },

    /** Called by ReviewManager after classification change. */
    refreshGraphColors: _refreshGraphColors,
  };

  window.AmlManager = AmlManager;
})();
