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
    // Removed accounts state
    removedAccounts: [],   // account objects hidden from main view
    allAccounts: [],       // all accounts (for restore)
    accountsStmt: null,    // stmt reference for re-render
  };

  // ============================================================
  // UPLOAD & ANALYZE
  // ============================================================

  function _setAmlStatus(text, pct){
    const el = QS("#aml_status"); if(el) el.textContent = text || "—";
    const bar = QS("#aml_bar"); if(bar) bar.style.width = (pct != null ? pct + "%" : "0%");
    const p = QS("#aml_pct"); if(p) p.textContent = (pct != null && pct > 0) ? Math.round(pct) + "%" : "";
  }

  function _showUpload(){
    _setAmlStatus("—", 0);
    const progressDiv = QS("#aml_progress .progress");
    if(progressDiv) progressDiv.classList.remove("indeterminate");
    _hide("aml_results");
    if(!St.batchMode) _hide("aml_batch_panel");
    const histCard = QS("#aml_history_card");
    if(histCard && St.history.length) _show("aml_history_card");
  }

  function _showProgress(text){
    _setAmlStatus(text || "Analizuję...", 0);
    // Show indeterminate animation on progress bar
    const progressDiv = QS("#aml_progress .progress");
    if(progressDiv) progressDiv.classList.add("indeterminate");
    _hide("aml_results");
    _hide("aml_history_card");
    if(!St.batchMode) _hide("aml_batch_panel");
  }

  function _showResults(){
    _setAmlStatus("Zakończono", 100);
    const progressDiv = QS("#aml_progress .progress");
    if(progressDiv) progressDiv.classList.remove("indeterminate");
    _show("aml_results");
    _hide("aml_history_card");
    _hide("aml_batch_panel");
  }

  function _showBatchPanel(){
    _hide("aml_results");
    _hide("aml_history_card");
    _show("aml_batch_panel");
  }

  function _showError(msg){
    const el = QS("#aml_status");
    if(el){
      el.textContent = "Błąd: " + msg;
      el.style.color = "var(--danger)";
      setTimeout(()=>{ el.style.color = ""; }, 8000);
    }
    const bar = QS("#aml_bar"); if(bar) bar.style.width = "0%";
    const p = QS("#aml_pct"); if(p) p.textContent = "";
    const progressDiv = QS("#aml_progress .progress");
    if(progressDiv) progressDiv.classList.remove("indeterminate");
  }

  function _showInfo(msg){
    // Informational toast (e.g. duplicate detected) — non-blocking
    const container = QS("#aml_results") || QS("#aml_progress") || document.body;
    const d = document.createElement("div");
    d.className = "small aml-info-toast";
    d.style.cssText = "background:var(--info-bg,#d1ecf1);color:var(--info-text,#0c5460);"
      + "padding:10px 16px;border-radius:8px;margin:8px 0;border:1px solid var(--info-border,#bee5eb);"
      + "font-size:0.92em;";
    d.textContent = "\u2139\uFE0F " + msg;
    container.prepend(d);
    setTimeout(()=> d.remove(), 8000);
  }

  async function _uploadAndAnalyze(file){
    if(!file || St.analyzing) return;
    if(!file.name.toLowerCase().endsWith(".pdf")){
      _showError("Tylko pliki PDF sa obslugiwane.");
      return;
    }

    St.analyzing = true;
    _showProgress("Parsowanie transakcji...");
    // Switch to determinate progress for the upload phase
    const _progDiv = QS("#aml_progress .progress");
    if(_progDiv) _progDiv.classList.remove("indeterminate");

    const fd = new FormData();
    fd.append("file", file, file.name);
    // Attach current project context so new analysis lands in the right project
    const _pid = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) ? AISTATE.projectId : "";
    if(_pid) fd.append("project_id", _pid);

    let pct = 0;
    const bar = QS("#aml_bar");
    const pctEl = QS("#aml_pct");
    const statusEl = QS("#aml_status");
    const progTimer = setInterval(()=>{
      pct = Math.min(pct + Math.random() * 8, 90);
      if(bar) bar.style.width = pct + "%";
      if(pctEl) pctEl.textContent = Math.round(pct) + "%";
    }, 800);

    const stages = [
      "Parsowanie transakcji...",
      "Klasyfikacja reguł...",
      "Detekcja anomalii...",
      "Budowa grafu...",
      "Generowanie raportu..."
    ];
    let stageIdx = 0;
    const stageTimer = setInterval(()=>{
      stageIdx++;
      if(stageIdx < stages.length && statusEl){
        statusEl.textContent = stages[stageIdx];
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

      if(result && (result.status === "ok" || result.status === "duplicate")){
        if(result.status === "duplicate"){
          // Show info toast about duplicate — load existing analysis
          const msg = result.message || "Ten wyciag zostal juz wczytany. Laduje istniejaca analize.";
          _showInfo ? _showInfo(msg) : alert(msg);
        }
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
      // Persist for session restore after page reload
      const pid = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) || "";
      localStorage.setItem("aistate_aml_statement_id", statementId);
      localStorage.setItem("aistate_aml_project_id", pid);
    }
    return data;
  }

  async function _loadHistory(){
    const pid = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) ? AISTATE.projectId : "";
    let url = "/api/aml/history?limit=50";
    if(pid) url += "&project_id=" + encodeURIComponent(pid);
    const data = await _safeApi(url);
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

    // Identified cards (use merged cards when available for multi-statement)
    const cards = St._mergedCards || detail.cards || result.cards || [];
    _renderCards(cards, stmt);

    // Identified accounts
    const accounts = St._mergedAccounts || detail.accounts || result.accounts || [];
    _renderAccounts(accounts, stmt);

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
    // Restore merged multi-statement charts (built by _mergeMultiAccountCharts before _renderResults)
    if(St._mergedCharts){
      for(const key in St._mergedCharts){
        St.chartsData[key] = St._mergedCharts[key];
      }
    }
    _renderChart("balance_timeline");

    // ML anomalies
    const mlAnomalies = detail.ml_anomalies || [];
    _renderMlAnomalies(mlAnomalies, transactions);

    // Graph
    _renderGraph(graph);

    // LLM section
    _setupLlmSection(detail.has_llm_prompt || result.has_llm_prompt);

    // Cross-account panel (shows only when 2+ accounts in case)
    if(St.caseId){
      _loadAndRenderCrossAccount(St.caseId);
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

    // Use merged info when available (multi-statement case)
    const mi = St._mergedInfo || null;
    const src = mi || stmt;

    const bank = src.bank_name || result.bank_name || "";
    const holder = src.account_holder || "";
    const iban = src.account_number || "";
    const periodFrom = src.period_from || "";
    const periodTo = src.period_to || "";
    const period = [periodFrom, periodTo].filter(Boolean).join(" \u2014 ");
    const cur = src.currency || "PLN";
    const txCount = mi ? mi._total_tx : ((result.transaction_count || St.allTransactions.length) || 0);
    const prevClosing = src.previous_closing_balance;
    const availBal = src.available_balance;
    const stmtCount = mi ? mi._statement_count : 0;

    let html = "";
    if(bank) html += `<div class="aml-info-row"><b>Bank:</b> ${_esc(bank)}</div>`;
    if(holder) html += `<div class="aml-info-row"><b>Właściciel:</b> ${_esc(holder)}</div>`;
    if(iban) html += `<div class="aml-info-row"><b>IBAN:</b> <span style="font-family:monospace">${_esc(iban)}</span></div>`;
    if(period) html += `<div class="aml-info-row"><b>Okres:</b> ${_esc(period)}</div>`;
    if(stmtCount > 1) html += `<div class="aml-info-row"><b>Wyciągi:</b> ${stmtCount}</div>`;
    if(cur && cur !== "PLN") html += `<div class="aml-info-row"><b>Waluta:</b> ${_esc(cur)}</div>`;

    // Balances grid
    html += '<div class="aml-info-stats">';
    if(src.opening_balance != null) html += `<span><b>Saldo otw.:</b> ${_fmtAmount(src.opening_balance, cur)}</span>`;
    if(src.closing_balance != null) html += `<span><b>Saldo konc.:</b> ${_fmtAmount(src.closing_balance, cur)}</span>`;
    if(availBal != null) html += `<span><b>Saldo dost.:</b> ${_fmtAmount(availBal, cur)}</span>`;
    if(prevClosing != null) html += `<span><b>Saldo konc. poprz.:</b> ${_fmtAmount(prevClosing, cur)}</span>`;
    html += '</div>';

    // Summary stats
    html += `<div class="small muted" style="margin-top:4px">Transakcje: ${txCount}`;
    if(result.pipeline_time_s) html += ` | Czas analizy: ${result.pipeline_time_s}s`;
    html += `</div>`;

    grid.innerHTML = html;
  }

  /**
   * Resolve a raw category key (e.g. "everyday:grocery") to a display name
   * using the category_labels map from the API and the current UI language.
   */
  function _catDisplayName(raw){
    if(!raw) return "";
    const leaf = raw.includes(":") ? raw.split(":").pop() : raw;
    const labels = (St.detail && St.detail.category_labels) || {};
    const meta = labels[leaf] || labels[raw];
    if(!meta) return leaf;
    const lang = (typeof getUiLang === "function") ? getUiLang() : "pl";
    return lang === "en" ? (meta.display_name_en || meta.display_name || leaf) : (meta.display_name || leaf);
  }

  function _renderCards(cards, stmt){
    const container = QS("#aml_cards_container");
    const cardCard = QS("#aml_cards_card");
    const countEl = QS("#aml_cards_count");

    if(!container || !cardCard) return;

    if(!cards || !cards.length){
      cardCard.style.display = "none";
      return;
    }

    cardCard.style.display = "";
    if(countEl) countEl.textContent = cards.length;

    const bankName = (stmt.bank_name || "Bank").toUpperCase();
    const cur = stmt.currency || "PLN";

    container.innerHTML = cards.map(c => {
      const brand = _esc(c.brand || "");
      const masked = _esc(c.card_masked || c.card_id || "****");
      const firstDate = _esc(c.first_date || "");
      const lastDate = _esc(c.last_date || "");
      const last4 = _esc(c.last_four || "");

      // Stats section
      const _t = typeof t === "function" ? t : (k => k);
      let statsHtml = `
        <div><b>${_t("aml.card.expenses")}</b><div class="val">${_fmtAmount(c.total_debit, cur)}</div></div>
        <div><b>${_t("aml.card.income")}</b><div class="val">${_fmtAmount(c.total_credit, cur)}</div></div>
        <div><b>${_t("aml.card.transactions")}</b><div class="val">${c.tx_count}</div></div>
        <div><b>${_t("aml.card.avg_amount")}</b><div class="val">${_fmtAmount(c.avg_amount, cur)}</div></div>
      `;

      // Top merchants — clickable: filter by merchant name (scoped to this card)
      const _filterTitle = _t("aml.card.click_filter");
      let detailsHtml = "";
      if(c.top_merchants && c.top_merchants.length){
        detailsHtml += `<div style="margin-bottom:4px;opacity:0.65;font-weight:700;font-size:10px">${_t("aml.card.top_merchants")}</div>`;
        c.top_merchants.slice(0, 5).forEach(m => {
          const name = _esc((m[0] || "").slice(0, 25));
          const raw = _esc(m[0] || "");
          const amt = _fmtAmount(m[1], cur);
          const cnt = m[2] || 0;
          detailsHtml += `<div class="detail-row aml-card-link" data-filter="${raw}" data-card-last4="${last4}" title="${_filterTitle}"><span>${name} (${cnt}x)</span><span>${amt}</span></div>`;
        });
      }

      // Top categories — localized, clickable (scoped to this card)
      if(c.top_categories && c.top_categories.length){
        detailsHtml += `<div style="margin-top:6px;margin-bottom:4px;opacity:0.65;font-weight:700;font-size:10px">${_t("aml.card.categories")}</div>`;
        c.top_categories.slice(0, 4).forEach(cat => {
          const rawCat = cat[0] || "";
          const displayName = _catDisplayName(rawCat);
          const amt = _fmtAmount(cat[1], cur);
          detailsHtml += `<div class="detail-row aml-card-link" data-filter-cat="${_esc(rawCat)}" data-card-last4="${last4}" title="${_filterTitle}"><span>${_esc(displayName)}</span><span>${amt}</span></div>`;
        });
      }

      // Locations — clickable: filter by location name (scoped to this card)
      if(c.locations && c.locations.length){
        detailsHtml += `<div style="margin-top:6px;margin-bottom:4px;opacity:0.65;font-weight:700;font-size:10px">${_t("aml.card.locations")}</div>`;
        c.locations.slice(0, 4).forEach(loc => {
          const locName = _esc(loc[0] || "");
          detailsHtml += `<div class="detail-row aml-card-link" data-filter="${locName}" data-card-last4="${last4}" title="${_filterTitle}"><span>${locName}</span><span>${loc[1]} tx</span></div>`;
        });
      }

      // Brand display: show detected brand or empty (not "DEBIT" fallback)
      const brandDisplay = brand || "";

      return `<div class="aml-card-item" data-brand="${brand}">
        <div class="aml-card-top">
          <div class="aml-card-bank">${_esc(bankName)}</div>
          ${brandDisplay ? `<div class="aml-card-brand">${brandDisplay}</div>` : ""}
        </div>
        <div class="aml-card-number">${masked}</div>
        <div class="aml-card-dates">
          <span>OD ${firstDate}</span>
          <span>DO ${lastDate}</span>
        </div>
        <div class="aml-card-stats">${statsHtml}</div>
        ${detailsHtml ? '<div class="aml-card-details">' + detailsHtml + '</div>' : ''}
      </div>`;
    }).join("");

    // Click handlers: filter transactions in Review section — scoped to card
    QSA(".aml-card-link", container).forEach(el => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const filterText = el.getAttribute("data-filter") || "";
        const filterCat = el.getAttribute("data-filter-cat") || "";
        const cardLast4 = el.getAttribute("data-card-last4") || "";

        // Target: Review & Classification search box
        const rvSearch = QS("#rv_search");
        const rvCard = QS("#aml_review_card");

        if(rvSearch){
          let searchTerms = "";
          if(filterCat){
            searchTerms = _catDisplayName(filterCat);
          } else {
            searchTerms = filterText;
          }
          // Prepend card's last 4 digits to scope filter to this card only.
          // Review search uses AND logic for space-separated terms, so
          // "9674 Łódź" finds only transactions matching BOTH terms.
          if(cardLast4 && cardLast4 !== "????"){
            searchTerms = cardLast4 + " " + searchTerms;
          }
          rvSearch.value = searchTerms.trim();
          // Trigger filter update
          rvSearch.dispatchEvent(new Event("input", {bubbles: true}));
        }

        // Scroll to review section
        if(rvCard){
          rvCard.scrollIntoView({behavior: "smooth", block: "start"});
        }
      });
    });
  }

  function _renderAccounts(accounts, stmt){
    const container = QS("#aml_accounts_container");
    const accountsCard = QS("#aml_accounts_card");
    const countEl = QS("#aml_accounts_count");

    if(!container || !accountsCard) return;

    // Store all accounts on first call; on subsequent calls only if accounts provided
    if(accounts && accounts.length){
      St.allAccounts = accounts;
      St.accountsStmt = stmt;
    }

    // Separate visible vs removed
    const removedNums = new Set(St.removedAccounts.map(a => a.account_number || ""));
    const visible = (St.allAccounts || []).filter(a => !removedNums.has(a.account_number || ""));

    if(!St.allAccounts || !St.allAccounts.length){
      accountsCard.style.display = "none";
      return;
    }

    accountsCard.style.display = "";
    if(countEl) countEl.textContent = visible.length;

    const cur = (stmt && stmt.currency) || "PLN";
    const _t = typeof t === "function" ? t : (k => k);

    // Ownership category labels and CSS classes
    const _catLabels = {
      own:         "Właściciel",
      third_party: "Kontrahent",
      friend:      "Znajomy",
      family:      "Rodzina",
      employer:    "Pracodawca",
    };
    const _catBadgeClass = {
      own:         "aml-acc-own",
      third_party: "aml-acc-third",
      friend:      "aml-acc-friend",
      family:      "aml-acc-family",
      employer:    "aml-acc-employer",
    };
    const _catBgClass = {
      own:         "aml-acc-own-bg",
      third_party: "aml-acc-default",
      friend:      "aml-acc-friend-bg",
      family:      "aml-acc-family-bg",
      employer:    "aml-acc-employer-bg",
    };

    // Helper to render a single account card (reused for both visible and removed)
    function _accountCardHtml(acc, mode){
      const ownership = acc.ownership || (acc.is_own_account ? "own" : "third_party");
      const isForeign = acc.is_foreign;
      const bankShort = _esc(acc.bank_short || "");
      const bankFull = _esc(acc.bank_full || "");
      const displayNum = _esc(acc.account_display || acc.account_number || "");
      const country = _esc(acc.country_name || "");
      const countryCode = _esc(acc.country_code || "");
      const firstDate = _esc(acc.first_date || "");
      const lastDate = _esc(acc.last_date || "");
      const accNum = _esc(acc.account_number || "");
      const accStmtId = _esc(acc._statement_id || St.statementId || "");

      // Ownership badge (clickable → category selector)
      const catLabel = _catLabels[ownership] || _catLabels.third_party;
      const catClass = _catBadgeClass[ownership] || _catBadgeClass.third_party;
      const ownershipBadge = `<span class="aml-acc-badge ${catClass} aml-acc-cat-btn" data-acc="${accNum}" data-cat="${ownership}" data-stmt="${accStmtId}" title="Kliknij aby zmienić kategorię">${catLabel}</span>`;

      // Country badge
      let countryBadge = "";
      if(isForeign){
        countryBadge = `<span class="aml-acc-badge aml-acc-foreign">${countryCode} ${country}</span>`;
      } else if(countryCode){
        countryBadge = `<span class="aml-acc-badge aml-acc-polish">${countryCode} ${country}</span>`;
      }

      // Stats section
      let statsHtml = `
        <div><b>Wpływy</b><div class="val aml-acc-credit">+${_fmtAmount(acc.total_credit, cur)}</div><div class="sub">${acc.credit_count} transakcji</div></div>
        <div><b>Wypływy</b><div class="val aml-acc-debit">-${_fmtAmount(acc.total_debit, cur)}</div><div class="sub">${acc.debit_count} transakcji</div></div>
        <div><b>Transakcje</b><div class="val">${acc.tx_count}</div></div>
      `;

      // Top counterparties — clickable: filter in Review section
      let cpHtml = "";
      if(acc.top_counterparties && acc.top_counterparties.length){
        cpHtml += `<div style="margin-bottom:4px;opacity:0.65;font-weight:700;font-size:10px">Kontrahenci</div>`;
        acc.top_counterparties.slice(0, 4).forEach(cp => {
          const name = _esc((cp[0] || "").slice(0, 30));
          const cnt = cp[1] || 0;
          cpHtml += `<div class="detail-row aml-acc-cp-link" data-filter="${name}" title="Kliknij aby filtrować transakcje" style="cursor:pointer"><span>${name}</span><span>${cnt}x</span></div>`;
        });
      }

      // Determine gradient style
      let gradientClass = _catBgClass[ownership] || "aml-acc-default";
      if(isForeign && ownership !== "own") gradientClass = "aml-acc-foreign-bg";

      // Remove or Restore button
      const actionBtn = mode === "removed"
        ? `<button class="aml-acc-restore-btn" data-acc-num="${accNum}" title="Przywróć rachunek">+</button>`
        : `<button class="aml-acc-remove-btn" data-acc-num="${accNum}" title="Usuń rachunek z widoku">&minus;</button>`;

      return `<div class="aml-account-item ${gradientClass}" data-acc-num="${accNum}">
        ${actionBtn}
        <div class="aml-acc-top">
          <div class="aml-acc-bank">${bankShort || countryCode || "BANK"}</div>
          <div class="aml-acc-badges">${ownershipBadge}${countryBadge}</div>
        </div>
        <div class="aml-acc-number" title="${bankFull}">${displayNum}</div>
        ${bankFull ? '<div class="aml-acc-bankfull">' + bankFull + '</div>' : ''}
        <div class="aml-acc-dates">
          <span>OD ${firstDate}</span>
          <span>DO ${lastDate}</span>
        </div>
        <div class="aml-acc-stats">${statsHtml}</div>
        ${cpHtml ? '<div class="aml-acc-details">' + cpHtml + '</div>' : ''}
      </div>`;
    }

    // Render visible accounts
    container.innerHTML = visible.map(acc => _accountCardHtml(acc, "visible")).join("");

    // Render removed accounts section
    const removedSection = QS("#aml_removed_accounts_section");
    const removedContainer = QS("#aml_removed_accounts_container");
    const removedCount = QS("#aml_removed_count");
    if(removedSection && removedContainer){
      if(St.removedAccounts.length > 0){
        removedSection.style.display = "";
        if(removedCount) removedCount.textContent = St.removedAccounts.length;
        removedContainer.innerHTML = St.removedAccounts.map(acc => _accountCardHtml(acc, "removed")).join("");
      } else {
        removedSection.style.display = "none";
        removedContainer.innerHTML = "";
      }
    }

    // Toggle expand/collapse for removed accounts
    const toggleBtn = QS("#aml_removed_accounts_toggle");
    if(toggleBtn && !toggleBtn._bound){
      toggleBtn._bound = true;
      toggleBtn.addEventListener("click", () => {
        const rc = QS("#aml_removed_accounts_container");
        const arrow = QS("#aml_removed_arrow");
        if(!rc) return;
        const open = rc.style.display !== "none";
        rc.style.display = open ? "none" : "";
        if(arrow) arrow.style.transform = open ? "" : "rotate(90deg)";
      });
    }

    // Bind category change, counterparty click, and remove/restore handlers on BOTH containers
    [container, removedContainer].forEach(cnt => {
      if(!cnt) return;

      // Category change click handlers
      QSA(".aml-acc-cat-btn", cnt).forEach(btn => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const accNum = btn.getAttribute("data-acc");
          const currentCat = btn.getAttribute("data-cat");
          const accStmtId = btn.getAttribute("data-stmt") || St.statementId;

          const cats = ["own", "third_party", "friend", "family", "employer"];
          const existing = cnt.querySelector(".aml-acc-cat-picker");
          if(existing) existing.remove();

          const picker = document.createElement("div");
          picker.className = "aml-acc-cat-picker";
          picker.style.cssText = "position:absolute;z-index:100;background:var(--bg-card,#fff);border:1px solid var(--border,#ddd);border-radius:8px;padding:6px;box-shadow:0 4px 16px rgba(0,0,0,0.18);display:flex;flex-direction:column;gap:2px;min-width:130px";

          cats.forEach(cat => {
            const opt = document.createElement("div");
            opt.textContent = _catLabels[cat];
            opt.style.cssText = "padding:5px 10px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:600;transition:background .15s";
            if(cat === currentCat) opt.style.opacity = "0.4";
            opt.addEventListener("mouseenter", () => { opt.style.background = "var(--bg-hover,#f0f0f0)"; });
            opt.addEventListener("mouseleave", () => { opt.style.background = "none"; });
            opt.addEventListener("click", async () => {
              picker.remove();
              if(cat === currentCat) return;
              try {
                const resp = await fetch("/api/aml/account-category", {
                  method: "PATCH",
                  headers: {"Content-Type": "application/json"},
                  body: JSON.stringify({
                    statement_id: accStmtId,
                    account_number: accNum,
                    category: cat,
                  }),
                });
                if(resp.ok){
                  const found = St.allAccounts.find(a => a.account_number === accNum);
                  if(found){
                    found.ownership = cat;
                    found.is_own_account = (cat === "own");
                    found.category_manual = true;
                  }
                  _renderAccounts(null, stmt);
                }
              } catch(err) {
                console.error("Category change failed:", err);
              }
            });
            picker.appendChild(opt);
          });

          const rect = btn.getBoundingClientRect();
          const containerRect = cnt.getBoundingClientRect();
          picker.style.position = "absolute";
          picker.style.top = (rect.bottom - containerRect.top + 2) + "px";
          picker.style.left = (rect.left - containerRect.left) + "px";
          cnt.style.position = "relative";
          cnt.appendChild(picker);

          const _close = (ev) => {
            if(!picker.contains(ev.target)){
              picker.remove();
              document.removeEventListener("click", _close);
            }
          };
          setTimeout(() => document.addEventListener("click", _close), 10);
        });
      });

      // Counterparty click handlers: filter transactions in Review section
      QSA(".aml-acc-cp-link", cnt).forEach(el => {
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          const filterText = el.getAttribute("data-filter") || "";
          const rvSearch = QS("#rv_search");
          const rvCard = QS("#aml_review_card");
          if(rvSearch && filterText){
            rvSearch.value = '"' + filterText + '"';
            rvSearch.dispatchEvent(new Event("input", {bubbles: true}));
          }
          if(rvCard){
            rvCard.scrollIntoView({behavior: "smooth", block: "start"});
          }
        });
      });
    });

    // Remove button handlers (visible accounts → move to removed)
    QSA(".aml-acc-remove-btn", container).forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const accNum = btn.getAttribute("data-acc-num");
        const acc = St.allAccounts.find(a => (a.account_number || "") === accNum);
        if(acc && !St.removedAccounts.find(a => a.account_number === accNum)){
          St.removedAccounts.push(acc);
        }
        _renderAccounts(null, stmt);
      });
    });

    // Restore button handlers (removed accounts → move back to visible)
    if(removedContainer){
      QSA(".aml-acc-restore-btn", removedContainer).forEach(btn => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const accNum = btn.getAttribute("data-acc-num");
          St.removedAccounts = St.removedAccounts.filter(a => (a.account_number || "") !== accNum);
          _renderAccounts(null, stmt);
        });
      });
    }
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
  // CROSS-ACCOUNT PANEL (multi-bank / multi-account view)
  // ============================================================

  async function _loadAndRenderCrossAccount(caseId){
    if(!caseId) return;

    // Check if case has multiple accounts
    const caseAccData = await _safeApi("/api/aml/case-accounts/" + encodeURIComponent(caseId));
    if(!caseAccData || caseAccData.account_count < 2){
      _hideCrossAccountPanel();
      return;
    }

    // Load cross-account analysis
    const xaData = await _safeApi("/api/aml/cross-account/" + encodeURIComponent(caseId));
    if(!xaData || xaData.account_count < 2){
      _hideCrossAccountPanel();
      return;
    }

    St._crossAccountData = xaData;
    _renderCrossAccountPanel(xaData, caseAccData);
  }

  function _hideCrossAccountPanel(){
    const panel = QS("#aml_cross_account_card");
    if(panel) panel.style.display = "none";
  }

  function _renderCrossAccountPanel(xaData, caseAccData){
    let panel = QS("#aml_cross_account_card");
    if(!panel){
      // Create panel dynamically — insert after bank info card
      const infoCard = QS("#aml_info_card");
      if(!infoCard) return;
      panel = document.createElement("div");
      panel.id = "aml_cross_account_card";
      panel.className = "card";
      panel.style.cssText = "margin-top:16px;";
      infoCard.parentNode.insertBefore(panel, infoCard.nextSibling);
    }

    panel.style.display = "";

    const accounts = xaData.accounts || [];
    const transfers = xaData.internal_transfers || [];
    const sharedCps = xaData.shared_counterparties || [];

    let html = `
      <div class="card-header" style="display:flex;align-items:center;gap:8px">
        <span style="font-size:1.2em">&#127974;</span>
        <strong>Multi-Account</strong>
        <span class="badge">${xaData.account_count} rachunkow</span>
      </div>
      <div class="card-body" style="padding:12px">`;

    // --- Account overview table ---
    html += `<div style="margin-bottom:16px">
      <div class="small muted" style="margin-bottom:6px">Rachunki w sprawie:</div>
      <table class="aml-table" style="width:100%;font-size:0.88em">
        <thead><tr>
          <th>Bank</th><th>Rachunek</th><th>Okres</th>
          <th style="text-align:right">Uznania</th>
          <th style="text-align:right">Obciazenia</th>
          <th style="text-align:right">Wyciagi</th>
        </tr></thead><tbody>`;

    for(const acc of accounts){
      const accNum = acc.account_number || "";
      const accDisplay = accNum.length >= 10
        ? accNum.slice(0,2) + " ..." + accNum.slice(-4)
        : accNum || "-";
      html += `<tr>
        <td><strong>${_esc(acc.bank_name || acc.bank_id || "?")}</strong></td>
        <td title="${_esc(accNum)}">${_esc(accDisplay)}</td>
        <td>${_esc(acc.period_from || "")} — ${_esc(acc.period_to || "")}</td>
        <td style="text-align:right;color:#15803d">${_fmtAmt(acc.total_credit)}</td>
        <td style="text-align:right;color:#b91c1c">${_fmtAmt(acc.total_debit)}</td>
        <td style="text-align:right">${acc.statement_count}</td>
      </tr>`;
    }

    html += `</tbody></table></div>`;

    // --- Consolidated totals ---
    html += `<div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">
      <div class="aml-stat-box" style="flex:1;min-width:140px;background:var(--success-bg,#dcfce7);padding:10px;border-radius:8px">
        <div class="small muted">Laczne uznania</div>
        <div style="font-size:1.2em;font-weight:600;color:#15803d">${_fmtAmt(xaData.total_credit)}</div>
      </div>
      <div class="aml-stat-box" style="flex:1;min-width:140px;background:var(--danger-bg,#fee2e2);padding:10px;border-radius:8px">
        <div class="small muted">Laczne obciazenia</div>
        <div style="font-size:1.2em;font-weight:600;color:#b91c1c">${_fmtAmt(xaData.total_debit)}</div>
      </div>
      <div class="aml-stat-box" style="flex:1;min-width:140px;background:var(--info-bg,#dbeafe);padding:10px;border-radius:8px">
        <div class="small muted">Transakcje lacznie</div>
        <div style="font-size:1.2em;font-weight:600">${xaData.total_tx_count}</div>
      </div>
    </div>`;

    // --- Internal transfers ---
    if(transfers.length > 0){
      const transferTotal = transfers.reduce((s,t)=>s+t.amount, 0);
      html += `<div style="margin-bottom:16px">
        <div class="small" style="margin-bottom:6px;font-weight:600">
          &#128260; Przelewy wlasne (${transfers.length}, lacznie ${_fmtAmt(transferTotal)})
        </div>
        <table class="aml-table" style="width:100%;font-size:0.85em">
          <thead><tr>
            <th>Data</th><th>Z rachunku</th><th>Na rachunek</th>
            <th style="text-align:right">Kwota</th><th>Pewnosc</th><th>Metoda</th>
          </tr></thead><tbody>`;

      for(const t of transfers.slice(0, 30)){
        const fromShort = (t.from_account||"").slice(-4) || "?";
        const toShort = (t.to_account||"").slice(-4) || "?";
        const confPct = Math.round((t.confidence||0)*100);
        const confColor = confPct >= 80 ? "#15803d" : confPct >= 60 ? "#d97706" : "#b91c1c";
        html += `<tr>
          <td>${_esc(t.date)}</td>
          <td title="${_esc(t.from_account)}">...${_esc(fromShort)}</td>
          <td title="${_esc(t.to_account)}">...${_esc(toShort)}</td>
          <td style="text-align:right">${_fmtAmt(t.amount)}</td>
          <td style="color:${confColor}">${confPct}%</td>
          <td class="small">${_esc(t.match_method)}</td>
        </tr>`;
      }
      if(transfers.length > 30){
        html += `<tr><td colspan="6" class="small muted">...i ${transfers.length-30} wiecej</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }

    // --- Shared counterparties ---
    if(sharedCps.length > 0){
      html += `<div style="margin-bottom:8px">
        <div class="small" style="margin-bottom:6px;font-weight:600">
          &#128101; Wspolni kontrahenci (${sharedCps.length})
        </div>
        <table class="aml-table" style="width:100%;font-size:0.85em">
          <thead><tr>
            <th>Kontrahent</th><th>Rachunki</th>
            <th style="text-align:right">Kwota</th>
            <th style="text-align:right">Transakcje</th><th>Okres</th>
          </tr></thead><tbody>`;

      for(const cp of sharedCps.slice(0, 20)){
        const accsStr = cp.accounts.map(a => "..." + (a||"").slice(-4)).join(", ");
        html += `<tr>
          <td>${_esc(cp.counterparty_name)}</td>
          <td class="small">${_esc(accsStr)}</td>
          <td style="text-align:right">${_fmtAmt(cp.total_amount)}</td>
          <td style="text-align:right">${cp.tx_count}</td>
          <td class="small">${_esc(cp.first_date)} — ${_esc(cp.last_date)}</td>
        </tr>`;
      }
      html += `</tbody></table></div>`;
    }

    // Warnings
    if(xaData.warnings && xaData.warnings.length){
      html += `<div class="small muted" style="margin-top:8px">`;
      for(const w of xaData.warnings){
        html += `<div>&#9432; ${_esc(w)}</div>`;
      }
      html += `</div>`;
    }

    html += `</div>`;
    panel.innerHTML = html;
  }

  function _fmtAmt(val){
    if(val == null || isNaN(val)) return "-";
    return Number(val).toLocaleString("pl-PL", {minimumFractionDigits:2, maximumFractionDigits:2});
  }

  // ============================================================
  // CHARTS (Chart.js) — zoom, scroll, range slider
  // ============================================================

  // Zoom / interaction state for balance_timeline
  const _chartZoom = {
    level: 1,           // 1 = fit-to-width, >1 = zoomed in
    minLevel: 1,
    maxLevel: 10,
    pxPerPoint: 0,      // base px per data point (computed)
    activeKey: null,     // currently rendered chart key
    bound: false,        // whether listeners are attached
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

  /** Build a Chart.js plugin for drawing gap zones. */
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

          const x1 = xScale.getPixelForValue(idx);
          const x2 = xScale.getPixelForValue(idx + 1);
          const gapX = x1;
          const gapW = x2 - x1;
          if(gapW < 2) continue;

          ctx.fillStyle = "rgba(217,119,6,0.08)";
          ctx.fillRect(gapX, top, gapW, bottom - top);

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

  /** Apply zoom level to chart container width + update range slider. */
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
      _updateRangeSlider();
      _updateZoomBtns();
      return;
    }

    _chartZoom.pxPerPoint = wrapWidth / pointCount;
    const targetWidth = Math.max(wrapWidth, pointCount * _chartZoom.pxPerPoint * _chartZoom.level);
    container.style.width = Math.round(targetWidth) + "px";
    container.style.minWidth = Math.round(targetWidth) + "px";

    if(St.chartInstance){
      St.chartInstance.resize();
    }
    _updateRangeSlider();
    _updateZoomBtns();
  }

  /** Update zoom button states (+/- disable when at limits). */
  function _updateZoomBtns(){
    const btnIn = QS("#aml_chart_zoom_in");
    const btnOut = QS("#aml_chart_zoom_out");
    const btnReset = QS("#aml_chart_zoom_reset");
    if(!btnIn || !btnOut) return;
    btnIn.disabled = (_chartZoom.level >= _chartZoom.maxLevel);
    btnOut.disabled = (_chartZoom.level <= _chartZoom.minLevel);
    if(btnReset) btnReset.disabled = (_chartZoom.level <= 1);
  }

  /** Zoom in/out by a step factor, keeping scroll centered. */
  function _chartZoomStep(factor){
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    if(!scrollWrap) return;

    const oldLevel = _chartZoom.level;
    const newLevel = Math.max(_chartZoom.minLevel, Math.min(_chartZoom.maxLevel, oldLevel * factor));
    if(Math.abs(newLevel - oldLevel) < 0.01) return;

    // Keep center of visible area centered after zoom
    const wrapW = scrollWrap.clientWidth;
    const centerX = scrollWrap.scrollLeft + wrapW / 2;
    const centerRatio = centerX / (scrollWrap.scrollWidth || 1);

    _chartZoom.level = newLevel;
    _applyTimelineZoom();

    requestAnimationFrame(()=>{
      const newCenterX = centerRatio * scrollWrap.scrollWidth;
      scrollWrap.scrollLeft = Math.max(0, newCenterX - wrapW / 2);
    });
  }

  /** Show/hide + sync the range slider beneath the chart. */
  function _updateRangeSlider(){
    const rangeWrap = QS("#aml_chart_range_wrap");
    const rangeInput = QS("#aml_chart_range");
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    if(!rangeWrap || !rangeInput || !scrollWrap) return;

    const isTimeline = (_chartZoom.activeKey === "balance_timeline" || _chartZoom.activeKey === "monthly_trend");
    const overflows = scrollWrap.scrollWidth > scrollWrap.clientWidth + 2;

    if(!isTimeline || !overflows){
      rangeWrap.style.display = "none";
      return;
    }

    rangeWrap.style.display = "";
    const maxScroll = scrollWrap.scrollWidth - scrollWrap.clientWidth;
    rangeInput.max = maxScroll;
    rangeInput.value = scrollWrap.scrollLeft;
  }

  /** Bind all chart interaction listeners (once). */
  function _bindChartInteractions(){
    if(_chartZoom.bound) return;
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    const rangeInput = QS("#aml_chart_range");
    if(!scrollWrap) return;
    _chartZoom.bound = true;

    // --- Range slider <-> scroll sync ---
    if(rangeInput){
      rangeInput.addEventListener("input", ()=>{
        scrollWrap.scrollLeft = Number(rangeInput.value);
      });
      scrollWrap.addEventListener("scroll", ()=>{
        const maxScroll = scrollWrap.scrollWidth - scrollWrap.clientWidth;
        if(maxScroll > 0){
          rangeInput.max = maxScroll;
          rangeInput.value = scrollWrap.scrollLeft;
        }
      });
    }

    // --- Zoom buttons ---
    const btnIn = QS("#aml_chart_zoom_in");
    const btnOut = QS("#aml_chart_zoom_out");
    const btnReset = QS("#aml_chart_zoom_reset");
    if(btnIn) btnIn.addEventListener("click", ()=> _chartZoomStep(1.5));
    if(btnOut) btnOut.addEventListener("click", ()=> _chartZoomStep(1/1.5));
    if(btnReset) btnReset.addEventListener("click", ()=>{
      _chartZoom.level = 1;
      _applyTimelineZoom();
      const sw = QS("#aml_chart_scroll_wrap");
      if(sw) sw.scrollLeft = 0;
    });
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

  /** Build a rich tooltip config for balance_timeline with tx details. */
  function _balanceTooltipConfig(txMeta, chartData){
    const multiMeta = chartData && chartData._multiMeta;
    const isMulti = multiMeta && multiMeta.length > 1;
    return {
      tooltip: {
        enabled: true,
        mode: "index",
        intersect: false,
        callbacks: {
          title(items){
            if(!items.length) return "";
            return items[0].label || "";
          },
          label(ctx){
            const dsIdx = ctx.datasetIndex;
            const ptIdx = ctx.dataIndex;
            const dsLabel = ctx.dataset.label || "";
            const val = ctx.parsed.y;
            if(val == null) return null; // skip null points

            let line = dsLabel + ": " + val.toLocaleString("pl-PL",{minimumFractionDigits:2}) + " PLN";

            // Find transaction metadata for this dataset+point
            const meta = isMulti ? (multiMeta[dsIdx] && multiMeta[dsIdx][ptIdx])
                                 : (txMeta && txMeta[ptIdx]);
            if(meta){
              const dir = meta.direction === "DEBIT" ? "\u2193" : "\u2191";
              const sign = meta.direction === "DEBIT" ? "-" : "+";
              line += `  ${dir}${sign}${meta.amount.toLocaleString("pl-PL",{minimumFractionDigits:2})}`;
            }
            return line;
          },
          afterLabel(ctx){
            const dsIdx = ctx.datasetIndex;
            const ptIdx = ctx.dataIndex;
            const meta = isMulti ? (multiMeta[dsIdx] && multiMeta[dsIdx][ptIdx])
                                 : (txMeta && txMeta[ptIdx]);
            if(!meta) return "";
            const lines = [];
            if(meta.title) lines.push("  " + meta.title);
            if(meta.counterparty) lines.push("  " + meta.counterparty);
            if(meta.category) lines.push("  Kat: " + meta.category);
            return lines;
          },
        },
        bodyFont: { size: 12 },
        titleFont: { size: 13, weight: "bold" },
        padding: 10,
        displayColors: isMulti,
        backgroundColor: "rgba(30,41,59,0.92)",
        maxWidth: 420,
      },
    };
  }

  /** Adaptive x-axis tick display based on zoom level and point density. */
  function _adaptiveXTicks(pointCount){
    // At low zoom (many points compressed) show fewer dates
    // At high zoom (spread out) show more detail
    const pxPerPt = _chartZoom.level * (QS("#aml_chart_scroll_wrap")?.clientWidth || 800) / Math.max(pointCount, 1);
    let maxTicksLimit;
    if(pxPerPt < 3)       maxTicksLimit = 8;    // very compressed
    else if(pxPerPt < 8)  maxTicksLimit = 15;
    else if(pxPerPt < 20) maxTicksLimit = 25;
    else                   maxTicksLimit = 50;   // expanded — show more
    return {
      x: {
        ticks: {
          maxTicksLimit: maxTicksLimit,
          maxRotation: 45,
          minRotation: 0,
          font: { size: pxPerPt < 5 ? 9 : 11 },
        },
      },
    };
  }

  function _renderChart(chartKey){
    const data = St.chartsData[chartKey];
    const container = QS("#aml_chart_container");
    const scrollWrap = QS("#aml_chart_scroll_wrap");
    const gapLegend = QS("#aml_chart_gap_legend");
    const rangeWrap = QS("#aml_chart_range_wrap");

    if(!data){
      if(container) container.innerHTML = '<div class="small muted" style="padding:20px">Brak danych wykresu</div>';
      if(gapLegend) gapLegend.style.display = "none";
      if(rangeWrap) rangeWrap.style.display = "none";
      return;
    }

    const isTimeline = (chartKey === "balance_timeline" || chartKey === "monthly_trend");

    // Reset zoom when switching chart type
    if(!isTimeline){
      _chartZoom.level = 1;
      _chartZoom.activeKey = null;
      if(container){
        container.style.width = "";
        container.style.minWidth = "100%";
      }
      if(rangeWrap) rangeWrap.style.display = "none";
    } else {
      // Reset zoom to 1 when switching to a different timeline chart
      if(_chartZoom.activeKey !== chartKey){
        _chartZoom.level = 1;
      }
      _chartZoom.activeKey = chartKey;
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
      const txMeta = data.tx_meta || null;

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

      // Balance timeline — rich tooltips, adaptive ticks, bigger hit radius
      if(chartKey === "balance_timeline"){
        chartConfig.options.elements = {
          point: { radius: 2, hoverRadius: 6, hitRadius: 10 },
        };
        Object.assign(chartConfig.options.plugins, _balanceTooltipConfig(txMeta, data));
        chartConfig.options.scales = _adaptiveXTicks(labels.length);
        // Interaction mode: nearest on x-axis for stable tooltip
        chartConfig.options.interaction = { mode: "index", intersect: false, axis: "x" };
      } else if(data.type === "line"){
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

      // Apply zoom & bind interactions (sets container width, triggers resize)
      if(isTimeline){
        // Start at zoom 1 (fit-to-container) — user can zoom via +/- buttons
        _applyTimelineZoom();
        _bindChartInteractions();
        // Show zoom controls only for timeline charts with enough data
        const zoomBar = QS("#aml_chart_zoom_bar");
        if(zoomBar) zoomBar.style.display = labels.length > 30 ? "" : "none";
      } else {
        const zoomBar = QS("#aml_chart_zoom_bar");
        if(zoomBar) zoomBar.style.display = "none";
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
    const btn = QS("#aml_generate_btn");
    const status = QS("#aml_llm_status");

    if(hasPrompt){
      if(btn) btn.disabled = false;
      if(status) status.textContent = "Wybierz model i kliknij Generuj na pasku narzędzi.";
    } else {
      if(btn) btn.disabled = true;
      if(status) status.textContent = "Brak danych do analizy LLM. Uruchom najpierw analizę AML.";
    }
  }

  async function _runLlmAnalysis(){
    if(!St.statementId || St.llmRunning) return;
    St.llmRunning = true;

    const btn = QS("#aml_generate_btn");
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
      const selectedModel = (QS("#aml_llm_model_select") || {}).value || "";
      const userPrompt = (QS("#aml_user_prompt") || {}).value || "";
      let url = "/api/aml/llm-stream/" + encodeURIComponent(St.statementId);
      const params = new URLSearchParams();
      if(selectedModel) params.set("model", selectedModel);
      if(userPrompt.trim()) params.set("user_prompt", userPrompt.trim());
      const qs = params.toString();
      if(qs) url += "?" + qs;
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

  // ---- Custom layout builders for bank flow analysis ----

  /**
   * FLOW LAYOUT: Bipartite — income sources left, account center, expenses right.
   * Uses Cytoscape "preset" layout with manually computed positions.
   */
  function _buildFlowLayout(cy){
    const w = cy.container().clientWidth || 800;
    const h = cy.container().clientHeight || 400;
    const pad = 60;

    // Classify nodes into: account (center), credit (left), debit (right)
    const accountNode = cy.nodes('[type="ACCOUNT"]');
    const creditNodes = [];  // money coming IN → left side
    const debitNodes = [];   // money going OUT → right side

    cy.nodes().forEach(n => {
      if(n.data("type") === "ACCOUNT") return;
      const nid = n.id();
      // Check edges: if this node is source → account = CREDIT (income)
      // If account is source → this node = DEBIT (expense)
      let inAmount = 0, outAmount = 0;
      cy.edges().forEach(e => {
        const amt = Math.abs(e.data("amount") || 0);
        if(e.data("source") === nid) inAmount += amt;   // this→account = income
        if(e.data("target") === nid) outAmount += amt;   // account→this = expense
      });
      if(inAmount >= outAmount){
        creditNodes.push({node: n, amount: inAmount});
      } else {
        debitNodes.push({node: n, amount: outAmount});
      }
    });

    // Sort by amount descending (biggest on top)
    creditNodes.sort((a,b) => b.amount - a.amount);
    debitNodes.sort((a,b) => b.amount - a.amount);

    const positions = {};

    // Account in center
    if(accountNode.length){
      positions[accountNode.id()] = {x: w / 2, y: h / 2};
    }

    // Left column: credit/income nodes
    const leftX = pad + 40;
    const creditSpacing = Math.min(60, (h - 2 * pad) / Math.max(creditNodes.length, 1));
    const creditStartY = Math.max(pad, h / 2 - (creditNodes.length * creditSpacing) / 2);
    creditNodes.forEach((item, i) => {
      positions[item.node.id()] = {x: leftX, y: creditStartY + i * creditSpacing};
    });

    // Right column: debit/expense nodes
    const rightX = w - pad - 40;
    const debitSpacing = Math.min(60, (h - 2 * pad) / Math.max(debitNodes.length, 1));
    const debitStartY = Math.max(pad, h / 2 - (debitNodes.length * debitSpacing) / 2);
    debitNodes.forEach((item, i) => {
      positions[item.node.id()] = {x: rightX, y: debitStartY + i * debitSpacing};
    });

    return {
      name: "preset",
      positions: function(node){ return positions[node.id()] || {x: w/2, y: h/2}; },
      animate: true,
      animationDuration: 500,
      fit: true,
      padding: 30,
    };
  }

  /**
   * AMOUNT LAYOUT: Concentric by transaction amount — biggest counterparties closest to center.
   */
  function _buildAmountLayout(cy){
    // Compute total amount per node from edges
    const nodeAmounts = {};
    let maxAmt = 0;
    cy.nodes().forEach(n => {
      if(n.data("type") === "ACCOUNT"){
        nodeAmounts[n.id()] = Infinity; // account always at center
        return;
      }
      let total = 0;
      n.connectedEdges().forEach(e => { total += Math.abs(e.data("amount") || 0); });
      nodeAmounts[n.id()] = total;
      if(total > maxAmt) maxAmt = total;
    });

    return {
      name: "concentric",
      animate: true,
      animationDuration: 500,
      padding: 30,
      minNodeSpacing: 35,
      concentric: function(node){
        const amt = nodeAmounts[node.id()];
        if(amt === Infinity) return 1000; // account at center
        if(maxAmt === 0) return 50;
        // Higher amount → higher concentric value → closer to center
        return Math.round((amt / maxAmt) * 100);
      },
      levelWidth: function(){ return 3; },
    };
  }

  /**
   * TIMELINE LAYOUT: X-axis = time, Y-axis = credit (top) / debit (bottom).
   * Nodes positioned by date of first transaction on their edges.
   */
  function _buildTimelineLayout(cy){
    const w = cy.container().clientWidth || 800;
    const h = cy.container().clientHeight || 400;
    const pad = 60;

    // Collect first_date per node from connected edges
    const nodeDates = {};
    const nodeDirections = {}; // "credit" or "debit"
    let minDate = null, maxDate = null;

    cy.nodes().forEach(n => {
      if(n.data("type") === "ACCOUNT") return;
      const nid = n.id();
      let earliest = null;
      let inAmt = 0, outAmt = 0;

      n.connectedEdges().forEach(e => {
        const fd = e.data("firstDate") || e.data("first_date") || "";
        if(fd && (!earliest || fd < earliest)) earliest = fd;
        const amt = Math.abs(e.data("amount") || 0);
        if(e.data("source") === nid) inAmt += amt;
        if(e.data("target") === nid) outAmt += amt;
      });

      if(earliest){
        nodeDates[nid] = earliest;
        if(!minDate || earliest < minDate) minDate = earliest;
        if(!maxDate || earliest > maxDate) maxDate = earliest;
      }
      nodeDirections[nid] = inAmt >= outAmt ? "credit" : "debit";
    });

    // Parse date strings to compute relative position
    function dateToNum(ds){
      if(!ds) return 0;
      try{ return new Date(ds.slice(0,10)).getTime(); }catch(e){ return 0; }
    }
    const minT = dateToNum(minDate);
    const maxT = dateToNum(maxDate);
    const range = maxT - minT || 1;

    const positions = {};

    // Account node at center-left
    const accountNode = cy.nodes('[type="ACCOUNT"]');
    if(accountNode.length){
      positions[accountNode.id()] = {x: pad, y: h / 2};
    }

    // Track Y positions per column to avoid overlap
    const creditY = {};  // x-bucket → next Y
    const debitY = {};

    cy.nodes().forEach(n => {
      if(n.data("type") === "ACCOUNT") return;
      const nid = n.id();
      const dateStr = nodeDates[nid];
      if(!dateStr){
        positions[nid] = {x: w/2, y: h/2};
        return;
      }

      const t = dateToNum(dateStr);
      const xPct = (t - minT) / range;
      const x = pad + 60 + xPct * (w - 2*pad - 80);

      // Bucket X into columns for overlap avoidance
      const xBucket = Math.round(x / 40);
      const isCredit = nodeDirections[nid] === "credit";

      if(isCredit){
        // Top half
        if(!creditY[xBucket]) creditY[xBucket] = pad + 20;
        const y = creditY[xBucket];
        creditY[xBucket] += 45;
        positions[nid] = {x, y: Math.min(y, h/2 - 30)};
      } else {
        // Bottom half
        if(!debitY[xBucket]) debitY[xBucket] = h/2 + 30;
        const y = debitY[xBucket];
        debitY[xBucket] += 45;
        positions[nid] = {x, y: Math.min(y, h - pad)};
      }
    });

    return {
      name: "preset",
      positions: function(node){ return positions[node.id()] || {x: w/2, y: h/2}; },
      animate: true,
      animationDuration: 500,
      fit: true,
      padding: 30,
    };
  }

  // Layout name → builder function map
  const _LAYOUT_BUILDERS = {
    flow: _buildFlowLayout,
    amount: _buildAmountLayout,
    timeline: _buildTimelineLayout,
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
        const meta = node.metadata || {};
        elements.push({
          data: {
            id: node.id,
            label: node.label || node.id,
            type: node.node_type || node.type || "COUNTERPARTY",
            riskLevel: node.risk_level || "none",
            classStatus: node.class_status || "",
            totalAmount: meta.total_amount || 0,
            txCount: meta.tx_count || 0,
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
            firstDate: edge.first_date || "",
            lastDate: edge.last_date || "",
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
              "width": function(ele){
                const amt = ele.data("totalAmount") || 0;
                return Math.max(30, Math.min(70, 30 + Math.sqrt(amt) / 15));
              },
              "height": function(ele){
                const amt = ele.data("totalAmount") || 0;
                return Math.max(30, Math.min(70, 30 + Math.sqrt(amt) / 15));
              },
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
        // Use flow layout as default — needs cy instance to compute positions
        layout: {name: "preset", positions: function(){ return {x:0, y:0}; }},
        maxZoom: 3,
        minZoom: 0.3,
      });

      // Apply initial flow layout now that cy instance exists
      St.cyInstance.layout(_buildFlowLayout(St.cyInstance)).run();

      // --- Layout buttons ---
      const layoutBtns = QSA(".aml-graph-layout-btn");
      layoutBtns.forEach(btn=>{
        btn.onclick = ()=>{
          const layoutName = btn.getAttribute("data-layout");
          if(!layoutName || !_LAYOUT_BUILDERS[layoutName] || !St.cyInstance) return;
          // Highlight active button
          layoutBtns.forEach(b=>{ b.style.background=""; b.style.color=""; });
          btn.style.background = "var(--primary)";
          btn.style.color = "#fff";
          // Build and run layout (custom builders need the cy instance)
          const layoutConfig = _LAYOUT_BUILDERS[layoutName](St.cyInstance);
          St.cyInstance.layout(layoutConfig).run();
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
      // Parse search: quoted phrases stay as one term, unquoted words are AND-ed.
      const terms = [];
      const re = /"([^"]+)"|(\S+)/g;
      let m;
      while((m = re.exec(searchVal)) !== null){
        const t = (m[1] || m[2] || "").trim();
        if(t) terms.push(t);
      }
      filtered = filtered.filter(tx => {
        const haystack = [
          tx.counterparty_raw || "",
          tx.title || "",
          tx.category || "",
          tx.raw_text || "",
        ].join(" ").toLowerCase();
        return terms.every(term => haystack.includes(term));
      });
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

    // Group statements by case_id (each case = one analysis batch)
    const groups = {};
    const groupOrder = [];
    for(const item of St.history){
      const key = item.case_id || item.statement_id;
      if(!groups[key]){
        groups[key] = [];
        groupOrder.push(key);
      }
      groups[key].push(item);
    }

    let html = "";
    for(const gk of groupOrder){
      const items = groups[gk];
      const first = items[0];
      const bankName = _esc(first.bank_name || "?");
      const stmtCount = items.length;

      // Aggregate stats across all statements in this group
      let totalTx = 0, maxScore = 0, hasScore = false;
      let minPeriod = "", maxPeriod = "";
      for(const it of items){
        totalTx += (it.tx_count || 0);
        if(it.risk_score != null){
          hasScore = true;
          maxScore = Math.max(maxScore, it.risk_score);
        }
        if(it.period_from && (!minPeriod || it.period_from < minPeriod)) minPeriod = it.period_from;
        if(it.period_to && (!maxPeriod || it.period_to > maxPeriod)) maxPeriod = it.period_to;
      }
      const score = hasScore ? Math.round(maxScore) : "?";
      const scoreColor = score >= 60 ? "var(--danger)" : score >= 30 ? "#d97706" : "var(--ok)";

      if(stmtCount === 1){
        // Single statement — render as before, clickable
        html += `<div class="aml-history-item" data-sid="${_esc(first.statement_id)}" style="display:flex;align-items:center;gap:8px">
          <span class="aml-hist-bank" style="flex:1">${bankName}</span>
          <span class="aml-hist-period">${_esc(first.period_from || "")} \u2014 ${_esc(first.period_to || "")}</span>
          <span class="aml-hist-score" style="color:${scoreColor}">${score}</span>
          <span class="aml-hist-tx small muted">${first.tx_count || 0} tx</span>
          <span class="aml-hist-date small muted">${_fmtDate(first.created_at)}</span>
          <button class="aml-hist-delete" data-sid="${_esc(first.statement_id)}" title="Usun analize" style="background:none;border:none;cursor:pointer;color:var(--danger,#b91c1c);font-size:16px;padding:2px 6px;border-radius:4px;opacity:0.5;line-height:1">&times;</button>
        </div>`;
      } else {
        // Multi-statement group — collapsible header + children
        const groupId = "hist_grp_" + gk.replace(/[^a-zA-Z0-9]/g, "_");
        html += `<div class="aml-history-group">
          <div class="aml-history-group-header" data-sid="${_esc(first.statement_id)}" data-toggle="${groupId}" style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <span class="aml-hist-toggle" id="${groupId}_toggle">\u25B6</span>
            <span class="aml-hist-bank" style="flex:1">${bankName} <span class="aml-hist-badge">${stmtCount}x</span></span>
            <span class="aml-hist-period">${_esc(minPeriod)} \u2014 ${_esc(maxPeriod)}</span>
            <span class="aml-hist-score" style="color:${scoreColor}">${score}</span>
            <span class="aml-hist-tx small muted">${totalTx} tx</span>
            <span class="aml-hist-date small muted">${_fmtDate(first.created_at)}</span>
          </div>
          <div class="aml-history-group-body" id="${groupId}" style="display:none;margin-left:20px">`;

        for(const it of items){
          const itScore = it.risk_score != null ? Math.round(it.risk_score) : "?";
          const itScoreColor = itScore >= 60 ? "var(--danger)" : itScore >= 30 ? "#d97706" : "var(--ok)";
          html += `<div class="aml-history-item aml-history-child" data-sid="${_esc(it.statement_id)}" style="display:flex;align-items:center;gap:8px">
            <span class="aml-hist-bank" style="flex:1;opacity:0.7">${_esc(it.period_from || "")} \u2014 ${_esc(it.period_to || "")}</span>
            <span class="aml-hist-score" style="color:${itScoreColor}">${itScore}</span>
            <span class="aml-hist-tx small muted">${it.tx_count || 0} tx</span>
            <span class="aml-hist-date small muted">${_fmtDate(it.created_at)}</span>
            <button class="aml-hist-delete" data-sid="${_esc(it.statement_id)}" title="Usun analize" style="background:none;border:none;cursor:pointer;color:var(--danger,#b91c1c);font-size:16px;padding:2px 6px;border-radius:4px;opacity:0.5;line-height:1">&times;</button>
          </div>`;
        }
        html += `</div></div>`;
      }
    }
    list.innerHTML = html;

    // Bind toggle for grouped headers — click toggles children, also opens analysis
    QSA(".aml-history-group-header", list).forEach(hdr => {
      hdr.addEventListener("click", async (e) => {
        if(e.target.closest(".aml-hist-delete")) return;

        // Toggle group open/closed
        const toggleId = hdr.getAttribute("data-toggle");
        const body = QS("#" + toggleId);
        const arrow = QS("#" + toggleId + "_toggle");
        if(body){
          const isOpen = body.style.display !== "none";
          body.style.display = isOpen ? "none" : "";
          if(arrow) arrow.textContent = isOpen ? "\u25B6" : "\u25BC";
        }

        // Also open the analysis (first statement in group — will load siblings)
        const sid = hdr.getAttribute("data-sid");
        if(!sid) return;
        _showProgress("Ladowanie analizy...");
        const detail = await _loadDetail(sid);
        const siblings = (detail && detail.sibling_statement_ids) || [];
        if(siblings.length > 1){
          await _mergeMultiAccountCharts(siblings);
        } else {
          St._mergedCharts = null;
          St._mergedInfo = null;
          St._mergedCards = null;
          St._mergedAccounts = null;
        }
        _renderResults();
        _showResults();
        if(window.ReviewManager){
          if(siblings.length > 1){
            await ReviewManager.loadForBatch(siblings);
          } else {
            await ReviewManager.loadForStatement(sid);
          }
        }
      });
    });

    // Bind clicks (open analysis)
    QSA(".aml-history-item", list).forEach(el=>{
      el.addEventListener("click", async (e)=>{
        // Ignore if delete button was clicked
        if(e.target.closest(".aml-hist-delete")) return;
        const sid = el.getAttribute("data-sid");
        if(!sid) return;
        _showProgress("Ladowanie analizy...");
        const detail = await _loadDetail(sid);

        // Multi-statement case: merge charts from all sibling statements
        const siblings = (detail && detail.sibling_statement_ids) || [];
        if(siblings.length > 1){
          await _mergeMultiAccountCharts(siblings);
        } else {
          St._mergedCharts = null;
          St._mergedInfo = null;
          St._mergedCards = null;
          St._mergedAccounts = null;
        }

        _renderResults();
        _showResults();

        // Load Review & Classification (batch-aware via sibling statements)
        if(window.ReviewManager){
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
          if(St.statementId === sid){
            St.statementId = null;
            St.detail = null;
            localStorage.removeItem("aistate_aml_statement_id");
            _showUpload();
          }
          _renderHistory();
        }
      });
    });
  }

  // ============================================================
  // BIND UI EVENTS
  // ============================================================

  function _bindUpload(){
    const fileInput = QS("#aml_file_input");

    // Toolbar upload button
    const toolbarAddBtn = QS("#aml_add_file_toolbar_btn");
    if(toolbarAddBtn && fileInput){
      toolbarAddBtn.onclick = ()=> fileInput.click();
    }
    if(fileInput){
      fileInput.onchange = _fileInputDefaultHandler;
    }

    // Drag & drop on entire AML content area
    const dropArea = QS("#aml_content");
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
        localStorage.removeItem("aistate_aml_statement_id");
        St.chartsData = {};
        St._mergedCharts = null;
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

    // LLM analysis button (toolbar)
    const llmBtn = QS("#aml_generate_btn");
    if(llmBtn){
      llmBtn.onclick = ()=> _runLlmAnalysis();
    }

    // Load AML LLM models on init
    _loadAmlLlmModels();
  }

  /** Load installed Ollama models into the AML LLM model selector. */
  async function _loadAmlLlmModels(){
    const sel = QS("#aml_llm_model_select");
    if(!sel) return;
    try {
      const data = await _safeApi("/api/ollama/status");
      const models = (data && Array.isArray(data.models)) ? data.models : [];
      sel.innerHTML = "";
      if(!models.length){
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Brak modeli (uruchom Ollama)";
        sel.appendChild(opt);
        sel.disabled = true;
        return;
      }
      // Prefer larger models for analysis
      const preferred = ["llama3.1","mistral","qwen","gemma"];
      let defaultModel = models[0];
      for(const pref of preferred){
        const found = models.find(m => m.toLowerCase().includes(pref));
        if(found){ defaultModel = found; break; }
      }
      models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if(m === defaultModel) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.disabled = false;
    } catch(e){
      console.warn("Failed to load AML LLM models:", e);
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
    St.removedAccounts = [];
    St.allAccounts = [];

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

      if(result && (result.status === "ok" || result.status === "duplicate")){
        if(result.status === "duplicate"){
          entry.status = "done";
          entry.statementId = result.statement_id;
          entry.error = "Duplikat — uzyto istniejacego wyciagu";
          // Don't add duplicate statement_id to batchResults again
          if(!St.batchResults.includes(result.statement_id)){
            St.batchResults.push(result.statement_id);
          }
        } else {
          entry.status = "done";
          entry.statementId = result.statement_id;
          St.batchResults.push(result.statement_id);
        }
        if(!St.batchCaseId && result.case_id){
          St.batchCaseId = result.case_id;
        }
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

    // Multi-account: merge balance timelines from all statements
    if(St.batchResults.length > 1){
      await _mergeMultiAccountCharts(St.batchResults);
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

  /**
   * Fetch chart data for all statements and merge ALL chart types into
   * combined multi-statement datasets.  Stores results in St._mergedCharts
   * so _renderResults can restore them after overwriting St.chartsData.
   */
  async function _mergeMultiAccountCharts(stmtIds){
    const palette = ["#1f5aa6","#b91c1c","#15803d","#7c3aed","#d97706","#0891b2","#be185d","#65a30d"];
    const bgPalette = [
      "rgba(31,90,166,0.08)","rgba(185,28,28,0.08)","rgba(21,128,61,0.08)",
      "rgba(124,58,237,0.08)","rgba(217,119,6,0.08)","rgba(8,145,178,0.08)",
      "rgba(190,24,93,0.08)","rgba(101,163,13,0.08)",
    ];

    try {
      // Fetch detail for all statements in parallel
      const allDetails = await Promise.all(
        stmtIds.map(sid => _safeApi("/api/aml/detail/" + encodeURIComponent(sid)))
      );

      const validDetails = allDetails.filter(d => d && d.charts);
      if(validDetails.length < 2){
        St._mergedCharts = null;
        St._mergedInfo = null;
        St._mergedCards = null;
        St._mergedAccounts = null;
        return;
      }

      // ---- 0. MERGE STATEMENT INFO (period, balances, tx count) ----
      {
        const stmts = validDetails.map(d => d.statement).filter(Boolean);
        if(stmts.length > 1){
          // Collect all periods and sort by period_from to find global range
          const allPeriods = stmts
            .filter(s => s.period_from)
            .sort((a,b) => (a.period_from || "").localeCompare(b.period_from || ""));
          const earliest = allPeriods.length ? allPeriods[0] : stmts[0];
          const latest = allPeriods.length
            ? allPeriods.reduce((a,b) => (b.period_to || "") > (a.period_to || "") ? b : a)
            : stmts[stmts.length - 1];

          // Sum tx counts from all details
          let totalTx = 0;
          for(const d of validDetails){
            totalTx += (d.transactions || []).length;
          }

          St._mergedInfo = {
            bank_name: earliest.bank_name || "",
            account_holder: earliest.account_holder || "",
            account_number: earliest.account_number || "",
            period_from: earliest.period_from || "",
            period_to: latest.period_to || "",
            opening_balance: earliest.opening_balance,
            closing_balance: latest.closing_balance,
            currency: earliest.currency || "PLN",
            available_balance: latest.available_balance,
            previous_closing_balance: earliest.previous_closing_balance,
            _statement_count: stmts.length,
            _total_tx: totalTx,
          };
        }
      }

      // ---- 0b. MERGE CARDS across all statements ----
      {
        const allCards = [];
        for(const d of validDetails){
          if(d.cards && d.cards.length) allCards.push(...d.cards);
        }
        // Deduplicate by card_id — merge stats for same card across statements
        if(allCards.length > 0){
          const cardMap = {};
          for(const c of allCards){
            const cid = c.card_id || "unknown";
            if(!cardMap[cid]){
              cardMap[cid] = {...c, _sources: 1};
            } else {
              const existing = cardMap[cid];
              existing.total_debit += (c.total_debit || 0);
              existing.total_credit += (c.total_credit || 0);
              existing.tx_count += (c.tx_count || 0);
              existing.max_amount = Math.max(existing.max_amount || 0, c.max_amount || 0);
              if(c.first_date && (!existing.first_date || c.first_date < existing.first_date)) existing.first_date = c.first_date;
              if(c.last_date && (!existing.last_date || c.last_date > existing.last_date)) existing.last_date = c.last_date;
              existing._sources += 1;

              // Merge top_merchants: aggregate by name, keep top 5
              const mMap = {};
              for(const m of (existing.top_merchants || [])){
                const key = m[0] || "";
                mMap[key] = [key, (mMap[key] ? mMap[key][1] : 0) + (m[1] || 0), (mMap[key] ? mMap[key][2] : 0) + (m[2] || 0)];
              }
              for(const m of (c.top_merchants || [])){
                const key = m[0] || "";
                mMap[key] = [key, (mMap[key] ? mMap[key][1] : 0) + (m[1] || 0), (mMap[key] ? mMap[key][2] : 0) + (m[2] || 0)];
              }
              existing.top_merchants = Object.values(mMap).sort((a, b) => b[1] - a[1]).slice(0, 5);

              // Merge top_categories: aggregate by name, keep top 6
              const catMap = {};
              for(const cat of (existing.top_categories || [])){
                const key = cat[0] || "";
                catMap[key] = [key, (catMap[key] ? catMap[key][1] : 0) + (cat[1] || 0)];
              }
              for(const cat of (c.top_categories || [])){
                const key = cat[0] || "";
                catMap[key] = [key, (catMap[key] ? catMap[key][1] : 0) + (cat[1] || 0)];
              }
              existing.top_categories = Object.values(catMap).sort((a, b) => b[1] - a[1]).slice(0, 6);

              // Merge locations: aggregate counts, keep top 8
              const locMap = {};
              for(const loc of (existing.locations || [])){
                const key = loc[0] || "";
                locMap[key] = [key, (locMap[key] ? locMap[key][1] : 0) + (loc[1] || 0)];
              }
              for(const loc of (c.locations || [])){
                const key = loc[0] || "";
                locMap[key] = [key, (locMap[key] ? locMap[key][1] : 0) + (loc[1] || 0)];
              }
              existing.locations = Object.values(locMap).sort((a, b) => b[1] - a[1]).slice(0, 8);
            }
          }
          // Recalculate avg
          const mergedCards = Object.values(cardMap);
          for(const c of mergedCards){
            c.avg_amount = c.tx_count > 0 ? Math.round((c.total_debit + c.total_credit) / c.tx_count * 100) / 100 : 0;
          }
          St._mergedCards = mergedCards;
        }
      }

      // ---- 0c. MERGE ACCOUNTS across all statements ----
      {
        const allAccounts = [];
        for(const d of validDetails){
          if(d.accounts && d.accounts.length) allAccounts.push(...d.accounts);
        }
        if(allAccounts.length > 0){
          const accMap = {};
          for(const a of allAccounts){
            const aid = a.account_number || "unknown";
            if(!accMap[aid]){
              accMap[aid] = {...a, _sources: 1};
            } else {
              const existing = accMap[aid];
              existing.total_credit += (a.total_credit || 0);
              existing.total_debit += (a.total_debit || 0);
              existing.tx_count += (a.tx_count || 0);
              existing.credit_count += (a.credit_count || 0);
              existing.debit_count += (a.debit_count || 0);
              if(a.first_date && (!existing.first_date || a.first_date < existing.first_date)) existing.first_date = a.first_date;
              if(a.last_date && (!existing.last_date || a.last_date > existing.last_date)) existing.last_date = a.last_date;
              if(a.is_own_account) existing.is_own_account = true;
              existing._sources += 1;
            }
          }
          St._mergedAccounts = Object.values(accMap);
        }
      }

      // ---- 1. BALANCE TIMELINE (multi-dataset line chart) ----
      const allTimelines = [];
      let allLabelsSet = new Set();

      for(let i = 0; i < validDetails.length; i++){
        const d = validDetails[i];
        const bt = (d.charts || {}).balance_timeline;
        if(!bt || !bt.labels || !bt.labels.length) continue;

        const stmt = d.statement || {};
        const acctNum = stmt.account_number || "";
        const period = stmt.period || "";
        let label = period;
        if(!label){
          const firstDate = bt.labels[0] || "";
          const lastDate = bt.labels[bt.labels.length - 1] || "";
          label = firstDate === lastDate ? firstDate : firstDate + " \u2014 " + lastDate;
        }
        const shortAcct = acctNum.length > 8 ? "..." + acctNum.slice(-4) : "";
        if(shortAcct) label += " (" + shortAcct + ")";

        for(const lbl of bt.labels) allLabelsSet.add(lbl);

        allTimelines.push({
          labels: bt.labels,
          data: bt.datasets[0].data,
          label: label,
          txMeta: bt.tx_meta || null,
          firstDate: bt.labels[0] || "",
        });
      }

      let mergedTimeline = null;
      if(allTimelines.length >= 2){
        allTimelines.sort((a, b) => a.firstDate.localeCompare(b.firstDate));
        const allLabels = Array.from(allLabelsSet).sort();
        const mergedDatasets = [];
        const mergedTxMeta = [];

        for(let ti = 0; ti < allTimelines.length; ti++){
          const tl = allTimelines[ti];
          const labelMap = {};
          for(let j = 0; j < tl.labels.length; j++) labelMap[tl.labels[j]] = j;

          const alignedData = [];
          const alignedMeta = [];
          const nextTl = allTimelines[ti + 1];
          const nextFirstDate = nextTl ? nextTl.labels[0] : null;

          for(const lbl of allLabels){
            if(lbl in labelMap){
              alignedData.push(tl.data[labelMap[lbl]]);
              alignedMeta.push(tl.txMeta ? tl.txMeta[labelMap[lbl]] : null);
            } else {
              alignedData.push(null);
              alignedMeta.push(null);
            }
          }

          if(nextFirstDate && tl.data.length > 0){
            const nextIdx = allLabels.indexOf(nextFirstDate);
            if(nextIdx >= 0 && alignedData[nextIdx] === null){
              alignedData[nextIdx] = tl.data[tl.data.length - 1];
              alignedMeta[nextIdx] = null;
            }
          }

          const ci = ti % palette.length;
          mergedDatasets.push({
            label: tl.label,
            data: alignedData,
            borderColor: palette[ci],
            backgroundColor: bgPalette[ci],
            fill: true, tension: 0.2, pointRadius: 1, spanGaps: true, borderWidth: 2,
          });
          mergedTxMeta.push(alignedMeta);
        }

        mergedTimeline = {
          type: "line",
          labels: allLabels,
          datasets: mergedDatasets,
          gaps: [],
          tx_meta: mergedTxMeta[0],
          _multiMeta: mergedTxMeta,
        };
      }

      // ---- 2. CATEGORY DISTRIBUTION (aggregate amounts per category) ----
      const catTotals = {};
      for(const d of validDetails){
        const cd = (d.charts || {}).category_distribution;
        if(!cd || !cd.labels) continue;
        for(let i = 0; i < cd.labels.length; i++){
          const cat = cd.labels[i];
          const val = (cd.datasets[0] || {}).data ? cd.datasets[0].data[i] : 0;
          catTotals[cat] = (catTotals[cat] || 0) + (val || 0);
        }
      }
      let mergedCategory = null;
      const catEntries = Object.entries(catTotals).sort((a,b) => b[1] - a[1]);
      if(catEntries.length > 0){
        const catPalette = ["#1f5aa6","#d97706","#b91c1c","#15803d","#7c3aed",
                            "#0891b2","#be185d","#65a30d","#c2410c","#4338ca","#6b7280"];
        mergedCategory = {
          type: "doughnut",
          labels: catEntries.map(e => e[0]),
          datasets: [{ data: catEntries.map(e => Math.round(e[1]*100)/100), backgroundColor: catPalette.slice(0, catEntries.length) }],
        };
      }

      // ---- 3. CHANNEL DISTRIBUTION (aggregate counts + amounts) ----
      const chCounts = {}, chAmounts = {};
      for(const d of validDetails){
        const ch = (d.charts || {}).channel_distribution;
        if(!ch || !ch.labels) continue;
        for(let i = 0; i < ch.labels.length; i++){
          const lbl = ch.labels[i];
          const ds0 = ch.datasets[0] || {};
          const ds1 = ch.datasets[1] || {};
          chCounts[lbl] = (chCounts[lbl] || 0) + ((ds0.data || [])[i] || 0);
          chAmounts[lbl] = (chAmounts[lbl] || 0) + ((ds1.data || [])[i] || 0);
        }
      }
      let mergedChannel = null;
      const chLabels = Object.keys(chCounts).sort();
      if(chLabels.length > 0){
        mergedChannel = {
          type: "bar",
          labels: chLabels,
          datasets: [
            { label: "Liczba transakcji", data: chLabels.map(l => chCounts[l]), backgroundColor: "rgba(31,90,166,0.7)", yAxisID: "y" },
            { label: "Kwota (PLN)", data: chLabels.map(l => Math.round(chAmounts[l]*100)/100), backgroundColor: "rgba(217,119,6,0.5)", yAxisID: "y1" },
          ],
        };
      }

      // ---- 4. DAILY ACTIVITY (aggregate day-of-week counts) ----
      const dayNames = ["Pon","Wt","Sr","Czw","Pt","Sob","Ndz"];
      const dayCounts = [0,0,0,0,0,0,0];
      for(const d of validDetails){
        const da = (d.charts || {}).daily_activity;
        if(!da || !da.datasets || !da.datasets[0]) continue;
        const src = da.datasets[0].data || [];
        for(let i = 0; i < Math.min(src.length, 7); i++) dayCounts[i] += (src[i] || 0);
      }
      let mergedDaily = null;
      if(dayCounts.some(v => v > 0)){
        mergedDaily = {
          type: "bar",
          labels: dayNames,
          datasets: [{ label: "Transakcje", data: dayCounts, backgroundColor: "rgba(31,90,166,0.7)" }],
        };
      }

      // ---- 5. MONTHLY TREND (aggregate credit + debit per month) ----
      const monthCredit = {}, monthDebit = {};
      for(const d of validDetails){
        const mt = (d.charts || {}).monthly_trend;
        if(!mt || !mt.labels) continue;
        const creditDs = mt.datasets[0] || {};
        const debitDs = mt.datasets[1] || {};
        for(let i = 0; i < mt.labels.length; i++){
          const m = mt.labels[i];
          monthCredit[m] = (monthCredit[m] || 0) + ((creditDs.data || [])[i] || 0);
          monthDebit[m] = (monthDebit[m] || 0) + ((debitDs.data || [])[i] || 0);
        }
      }
      let mergedMonthly = null;
      const months = Object.keys({...monthCredit, ...monthDebit}).sort();
      if(months.length > 0){
        mergedMonthly = {
          type: "bar",
          labels: months,
          datasets: [
            { label: "Wplywy", data: months.map(m => Math.round((monthCredit[m]||0)*100)/100), backgroundColor: "rgba(21,128,61,0.7)" },
            { label: "Wydatki", data: months.map(m => Math.round((monthDebit[m]||0)*100)/100), backgroundColor: "rgba(185,28,28,0.6)" },
          ],
        };
      }

      // ---- 6. TOP COUNTERPARTIES (aggregate amounts across statements) ----
      const cpTotals = {};
      for(const d of validDetails){
        const tc = (d.charts || {}).top_counterparties;
        if(!tc || !tc.labels) continue;
        for(let i = 0; i < tc.labels.length; i++){
          const name = tc.labels[i];
          const val = (tc.datasets[0] || {}).data ? tc.datasets[0].data[i] : 0;
          cpTotals[name] = (cpTotals[name] || 0) + (val || 0);
        }
      }
      let mergedCounterparties = null;
      const cpSorted = Object.entries(cpTotals).sort((a,b) => b[1] - a[1]).slice(0, 15);
      if(cpSorted.length > 0){
        mergedCounterparties = {
          type: "bar",
          labels: cpSorted.map(e => e[0]),
          datasets: [{ label: "Kwota (PLN)", data: cpSorted.map(e => Math.round(e[1]*100)/100), backgroundColor: "rgba(31,90,166,0.7)" }],
          options: { indexAxis: "y" },
        };
      }

      // ---- Store all merged charts ----
      if(!St.chartsData) St.chartsData = {};
      St._mergedCharts = {};
      if(mergedTimeline){ St._mergedCharts.balance_timeline = mergedTimeline; St.chartsData.balance_timeline = mergedTimeline; }
      if(mergedCategory){ St._mergedCharts.category_distribution = mergedCategory; St.chartsData.category_distribution = mergedCategory; }
      if(mergedChannel){ St._mergedCharts.channel_distribution = mergedChannel; St.chartsData.channel_distribution = mergedChannel; }
      if(mergedDaily){ St._mergedCharts.daily_activity = mergedDaily; St.chartsData.daily_activity = mergedDaily; }
      if(mergedMonthly){ St._mergedCharts.monthly_trend = mergedMonthly; St.chartsData.monthly_trend = mergedMonthly; }
      if(mergedCounterparties){ St._mergedCharts.top_counterparties = mergedCounterparties; St.chartsData.top_counterparties = mergedCounterparties; }

    } catch(e){
      console.warn("Multi-statement chart merge failed:", e);
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
      let graphUrl = "/api/aml/graph/" + encodeURIComponent(St.caseId);
      if(St.statementId) graphUrl += "?statement_id=" + encodeURIComponent(St.statementId);
      const graph = await _safeApi(graphUrl);
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

      // Auto-restore last viewed analysis (from localStorage or first in history)
      const savedSid = localStorage.getItem("aistate_aml_statement_id") || "";
      const pid = (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) || "";
      const savedPid = localStorage.getItem("aistate_aml_project_id") || "";

      let restoreSid = "";
      if(savedSid && savedPid === pid){
        // Restore the specific statement the user was viewing
        restoreSid = savedSid;
      } else if(St.history.length){
        // No saved state or project changed — load the most recent analysis
        restoreSid = St.history[0].statement_id;
      }

      if(restoreSid){
        _showProgress("Ładowanie analizy...");
        const detail = await _loadDetail(restoreSid);
        if(detail && detail.statement){
          const siblings = detail.sibling_statement_ids || [];
          if(siblings.length > 1){
            await _mergeMultiAccountCharts(siblings);
          } else {
            St._mergedCharts = null;
            St._mergedInfo = null;
            St._mergedCards = null;
            St._mergedAccounts = null;
          }
          _renderResults();
          _showResults();
          if(window.ReviewManager){
            if(siblings.length > 1){
              await ReviewManager.loadForBatch(siblings);
            } else {
              await ReviewManager.loadForStatement(restoreSid);
            }
          }
        } else {
          _showUpload();
        }
      } else {
        _showUpload();
      }
    },

    /** Called by ReviewManager after classification change. */
    refreshGraphColors: _refreshGraphColors,
  };

  window.AmlManager = AmlManager;
})();
