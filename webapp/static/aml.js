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
    cmHeaderFields: [],   // [{field_type, value, raw_label}] — editable header fields
  };

  // ============================================================
  // UPLOAD & ANALYZE
  // ============================================================

  function _showUpload(){
    _show("aml_upload_zone");
    _hide("aml_progress_card");
    _hide("aml_results");
    _hide("aml_mapping_card");
    const histCard = QS("#aml_history_card");
    if(histCard && St.history.length) _show("aml_history_card");
  }

  function _showProgress(text){
    _hide("aml_upload_zone");
    _show("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    _hide("aml_mapping_card");
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
  }

  function _showMapping(){
    _hide("aml_upload_zone");
    _hide("aml_progress_card");
    _hide("aml_results");
    _hide("aml_history_card");
    _show("aml_mapping_card");
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

        // If a saved template matches, use it
        if(result.template && result.template.column_mapping && !result.template._partial_match){
          St.cmMapping = result.template.column_mapping;
        }

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

    // Bank info
    _renderBankInfo(stmt, result);

    // Alerts
    const alerts = risk.score_breakdown && risk.score_breakdown.alerts
      ? risk.score_breakdown.alerts
      : (result.alerts || []);
    _renderAlerts(alerts);

    // Charts
    const charts = detail.charts || result.charts || {};
    St.chartsData = charts;
    _renderChart("balance_timeline");

    // ML anomalies
    const mlAnomalies = detail.ml_anomalies || [];
    _renderMlAnomalies(mlAnomalies, transactions);

    // LLM section
    _setupLlmSection(detail.has_llm_prompt || result.has_llm_prompt);

    // Graph
    _renderGraph(graph);

    // Transactions
    _renderTransactions(transactions);

    // Memory
    _loadMemory();

    // Trigger review module for integrated view
    if(window.ReviewManager && St.statementId){
      ReviewManager.loadForStatement(St.statementId);
    }
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

    grid.innerHTML = `
      ${bank ? `<div class="aml-info-row"><b>Bank:</b> ${_esc(bank)}</div>` : ""}
      ${holder ? `<div class="aml-info-row"><b>Wlasciciel:</b> ${_esc(holder)}</div>` : ""}
      ${iban ? `<div class="aml-info-row"><b>IBAN:</b> <span style="font-family:monospace">${_esc(iban)}</span></div>` : ""}
      ${period ? `<div class="aml-info-row"><b>Okres:</b> ${_esc(period)}</div>` : ""}
      <div class="aml-info-stats">
        <span><b>Saldo pocz.:</b> ${_fmtAmount(stmt.opening_balance, cur)}</span>
        <span><b>Saldo konc.:</b> ${_fmtAmount(stmt.closing_balance, cur)}</span>
      </div>
      <div class="small muted">Transakcje: ${(result.transaction_count || St.allTransactions.length) || 0} | Czas analizy: ${result.pipeline_time_s || "?"}s</div>
    `;
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

    if(btn) btn.disabled = true;
    if(status) status.textContent = "Generowanie analizy LLM... (to moze potrwac 30-120s)";
    if(resultDiv) resultDiv.style.display = "none";

    try{
      const data = await _api("/api/aml/llm-analyze/" + encodeURIComponent(St.statementId), {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({}),
      });

      if(data && data.status === "ok" && data.analysis){
        if(textDiv) textDiv.innerHTML = _formatLlmText(data.analysis);
        if(resultDiv) resultDiv.style.display = "";
        if(status) status.textContent = "Analiza wygenerowana pomyslnie.";
      } else {
        if(status) status.textContent = "Blad: " + (data && data.error ? data.error : "Nieznany blad");
      }
    } catch(e) {
      if(status) status.textContent = "Blad: " + String(e.message || e);
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

  function _renderGraph(graphData){
    const container = QS("#aml_graph_container");
    if(!container) return;

    if(!graphData || !graphData.nodes || !graphData.nodes.length){
      container.innerHTML = '<div class="small muted" style="padding:20px">Brak danych grafu</div>';
      return;
    }

    _ensureCytoscape(()=>{
      const riskColors = {high:"#b91c1c", medium:"#d97706", low:"#2563eb", none:"#6b7280"};
      const typeShapes = {ACCOUNT:"diamond", MERCHANT:"round-rectangle", CASH_NODE:"hexagon", PAYMENT_PROVIDER:"barrel"};

      const elements = [];

      for(const node of graphData.nodes){
        elements.push({
          data: {
            id: node.id,
            label: node.label || node.id,
            type: node.node_type || node.type || "COUNTERPARTY",
            riskLevel: node.risk_level || "none",
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
              "background-color": function(ele){
                return riskColors[ele.data("riskLevel")] || "#6b7280";
              },
              "color": "#1e293b",
              "text-valign": "bottom",
              "text-margin-y": 6,
              "shape": function(ele){
                return typeShapes[ele.data("type")] || "ellipse";
              },
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
              "line-color": "#94a3b8",
              "target-arrow-color": "#64748b",
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
        layout: {
          name: "cose",
          animate: false,
          nodeRepulsion: function(){ return 8000; },
          idealEdgeLength: function(){ return 120; },
          edgeElasticity: function(){ return 100; },
          gravity: 0.3,
          padding: 30,
        },
        maxZoom: 3,
        minZoom: 0.3,
      });

      // Risk filter
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
              const src = e.source();
              const tgt = e.target();
              if(src.visible() && tgt.visible()){
                e.show();
              } else {
                e.hide();
              }
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
    if(!card || !list) return;

    if(!St.history.length){
      card.style.display = "none";
      return;
    }

    card.style.display = "";
    list.innerHTML = St.history.map(item => {
      const score = item.risk_score != null ? Math.round(item.risk_score) : "?";
      const scoreColor = score >= 60 ? "var(--danger)" : score >= 30 ? "#d97706" : "var(--ok)";
      return `<div class="aml-history-item" data-sid="${_esc(item.statement_id)}">
        <span class="aml-hist-bank">${_esc(item.bank_name || "?")}</span>
        <span class="aml-hist-period">${_esc(item.period_from || "")} \u2014 ${_esc(item.period_to || "")}</span>
        <span class="aml-hist-score" style="color:${scoreColor}">${score}</span>
        <span class="aml-hist-tx small muted">${item.tx_count || 0} tx</span>
        <span class="aml-hist-date small muted">${_fmtDate(item.created_at)}</span>
      </div>`;
    }).join("");

    // Bind clicks
    QSA(".aml-history-item", list).forEach(el=>{
      el.addEventListener("click", async ()=>{
        const sid = el.getAttribute("data-sid");
        if(!sid) return;
        _showProgress("Ladowanie analizy...");
        await _loadDetail(sid);
        _renderResults();
        _showResults();
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
        const f = fileInput.files && fileInput.files[0];
        if(f) _uploadAndAnalyze(f);
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
        const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if(f) _uploadAndAnalyze(f);
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
    bank_name:       {label:"Nazwa banku",       icon:"\uD83C\uDFE6"},
    account_number:  {label:"Nr rachunku / IBAN", icon:"\uD83D\uDD22"},
    account_holder:  {label:"Wlasciciel konta",  icon:"\uD83D\uDC64"},
    period_from:     {label:"Okres od",           icon:"\uD83D\uDCC5"},
    period_to:       {label:"Okres do",           icon:"\uD83D\uDCC5"},
    opening_balance: {label:"Saldo poczatkowe",   icon:"\uD83D\uDCB0"},
    closing_balance: {label:"Saldo koncowe",      icon:"\uD83D\uDCB0"},
    currency:        {label:"Waluta",             icon:"\uD83D\uDCB1"},
    skip:            {label:"Pomin",              icon:"\u23ED\uFE0F"},
  };

  function _renderColumnMapping(){
    const preview = St.cmPreview;
    if(!preview) return;

    // Bank label
    const bankLabel = QS("#cm_bank_label");
    if(bankLabel){
      let label = preview.bank_name || "Nieznany bank";
      if(preview.template && !preview.template._partial_match){
        label += " (szablon: " + (preview.template.name || "domyslny") + ")";
      }
      bankLabel.textContent = label;
    }

    // Warnings
    const warningsEl = QS("#cm_warnings");
    if(warningsEl && preview.warnings && preview.warnings.length){
      warningsEl.innerHTML = preview.warnings.map(w =>
        `<div class="small" style="color:var(--danger);margin:2px 0">\u26A0 ${_esc(w)}</div>`
      ).join("");
    }

    // Store columns for SVG overlay
    St.cmColumns = (preview.columns || []).map(c => ({...c}));

    // Build header fields from detected header_region
    _buildHeaderFields(preview.header_region);

    // Render header fields editor
    _renderHeaderFields();

    // Load first page image
    _cmLoadPageImage(0);

    // Render column type selectors
    _renderCmHeaders();

    // Auto-run preview parse
    _cmPreviewParse();
  }

  // ============================================================
  // HEADER REGION EDITOR
  // ============================================================

  function _buildHeaderFields(region){
    St.cmHeaderFields = [];
    if(!region) return;

    // Pre-populate from auto-detected fields
    const fieldMap = {
      account_number: "Nr rachunku",
      opening_balance: "Saldo poczatkowe",
      closing_balance: "Saldo koncowe",
      period_from: "Okres od",
      period_to: "Okres do",
    };
    for(const [key, rawLabel] of Object.entries(fieldMap)){
      const val = region[key];
      if(val != null && val !== ""){
        St.cmHeaderFields.push({
          field_type: key,
          value: String(val),
          raw_label: rawLabel,
        });
      }
    }

    // Add bank_name from preview
    const preview = St.cmPreview;
    if(preview && preview.bank_name){
      St.cmHeaderFields.unshift({
        field_type: "bank_name",
        value: preview.bank_name,
        raw_label: "Bank",
      });
    }

    // If raw_text has content we didn't capture, add as unassigned
    if(region.raw_text){
      const captured = St.cmHeaderFields.map(f => f.value).join(" ");
      // Check for IBAN-like patterns not yet captured
      const ibanMatch = region.raw_text.match(/(?:PL\s*)?(\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4})/);
      if(ibanMatch && !St.cmHeaderFields.find(f => f.field_type === "account_number")){
        St.cmHeaderFields.push({
          field_type: "account_number",
          value: ibanMatch[0].replace(/\s/g, ""),
          raw_label: "IBAN (wykryty)",
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
      html += `<div class="cm-hdr-field" style="display:flex;flex-direction:column;gap:2px;min-width:140px;padding:6px 8px;border:1px solid var(--border,#e2e8f0);border-radius:8px;background:var(--bg-alt,#f8fafc)">
        <select class="cm-hdr-type-sel input" data-idx="${i}" style="padding:2px 5px;border-radius:5px;font-size:11px">`;

      for(const [key, tmeta] of Object.entries(_HEADER_FIELD_TYPES)){
        const sel = f.field_type === key ? " selected" : "";
        html += `<option value="${_esc(key)}"${sel}>${tmeta.icon} ${_esc(tmeta.label)}</option>`;
      }

      html += `</select>
        <input class="cm-hdr-value-input input" data-idx="${i}" value="${_esc(f.value)}" style="padding:3px 6px;border-radius:5px;font-size:12px;font-weight:600" title="Kliknij aby edytowac">
        <button class="cm-hdr-del" data-idx="${i}" style="align-self:flex-end;background:none;border:none;color:var(--danger,#b91c1c);cursor:pointer;font-size:11px;padding:0" title="Usun pole">\u2715</button>
      </div>`;
    }

    html += `<button class="btn mini" id="cm_add_header_field" style="align-self:center;min-width:40px" title="Dodaj pole naglowka">+</button>`;
    container.innerHTML = html;

    // Bind events
    QSA(".cm-hdr-type-sel", container).forEach(sel => {
      sel.addEventListener("change", ()=>{
        const idx = parseInt(sel.getAttribute("data-idx"), 10);
        if(idx < St.cmHeaderFields.length) St.cmHeaderFields[idx].field_type = sel.value;
      });
    });

    QSA(".cm-hdr-value-input", container).forEach(inp => {
      inp.addEventListener("change", ()=>{
        const idx = parseInt(inp.getAttribute("data-idx"), 10);
        if(idx < St.cmHeaderFields.length) St.cmHeaderFields[idx].value = inp.value.trim();
      });
    });

    QSA(".cm-hdr-del", container).forEach(btn => {
      btn.addEventListener("click", ()=>{
        const idx = parseInt(btn.getAttribute("data-idx"), 10);
        St.cmHeaderFields.splice(idx, 1);
        _renderHeaderFields();
      });
    });

    const addBtn = container.querySelector("#cm_add_header_field");
    if(addBtn) addBtn.addEventListener("click", ()=> _addHeaderField());
  }

  function _addHeaderField(){
    St.cmHeaderFields.push({
      field_type: "skip",
      value: "",
      raw_label: "Nowe pole",
    });
    _renderHeaderFields();
    // Focus the last input
    const inputs = QSA(".cm-hdr-value-input");
    if(inputs.length) inputs[inputs.length - 1].focus();
  }

  function _getHeaderFieldsForApi(){
    const result = {};
    for(const f of St.cmHeaderFields){
      if(f.field_type !== "skip" && f.value.trim()){
        result[f.field_type] = f.value.trim();
      }
    }
    return result;
  }

  // ============================================================
  // COLUMN OPERATIONS (add, split, remove, rename)
  // ============================================================

  function _cmAddColumn(){
    // Add a new column at the right side
    const lastCol = St.cmColumns.length ? St.cmColumns[St.cmColumns.length - 1] : null;
    const newXMin = lastCol ? lastCol.x_max : 0;
    const newXMax = newXMin + 80;

    // If last column exists, take some space from it
    if(lastCol && (lastCol.x_max - lastCol.x_min) > 60){
      const splitX = lastCol.x_min + (lastCol.x_max - lastCol.x_min) * 0.6;
      lastCol.x_max = splitX;
      St.cmColumns.push({
        label: "Nowa kolumna",
        col_type: "skip",
        x_min: splitX,
        x_max: splitX + (newXMax - newXMin),
        header_y: lastCol.header_y,
      });
    } else {
      St.cmColumns.push({
        label: "Nowa kolumna",
        col_type: "skip",
        x_min: newXMin,
        x_max: newXMax,
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

  function _cmLoadPageImage(pageNum){
    const img = QS("#cm_page_img");
    if(!img) return;

    const preview = St.cmPreview;
    const pages = preview.pages || [];
    if(pageNum >= pages.length) return;

    const pageInfo = pages[pageNum];
    img.onload = () => {
      // Calculate scale: rendered image size vs PDF coordinate space
      St.cmPageScale = img.naturalWidth / pageInfo.width;
      _cmRenderOverlay();
    };
    img.src = `/api/aml/page-image/${pageNum}?t=${Date.now()}`;

    // Page selector
    const pageSel = QS("#cm_page_select");
    if(pageSel && pages.length > 1){
      pageSel.style.display = "";
      pageSel.innerHTML = pages.map((p, i) =>
        `<option value="${i}" ${i === pageNum ? "selected" : ""}>Str. ${i + 1}</option>`
      ).join("");
    }
  }

  function _cmRenderOverlay(){
    const svg = QS("#cm_overlay_svg");
    const img = QS("#cm_page_img");
    if(!svg || !img || !img.naturalWidth) return;

    const scale = St.cmPageScale;
    const imgW = img.naturalWidth;
    const imgH = img.naturalHeight;

    svg.setAttribute("viewBox", `0 0 ${imgW} ${imgH}`);
    svg.style.pointerEvents = "none";

    let markup = "";

    // Draw column zones as semi-transparent colored rectangles
    for(let i = 0; i < St.cmColumns.length; i++){
      const col = St.cmColumns[i];
      const x = col.x_min * scale;
      const w = (col.x_max - col.x_min) * scale;
      const color = _TYPE_COLORS[col.col_type] || "#94a3b8";
      const y = (col.header_y || 0) * scale;

      // Column fill (from header to bottom)
      markup += `<rect x="${x}" y="${y}" width="${w}" height="${imgH - y}" fill="${color}" fill-opacity="0.10" />`;

      // Column header band
      markup += `<rect x="${x}" y="${y}" width="${w}" height="${20 * scale}" fill="${color}" fill-opacity="0.30" />`;

      // Column label
      const label = (St.cmColumnTypes[col.col_type] || {}).label || col.label || "";
      markup += `<text x="${x + 4}" y="${y + 14 * scale}" font-size="${11 * scale}" fill="${color}" font-weight="bold" style="pointer-events:none">${_esc(label)}</text>`;

      // Right boundary line (draggable)
      if(i < St.cmColumns.length - 1){
        const bx = col.x_max * scale;
        markup += `<line x1="${bx}" y1="${y}" x2="${bx}" y2="${imgH}" stroke="${color}" stroke-width="2" stroke-dasharray="6,3" style="pointer-events:stroke;cursor:col-resize" data-boundary="${i}" />`;
      }
    }

    // Detected transactions — alternating bands
    const transactions = St.cmPreview.transactions || [];
    // Show transaction markers (small ticks on the left)
    for(let t = 0; t < Math.min(transactions.length, 50); t++){
      const tx = transactions[t];
      if(!tx.raw_fields) continue;
    }

    svg.innerHTML = markup;

    // Enable drag on boundary lines
    _cmBindBoundaryDrag(svg, scale);
  }

  function _cmBindBoundaryDrag(svg, scale){
    const container = QS("#cm_visual_container");
    if(!container) return;

    // Use a transparent overlay for drag events
    const lines = svg.querySelectorAll("line[data-boundary]");
    lines.forEach(line => {
      line.style.pointerEvents = "stroke";
      line.style.cursor = "col-resize";
    });

    // Mouse/touch drag handling via overlay
    let dragIdx = -1;
    let startX = 0;

    container.addEventListener("mousedown", (e) => {
      // Check if click is near a boundary line
      const rect = container.getBoundingClientRect();
      const mx = e.clientX - rect.left;

      for(let i = 0; i < St.cmColumns.length - 1; i++){
        const bx = St.cmColumns[i].x_max * scale * (container.clientWidth / (QS("#cm_page_img")?.naturalWidth || 1));
        if(Math.abs(mx - bx) < 8){
          dragIdx = i;
          startX = mx;
          e.preventDefault();
          container.style.cursor = "col-resize";
          return;
        }
      }
    });

    const _onMove = (e) => {
      if(dragIdx < 0) return;
      const rect = container.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const img = QS("#cm_page_img");
      if(!img) return;

      const displayScale = container.clientWidth / img.naturalWidth;
      const pdfX = mx / (displayScale * scale);

      // Clamp to reasonable bounds
      const minX = (dragIdx > 0 ? St.cmColumns[dragIdx].x_min + 10 : 10);
      const maxX = (dragIdx + 2 < St.cmColumns.length ? St.cmColumns[dragIdx + 2].x_max - 10 : 9999);
      const newX = Math.max(minX, Math.min(maxX, pdfX));

      St.cmColumns[dragIdx].x_max = newX;
      St.cmColumns[dragIdx + 1].x_min = newX;
      _cmRenderOverlay();
    };

    const _onUp = () => {
      if(dragIdx >= 0){
        dragIdx = -1;
        container.style.cursor = "";
        // Update mapping from current column types
        _cmSyncMapping();
      }
    };

    document.addEventListener("mousemove", _onMove);
    document.addEventListener("mouseup", _onUp);
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

    // Build column_bounds from current columns
    const column_bounds = St.cmColumns.map(c => ({x_min: c.x_min, x_max: c.x_max}));

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
        _renderCmParsedPreview(container, data.transactions, data.transaction_count);
      } else {
        container.innerHTML = `<div class="small" style="color:var(--danger)">${_esc(data && data.error ? data.error : "Blad parsowania")}</div>`;
      }
    } catch(e){
      container.innerHTML = `<div class="small" style="color:var(--danger)">Blad: ${_esc(e.message || e)}</div>`;
    }
  }

  function _renderCmParsedPreview(container, transactions, total){
    if(!transactions || !transactions.length){
      container.innerHTML = '<div class="small muted">Brak rozpoznanych transakcji. Sprawdz mapowanie kolumn.</div>';
      return;
    }

    let html = `<div class="small muted" style="margin-bottom:4px">Rozpoznano <b>${total}</b> transakcji. Podglad:</div>`;
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

    _runFullPipeline(preview.file_path, St.cmMapping, {
      save_template: saveTemplate,
      template_name: templateName,
      set_default: setDefault,
      template_id: templateId,
      bank_id: preview.bank_id,
      bank_name: preview.bank_name,
      header_cells: St.cmColumns.map(c => c.label),
      column_bounds: St.cmColumns.map(c => ({x_min: c.x_min, x_max: c.x_max, label: c.label, col_type: c.col_type})),
      header_fields: _getHeaderFieldsForApi(),
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

    // Page selector
    const pageSel = QS("#cm_page_select");
    if(pageSel){
      pageSel.addEventListener("change", ()=>{
        _cmLoadPageImage(parseInt(pageSel.value, 10) || 0);
      });
    }
  }

  // ============================================================
  // HELPERS
  // ============================================================

  function _show(id){ const el = QS("#" + id); if(el) el.style.display = ""; }
  function _hide(id){ const el = QS("#" + id); if(el) el.style.display = "none"; }

  // ============================================================
  // PUBLIC API
  // ============================================================

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
    }
  };

  window.AmlManager = AmlManager;
})();
