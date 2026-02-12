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
    // Spatial column mapping state
    cmPreview: null,      // from POST /api/aml/preview-pdf (spatial data)
    cmMapping: {},        // {col_index_str: column_type}
    cmColumnTypes: {},    // metadata from API
    cmColumns: [],        // [{label, col_type, x_min, x_max}] — detected/user-adjusted
    cmPageScale: 1,       // image scale factor vs PDF coordinates
    cmDragging: null,     // index of column boundary being dragged
    cmHeaderFields: [],   // [{field_type, value, raw_label, box}] — editable header fields
    cmHeaderWords: [],    // [{text, x0, top, x1, bottom}] — all words in header region
    cmActiveHdrField: -1, // index of currently highlighted header field (-1 = none)
    cmPageElements: [],   // [{img, svg, container, pageInfo, pageNum, scale}] per page
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
    _hide("aml_mapping_card");
    if(!St.batchMode) _hide("aml_batch_panel");
    const histCard = QS("#aml_history_card");
    if(histCard && St.history.length) _show("aml_history_card");
  }

  function _showProgress(text){
    _hide("aml_upload_zone");
    _show("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    _hide("aml_mapping_card");
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
    _hide("aml_mapping_card");
    _hide("aml_batch_panel");
  }

  function _showMapping(){
    _hide("aml_upload_zone");
    _hide("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    _show("aml_mapping_card");
    if(!St.batchMode) _hide("aml_batch_panel");
  }

  function _showBatchPanel(){
    _hide("aml_upload_zone");
    _hide("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    _hide("aml_mapping_card");
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
    _showProgress("Przesylanie PDF i rozpoznawanie kolumn...");

    const fd = new FormData();
    fd.append("file", file, file.name);

    try{
      const result = await _api("/api/aml/preview-pdf", {method:"POST", body:fd});

      if(result && result.status === "ok"){
        St.cmPreview = result;
        St.cmMapping = result.auto_mapping || {};
        St.cmColumnTypes = result.column_types || {};

        // Template auto-apply is handled in _renderColumnMapping() after columns are created

        _renderColumnMapping();
        _showMapping();
      } else if(result && result.status === "no_tables"){
        _showError("Nie znaleziono tabel w PDF. Sprobuj inny plik.");
      } else {
        _showError(result && result.error ? String(result.error) : "Blad podgladu PDF");
      }
    } catch(e) {
      _showError("Blad: " + String(e.message || e));
    } finally {
      St.analyzing = false;
    }
  }

  async function _runFullPipeline(filePath, mapping, opts){
    St.analyzing = true;
    _showProgress("Analiza AML...");

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
      const body = {
        file_path: filePath,
        column_mapping: mapping,
        header_row: opts.header_row || 0,
        data_start_row: opts.data_start_row || 1,
        main_table_index: opts.main_table_index || 0,
        save_template: opts.save_template || false,
        template_name: opts.template_name || "",
        set_default: opts.set_default || false,
        template_id: opts.template_id || "",
        bank_id: opts.bank_id || "",
        bank_name: opts.bank_name || "",
        header_cells: opts.header_cells || [],
        column_bounds: opts.column_bounds || null,
        header_fields: opts.header_fields || {},
        case_id: opts.case_id || "",
      };

      const result = await _api("/api/aml/confirm-mapping", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(body),
      });

      clearInterval(progTimer);
      clearInterval(stageTimer);

      if(result && result.status === "ok"){
        St.lastResult = result;
        St.statementId = result.statement_id;
        St.caseId = result.case_id;

        await _loadDetail(result.statement_id);
        _renderResults();
        _showResults();

        // Trigger review module
        if(window.ReviewManager && result.statement_id){
          ReviewManager.loadForStatement(result.statement_id);
        }

        // Auto-run LLM analysis if checkbox was checked
        if(opts.run_llm && result.has_llm_prompt){
          _runLlmAnalysis();
        }
      } else {
        _showError(result && result.error ? String(result.error) : "Blad analizy");
        _showMapping();
      }
    } catch(e) {
      clearInterval(progTimer);
      clearInterval(stageTimer);
      _showError("Blad: " + String(e.message || e));
      _showMapping();
    } finally {
      St.analyzing = false;
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

    // Review module (classification)
    if(window.ReviewManager && St.statementId){
      ReviewManager.loadForStatement(St.statementId);
    }

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
  // CHARTS (Chart.js)
  // ============================================================

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

  function _renderChart(chartKey){
    const data = St.chartsData[chartKey];
    if(!data){
      const container = QS("#aml_chart_container");
      if(container) container.innerHTML = '<div class="small muted" style="padding:20px">Brak danych wykresu</div>';
      return;
    }

    _ensureChartJs(()=>{
      const container = QS("#aml_chart_container");
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

      const chartConfig = {
        type: data.type || "bar",
        data: {
          labels: data.labels || [],
          datasets: data.datasets || [],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: (data.datasets || []).length > 1 },
          },
        },
      };

      // Special options for specific chart types
      if(data.options && data.options.indexAxis){
        chartConfig.options.indexAxis = data.options.indexAxis;
      }
      if(data.type === "line"){
        chartConfig.options.elements = { point: { radius: 1 } };
      }
      // Dual y-axis for channel distribution
      if(data.datasets && data.datasets.some(ds => ds.yAxisID === "y1")){
        chartConfig.options.scales = {
          y: { type: "linear", display: true, position: "left" },
          y1: { type: "linear", display: true, position: "right", grid: { drawOnChartArea: false } },
        };
      }

      St.chartInstance = new Chart(canvas, chartConfig);
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
        await _loadDetail(sid);
        _renderResults();
        _showResults();
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
        if(!confirm("Usunac te analize? Operacja usunie wyciag i wszystkie powiazane transakcje.")) return;
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
      fileInput.onchange = ()=>{
        const files = fileInput.files;
        if(!files || !files.length) return;
        if(files.length === 1){
          _uploadAndAnalyze(files[0]);
        } else {
          _startBatch(Array.from(files));
        }
        fileInput.value = "";
      };
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

  // ============================================================
  // COLUMN MAPPING UI — Visual PDF overlay with SVG mask
  // ============================================================

  const _TYPE_COLORS = {
    date:"#3b82f6", value_date:"#60a5fa", description:"#8b5cf6",
    counterparty:"#06b6d4", amount:"#f59e0b", debit:"#ef4444",
    credit:"#22c55e", balance:"#6366f1", bank_type:"#a855f7",
    reference:"#64748b", skip:"#94a3b8",
  };

  // Header field types that can be assigned
  const _HEADER_FIELD_TYPES = {
    bank_name:               {label:"Nazwa banku",              icon:"\uD83C\uDFE6"},
    account_number:          {label:"Nr rachunku / IBAN",       icon:"\uD83D\uDD22"},
    account_holder:          {label:"W\u0142a\u015Bciciel konta",         icon:"\uD83D\uDC64"},
    period_from:             {label:"Okres od",                 icon:"\uD83D\uDCC5"},
    period_to:               {label:"Okres do",                 icon:"\uD83D\uDCC5"},
    opening_balance:         {label:"Saldo pocz\u0105tkowe",         icon:"\uD83D\uDCB0"},
    closing_balance:         {label:"Saldo ko\u0144cowe",            icon:"\uD83D\uDCB0"},
    available_balance:       {label:"Saldo dost\u0119pne",           icon:"\uD83D\uDCB0"},
    previous_closing_balance:{label:"Saldo ko\u0144c. poprz. wyc.",  icon:"\uD83D\uDCB0"},
    declared_credits_count:  {label:"Suma uzna\u0144 (liczba)",      icon:"\uD83D\uDCE5"},
    declared_credits_sum:    {label:"Suma uzna\u0144 (kwota)",       icon:"\uD83D\uDCE5"},
    declared_debits_count:   {label:"Suma obci\u0105\u017Ce\u0144 (liczba)",   icon:"\uD83D\uDCE4"},
    declared_debits_sum:     {label:"Suma obci\u0105\u017Ce\u0144 (kwota)",    icon:"\uD83D\uDCE4"},
    debt_limit:              {label:"Limit zad\u0142u\u017Cenia",         icon:"\uD83D\uDCCA"},
    overdue_commission:      {label:"Kwota prowizji zaleg\u0142ej",  icon:"\uD83D\uDCCB"},
    blocked_amount:          {label:"Kwota zablokowana",        icon:"\uD83D\uDD12"},
    currency:                {label:"Waluta",                   icon:"\uD83D\uDCB1"},
    skip:                    {label:"Pomi\u0144",                    icon:"\u23ED\uFE0F"},
  };

  function _renderColumnMapping(){
    const preview = St.cmPreview;
    if(!preview) return;

    // Bank label
    const bankLabel = QS("#cm_bank_label");
    if(bankLabel){
      bankLabel.textContent = preview.bank_name || "Nieznany bank";
    }

    // Template banner
    _renderTemplateBanner(preview);

    // Warnings
    const warningsEl = QS("#cm_warnings");
    if(warningsEl && preview.warnings && preview.warnings.length){
      warningsEl.innerHTML = preview.warnings.map(w =>
        `<div class="small" style="color:var(--danger);margin:2px 0">\u26A0 ${_esc(w)}</div>`
      ).join("");
    }

    // Store columns for SVG overlay
    St.cmColumns = (preview.columns || []).map(c => ({...c}));

    // Auto-apply template to columns (exact match = auto-apply)
    const tpl = preview.template;
    if(tpl && tpl.column_mapping && !tpl._partial_match){
      // Full bounds restore if available
      const tplBounds = tpl.column_bounds || [];
      const tplMapping = tpl.column_mapping || {};
      if(tplBounds.length > 0 && tplBounds[0] && tplBounds[0].x_min != null){
        St.cmColumns = tplBounds.map((b, i) => ({
          label: b.label || "",
          col_type: tplMapping[String(i)] || b.col_type || "skip",
          x_min: b.x_min,
          x_max: b.x_max,
          header_y: St.cmColumns[0] ? St.cmColumns[0].header_y : 50,
        }));
        _cmSyncMapping();
        console.log("[AML] Auto-applied template (bounds):", tpl.name);
      } else {
        _applyTemplateToColumns(tpl);
      }
    } else if(St.cmMapping && Object.keys(St.cmMapping).length){
      // Use auto-detected mapping (no template or partial match)
      for(const [idxStr, colType] of Object.entries(St.cmMapping)){
        const idx = parseInt(idxStr, 10);
        if(idx >= 0 && idx < St.cmColumns.length){
          St.cmColumns[idx].col_type = colType;
        }
      }
    }

    // Build header fields from detected header_region
    _buildHeaderFields(preview.header_region);

    // If template was auto-applied, merge saved header fields
    if(tpl && tpl.column_mapping && !tpl._partial_match){
      _restoreHeaderFieldsFromTemplate(tpl);
    }

    // Render header fields editor
    _renderHeaderFields();

    // Load first page image
    _cmLoadAllPages();

    // Render column type selectors
    _renderCmHeaders();

    // Auto-run preview parse
    _cmPreviewParse();
  }

  // ============================================================
  // TEMPLATE BANNER
  // ============================================================

  function _renderTemplateBanner(preview){
    const banner = QS("#cm_template_banner");
    if(!banner) return;

    const tpl = preview.template;
    const bankTemplates = preview.bank_templates || [];
    const bankName = preview.bank_name || "Nieznany bank";

    if(!tpl && !bankTemplates.length){
      // No templates — hide banner
      banner.style.display = "none";
      return;
    }

    const titleEl = QS("#cm_tpl_title");
    const subtitleEl = QS("#cm_tpl_subtitle");
    const selectEl = QS("#cm_tpl_select");
    const applyBtn = QS("#cm_tpl_apply_btn");
    const ignoreBtn = QS("#cm_tpl_ignore_btn");
    const deleteBtn = QS("#cm_tpl_delete_btn");

    if(tpl && !tpl._partial_match){
      // Exact match — auto-applied
      if(titleEl) titleEl.textContent = "Rozpoznano: " + bankName;
      const hfCount = Object.keys(tpl.header_fields || {}).length;
      let subMsg = "Szablon \"" + (tpl.name || "domyslny") + "\" zastosowany automatycznie";
      if(hfCount > 0){
        subMsg += " (kolumny + " + hfCount + " pol naglowka)";
      } else {
        subMsg += " (kolumny). Brak pol naglowka — zapisz szablon ponownie";
      }
      subMsg += (tpl.times_used ? ". Uzywany " + tpl.times_used + "x" : "") + ".";
      if(subtitleEl) subtitleEl.textContent = subMsg;
      banner.style.borderLeftColor = "var(--ok,#15803d)";
      banner.style.background = "var(--bg-success,#f0fdf4)";
      if(applyBtn) applyBtn.style.display = "none";
    } else if(tpl && tpl._partial_match){
      // Partial match (default template, headers differ)
      if(titleEl) titleEl.textContent = "Rozpoznano: " + bankName;
      if(subtitleEl) subtitleEl.textContent = "Znaleziono szablon \"" + (tpl.name || "domyslny")
        + "\" ale naglowki sie roznia. Sprawdz mapowanie kolumn.";
      banner.style.borderLeftColor = "#d97706";
      banner.style.background = "#fffbeb";
      if(applyBtn) applyBtn.style.display = "";
    } else {
      // No exact match but other templates exist
      if(titleEl) titleEl.textContent = "Rozpoznano: " + bankName;
      if(subtitleEl) subtitleEl.textContent = bankTemplates.length + " szablon(ow) dostepnych. Wybierz aby zastosowac.";
      banner.style.borderLeftColor = "#3b82f6";
      banner.style.background = "#eff6ff";
      if(applyBtn) applyBtn.style.display = "";
    }

    // Template selector — show when templates exist and wasn't auto-applied
    const needSelector = bankTemplates.length > 1 || (bankTemplates.length === 1 && (!tpl || tpl._partial_match));
    if(selectEl){
      if(needSelector){
        selectEl.style.display = "";
        const opts = bankTemplates.map(t => {
          const selected = tpl && t.id === tpl.id ? " selected" : (bankTemplates.length === 1 ? " selected" : "");
          const dflt = t.is_default ? " [domyslny]" : "";
          const used = t.times_used ? " (" + t.times_used + "x)" : "";
          return `<option value="${_esc(t.id)}"${selected}>${_esc(t.name || "Szablon")}${dflt}${used}</option>`;
        }).join("");
        selectEl.innerHTML = bankTemplates.length > 1
          ? '<option value="">-- Wybierz szablon --</option>' + opts
          : opts;
      } else {
        selectEl.style.display = "none";
      }
    }

    banner.style.display = "";

    // Show delete button when template is identified (exact or partial)
    if(deleteBtn){
      deleteBtn.style.display = (tpl && tpl.id) ? "" : "none";
    }

    // Bind events
    if(applyBtn){
      applyBtn.onclick = ()=> _applySelectedTemplate();
    }
    if(ignoreBtn){
      ignoreBtn.onclick = ()=>{ banner.style.display = "none"; };
    }
    if(deleteBtn){
      deleteBtn.onclick = async ()=>{
        // Determine which template to delete
        let tplId = "";
        if(selectEl && selectEl.value){
          tplId = selectEl.value;
        } else if(tpl && tpl.id){
          tplId = tpl.id;
        }
        if(!tplId){
          deleteBtn.style.display = "none";
          return;
        }
        if(!confirm("Czy na pewno usunac ten szablon? Operacja jest nieodwracalna.")) return;
        const res = await _safeApi("/api/aml/templates/" + encodeURIComponent(tplId), {method:"DELETE"});
        if(res){
          if(subtitleEl) subtitleEl.textContent = "Szablon usuniety.";
          banner.style.borderLeftColor = "#6b7280";
          banner.style.background = "#f9fafb";
          if(applyBtn) applyBtn.style.display = "none";
          deleteBtn.style.display = "none";
          if(selectEl){
            // Remove deleted template from selector
            const opt = selectEl.querySelector(`option[value="${tplId}"]`);
            if(opt) opt.remove();
            if(!selectEl.options.length || (selectEl.options.length === 1 && !selectEl.options[0].value)){
              selectEl.style.display = "none";
            }
          }
        }
      };
    }
    if(selectEl){
      selectEl.onchange = ()=>{
        if(applyBtn) applyBtn.style.display = selectEl.value ? "" : "none";
        // Update delete button based on selection
        if(deleteBtn) deleteBtn.style.display = selectEl.value ? "" : ((tpl && tpl.id) ? "" : "none");
      };
    }
  }

  function _applyTemplateToColumns(tpl){
    /**
     * Applies a template's column_mapping to current St.cmColumns.
     *
     * Three strategies in order:
     *   1) Exact label match — "Data" == "Data"
     *   2) Fuzzy label match — "Opis" matches "Opis operacji" (contains/prefix)
     *   3) Index fallback — use numeric indices if labels don't help
     */
    const mapping = tpl.column_mapping || {};
    const sampleHeaders = tpl.sample_headers || [];

    // Build ordered entries [{label, type, idx}] from template
    const tplEntries = [];
    for(const [idxStr, colType] of Object.entries(mapping)){
      const idx = parseInt(idxStr, 10);
      const label = (idx >= 0 && idx < sampleHeaders.length)
        ? String(sampleHeaders[idx] || "").trim().toLowerCase() : "";
      tplEntries.push({label, type: colType, idx});
    }

    // Reset all columns
    for(let i = 0; i < St.cmColumns.length; i++){
      St.cmColumns[i].col_type = "skip";
    }

    const usedTpl = new Set();  // template entries already consumed
    let matched = 0;
    let strategy = "none";

    // --- Strategy 1: Exact label match ---
    for(let i = 0; i < St.cmColumns.length; i++){
      const cur = String(St.cmColumns[i].label || "").trim().toLowerCase();
      if(!cur) continue;
      for(let j = 0; j < tplEntries.length; j++){
        if(usedTpl.has(j) || !tplEntries[j].label) continue;
        if(tplEntries[j].label === cur){
          St.cmColumns[i].col_type = tplEntries[j].type;
          usedTpl.add(j);
          matched++;
          break;
        }
      }
    }
    if(matched > 0) strategy = "exact";

    // --- Strategy 2: Fuzzy label match (for remaining unmatched) ---
    for(let i = 0; i < St.cmColumns.length; i++){
      if(St.cmColumns[i].col_type !== "skip") continue;
      const cur = String(St.cmColumns[i].label || "").trim().toLowerCase();
      if(!cur) continue;

      let bestJ = -1, bestScore = 0;
      for(let j = 0; j < tplEntries.length; j++){
        if(usedTpl.has(j) || !tplEntries[j].label) continue;
        const tl = tplEntries[j].label;
        let score = 0;
        // Either string contains the other
        if(cur.includes(tl) || tl.includes(cur)) score = 3;
        // First word matches (>= 3 chars)
        else {
          const cw = cur.split(/\s/)[0];
          const tw = tl.split(/\s/)[0];
          if(cw.length >= 3 && cw === tw) score = 2;
        }
        if(score > bestScore){ bestScore = score; bestJ = j; }
      }
      if(bestJ >= 0){
        St.cmColumns[i].col_type = tplEntries[bestJ].type;
        usedTpl.add(bestJ);
        matched++;
        if(strategy === "none") strategy = "fuzzy";
      }
    }

    // --- Strategy 3: Index fallback (only if nothing matched at all) ---
    if(matched === 0){
      for(const e of tplEntries){
        if(e.idx >= 0 && e.idx < St.cmColumns.length && St.cmColumns[e.idx].col_type === "skip"){
          St.cmColumns[e.idx].col_type = e.type;
          matched++;
        }
      }
      if(matched > 0) strategy = "index";
    }

    _cmSyncMapping();

    console.log("[AML] Template applied:", tpl.name,
      "matched:", matched + "/" + St.cmColumns.length,
      "strategy:", strategy,
      "types:", St.cmColumns.map(c => c.col_type));

    return matched;
  }

  function _applySelectedTemplate(){
    const preview = St.cmPreview;
    if(!preview) return;

    const selectEl = QS("#cm_tpl_select");
    const bankTemplates = preview.bank_templates || [];

    // Find selected template: dropdown → preview.template → first bank template
    let tpl = null;
    if(selectEl && selectEl.value){
      tpl = bankTemplates.find(t => t.id === selectEl.value);
    }
    if(!tpl && preview.template && preview.template.column_mapping){
      tpl = preview.template;
    }
    if(!tpl && bankTemplates.length){
      tpl = bankTemplates[0];
    }
    if(!tpl || !tpl.column_mapping) return;

    // If template has saved column_bounds, restore full column definitions
    const tplBounds = tpl.column_bounds || [];
    const tplMapping = tpl.column_mapping || {};
    let matched = 0;

    if(tplBounds.length > 0 && tplBounds[0] && tplBounds[0].x_min != null){
      // Rebuild columns entirely from template bounds
      St.cmColumns = tplBounds.map((b, i) => ({
        label: b.label || "",
        col_type: tplMapping[String(i)] || b.col_type || "skip",
        x_min: b.x_min,
        x_max: b.x_max,
        header_y: St.cmColumns[0] ? St.cmColumns[0].header_y : 50,
      }));
      _cmSyncMapping();
      matched = Object.keys(tplMapping).length;
      console.log("[AML] Template applied (full bounds restore):", tpl.name,
        "cols:", St.cmColumns.length, "types:", St.cmColumns.map(c => c.col_type));
    } else {
      // No bounds — use label/index matching on existing columns
      matched = _applyTemplateToColumns(tpl);
    }

    // Update the banner with match count
    const subtitleEl = QS("#cm_tpl_subtitle");
    if(subtitleEl){
      const total = St.cmColumns.length;
      if(matched > 0){
        subtitleEl.textContent = "Szablon \"" + (tpl.name || "domyslny") + "\" zastosowany — " + matched + "/" + total + " kolumn.";
      } else {
        subtitleEl.textContent = "Szablon \"" + (tpl.name || "domyslny") + "\" — nie udalo sie dopasowac. Sprawdz recznie.";
      }
    }
    const applyBtn = QS("#cm_tpl_apply_btn");
    if(applyBtn) applyBtn.style.display = "none";

    const banner = QS("#cm_template_banner");
    if(banner){
      banner.style.borderLeftColor = "var(--ok,#15803d)";
      banner.style.background = "var(--bg-success,#f0fdf4)";
    }

    // Restore header fields from template (saldo, IBAN, etc.)
    const hfRestored = _restoreHeaderFieldsFromTemplate(tpl);

    // Update banner to include header field info
    if(subtitleEl){
      const total = St.cmColumns.length;
      let msg = "Szablon \"" + (tpl.name || "domyslny") + "\" zastosowany";
      msg += " — " + matched + "/" + total + " kolumn";
      if(hfRestored > 0){
        msg += ", " + hfRestored + " pol naglowka";
      } else {
        const hfCount = Object.keys(tpl.header_fields || {}).length;
        if(hfCount === 0){
          msg += ". Brak pol naglowka w szablonie — zapisz ponownie aby je zachowac";
        }
      }
      msg += ".";
      subtitleEl.textContent = msg;
    }

    // Re-render everything: headers, SVG overlay, and parse preview
    _renderCmHeaders();
    _cmRenderOverlay();
    _cmPreviewParse();
  }

  function _restoreHeaderFieldsFromTemplate(tpl){
    const savedFields = tpl.header_fields;
    console.log("[AML] Template header_fields:", JSON.stringify(savedFields),
      "| current cmHeaderFields:", St.cmHeaderFields.length);
    if(!savedFields || typeof savedFields !== "object" || !Object.keys(savedFields).length){
      console.log("[AML] No header_fields in template — skipping restore");
      return 0;
    }

    let restored = 0;

    // Merge template header fields into current St.cmHeaderFields
    // For each saved field: overwrite if exists, add if missing
    for(const [fieldType, savedValue] of Object.entries(savedFields)){
      if(!savedValue || fieldType === "skip") continue;
      const existing = St.cmHeaderFields.find(f => f.field_type === fieldType);
      if(existing){
        // Always overwrite with template value — user saved it for a reason
        existing.value = String(savedValue);
        restored++;
      } else {
        // Add field that wasn't auto-detected this time
        const meta = _HEADER_FIELD_TYPES[fieldType];
        St.cmHeaderFields.push({
          field_type: fieldType,
          value: String(savedValue),
          raw_label: meta ? meta.label : fieldType,
          box: null,
        });
        restored++;
      }
    }

    console.log("[AML] Restored", restored, "header fields from template");
    _renderHeaderFields();
    return restored;
  }

  // ============================================================
  // HEADER REGION EDITOR
  // ============================================================

  function _buildHeaderFields(region){
    St.cmHeaderFields = [];
    if(!region) return;

    // Store header words for overlay (all text in header region)
    St.cmHeaderWords = region.words || [];

    // Store field_boxes from backend detection for SVG overlay
    const fieldBoxes = region.field_boxes || [];

    // Helper: find box for field_type from detected boxes
    const _findBox = (type) => {
      const b = fieldBoxes.find(fb => fb.field_type === type);
      return b ? {x0: b.x0, top: b.top, x1: b.x1, bottom: b.bottom} : null;
    };

    // Bank name — from detected first line or preview
    const preview = St.cmPreview;
    const bankName = region.bank_name_detected || (preview && preview.bank_name) || "";
    if(bankName){
      St.cmHeaderFields.push({
        field_type: "bank_name",
        value: bankName,
        raw_label: "Bank",
        box: _findBox("bank_name"),
      });
    }

    // All known fields — order matters for display
    const fieldMap = [
      ["account_number", "Nr rachunku"],
      ["account_holder", "Posiadacz"],
      ["period_from", "Okres od"],
      ["period_to", "Okres do"],
      ["opening_balance", "Saldo pocz\u0105tkowe"],
      ["closing_balance", "Saldo ko\u0144cowe"],
      ["available_balance", "Saldo dost\u0119pne"],
      ["previous_closing_balance", "Saldo ko\u0144c. poprz. wyci\u0105gu"],
      ["declared_credits_count", "Suma uzna\u0144 (liczba)"],
      ["declared_credits_sum", "Suma uzna\u0144 (kwota)"],
      ["declared_debits_count", "Suma obci\u0105\u017Ce\u0144 (liczba)"],
      ["declared_debits_sum", "Suma obci\u0105\u017Ce\u0144 (kwota)"],
      ["debt_limit", "Limit zad\u0142u\u017Cenia"],
      ["overdue_commission", "Kwota prowizji zaleg\u0142ej"],
      ["blocked_amount", "Kwota zablokowana"],
      ["currency", "Waluta"],
    ];
    for(const [key, rawLabel] of fieldMap){
      const val = region[key];
      if(val != null && val !== ""){
        St.cmHeaderFields.push({
          field_type: key,
          value: String(val),
          raw_label: rawLabel,
          box: _findBox(key),
        });
      }
    }

    // If raw_text has IBAN not yet captured, add it
    if(region.raw_text && !St.cmHeaderFields.find(f => f.field_type === "account_number")){
      const ibanMatch = region.raw_text.match(/(?:PL\s*)?(\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4})/);
      if(ibanMatch){
        St.cmHeaderFields.push({
          field_type: "account_number",
          value: ibanMatch[0].replace(/\s/g, ""),
          raw_label: "IBAN (wykryty)",
          box: _findBox("account_number"),
        });
      }
    }
  }

  function _renderHeaderFields(){
    const container = QS("#cm_header_fields");
    if(!container) return;

    if(!St.cmHeaderFields.length){
      container.innerHTML = '<div class="small muted">Nie wykryto danych naglowka. Mozesz dodac pole recznie.</div>' +
        '<button class="btn mini" id="cm_add_header_field" style="margin-top:4px">+ Dodaj pole</button>';
      const addBtn = container.querySelector("#cm_add_header_field");
      if(addBtn) addBtn.addEventListener("click", ()=> _addHeaderField());
      return;
    }

    let html = '';
    for(let i = 0; i < St.cmHeaderFields.length; i++){
      const f = St.cmHeaderFields[i];
      const meta = _HEADER_FIELD_TYPES[f.field_type] || _HEADER_FIELD_TYPES.skip;
      const hasBox = f.box != null;
      const activeStyle = St.cmActiveHdrField === i
        ? "border-color:#3b82f6;box-shadow:0 0 0 2px rgba(59,130,246,0.3)" : "";
      html += `<div class="cm-hdr-field" data-idx="${i}" style="display:flex;flex-direction:column;gap:2px;min-width:140px;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:8px;background:var(--bg-alt,#f8fafc);cursor:pointer;${activeStyle}">
        <div style="display:flex;gap:4px;align-items:center">
          <select class="cm-hdr-type-sel input" data-idx="${i}" style="padding:2px 5px;border-radius:5px;font-size:11px;flex:1">`;

      for(const [key, tmeta] of Object.entries(_HEADER_FIELD_TYPES)){
        const sel = f.field_type === key ? " selected" : "";
        html += `<option value="${_esc(key)}"${sel}>${tmeta.icon} ${_esc(tmeta.label)}</option>`;
      }

      html += `</select>
          <button class="cm-hdr-locate" data-idx="${i}" style="background:none;border:1px solid var(--border,#ddd);border-radius:4px;cursor:pointer;font-size:10px;padding:1px 4px;color:${hasBox ? "#3b82f6" : "var(--text-muted,#94a3b8)"}" title="${hasBox ? "Pokaz/edytuj pole na PDF" : "Zaznacz pole na PDF klikajac i przeciagajac"}">\u25A3</button>
          <button class="cm-hdr-del" data-idx="${i}" style="background:none;border:none;color:var(--danger,#b91c1c);cursor:pointer;font-size:11px;padding:0" title="Usun pole">\u2715</button>
        </div>
        <input class="cm-hdr-value-input input" data-idx="${i}" value="${_esc(f.value)}" style="padding:3px 6px;border-radius:5px;font-size:12px;font-weight:600" title="Kliknij aby edytowac">
      </div>`;
    }

    html += `<button class="btn mini" id="cm_add_header_field" style="align-self:center;min-width:40px" title="Dodaj pole naglowka">+</button>`;
    container.innerHTML = html;

    // Bind events
    QSA(".cm-hdr-type-sel", container).forEach(sel => {
      sel.addEventListener("change", ()=>{
        const idx = parseInt(sel.getAttribute("data-idx"), 10);
        if(idx < St.cmHeaderFields.length){
          St.cmHeaderFields[idx].field_type = sel.value;
          _cmRenderOverlay();
        }
      });
    });

    QSA(".cm-hdr-value-input", container).forEach(inp => {
      inp.addEventListener("change", ()=>{
        const idx = parseInt(inp.getAttribute("data-idx"), 10);
        if(idx < St.cmHeaderFields.length) St.cmHeaderFields[idx].value = inp.value.trim();
      });
    });

    QSA(".cm-hdr-del", container).forEach(btn => {
      btn.addEventListener("click", (e)=>{
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        St.cmHeaderFields.splice(idx, 1);
        if(St.cmActiveHdrField === idx) St.cmActiveHdrField = -1;
        _renderHeaderFields();
        _cmRenderOverlay();
      });
    });

    // Locate/highlight button: toggle active field highlight on PDF
    QSA(".cm-hdr-locate", container).forEach(btn => {
      btn.addEventListener("click", (e)=>{
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        if(St.cmActiveHdrField === idx){
          // Toggle off — deselect
          St.cmActiveHdrField = -1;
        } else {
          St.cmActiveHdrField = idx;
        }
        _renderHeaderFields();
        _cmRenderOverlay();
      });
    });

    // Clicking the card itself also activates/deactivates
    QSA(".cm-hdr-field", container).forEach(card => {
      card.addEventListener("click", ()=>{
        const idx = parseInt(card.getAttribute("data-idx"), 10);
        if(St.cmActiveHdrField === idx){
          St.cmActiveHdrField = -1;
        } else {
          St.cmActiveHdrField = idx;
        }
        _renderHeaderFields();
        _cmRenderOverlay();
      });
    });

    const addBtn = container.querySelector("#cm_add_header_field");
    if(addBtn) addBtn.addEventListener("click", ()=> _addHeaderField());
  }

  function _addHeaderField(){
    // Create a placeholder box in the header region center
    let defaultBox = null;
    if(St.cmHeaderWords && St.cmHeaderWords.length){
      // Place new box near the bottom of existing header words
      const allY = St.cmHeaderWords.map(w => w.bottom);
      const maxY = Math.max(...allY);
      const allX = St.cmHeaderWords.map(w => w.x0);
      const midX = (Math.min(...allX) + Math.max(...St.cmHeaderWords.map(w => w.x1))) / 2;
      defaultBox = {x0: midX - 50, top: maxY - 10, x1: midX + 50, bottom: maxY + 4};
    } else if(St.cmColumns.length){
      // Fallback: place above first column header
      const hy = St.cmColumns[0].header_y || 50;
      defaultBox = {x0: 30, top: hy - 20, x1: 200, bottom: hy - 5};
    }

    const newIdx = St.cmHeaderFields.length;
    St.cmHeaderFields.push({
      field_type: "skip",
      value: "",
      raw_label: "Nowe pole",
      box: defaultBox,
    });

    // Auto-activate so user can immediately drag/resize the box
    St.cmActiveHdrField = newIdx;
    _renderHeaderFields();
    _cmRenderOverlay();

    // Focus the value input
    const inputs = QSA(".cm-hdr-value-input");
    if(inputs.length) inputs[inputs.length - 1].focus();
  }

  // Amount-type fields that need numeric sanitization
  const _AMOUNT_FIELDS = new Set([
    "opening_balance","closing_balance","available_balance",
    "previous_closing_balance","declared_credits_sum","declared_debits_sum",
    "debt_limit","overdue_commission","blocked_amount",
  ]);
  const _COUNT_FIELDS = new Set([
    "declared_credits_count","declared_debits_count",
  ]);

  /** Strip currency suffix and normalize Polish number format to plain number string. */
  function _sanitizeNumericValue(s){
    if(!s) return s;
    s = s.trim();
    // Strip currency codes/symbols
    s = s.replace(/\s*(PLN|EUR|USD|GBP|CHF|CZK|SEK|NOK|DKK|zł|zl)\s*$/i, "");
    s = s.replace(/^\s*(PLN|EUR|USD|GBP|CHF|CZK|SEK|NOK|DKK|zł|zl)\s*/i, "");
    s = s.trim();
    // Normalize: "21 850,08" → "21850.08", "1.234,56" → "1234.56"
    const noNbsp = s.replace(/\u00a0/g, "").replace(/\s/g, "");
    if(noNbsp.includes(",") && !noNbsp.includes(".")){
      return noNbsp.replace(",", ".");
    } else if(noNbsp.includes(",") && noNbsp.includes(".")){
      return noNbsp.replace(/,/g, "");  // "1,234.56" or "1.234,56"
    }
    return noNbsp;
  }

  function _getHeaderFieldsForApi(){
    const result = {};
    for(const f of St.cmHeaderFields){
      if(f.field_type !== "skip" && f.value.trim()){
        let val = f.value.trim();
        // Sanitize numeric fields — strip currency, normalize format
        if(_AMOUNT_FIELDS.has(f.field_type) || _COUNT_FIELDS.has(f.field_type)){
          val = _sanitizeNumericValue(val);
        }
        result[f.field_type] = val;
      }
    }
    return result;
  }

  // ============================================================
  // COLUMN OPERATIONS (add, split, remove, rename)
  // ============================================================

  function _cmAddColumn(){
    // Add a new column by splitting the last column
    const lastCol = St.cmColumns.length ? St.cmColumns[St.cmColumns.length - 1] : null;

    if(lastCol && (lastCol.x_max - lastCol.x_min) > 30){
      // Split last column: 60% stays, 40% becomes new
      const origMax = lastCol.x_max;
      const splitX = lastCol.x_min + (lastCol.x_max - lastCol.x_min) * 0.6;
      lastCol.x_max = splitX;
      St.cmColumns.push({
        label: "Nowa kolumna",
        col_type: "skip",
        x_min: splitX,
        x_max: origMax,
        header_y: lastCol.header_y,
      });
    } else {
      // Fallback: get page width from preview and add column at end
      const pageW = (St.cmPreview && St.cmPreview.pages && St.cmPreview.pages[0])
        ? St.cmPreview.pages[0].width : 600;
      const xMin = lastCol ? lastCol.x_max : 0;
      St.cmColumns.push({
        label: "Nowa kolumna",
        col_type: "skip",
        x_min: xMin,
        x_max: Math.min(xMin + 80, pageW),
        header_y: St.cmColumns[0]?.header_y || 50,
      });
    }

    _cmSyncMapping();
    _renderCmHeaders();
    _cmRenderOverlay();
  }

  function _cmSplitColumn(idx){
    if(idx < 0 || idx >= St.cmColumns.length) return;
    const col = St.cmColumns[idx];
    const midX = (col.x_min + col.x_max) / 2;

    // Create new column from the right half
    const newCol = {
      label: col.label + " (2)",
      col_type: "skip",
      x_min: midX,
      x_max: col.x_max,
      header_y: col.header_y,
    };

    // Shrink original to left half
    col.x_max = midX;

    // Insert new after current
    St.cmColumns.splice(idx + 1, 0, newCol);

    _cmSyncMapping();
    _renderCmHeaders();
    _cmRenderOverlay();
  }

  function _cmRemoveColumn(idx){
    if(idx < 0 || idx >= St.cmColumns.length) return;
    if(St.cmColumns.length <= 1) return; // Keep at least one

    const removed = St.cmColumns[idx];

    // Redistribute space to neighbors
    if(idx > 0){
      St.cmColumns[idx - 1].x_max = removed.x_max;
    } else if(idx < St.cmColumns.length - 1){
      St.cmColumns[idx + 1].x_min = removed.x_min;
    }

    St.cmColumns.splice(idx, 1);
    _cmSyncMapping();
    _renderCmHeaders();
    _cmRenderOverlay();
  }

  function _cmRenameColumn(idx){
    if(idx < 0 || idx >= St.cmColumns.length) return;
    const col = St.cmColumns[idx];

    // Find the label element and turn it into an input
    const labelEl = QS(`.cm-col-label[data-col="${idx}"]`);
    if(!labelEl) return;

    const input = document.createElement("input");
    input.className = "input";
    input.style.cssText = "padding:2px 4px;font-size:11px;border-radius:4px;width:100%";
    input.value = col.label;
    labelEl.replaceWith(input);
    input.focus();
    input.select();

    const _finish = ()=>{
      col.label = input.value.trim() || col.label;
      _renderCmHeaders();
      _cmRenderOverlay();
    };
    input.addEventListener("blur", _finish);
    input.addEventListener("keydown", (e)=>{
      if(e.key === "Enter") _finish();
      if(e.key === "Escape"){ input.value = col.label; _finish(); }
    });
  }

  function _cmLoadAllPages(){
    const container = QS("#cm_pages_container");
    if(!container) return;

    const preview = St.cmPreview;
    const pages = preview.pages || [];
    if(!pages.length) return;

    container.innerHTML = "";
    St.cmPageElements = []; // store {img, svg, container, pageInfo} per page

    const t = Date.now();
    let loadedCount = 0;

    for(let i = 0; i < pages.length; i++){
      const pageInfo = pages[i];

      // Page label
      const label = document.createElement("div");
      label.className = "small muted";
      label.style.cssText = "text-align:center;padding:4px 0;font-weight:600";
      label.textContent = `Strona ${i + 1} / ${pages.length}`;
      if(i > 0) label.style.borderTop = "2px dashed var(--border,#e2e8f0)";
      container.appendChild(label);

      // Page wrapper (holds img + svg)
      const wrap = document.createElement("div");
      wrap.className = "cm-page-wrap";
      wrap.style.cssText = "position:relative;display:block;user-select:none;-webkit-user-select:none;overflow:hidden;width:100%;max-width:100%;box-sizing:border-box";
      wrap.setAttribute("data-page", String(i));
      // Prevent browser image/text drag
      wrap.addEventListener("dragstart", (ev) => ev.preventDefault());

      const img = document.createElement("img");
      img.style.cssText = "display:block;width:calc(100% - 20px);height:auto;user-select:none;-webkit-user-drag:none;pointer-events:none";
      img.alt = `Strona ${i + 1}`;
      img.draggable = false;

      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:all";

      wrap.appendChild(img);
      wrap.appendChild(svg);
      container.appendChild(wrap);

      const entry = {img, svg, container: wrap, pageInfo, pageNum: i};
      St.cmPageElements.push(entry);

      img.onload = () => {
        // Scale: rendered image pixels vs PDF coordinate space
        entry.scale = img.naturalWidth / pageInfo.width;
        loadedCount++;
        if(loadedCount === pages.length){
          // All pages loaded — use first page scale as reference
          St.cmPageScale = St.cmPageElements[0].scale;
          _cmRenderOverlay();
        }
      };
      img.src = `/api/aml/page-image/${i}?t=${t}`;
    }

    // Page count display
    const pageSel = QS("#cm_page_select");
    if(pageSel) pageSel.style.display = "none"; // not needed anymore
  }

  // Colors for header field boxes
  const _HDR_FIELD_COLORS = {
    bank_name: "#8b5cf6", account_number: "#3b82f6", account_holder: "#06b6d4",
    period_from: "#22c55e", period_to: "#22c55e",
    opening_balance: "#f59e0b", closing_balance: "#f59e0b", available_balance: "#eab308",
    previous_closing_balance: "#d97706",
    declared_credits_count: "#10b981", declared_credits_sum: "#10b981",
    declared_debits_count: "#ef4444", declared_debits_sum: "#ef4444",
    debt_limit: "#6366f1", overdue_commission: "#e11d48", blocked_amount: "#a855f7",
    currency: "#64748b", skip: "#94a3b8",
  };

  function _cmRenderOverlay(){
    const pageEls = St.cmPageElements;
    if(!pageEls || !pageEls.length) return;

    for(let p = 0; p < pageEls.length; p++){
      const pe = pageEls[p];
      const svg = pe.svg;
      const img = pe.img;
      if(!img || !img.naturalWidth) continue;

      const scale = pe.scale || St.cmPageScale;
      const imgW = img.naturalWidth;
      const imgH = img.naturalHeight;

      svg.setAttribute("viewBox", `0 0 ${imgW} ${imgH}`);
      svg.style.pointerEvents = "none";

      let markup = "";

      // --- Header field boxes (page 0 only) ---
      if(p === 0){
        for(let i = 0; i < St.cmHeaderFields.length; i++){
          const f = St.cmHeaderFields[i];
          if(!f.box) continue;
          const isActive = (St.cmActiveHdrField === i);
          const color = _HDR_FIELD_COLORS[f.field_type] || "#94a3b8";
          const opacity = isActive ? 0.25 : 0.08;
          const strokeW = isActive ? 2.5 : 1.5;
          const dash = isActive ? "" : "4,2";

          const rx = f.box.x0 * scale;
          const ry = f.box.top * scale;
          const rw = (f.box.x1 - f.box.x0) * scale;
          const rh = (f.box.bottom - f.box.top) * scale;
          const pad = 3 * scale;

          markup += `<rect x="${rx - pad}" y="${ry - pad}" width="${rw + 2 * pad}" height="${rh + 2 * pad}" fill="${color}" fill-opacity="${opacity}" stroke="${color}" stroke-width="${strokeW}" ${dash ? `stroke-dasharray="${dash}"` : ""} rx="${2 * scale}" data-hdr-field="${i}" style="pointer-events:visiblePainted;cursor:move" />`;

          const meta = _HEADER_FIELD_TYPES[f.field_type] || _HEADER_FIELD_TYPES.skip;
          markup += `<text x="${rx - pad}" y="${ry - pad - 2 * scale}" font-size="${9 * scale}" fill="${color}" font-weight="bold" style="pointer-events:none">${meta.icon || ""} ${_esc(meta.label)}</text>`;

          if(isActive){
            const handles = [
              {cx: rx - pad, cy: ry - pad, cursor: "nwse-resize", corner: "tl"},
              {cx: rx + rw + pad, cy: ry - pad, cursor: "nesw-resize", corner: "tr"},
              {cx: rx - pad, cy: ry + rh + pad, cursor: "nesw-resize", corner: "bl"},
              {cx: rx + rw + pad, cy: ry + rh + pad, cursor: "nwse-resize", corner: "br"},
            ];
            for(const h of handles){
              markup += `<rect x="${h.cx - 3 * scale}" y="${h.cy - 3 * scale}" width="${6 * scale}" height="${6 * scale}" fill="${color}" stroke="white" stroke-width="1" rx="${1 * scale}" data-hdr-handle="${i}" data-corner="${h.corner}" style="pointer-events:visiblePainted;cursor:${h.cursor}" />`;
            }
          }
        }
      }

      // --- Column zones (all pages) ---
      for(let i = 0; i < St.cmColumns.length; i++){
        const col = St.cmColumns[i];
        const x = col.x_min * scale;
        const w = (col.x_max - col.x_min) * scale;
        const color = _TYPE_COLORS[col.col_type] || "#94a3b8";

        // On first page: start at header_y; on subsequent pages: from top
        const y = (p === 0) ? (col.header_y || 0) * scale : 0;

        // Column fill
        markup += `<rect x="${x}" y="${y}" width="${w}" height="${imgH - y}" fill="${color}" fill-opacity="0.10" />`;

        // Column header band (first page only)
        if(p === 0){
          markup += `<rect x="${x}" y="${y}" width="${w}" height="${20 * scale}" fill="${color}" fill-opacity="0.30" />`;
          const label = (St.cmColumnTypes[col.col_type] || {}).label || col.label || "";
          markup += `<text x="${x + 4}" y="${y + 14 * scale}" font-size="${11 * scale}" fill="${color}" font-weight="bold" style="pointer-events:none">${_esc(label)}</text>`;
        }

        // Left edge of first column (draggable)
        if(i === 0){
          const lx = col.x_min * scale;
          markup += `<line x1="${lx}" y1="${y}" x2="${lx}" y2="${imgH}" stroke="${color}" stroke-width="2" stroke-dasharray="3,3" style="cursor:col-resize" data-edge="left" />`;
          // Invisible wider hit zone
          markup += `<line x1="${lx}" y1="${y}" x2="${lx}" y2="${imgH}" stroke="transparent" stroke-width="${16 * scale}" style="pointer-events:stroke;cursor:col-resize" data-edge="left" />`;
        }

        // Right boundary line (draggable) — between columns
        if(i < St.cmColumns.length - 1){
          const bx = col.x_max * scale;
          markup += `<line x1="${bx}" y1="${y}" x2="${bx}" y2="${imgH}" stroke="${color}" stroke-width="2" stroke-dasharray="6,3" style="cursor:col-resize" data-boundary="${i}" />`;
          // Invisible wider hit zone
          markup += `<line x1="${bx}" y1="${y}" x2="${bx}" y2="${imgH}" stroke="transparent" stroke-width="${16 * scale}" style="pointer-events:stroke;cursor:col-resize" data-boundary="${i}" />`;
        }

        // Right edge of last column (draggable)
        if(i === St.cmColumns.length - 1){
          const rx = col.x_max * scale;
          markup += `<line x1="${rx}" y1="${y}" x2="${rx}" y2="${imgH}" stroke="${color}" stroke-width="2" stroke-dasharray="3,3" style="cursor:col-resize" data-edge="right" />`;
          markup += `<line x1="${rx}" y1="${y}" x2="${rx}" y2="${imgH}" stroke="transparent" stroke-width="${16 * scale}" style="pointer-events:stroke;cursor:col-resize" data-edge="right" />`;
        }
      }

      svg.innerHTML = markup;

      // Store current scale on svg element (updated every re-render)
      svg._currentScale = scale;

      // Bind drag handlers once per page-svg
      if(!svg._dragBound){
        _cmBindDragHandlers(svg);
        svg._dragBound = true;
      }
    }

    // Global move/up handlers (bound once)
    _cmEnsureGlobalDrag();
  }

  // ---- Shared drag state (one drag at a time) ----
  let _dragState = null; // {type: "boundary"|"hdr-move"|"hdr-resize", svg, scale, ...}

  function _cmBindDragHandlers(svg){
    const wrap = svg.parentElement; // per-page wrapper
    if(!wrap) return;

    // Read current scale dynamically (updated by _cmRenderOverlay)
    const _getScale = () => svg._currentScale || St.cmPageScale || 1;

    // Compute PDF coordinates relative to this page wrapper
    const _pdfCoords = (e) => {
      const scale = _getScale();
      const rect = wrap.getBoundingClientRect();
      const img = wrap.querySelector("img");
      if(!img || !img.naturalWidth) return {x: 0, y: 0};
      const displayScale = wrap.clientWidth / img.naturalWidth;
      return {
        x: (e.clientX - rect.left) / (displayScale * scale),
        y: (e.clientY - rect.top) / (displayScale * scale),
      };
    };

    // ---- Mousedown: start a drag ----
    const _onDown = (e) => {
      if(_dragState) return;
      const el = e.target;
      const scale = _getScale();

      // 1) Header field handle (resize)
      if(el && el.hasAttribute("data-hdr-handle")){
        const idx = parseInt(el.getAttribute("data-hdr-handle"), 10);
        const f = St.cmHeaderFields[idx];
        if(!f || !f.box) return;
        _dragState = {
          type: "hdr-resize", idx, corner: el.getAttribute("data-corner") || "",
          startMouse: _pdfCoords(e), startBox: {...f.box}, svg, scale,
        };
        e.preventDefault(); e.stopPropagation();
        return;
      }

      // 2) Header field rect (move)
      if(el && el.hasAttribute("data-hdr-field")){
        const idx = parseInt(el.getAttribute("data-hdr-field"), 10);
        const f = St.cmHeaderFields[idx];
        if(!f || !f.box) return;
        _dragState = {
          type: "hdr-move", idx,
          startMouse: _pdfCoords(e), startBox: {...f.box}, svg, scale,
        };
        e.preventDefault(); e.stopPropagation();
        if(St.cmActiveHdrField !== idx){
          St.cmActiveHdrField = idx;
          _renderHeaderFields();
          _cmRenderOverlay();
        }
        return;
      }

      // 3) Column boundary or outer edge (by proximity)
      const rect = wrap.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const img = wrap.querySelector("img");
      const dispScale = img ? wrap.clientWidth / img.naturalWidth : 1;
      const hitZone = 20;

      // Check all column boundaries: left edge, internal, right edge
      // Build array of {screenX, action} sorted by distance from click
      const edges = [];
      if(St.cmColumns.length > 0){
        // Left outer edge
        edges.push({
          sx: St.cmColumns[0].x_min * scale * dispScale,
          action: {type: "edge-left", svg, scale},
        });
        // Internal boundaries (right side of each column = left side of next)
        for(let i = 0; i < St.cmColumns.length - 1; i++){
          edges.push({
            sx: St.cmColumns[i].x_max * scale * dispScale,
            action: {type: "boundary", idx: i, svg, scale},
          });
        }
        // Right outer edge
        edges.push({
          sx: St.cmColumns[St.cmColumns.length - 1].x_max * scale * dispScale,
          action: {type: "edge-right", svg, scale},
        });
      }

      // Find closest edge within hit zone
      let bestDist = hitZone;
      let bestAction = null;
      for(const edge of edges){
        const dist = Math.abs(mx - edge.sx);
        if(dist < bestDist){
          bestDist = dist;
          bestAction = edge.action;
        }
      }
      if(bestAction){
        _dragState = bestAction;
        e.preventDefault();
        wrap.style.cursor = "col-resize";
        return;
      }
    };

    // Show col-resize cursor on hover near boundaries
    wrap.addEventListener("mousemove", (e) => {
      if(_dragState) return;
      const scale = _getScale();
      const rect = wrap.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const img = wrap.querySelector("img");
      const dispScale = img ? wrap.clientWidth / img.naturalWidth : 1;
      const hoverZone = 12;

      let nearEdge = false;
      for(let i = 0; i < St.cmColumns.length; i++){
        const col = St.cmColumns[i];
        if(i === 0 && Math.abs(mx - col.x_min * scale * dispScale) < hoverZone){ nearEdge = true; break; }
        if(Math.abs(mx - col.x_max * scale * dispScale) < hoverZone){ nearEdge = true; break; }
      }
      wrap.style.cursor = nearEdge ? "col-resize" : "";
    });

    wrap.addEventListener("mousedown", _onDown);
    svg.addEventListener("mousedown", _onDown);
  }

  // Global move/up handlers (bound once)
  let _dragGlobalBound = false;
  function _cmEnsureGlobalDrag(){
    if(_dragGlobalBound) return;
    _dragGlobalBound = true;

    document.addEventListener("mousemove", (e) => {
      if(!_dragState) return;
      const d = _dragState;
      const svg = d.svg;
      const scale = d.scale;
      const wrap = svg ? svg.parentElement : null;

      if(d.type === "boundary" || d.type === "edge-left" || d.type === "edge-right"){
        if(!wrap) return;
        const img = wrap.querySelector("img");
        if(!img) return;
        const rect = wrap.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const displayScale = wrap.clientWidth / img.naturalWidth;
        const pdfX = mx / (displayScale * scale);

        if(d.type === "edge-left"){
          // Move left edge of first column
          const col0 = St.cmColumns[0];
          if(!col0) return;
          const maxX = col0.x_max - 10;
          col0.x_min = Math.max(0, Math.min(maxX, pdfX));
          // Fast update on all pages
          for(const pe of (St.cmPageElements || [])){
            const lines = pe.svg.querySelectorAll('line[data-edge="left"]');
            lines.forEach(line => {
              const sx = col0.x_min * (pe.scale || scale);
              line.setAttribute("x1", sx); line.setAttribute("x2", sx);
            });
          }
        } else if(d.type === "edge-right"){
          // Move right edge of last column
          const lastCol = St.cmColumns[St.cmColumns.length - 1];
          if(!lastCol) return;
          const minX = lastCol.x_min + 10;
          lastCol.x_max = Math.max(minX, pdfX);
          for(const pe of (St.cmPageElements || [])){
            const lines = pe.svg.querySelectorAll('line[data-edge="right"]');
            lines.forEach(line => {
              const sx = lastCol.x_max * (pe.scale || scale);
              line.setAttribute("x1", sx); line.setAttribute("x2", sx);
            });
          }
        } else {
          // Internal boundary
          const minX = (d.idx > 0 ? St.cmColumns[d.idx].x_min + 10 : 10);
          const maxX = (d.idx + 2 < St.cmColumns.length ? St.cmColumns[d.idx + 2].x_max - 10 : 9999);
          const newX = Math.max(minX, Math.min(maxX, pdfX));
          St.cmColumns[d.idx].x_max = newX;
          St.cmColumns[d.idx + 1].x_min = newX;
          for(const pe of (St.cmPageElements || [])){
            // Update both visible and invisible hit zone lines
            pe.svg.querySelectorAll(`line[data-boundary="${d.idx}"]`).forEach(line => {
              const sx = newX * (pe.scale || scale);
              line.setAttribute("x1", sx); line.setAttribute("x2", sx);
            });
          }
        }
        return;
      }

      // Header field drag
      const f = St.cmHeaderFields[d.idx];
      if(!f || !wrap) return;
      const rect2 = wrap.getBoundingClientRect();
      const img2 = wrap.querySelector("img");
      if(!img2 || !img2.naturalWidth) return;
      const dScale = wrap.clientWidth / img2.naturalWidth;
      const cur = {
        x: (e.clientX - rect2.left) / (dScale * scale),
        y: (e.clientY - rect2.top) / (dScale * scale),
      };
      const dx = cur.x - d.startMouse.x;
      const dy = cur.y - d.startMouse.y;

      if(d.type === "hdr-move"){
        f.box = {
          x0: d.startBox.x0 + dx, top: d.startBox.top + dy,
          x1: d.startBox.x1 + dx, bottom: d.startBox.bottom + dy,
        };
      } else if(d.type === "hdr-resize"){
        f.box = {...d.startBox};
        if(d.corner.includes("l")) f.box.x0 = d.startBox.x0 + dx;
        if(d.corner.includes("r")) f.box.x1 = d.startBox.x1 + dx;
        if(d.corner.includes("t")) f.box.top = d.startBox.top + dy;
        if(d.corner.includes("b")) f.box.bottom = d.startBox.bottom + dy;
        if(f.box.x1 - f.box.x0 < 10) f.box.x1 = f.box.x0 + 10;
        if(f.box.bottom - f.box.top < 5) f.box.bottom = f.box.top + 5;
      }

      // Fast update: move SVG elements directly (only page 0 svg)
      const pad = 3 * scale;
      const mainRect = svg.querySelector(`rect[data-hdr-field="${d.idx}"]`);
      if(mainRect){
        const rx = f.box.x0 * scale - pad;
        const ry = f.box.top * scale - pad;
        const rw = (f.box.x1 - f.box.x0) * scale + 2 * pad;
        const rh = (f.box.bottom - f.box.top) * scale + 2 * pad;
        mainRect.setAttribute("x", rx); mainRect.setAttribute("y", ry);
        mainRect.setAttribute("width", rw); mainRect.setAttribute("height", rh);
      }
      const handles = svg.querySelectorAll(`rect[data-hdr-handle="${d.idx}"]`);
      if(handles.length === 4){
        const rx = f.box.x0 * scale - pad;
        const ry = f.box.top * scale - pad;
        const rw = (f.box.x1 - f.box.x0) * scale + 2 * pad;
        const rh = (f.box.bottom - f.box.top) * scale + 2 * pad;
        const hs = 3 * scale;
        const corners = [{x: rx, y: ry}, {x: rx + rw, y: ry}, {x: rx, y: ry + rh}, {x: rx + rw, y: ry + rh}];
        handles.forEach((h, hi) => {
          h.setAttribute("x", corners[hi].x - hs);
          h.setAttribute("y", corners[hi].y - hs);
        });
      }
    });

    document.addEventListener("mouseup", () => {
      if(!_dragState) return;
      const d = _dragState;
      _dragState = null;
      if(d.svg && d.svg.parentElement) d.svg.parentElement.style.cursor = "";

      if(d.type === "boundary" || d.type === "edge-left" || d.type === "edge-right"){
        _cmSyncMapping();
        _cmRenderOverlay();
        return;
      }

      const f = St.cmHeaderFields[d.idx];
      if(f && f.box){
        const wordsInBox = (St.cmHeaderWords || []).filter(w =>
          w.x0 >= f.box.x0 - 2 && w.x1 <= f.box.x1 + 2 &&
          w.top >= f.box.top - 2 && w.bottom <= f.box.bottom + 2
        );
        if(wordsInBox.length > 0){
          f.value = wordsInBox.map(w => w.text).join(" ");
        }
        _renderHeaderFields();
        _cmRenderOverlay();
      }
    });
  }

  // Allow creating a new header field box by double-clicking on PDF (page 0)
  function _cmBindHeaderFieldCreate(){
    // Use event delegation on the pages container
    const pagesContainer = QS("#cm_pages_container");
    if(!pagesContainer) return;

    pagesContainer.addEventListener("dblclick", (e) => {
      // Only when a field is active with no box
      const activeIdx = St.cmActiveHdrField;
      if(activeIdx < 0 || activeIdx >= St.cmHeaderFields.length) return;
      const f = St.cmHeaderFields[activeIdx];
      if(f.box) return; // already has a box

      // Find which page wrapper was clicked
      const wrap = e.target.closest(".cm-page-wrap");
      if(!wrap) return;
      const pageNum = parseInt(wrap.getAttribute("data-page") || "0", 10);
      if(pageNum !== 0) return; // header fields only on page 0

      const rect = wrap.getBoundingClientRect();
      const img = wrap.querySelector("img");
      if(!img || !img.naturalWidth) return;
      const scale = St.cmPageScale;
      const displayScale = wrap.clientWidth / img.naturalWidth;
      const pdfX = (e.clientX - rect.left) / (displayScale * scale);
      const pdfY = (e.clientY - rect.top) / (displayScale * scale);

      // Create a small box at click position
      f.box = {x0: pdfX - 40, top: pdfY - 6, x1: pdfX + 40, bottom: pdfY + 6};

      _renderHeaderFields();
      _cmRenderOverlay();
    });
  }

  function _cmSyncMapping(){
    St.cmMapping = {};
    for(let i = 0; i < St.cmColumns.length; i++){
      if(St.cmColumns[i].col_type && St.cmColumns[i].col_type !== "skip"){
        St.cmMapping[String(i)] = St.cmColumns[i].col_type;
      }
    }
  }

  function _renderCmHeaders(){
    const container = QS("#cm_headers");
    if(!container) return;

    const types = St.cmColumnTypes;
    let html = '<div style="display:flex;gap:4px;overflow-x:auto;padding:4px 0">';

    for(let i = 0; i < St.cmColumns.length; i++){
      const col = St.cmColumns[i];
      const currentType = col.col_type || "";
      const color = _TYPE_COLORS[currentType] || "#94a3b8";

      html += `<div class="cm-col-hdr" style="min-width:80px;flex:1;border-top:3px solid ${color};padding-top:4px;position:relative">
        <div class="cm-col-label small" data-col="${i}" style="margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer" title="Kliknij aby zmienic nazwe: ${_esc(col.label)}">${_esc(col.label || "(pusta)")}</div>
        <select class="cm-type-select input" data-col="${i}" style="padding:3px 5px;border-radius:6px;font-size:12px;width:100%">
          <option value="skip">\u2014 Pomin</option>`;

      for(const [key, tmeta] of Object.entries(types)){
        const sel = currentType === key ? " selected" : "";
        html += `<option value="${_esc(key)}"${sel}>${tmeta.icon || ""} ${_esc(tmeta.label)}</option>`;
      }

      html += `</select>
        <div style="display:flex;gap:2px;margin-top:3px">
          <button class="cm-col-split" data-col="${i}" style="flex:1;background:none;border:1px solid var(--border,#ddd);border-radius:4px;font-size:10px;cursor:pointer;padding:1px 0;color:var(--text-muted,#64748b)" title="Podziel kolumne na dwie">\u2702</button>
          <button class="cm-col-remove" data-col="${i}" style="flex:1;background:none;border:1px solid var(--border,#ddd);border-radius:4px;font-size:10px;cursor:pointer;padding:1px 0;color:var(--danger,#b91c1c)" title="Usun kolumne">\u2715</button>
        </div>
      </div>`;
    }
    html += '</div>';
    container.innerHTML = html;

    // Bind type dropdown changes
    QSA(".cm-type-select", container).forEach(sel => {
      sel.addEventListener("change", () => {
        const idx = parseInt(sel.getAttribute("data-col"), 10);
        if(idx < St.cmColumns.length){
          St.cmColumns[idx].col_type = sel.value;
          _cmSyncMapping();
          _cmRenderOverlay();
        }
      });
    });

    // Bind label click → rename
    QSA(".cm-col-label", container).forEach(el => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.getAttribute("data-col"), 10);
        _cmRenameColumn(idx);
      });
    });

    // Bind split
    QSA(".cm-col-split", container).forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-col"), 10);
        _cmSplitColumn(idx);
      });
    });

    // Bind remove
    QSA(".cm-col-remove", container).forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-col"), 10);
        _cmRemoveColumn(idx);
      });
    });
  }

  async function _cmPreviewParse(){
    const preview = St.cmPreview;
    if(!preview) return;

    const container = QS("#cm_parsed_preview");
    if(!container) return;
    container.innerHTML = '<div class="small muted">Parsowanie...</div>';

    // Build column_bounds from current columns (full info for backend)
    const column_bounds = St.cmColumns.map(c => ({
      x_min: c.x_min, x_max: c.x_max, label: c.label, col_type: c.col_type,
    }));

    try{
      const data = await _api("/api/aml/preview-parse", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          file_path: preview.file_path,
          column_mapping: St.cmMapping,
          column_bounds: column_bounds,
        }),
      });

      if(data && data.status === "ok" && data.transactions){
        _renderCmParsedPreview(container, data.transactions, data.transaction_count, data.pages_parsed, data.page_count);
      } else {
        container.innerHTML = `<div class="small" style="color:var(--danger)">${_esc(data && data.error ? data.error : "Blad parsowania")}</div>`;
      }
    } catch(e){
      container.innerHTML = `<div class="small" style="color:var(--danger)">Blad: ${_esc(e.message || e)}</div>`;
    }
  }

  function _renderCmParsedPreview(container, transactions, total, pagesParsed, pageCount){
    if(!transactions || !transactions.length){
      container.innerHTML = '<div class="small muted">Brak rozpoznanych transakcji. Sprawdz mapowanie kolumn.</div>';
      return;
    }

    const pgInfo = (pagesParsed && pageCount && pagesParsed < pageCount)
      ? ` <span style="color:var(--warning,#d97706)">(podglad: ${pagesParsed}/${pageCount} stron — pelna analiza obejmie wszystkie)</span>`
      : (pagesParsed && pageCount ? ` (${pagesParsed}/${pageCount} stron)` : "");
    let html = `<div class="small muted" style="margin-bottom:4px">Rozpoznano <b>${total}</b> transakcji${pgInfo}. Podglad:</div>`;
    html += '<table style="width:100%;font-size:11px;border-collapse:collapse">';
    html += '<tr style="background:var(--bg-alt,#f1f5f9);font-weight:bold"><td style="padding:3px 5px">Data</td><td>Kontrahent</td><td>Tytul</td><td style="text-align:right">Kwota</td><td style="text-align:right">Saldo</td></tr>';

    for(const tx of transactions.slice(0, 15)){
      const amt = Number(tx.amount || 0);
      const color = amt < 0 ? "var(--danger,#b91c1c)" : "var(--ok,#15803d)";
      html += `<tr style="border-bottom:1px solid var(--border,#e2e8f0)">
        <td style="padding:2px 5px;white-space:nowrap">${_esc(tx.date || "")}</td>
        <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(tx.counterparty || "")}">${_esc((tx.counterparty || "").slice(0,35))}</td>
        <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(tx.title || "")}">${_esc((tx.title || "").slice(0,50))}</td>
        <td style="text-align:right;color:${color};white-space:nowrap;font-weight:600">${_fmtAmount(amt, "")}</td>
        <td style="text-align:right;white-space:nowrap">${tx.balance_after != null ? _fmtAmount(tx.balance_after, "") : ""}</td>
      </tr>`;
    }

    html += '</table>';
    container.innerHTML = html;
  }

  function _cmConfirm(){
    const preview = St.cmPreview;
    if(!preview) return;

    const saveTemplate = QS("#cm_save_template")?.checked || false;
    const setDefault = QS("#cm_set_default")?.checked || false;
    const templateName = QS("#cm_template_name")?.value || "";
    const templateId = preview.template ? (preview.template.id || "") : "";
    const runLlm = QS("#cm_run_llm")?.checked || false;

    const _hfForApi = _getHeaderFieldsForApi();
    console.log("[AML] Confirm — save_template:", saveTemplate,
      "| header_fields:", JSON.stringify(_hfForApi));

    _runFullPipeline(preview.file_path, St.cmMapping, {
      save_template: saveTemplate,
      template_name: templateName,
      set_default: setDefault,
      template_id: templateId,
      bank_id: preview.bank_id,
      bank_name: preview.bank_name,
      header_cells: St.cmColumns.map(c => c.label),
      column_bounds: St.cmColumns.map(c => ({x_min: c.x_min, x_max: c.x_max, label: c.label, col_type: c.col_type})),
      header_fields: _hfForApi,
      run_llm: runLlm,
    });
  }

  function _bindColumnMapping(){
    const backBtn = QS("#cm_back_btn");
    if(backBtn) backBtn.addEventListener("click", ()=> _showUpload());

    const refreshBtn = QS("#cm_refresh_preview");
    if(refreshBtn) refreshBtn.addEventListener("click", ()=> _cmPreviewParse());

    const confirmBtn = QS("#cm_confirm_btn");
    if(confirmBtn) confirmBtn.addEventListener("click", ()=> _cmConfirm());

    const saveCheck = QS("#cm_save_template");
    const nameInput = QS("#cm_template_name");
    if(saveCheck && nameInput){
      saveCheck.addEventListener("change", ()=>{
        nameInput.style.display = saveCheck.checked ? "" : "none";
      });
    }

    // Add column button
    const addColBtn = QS("#cm_add_col_btn");
    if(addColBtn) addColBtn.addEventListener("click", ()=> _cmAddColumn());

    // Double-click on PDF to place a header field box
    _cmBindHeaderFieldCreate();
  }

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
      status: "queued",   // queued | uploading | mapping | processing | done | error
      statementId: null,
      error: null,
      preview: null,       // preview-pdf response (for auto-template check)
    }));
    St.batchIdx = -1;
    St.batchCaseId = "";
    St.batchResults = [];

    console.log("[AML Batch] Starting batch:", pdfs.length, "files");
    _renderBatchPanel();
    _showBatchPanel();
    _processBatchNext();
  }

  async function _processBatchNext(){
    St.batchIdx++;
    if(St.batchIdx >= St.batchFiles.length){
      // All files processed — run cross-validation
      await _batchFinalize();
      return;
    }

    const entry = St.batchFiles[St.batchIdx];
    entry.status = "uploading";
    _renderBatchPanel();

    const fd = new FormData();
    fd.append("file", entry.file, entry.name);

    try {
      const result = await _api("/api/aml/preview-pdf", {method:"POST", body:fd});

      if(result && result.status === "ok"){
        entry.preview = result;
        entry.status = "mapping";
        _renderBatchPanel();

        // Check if template auto-applies (exact match, not partial)
        const tpl = result.template;
        const hasFullTemplate = tpl && tpl.column_mapping && !tpl._partial_match;

        if(hasFullTemplate){
          // Auto-run pipeline — no manual mapping needed
          console.log("[AML Batch] Auto-template for", entry.name, ":", tpl.name);
          entry.status = "processing";
          _renderBatchPanel();
          await _batchRunPipeline(entry, result, tpl);
        } else {
          // Need manual mapping — show mapping UI for this file
          console.log("[AML Batch] Manual mapping needed for", entry.name);
          _batchShowMappingForFile(entry, result);
          // _processBatchNext will be called from _batchConfirmMapping
          return;
        }
      } else if(result && result.status === "no_tables"){
        entry.status = "error";
        entry.error = "Nie znaleziono tabel w PDF";
        _renderBatchPanel();
      } else {
        entry.status = "error";
        entry.error = result && result.error ? String(result.error) : "Blad podgladu PDF";
        _renderBatchPanel();
      }
    } catch(e){
      entry.status = "error";
      entry.error = String(e.message || e);
      _renderBatchPanel();
    }

    // Continue to next file
    _processBatchNext();
  }

  async function _batchRunPipeline(entry, preview, tpl){
    // Build column mapping from template
    const columns = (preview.columns || []).map(c => ({...c}));
    let mapping = {};
    const tplBounds = tpl.column_bounds || [];
    const tplMapping = tpl.column_mapping || {};
    let finalColumns = columns;

    if(tplBounds.length > 0 && tplBounds[0] && tplBounds[0].x_min != null){
      finalColumns = tplBounds.map((b, i) => ({
        label: b.label || "",
        col_type: tplMapping[String(i)] || b.col_type || "skip",
        x_min: b.x_min,
        x_max: b.x_max,
      }));
      mapping = {...tplMapping};
    } else {
      // Apply by label matching (reuse logic from _applyTemplateToColumns)
      const sampleHeaders = tpl.sample_headers || [];
      for(const [idxStr, colType] of Object.entries(tplMapping)){
        const tIdx = parseInt(idxStr, 10);
        const tLabel = (tIdx >= 0 && tIdx < sampleHeaders.length)
          ? String(sampleHeaders[tIdx] || "").trim().toLowerCase() : "";
        // Try exact label match
        let matched = false;
        for(let i = 0; i < columns.length; i++){
          const cur = String(columns[i].label || "").trim().toLowerCase();
          if(cur && tLabel && cur === tLabel){
            mapping[String(i)] = colType;
            columns[i].col_type = colType;
            matched = true;
            break;
          }
        }
        if(!matched){
          // Fallback to index
          if(tIdx >= 0 && tIdx < columns.length){
            mapping[String(tIdx)] = colType;
            columns[tIdx].col_type = colType;
          }
        }
      }
      finalColumns = columns;
    }

    // Build header fields from template
    const headerFields = {};
    const savedHf = tpl.header_fields || {};
    const detectedHf = preview.header_region || {};
    // Use detected values first, then overlay template values
    const allFieldKeys = new Set([
      ...Object.keys(detectedHf),
      ...Object.keys(savedHf),
    ]);
    const skipKeys = new Set(["words","raw_text","field_boxes","bank_name_detected"]);
    for(const key of allFieldKeys){
      if(skipKeys.has(key)) continue;
      let val = detectedHf[key];
      if(savedHf[key]) val = savedHf[key]; // template overrides
      if(val != null && val !== ""){
        let sVal = String(val);
        if(_AMOUNT_FIELDS.has(key) || _COUNT_FIELDS.has(key)){
          sVal = _sanitizeNumericValue(sVal);
        }
        if(sVal) headerFields[key] = sVal;
      }
    }

    const body = {
      file_path: preview.file_path,
      column_mapping: mapping,
      header_row: 0,
      data_start_row: 1,
      main_table_index: 0,
      save_template: false,
      template_name: "",
      set_default: false,
      template_id: tpl.id || "",
      bank_id: preview.bank_id || "",
      bank_name: preview.bank_name || "",
      header_cells: finalColumns.map(c => c.label),
      column_bounds: finalColumns.map(c => ({x_min: c.x_min, x_max: c.x_max, label: c.label, col_type: c.col_type})),
      header_fields: headerFields,
      case_id: St.batchCaseId,
    };

    try {
      const result = await _api("/api/aml/confirm-mapping", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body),
      });

      if(result && result.status === "ok"){
        entry.status = "done";
        entry.statementId = result.statement_id;
        // Capture case_id from first successful result
        if(!St.batchCaseId && result.case_id){
          St.batchCaseId = result.case_id;
        }
        St.batchResults.push(result.statement_id);
        console.log("[AML Batch] Done:", entry.name, "stmt:", result.statement_id);
      } else {
        entry.status = "error";
        entry.error = result && result.error ? String(result.error) : "Blad analizy";
      }
    } catch(e){
      entry.status = "error";
      entry.error = String(e.message || e);
    }

    _renderBatchPanel();
  }

  function _batchShowMappingForFile(entry, preview){
    // Store the preview for normal mapping UI
    St.cmPreview = preview;
    St.cmMapping = preview.auto_mapping || {};
    St.cmColumnTypes = preview.column_types || {};

    _renderColumnMapping();
    _showMapping();
    // Also keep batch panel visible
    _show("aml_batch_panel");

    // Override the confirm button to use batch flow
    const confirmBtn = QS("#cm_confirm_btn");
    if(confirmBtn){
      confirmBtn.onclick = ()=> _batchConfirmMapping(entry);
    }
  }

  async function _batchConfirmMapping(entry){
    const preview = St.cmPreview;
    if(!preview) return;

    entry.status = "processing";
    _renderBatchPanel();

    const saveTemplate = QS("#cm_save_template")?.checked || false;
    const setDefault = QS("#cm_set_default")?.checked || false;
    const templateName = QS("#cm_template_name")?.value || "";
    const templateId = preview.template ? (preview.template.id || "") : "";

    const _hfForApi = _getHeaderFieldsForApi();

    const body = {
      file_path: preview.file_path,
      column_mapping: St.cmMapping,
      header_row: 0,
      data_start_row: 1,
      main_table_index: 0,
      save_template: saveTemplate,
      template_name: templateName,
      set_default: setDefault,
      template_id: templateId,
      bank_id: preview.bank_id || "",
      bank_name: preview.bank_name || "",
      header_cells: St.cmColumns.map(c => c.label),
      column_bounds: St.cmColumns.map(c => ({x_min: c.x_min, x_max: c.x_max, label: c.label, col_type: c.col_type})),
      header_fields: _hfForApi,
      case_id: St.batchCaseId,
    };

    try {
      const result = await _api("/api/aml/confirm-mapping", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body),
      });

      if(result && result.status === "ok"){
        entry.status = "done";
        entry.statementId = result.statement_id;
        if(!St.batchCaseId && result.case_id){
          St.batchCaseId = result.case_id;
        }
        St.batchResults.push(result.statement_id);
      } else {
        entry.status = "error";
        entry.error = result && result.error ? String(result.error) : "Blad analizy";
      }
    } catch(e){
      entry.status = "error";
      entry.error = String(e.message || e);
    }

    _renderBatchPanel();

    // Restore original confirm button handler
    const confirmBtn = QS("#cm_confirm_btn");
    if(confirmBtn) confirmBtn.onclick = ()=> _cmConfirm();

    // Continue batch
    _processBatchNext();
  }

  async function _batchFinalize(){
    console.log("[AML Batch] Finalize. Results:", St.batchResults.length, "/", St.batchFiles.length);
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

    // If we have any successful results, load the last one for review
    if(St.batchResults.length > 0){
      const lastStmtId = St.batchResults[St.batchResults.length - 1];
      await _loadDetail(lastStmtId);
    }
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
        case "queued": return "\u23F3";     // hourglass
        case "uploading": return "\u2B06\uFE0F"; // up arrow
        case "mapping": return "\uD83D\uDDC2\uFE0F"; // file cabinet
        case "processing": return "\u2699\uFE0F"; // gear
        case "done": return "\u2705";       // checkmark
        case "error": return "\u274C";      // cross
        default: return "\u2022";
      }
    };
    const _statusLabel = (status) => {
      switch(status){
        case "queued": return "W kolejce";
        case "uploading": return "Przesylanie...";
        case "mapping": return "Mapowanie kolumn...";
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
        case "mapping": return "#3b82f6";
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
      viewBtn.onclick = async ()=>{
        if(St.batchResults.length > 0){
          const lastId = St.batchResults[St.batchResults.length - 1];
          await _loadDetail(lastId);
          _renderResults();
          _showResults();
          // Keep batch panel hidden but accessible
          _hide("aml_batch_panel");
          if(window.ReviewManager && lastId){
            ReviewManager.loadForStatement(lastId);
          }
        }
      };
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
      _bindColumnMapping();
      await _loadHistory();
      _showUpload();
    },

    /** Called by ReviewManager after classification change. */
    refreshGraphColors: _refreshGraphColors,
  };

  window.AmlManager = AmlManager;
})();
