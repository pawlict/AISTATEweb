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
    // Column mapping state
    cmPreview: null,      // from POST /api/aml/preview-pdf
    cmMapping: {},        // {col_index_str: column_type}
    cmColumnTypes: {},    // metadata from API
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
  // COLUMN MAPPING UI
  // ============================================================

  function _renderColumnMapping(){
    const preview = St.cmPreview;
    if(!preview) return;

    // Bank label
    const bankLabel = QS("#cm_bank_label");
    if(bankLabel) bankLabel.textContent = preview.bank_name || "Nieznany bank";

    // Template info
    if(preview.template && !preview.template._partial_match){
      const bankL = QS("#cm_bank_label");
      if(bankL) bankL.textContent = (preview.bank_name || "") + " (szablon: " + (preview.template.name || "domyslny") + ")";
    }

    // Render column headers with dropdowns
    _renderCmHeaders(preview);

    // Render raw table
    _renderCmTable(preview);
  }

  function _renderCmHeaders(preview){
    const container = QS("#cm_headers");
    if(!container) return;

    const headerCells = preview.header_cells || [];
    const types = St.cmColumnTypes;

    let html = '<div style="display:flex;gap:4px;overflow-x:auto;padding:4px 0">';
    for(let i = 0; i < headerCells.length; i++){
      const iStr = String(i);
      const currentType = St.cmMapping[iStr] || "";
      const meta = types[currentType] || {};

      html += `<div class="cm-col-hdr" style="min-width:100px;flex:1">
        <div class="small" style="margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${_esc(headerCells[i])}">${_esc(headerCells[i] || "(pusta)")}</div>
        <select class="cm-type-select input" data-col="${i}" style="padding:3px 5px;border-radius:6px;font-size:12px;width:100%">
          <option value="">\u2014 Pomija</option>`;

      for(const [key, tmeta] of Object.entries(types)){
        const sel = currentType === key ? " selected" : "";
        html += `<option value="${_esc(key)}"${sel}>${tmeta.icon || ""} ${_esc(tmeta.label)}</option>`;
      }

      html += `</select></div>`;
    }
    html += '</div>';
    container.innerHTML = html;

    // Bind dropdown changes
    QSA(".cm-type-select", container).forEach(sel => {
      sel.addEventListener("change", () => {
        const col = sel.getAttribute("data-col");
        if(sel.value){
          St.cmMapping[col] = sel.value;
        } else {
          delete St.cmMapping[col];
        }
        _renderCmTable(St.cmPreview);
      });
    });
  }

  function _renderCmTable(preview){
    const wrap = QS("#cm_table_wrap");
    if(!wrap || !preview) return;

    const rows = preview.rows || [];
    if(!rows.length){
      wrap.innerHTML = '<div class="small muted" style="padding:10px">Brak danych w tabeli.</div>';
      return;
    }

    const headerRow = preview.header_row || 0;
    const dataStart = preview.data_start_row || headerRow + 1;
    const types = St.cmColumnTypes;

    // Build type color hints
    const typeColors = {
      date:"#3b82f6", value_date:"#60a5fa", description:"#8b5cf6",
      counterparty:"#06b6d4", amount:"#f59e0b", debit:"#ef4444",
      credit:"#22c55e", balance:"#6366f1", bank_type:"#a855f7",
      reference:"#64748b", skip:"#d1d5db",
    };

    let html = '<table class="cm-preview-table" style="width:100%;font-size:12px;border-collapse:collapse">';

    // Column type indicator row
    html += '<tr>';
    const colCount = rows[0] ? rows[0].cells.length : 0;
    for(let c = 0; c < colCount; c++){
      const cType = St.cmMapping[String(c)] || "";
      const color = typeColors[cType] || "transparent";
      const label = (types[cType] || {}).label || "";
      html += `<td style="background:${color};color:#fff;font-size:10px;padding:2px 4px;text-align:center;white-space:nowrap">${_esc(label)}</td>`;
    }
    html += '</tr>';

    for(const row of rows){
      const isHdr = row.is_header;
      const isData = row.index >= dataStart;
      const style = isHdr ? "font-weight:bold;background:var(--bg-alt,#f1f5f9)" : "";
      html += `<tr style="${style}">`;
      for(let c = 0; c < row.cells.length; c++){
        const cType = St.cmMapping[String(c)] || "";
        const borderLeft = cType ? `border-left:2px solid ${typeColors[cType] || "#ccc"}` : "";
        html += `<td style="padding:3px 5px;border-bottom:1px solid var(--border,#e2e8f0);white-space:nowrap;max-width:180px;overflow:hidden;text-overflow:ellipsis;${borderLeft}" title="${_esc(row.cells[c])}">${_esc(row.cells[c])}</td>`;
      }
      html += '</tr>';
    }
    html += '</table>';
    wrap.innerHTML = html;
  }

  async function _cmPreviewParse(){
    const preview = St.cmPreview;
    if(!preview) return;

    const container = QS("#cm_parsed_preview");
    if(!container) return;
    container.innerHTML = '<div class="small muted">Parsowanie...</div>';

    try{
      const data = await _api("/api/aml/preview-parse", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          file_path: preview.file_path,
          column_mapping: St.cmMapping,
          header_row: preview.header_row || 0,
          data_start_row: preview.data_start_row || 1,
          main_table_index: preview.main_table_index || 0,
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

    let html = `<div class="small muted" style="margin-bottom:4px">Rozpoznano ${total} transakcji. Podglad pierwszych ${Math.min(transactions.length, 10)}:</div>`;
    html += '<table style="width:100%;font-size:11px;border-collapse:collapse">';
    html += '<tr style="background:var(--bg-alt,#f1f5f9);font-weight:bold"><td style="padding:3px 5px">Data</td><td>Kontrahent</td><td>Tytul</td><td style="text-align:right">Kwota</td><td style="text-align:right">Saldo</td></tr>';

    for(const tx of transactions.slice(0, 10)){
      const amt = Number(tx.amount || 0);
      const color = amt < 0 ? "var(--danger,#b91c1c)" : "var(--ok,#15803d)";
      html += `<tr style="border-bottom:1px solid var(--border,#e2e8f0)">
        <td style="padding:2px 5px;white-space:nowrap">${_esc(tx.date || "")}</td>
        <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc((tx.counterparty || "").slice(0,30))}</td>
        <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc((tx.title || "").slice(0,40))}</td>
        <td style="text-align:right;color:${color};white-space:nowrap">${_fmtAmount(amt, "")}</td>
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
      header_row: preview.header_row,
      data_start_row: preview.data_start_row,
      main_table_index: preview.main_table_index,
      save_template: saveTemplate,
      template_name: templateName,
      set_default: setDefault,
      template_id: templateId,
      bank_id: preview.bank_id,
      bank_name: preview.bank_name,
      header_cells: preview.header_cells,
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
