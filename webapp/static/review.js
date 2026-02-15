// Transaction Review UI module (AISTATEweb)
// Integrated into AML tab — columnar view with classification, header blocks, account profiles

(function(){
  "use strict";

  const QS  = (sel, root=document) => root.querySelector(sel);
  const QSA = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  function _esc(s){
    const d = document.createElement("div");
    d.textContent = String(s ?? "");
    return d.innerHTML;
  }

  function _fmtAmount(v, currency){
    if(v == null || v === "") return "\u2014";
    const n = Number(v);
    if(isNaN(n)) return String(v);
    return n.toLocaleString("pl-PL", {minimumFractionDigits:2, maximumFractionDigits:2}) + " " + (currency || "PLN");
  }

  async function _api(url, opts){
    return await api(url, opts);
  }
  async function _safeApi(url, opts){
    try{ return await api(url, opts); }catch(e){ return null; }
  }

  // Classification metadata
  const CLS_META = {
    neutral:    {label:"Neutralny",  color:"#60a5fa", icon: aiIcon("info_circle",14,"#60a5fa"), bg:"rgba(96,165,250,.08)", html:true},
    legitimate: {label:"Poprawny",   color:"#15803d", icon: aiIcon("success",14), bg:"rgba(21,128,61,.08)", html:true},
    suspicious: {label:"Podejrzany", color:"#dc2626", icon: aiIcon("warning",14), bg:"rgba(220,38,38,.08)", html:true},
    monitoring: {label:"Obserwacja", color:"#ea580c", icon: aiIcon("vision",14,"#ea580c"), bg:"rgba(234,88,12,.08)", html:true},
  };

  // ============================================================
  // INCOME KEYWORD AUTO-CLASSIFICATION
  // ============================================================

  // Regex patterns for income keywords (Polish, with/without diacritics, declensions)
  const _INCOME_PATTERNS = [
    /u[pP]osa[żźz]eni/i,                     // uposażenie / uposazenie
    /[śs]wiadczeni\w*\s*(mieszk|wypocz)?/i,  // świadczenie, swiadczenie (mieszkaniowe, wypoczynkowe)
    /dop[łl]at\w*\s*(do\s+wypocz)?/i,        // dopłata / doplata (do wypoczynku)
    /wynagrodzeni/i,                          // wynagrodzenie
    /pensj/i,                                 // pensja
    /zasi[łl]e?k/i,                           // zasiłek / zasilek
    /emerytur/i,                              // emerytura
    /rent[ay]/i,                              // renta
  ];

  function _isIncomeKeyword(text){
    if(!text) return false;
    const s = String(text).toLowerCase();
    return _INCOME_PATTERNS.some(rx => rx.test(s));
  }

  // ============================================================
  // SUSPICIOUS TX COUNTERPARTY FILTERING
  // ============================================================

  /**
   * Detect if counterparty string is just a bare transaction/reference number.
   * Returns true for strings like "1234567890", "TX123456", "REF00123456789".
   * Returns false for meaningful names like "www.lotto.pl", "Jan Kowalski", "BIEDRONKA".
   */
  function _isBareTransactionId(raw){
    if(!raw) return true;
    const s = String(raw).trim();
    if(!s) return true;
    // Pure digits (6+ chars)
    if(/^\d{6,}$/.test(s)) return true;
    // Short prefix + digits only (e.g. TX1234567, REF123456)
    if(/^[A-Za-z]{1,5}\d{6,}$/.test(s)) return true;
    // Digits separated by slashes/dashes (e.g. 12345/678/90)
    if(/^[\d\/\-\.]{6,}$/.test(s)) return true;
    return false;
  }

  /**
   * Extract meaningful counterparty info from raw text.
   * If the text starts with a transaction ID but contains more (URL, name),
   * extract and return the meaningful part.
   * Returns null if nothing meaningful found.
   */
  function _extractMeaningfulCounterparty(raw){
    if(!raw) return null;
    const s = String(raw).trim();
    if(!s) return null;

    // If the whole thing is a bare ID, nothing meaningful
    if(_isBareTransactionId(s)) return null;

    // Try to strip leading transaction-number-like prefix
    // e.g. "1234567890 www.lotto.pl" → "www.lotto.pl"
    const stripped = s.replace(/^[A-Za-z]{0,5}\d{6,}\s+/, "").trim();
    if(stripped && !_isBareTransactionId(stripped)) return stripped;

    // Return original if it's meaningful
    return s;
  }

  // ============================================================
  // STATE
  // ============================================================

  const St = {
    statementId: null,
    statementIds: [],     // for batch mode — all statement IDs
    transactions: [],
    filteredTx: [],
    header: null,
    headers: [],          // for batch mode — [{id, header, label, periodFrom, periodTo}]
    classifications: {},  // tx_id -> classification
    txStatementMap: {},   // tx_id -> statement_id (for batch classification)
    profile: null,
    headerDirty: {},      // field -> new value
    batchMode: false,
  };

  // ============================================================
  // INIT & LOAD
  // ============================================================

  async function _loadReview(statementId){
    if(!statementId) return;
    St.statementId = statementId;
    St.statementIds = [statementId];
    St.batchMode = false;
    St.txStatementMap = {};
    St.headers = [];

    const data = await _safeApi("/api/aml/review/" + encodeURIComponent(statementId));
    if(!data) return;

    St.transactions = data.transactions || [];
    St.header = data.header || null;

    // Map tx -> statement
    for(const tx of St.transactions){
      St.txStatementMap[tx.id] = statementId;
    }

    // Build classification map + auto-classify income keywords
    _buildClassifications(statementId);

    // Load account profile
    const profileData = await _safeApi("/api/aml/accounts/for-statement/" + encodeURIComponent(statementId));
    St.profile = profileData ? profileData.profile : null;

    _renderAccountProfile();
    _renderHeader();
    _renderStats();
    _renderSuspiciousSummary();
    _fillChannelFilter();
    _filterAndRender();
  }

  /** Load multiple statements for batch review. */
  async function _loadReviewBatch(statementIds){
    if(!statementIds || !statementIds.length) return;
    St.statementIds = statementIds;
    St.statementId = statementIds[0];
    St.batchMode = true;
    St.txStatementMap = {};
    St.classifications = {};
    St.headers = [];

    // Load all statements in parallel
    const allData = await Promise.all(
      statementIds.map(id => _safeApi("/api/aml/review/" + encodeURIComponent(id)))
    );

    // Merge: collect headers and transactions
    let allTx = [];
    for(let i = 0; i < allData.length; i++){
      const data = allData[i];
      if(!data) continue;

      const stmtId = statementIds[i];
      const header = data.header || null;

      // Extract period info from header blocks
      let periodFrom = "", periodTo = "", bankName = "";
      if(header && header.blocks){
        for(const b of header.blocks){
          if(b.field === "period_from") periodFrom = b.value || "";
          if(b.field === "period_to") periodTo = b.value || "";
          if(b.field === "bank_name") bankName = b.value || "";
        }
      }

      const label = bankName
        ? `${bankName}: ${periodFrom || "?"} \u2014 ${periodTo || "?"}`
        : `Wyciag ${i+1}: ${periodFrom || "?"} \u2014 ${periodTo || "?"}`;

      St.headers.push({id: stmtId, header, label, periodFrom, periodTo, bankName, idx: i});

      const txs = data.transactions || [];
      for(const tx of txs){
        tx._statement_id = stmtId;
        tx._statement_idx = i;
        tx._statement_label = label;
        St.txStatementMap[tx.id] = stmtId;
        allTx.push(tx);
      }
    }

    // Sort by period start, then by booking date
    // First, sort headers by periodFrom
    St.headers.sort((a, b) => (a.periodFrom || "").localeCompare(b.periodFrom || ""));
    const headerOrder = {};
    St.headers.forEach((h, idx) => { headerOrder[h.id] = idx; });

    // Sort transactions: first by statement period order, then by booking_date
    allTx.sort((a, b) => {
      const orderA = headerOrder[a._statement_id] ?? 999;
      const orderB = headerOrder[b._statement_id] ?? 999;
      if(orderA !== orderB) return orderA - orderB;
      const da = a.booking_date || "";
      const db = b.booking_date || "";
      return da.localeCompare(db);
    });

    St.transactions = allTx;

    // Use first statement's header as primary
    if(St.headers.length > 0){
      St.header = St.headers[0].header;
    }

    // Build classifications for all statements
    for(const stmtId of statementIds){
      _buildClassifications(stmtId);
    }

    // Load account profile for first statement
    const profileData = await _safeApi("/api/aml/accounts/for-statement/" + encodeURIComponent(statementIds[0]));
    St.profile = profileData ? profileData.profile : null;

    _renderAccountProfile();
    _renderBatchHeaders();
    _renderStats();
    _renderSuspiciousSummary();
    _fillChannelFilter();
    _filterAndRender();
  }

  /** Build classification map + auto-classify income keywords for a statement. */
  function _buildClassifications(statementId){
    for(const tx of St.transactions){
      if(St.txStatementMap[tx.id] !== statementId) continue;
      let cls = tx.classification || "neutral";

      if(cls === "neutral"){
        const amt = parseFloat(tx.amount || 0);
        const isCredit = tx.direction === "CREDIT" || amt > 0;
        if(isCredit){
          const titleMatch = _isIncomeKeyword(tx.title);
          const cpMatch = _isIncomeKeyword(tx.counterparty_raw);
          if(titleMatch || cpMatch){
            cls = "legitimate";
            _safeApi("/api/aml/review/" + encodeURIComponent(statementId) + "/classify", {
              method:"POST",
              headers:{"Content-Type":"application/json"},
              body: JSON.stringify({tx_id: tx.id, classification: "legitimate", note: "Auto: slowo kluczowe przychodu"}),
            });
          }
        }
      }

      St.classifications[tx.id] = cls;
    }
  }

  // ============================================================
  // ACCOUNT PROFILE
  // ============================================================

  function _renderAccountProfile(){
    const info = QS("#rv_account_info");
    if(!info) return;

    if(!St.profile){
      // Auto-create from statement header
      if(St.header && St.header.blocks){
        const iban = _getBlock("account_number");
        const holder = _getBlock("account_holder");
        const bankId = _getBlock("bank_id");
        const bankName = _getBlock("bank_name");
        if(iban){
          _safeApi("/api/aml/accounts", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify({account_number:iban, bank_id:bankId, bank_name:bankName, account_holder:holder, account_type:"private"}),
          }).then(async (res)=>{
            if(res && res.profile) St.profile = res.profile;
            _renderAccountProfile();
          });
          info.innerHTML = '<div class="small muted">Tworzenie profilu konta...</div>';
          return;
        }
      }
      info.innerHTML = '<div class="small muted">Brak informacji o koncie.</div>';
      return;
    }

    const p = St.profile;
    const typeSel = QS("#rv_account_type");
    const anonToggle = QS("#rv_anonymize_toggle");
    if(typeSel) typeSel.value = p.account_type || "private";
    if(anonToggle) anonToggle.checked = !!p.is_anonymized;

    const displayIban = p.display_iban || p.account_number || "";
    const displayHolder = p.display_holder || p.display_name || p.owner_label || "";

    info.innerHTML = `
      <div class="rv-account-grid">
        <div class="rv-acct-field"><b>IBAN:</b> <span style="font-family:monospace">${_esc(displayIban)}</span></div>
        <div class="rv-acct-field"><b>Wlasciciel:</b> ${_esc(displayHolder)}</div>
        <div class="rv-acct-field"><b>Bank:</b> ${_esc(p.bank_name || "")}</div>
        <div class="rv-acct-field"><b>Etykieta:</b> ${_esc(p.owner_label || "")}</div>
      </div>
    `;
  }

  function _getBlock(field){
    if(!St.header || !St.header.blocks) return "";
    const b = St.header.blocks.find(x => x.field === field);
    return b ? (b.value || "") : "";
  }

  async function _updateAccountProfile(){
    if(!St.profile) return;
    const typeSel = QS("#rv_account_type");
    const anonToggle = QS("#rv_anonymize_toggle");
    await _safeApi("/api/aml/accounts/" + encodeURIComponent(St.profile.id), {
      method:"PATCH",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        account_type: typeSel ? typeSel.value : "private",
        is_anonymized: anonToggle ? anonToggle.checked : true,
      }),
    });
    // Reload profile
    const profileData = await _safeApi("/api/aml/accounts/for-statement/" + encodeURIComponent(St.statementId));
    St.profile = profileData ? profileData.profile : null;
    _renderAccountProfile();
  }

  // ============================================================
  // HEADER BLOCKS
  // ============================================================

  function _renderHeader(){
    const grid = QS("#rv_header_grid");
    const warningsEl = QS("#rv_header_warnings");
    if(!grid || !St.header) return;

    St.headerDirty = {};
    const blocks = St.header.blocks || [];

    grid.innerHTML = blocks.map(b => {
      const editable = b.editable;
      const typeIcon = b.type === "amount" ? aiIcon('finance',14) : b.type === "date" ? aiIcon('notes',14) : b.type === "iban" ? aiIcon('finance',14) : "";
      return `<div class="rv-hdr-block ${editable ? 'rv-hdr-editable' : ''}" data-field="${_esc(b.field)}">
        <div class="rv-hdr-label">${typeIcon} ${_esc(b.label)}</div>
        <div class="rv-hdr-value" ${editable ? 'contenteditable="true"' : ''} data-field="${_esc(b.field)}" data-original="${_esc(b.value)}">${_esc(b.value || "\u2014")}</div>
      </div>`;
    }).join("");

    // Track edits
    QSA(".rv-hdr-value[contenteditable]", grid).forEach(el => {
      el.addEventListener("input", ()=>{
        const field = el.getAttribute("data-field");
        const original = el.getAttribute("data-original");
        const current = el.textContent.trim();
        if(current !== original){
          St.headerDirty[field] = current;
          el.classList.add("rv-hdr-changed");
        } else {
          delete St.headerDirty[field];
          el.classList.remove("rv-hdr-changed");
        }
      });
    });

    // Warnings
    if(warningsEl){
      const warnings = St.header.warnings || [];
      if(warnings.length){
        warningsEl.innerHTML = warnings.map(w => {
          const isOk = /\bOK\b/.test(w);
          const color = isOk ? "var(--success, #16a34a)" : "var(--danger)";
          const icon = isOk ? aiIcon("success",12) : aiIcon("warning",12);
          return `<div class="small" style="color:${color};margin:2px 0">${icon} ${_esc(w)}</div>`;
        }).join("");
      } else {
        warningsEl.innerHTML = "";
      }
    }
  }

  /** Render compact header blocks for ALL statements in batch mode. */
  function _renderBatchHeaders(){
    const grid = QS("#rv_header_grid");
    const warningsEl = QS("#rv_header_warnings");
    if(!grid) return;

    if(!St.headers.length){
      _renderHeader(); // fallback to single-statement
      return;
    }

    let html = "";
    for(const hdr of St.headers){
      const h = hdr.header;
      if(!h || !h.blocks) continue;

      // Period separator
      html += `<div class="rv-batch-separator" style="grid-column:1/-1;padding:8px 10px;margin:4px 0;background:var(--bg-alt,#f1f5f9);border-radius:6px;border-left:4px solid var(--primary,#3b82f6);font-weight:600;font-size:13px">\uD83D\uDCC4 ${_esc(hdr.label)}</div>`;

      // Show key blocks only (bank, period, balances)
      const keyFields = ["bank_name","account_number","period_from","period_to","opening_balance","closing_balance","currency"];
      const blocks = h.blocks.filter(b => keyFields.includes(b.field));
      for(const b of blocks){
        const typeIcon = b.type === "amount" ? "\uD83D\uDCB0" : b.type === "date" ? "\uD83D\uDCC5" : b.type === "iban" ? "\uD83C\uDFE6" : "";
        html += `<div class="rv-hdr-block" data-field="${_esc(b.field)}" data-stmt="${_esc(hdr.id)}">
          <div class="rv-hdr-label">${typeIcon} ${_esc(b.label)}</div>
          <div class="rv-hdr-value">${_esc(b.value || "\u2014")}</div>
        </div>`;
      }
    }

    grid.innerHTML = html;

    // Warnings (aggregate)
    if(warningsEl){
      let allWarnings = [];
      for(const hdr of St.headers){
        const ws = (hdr.header && hdr.header.warnings) || [];
        for(const w of ws){
          allWarnings.push(`[${hdr.label}] ${w}`);
        }
      }
      if(allWarnings.length){
        warningsEl.innerHTML = allWarnings.map(w => {
          const isOk = /\bOK\b/.test(w);
          const color = isOk ? "var(--success, #16a34a)" : "var(--danger)";
          const icon = isOk ? aiIcon("success",12) : aiIcon("warning",12);
          return `<div class="small" style="color:${color};margin:2px 0">${icon} ${_esc(w)}</div>`;
        }).join("");
      } else {
        warningsEl.innerHTML = "";
      }
    }
  }

  async function _saveHeaderChanges(){
    if(!St.statementId || !Object.keys(St.headerDirty).length) return;

    for(const [field, value] of Object.entries(St.headerDirty)){
      await _safeApi("/api/aml/review/" + encodeURIComponent(St.statementId) + "/header-update", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({field, value}),
      });

      // Create field rule for future use
      const bankId = _getBlock("bank_id");
      if(bankId){
        await _safeApi("/api/aml/field-rules", {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({
            bank_id: bankId,
            rule_type: "header_remap",
            source_field: field,
            target_field: field,
            note: "Korekta uzytkownika: " + value,
          }),
        });
      }
    }

    St.headerDirty = {};
    // Refresh header
    const data = await _safeApi("/api/aml/review/" + encodeURIComponent(St.statementId));
    if(data) St.header = data.header || St.header;
    _renderHeader();
  }

  // ============================================================
  // CLASSIFICATION STATS
  // ============================================================

  function _renderStats(){
    const bar = QS("#rv_stats_bar");
    const legend = QS("#rv_stats_legend");
    if(!bar) return;

    const counts = {neutral:0, legitimate:0, suspicious:0, monitoring:0};
    for(const cls of Object.values(St.classifications)){
      if(counts[cls] !== undefined) counts[cls]++;
    }

    const total = Object.values(counts).reduce((a,b)=>a+b, 0) || 1;

    // Stacked bar
    bar.innerHTML = Object.entries(CLS_META).map(([key, meta]) => {
      const pct = (counts[key] / total * 100).toFixed(1);
      if(counts[key] === 0) return "";
      return `<div class="rv-stats-seg" style="width:${pct}%;background:${meta.color}" title="${meta.label}: ${counts[key]}"></div>`;
    }).join("");

    // Legend
    if(legend){
      legend.innerHTML = Object.entries(CLS_META).map(([key, meta]) => {
        return `<span class="rv-stats-item">
          <span class="rv-stats-dot" style="background:${meta.color}"></span>
          ${meta.label}: <b>${counts[key]}</b>
        </span>`;
      }).join("");
    }
  }

  // ============================================================
  // SUSPICIOUS TRANSACTIONS SUMMARY
  // ============================================================

  function _renderSuspiciousSummary(){
    const container = QS("#rv_suspicious_summary");
    const listEl = QS("#rv_suspicious_list");
    const countEl = QS("#rv_suspicious_count");
    if(!container || !listEl) return;

    const allSuspicious = St.transactions.filter(tx =>
      (St.classifications[tx.id] || "neutral") === "suspicious"
    );

    // Filter: skip TX where counterparty is just a bare transaction ID
    // (still suspicious in main table, but not shown in summary / not memorized)
    const suspicious = allSuspicious.filter(tx => {
      const meaningful = _extractMeaningfulCounterparty(tx.counterparty_raw);
      return meaningful !== null;
    });

    if(!suspicious.length){
      container.style.display = "none";
      return;
    }

    container.style.display = "";
    if(countEl) countEl.textContent = suspicious.length;

    let html = '<table style="width:100%;font-size:12px;border-collapse:collapse">';
    html += '<tr style="background:rgba(185,28,28,.06);font-weight:bold"><td style="padding:4px 6px">Data</td><td>Kontrahent</td><td>Tytul</td><td style="text-align:right">Kwota</td><td>Kanal</td></tr>';

    for(const tx of suspicious){
      const amt = parseFloat(tx.amount || 0);
      const color = amt < 0 ? "#b91c1c" : "#15803d";
      const cpDisplay = _extractMeaningfulCounterparty(tx.counterparty_raw) || tx.counterparty_raw || "";
      html += `<tr style="border-bottom:1px solid rgba(185,28,28,.15)">
        <td style="padding:3px 6px;white-space:nowrap">${_esc(tx.booking_date || "")}</td>
        <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(tx.counterparty_raw || "")}">${_esc(cpDisplay.slice(0,40))}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(tx.title || "")}">${_esc((tx.title || "").slice(0,50))}</td>
        <td style="text-align:right;color:${color};font-weight:600;white-space:nowrap">${_fmtAmount(amt, "PLN")}</td>
        <td class="small muted">${_esc(tx.channel || "")}</td>
      </tr>`;
    }

    html += '</table>';
    listEl.innerHTML = html;
  }

  // ============================================================
  // TRANSACTION TABLE
  // ============================================================

  function _fillChannelFilter(){
    const sel = QS("#rv_filter_channel");
    if(!sel) return;
    const channels = new Set();
    for(const tx of St.transactions){
      if(tx.channel) channels.add(tx.channel);
    }
    sel.innerHTML = '<option value="">Kanal: wszystkie</option>';
    for(const ch of [...channels].sort()){
      sel.innerHTML += `<option value="${_esc(ch)}">${_esc(ch)}</option>`;
    }
  }

  function _filterAndRender(){
    const searchVal = (QS("#rv_search")?.value || "").toLowerCase().trim();
    const classVal = QS("#rv_filter_class")?.value || "";
    const channelVal = QS("#rv_filter_channel")?.value || "";

    let filtered = St.transactions;
    if(searchVal){
      filtered = filtered.filter(tx =>
        (tx.counterparty_raw || "").toLowerCase().includes(searchVal) ||
        (tx.title || "").toLowerCase().includes(searchVal) ||
        (tx.category || "").toLowerCase().includes(searchVal) ||
        (tx.amount || "").toString().includes(searchVal)
      );
    }
    if(classVal){
      filtered = filtered.filter(tx => (St.classifications[tx.id] || "neutral") === classVal);
    }
    if(channelVal){
      filtered = filtered.filter(tx => tx.channel === channelVal);
    }

    St.filteredTx = filtered;
    const countEl = QS("#rv_tx_count");
    if(countEl){
      let label = filtered.length + " / " + St.transactions.length;
      if(St.batchMode && St.statementIds.length > 1){
        label += " (" + St.statementIds.length + " wyciag" + (St.statementIds.length > 1 ? "ow" : "") + ")";
      }
      countEl.textContent = label;
    }

    _renderTable(filtered);
  }

  function _renderTable(transactions){
    const wrap = QS("#rv_table_wrap");
    if(!wrap) return;

    if(!transactions.length){
      wrap.innerHTML = '<div class="small muted" style="padding:10px">Brak transakcji</div>';
      return;
    }

    const colCount = 10;

    let html = `<table class="rv-tx-table">
      <thead><tr>
        <th class="rv-col-date">Data</th>
        <th class="rv-col-date">Data wal.</th>
        <th class="rv-col-type">Typ</th>
        <th class="rv-col-cp">Kontrahent</th>
        <th class="rv-col-title">Tytul</th>
        <th class="rv-col-amt">Kwota</th>
        <th class="rv-col-bal">Saldo po</th>
        <th class="rv-col-ch">Kanal</th>
        <th class="rv-col-cat">Kategoria</th>
        <th class="rv-col-class">Klasyfikacja</th>
      </tr></thead><tbody>`;

    let lastStmtId = null;

    for(const tx of transactions){
      // Period separator row in batch mode
      if(St.batchMode && tx._statement_id && tx._statement_id !== lastStmtId){
        lastStmtId = tx._statement_id;
        const label = tx._statement_label || "Wyciag";
        html += `<tr class="rv-period-separator">
          <td colspan="${colCount}" style="padding:8px 10px;background:var(--bg-alt,#f0f4f8);border-left:4px solid var(--primary,#3b82f6);font-weight:600;font-size:13px;color:var(--primary,#3b82f6)">\uD83D\uDCC4 ${_esc(label)}</td>
        </tr>`;
      }

      const amt = Number(tx.amount || 0);
      const isDebit = tx.direction === "DEBIT" || amt < 0;
      const amtClass = isDebit ? "rv-debit" : "rv-credit";
      const absAmt = Math.abs(amt);
      const cls = St.classifications[tx.id] || "neutral";
      const clsMeta = CLS_META[cls] || CLS_META.neutral;
      const tags = Array.isArray(tx.risk_tags) ? tx.risk_tags : [];
      const isAnomaly = tx.is_anomaly;
      const rowClass = cls === "suspicious" ? "rv-row-suspicious" :
                       cls === "monitoring" ? "rv-row-monitoring" :
                       cls === "legitimate" ? "rv-row-legitimate" :
                       isAnomaly ? "rv-row-anomaly" : "";

      html += `<tr class="${rowClass}" data-txid="${_esc(tx.id)}">
        <td class="rv-col-date">${_esc(tx.booking_date || "")}</td>
        <td class="rv-col-date">${_esc(tx.tx_date || "")}</td>
        <td class="rv-col-type">${_esc(tx.bank_category || "")}</td>
        <td class="rv-col-cp" title="${_esc(tx.counterparty_raw || "")}">${_esc((tx.counterparty_raw || "").slice(0,35))}</td>
        <td class="rv-col-title" title="${_esc(tx.title || "")}">${_esc((tx.title || "").slice(0,45))}</td>
        <td class="rv-col-amt ${amtClass}">${isDebit ? "-" : "+"}${absAmt.toLocaleString("pl-PL",{minimumFractionDigits:2, maximumFractionDigits:2})}</td>
        <td class="rv-col-bal">${tx.balance_after != null ? _fmtAmount(tx.balance_after, "") : ""}</td>
        <td class="rv-col-ch">${_esc(tx.channel || "")}</td>
        <td class="rv-col-cat">${_esc(tx.category || "")}${tags.length ? ' <span class="rv-risk-tag">' + tags.map(t=>_esc(t)).join(", ") + '</span>' : ''}</td>
        <td class="rv-col-class">
          <div class="rv-cls-btns" data-txid="${_esc(tx.id)}">
            ${Object.entries(CLS_META).map(([k, m]) => {
              const active = cls === k ? "rv-cls-active" : "";
              return `<button class="rv-cls-btn ${active}" data-cls="${k}" style="--cls-color:${m.color}" title="${m.label}">${m.icon}</button>`;
            }).join("")}
          </div>
        </td>
      </tr>`;
    }

    html += "</tbody></table>";
    wrap.innerHTML = html;

    // Bind classification buttons
    QSA(".rv-cls-btn", wrap).forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const txId = btn.closest(".rv-cls-btns").getAttribute("data-txid");
        const cls = btn.getAttribute("data-cls");
        await _classifyTx(txId, cls);
      });
    });
  }

  async function _classifyTx(txId, classification){
    if(!txId) return;

    // In batch mode, find the correct statement ID for this tx
    const stmtId = St.txStatementMap[txId] || St.statementId;
    if(!stmtId) return;

    St.classifications[txId] = classification;

    // Update UI immediately
    const btnsDiv = QS(`.rv-cls-btns[data-txid="${txId}"]`);
    if(btnsDiv){
      QSA(".rv-cls-btn", btnsDiv).forEach(b => b.classList.remove("rv-cls-active"));
      const activeBtn = QS(`.rv-cls-btn[data-cls="${classification}"]`, btnsDiv);
      if(activeBtn) activeBtn.classList.add("rv-cls-active");

      // Update row style
      const row = btnsDiv.closest("tr");
      if(row){
        row.className = classification === "suspicious" ? "rv-row-suspicious" :
                        classification === "monitoring" ? "rv-row-monitoring" :
                        classification === "legitimate" ? "rv-row-legitimate" : "";
      }
    }

    _renderStats();
    _renderSuspiciousSummary();

    // Save to backend (use correct statement ID per transaction)
    await _safeApi("/api/aml/review/" + encodeURIComponent(stmtId) + "/classify", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({tx_id: txId, classification: classification}),
    });

    // Refresh graph colors to reflect classification
    if(window.AmlManager && window.AmlManager.refreshGraphColors){
      window.AmlManager.refreshGraphColors();
    }

    // If marked as suspicious, remember counterparty in memory
    // (skip if counterparty is just a bare transaction number)
    if(classification === "suspicious"){
      const tx = St.transactions.find(t => t.id === txId);
      if(tx){
        const meaningful = _extractMeaningfulCounterparty(tx.counterparty_raw);
        if(meaningful){
          _safeApi("/api/memory", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify({
              name: meaningful,
              label: "blacklist",
              note: "Oznaczony jako podejrzany w analizie " + (St.statementId || "").slice(0,8),
            }),
          });
        }
      }
    }
  }

  // ============================================================
  // BIND UI
  // ============================================================

  function _bindEvents(){
    const search = QS("#rv_search");
    if(search) search.addEventListener("input", () => _filterAndRender());

    const filterClass = QS("#rv_filter_class");
    if(filterClass) filterClass.addEventListener("change", () => _filterAndRender());

    const filterCh = QS("#rv_filter_channel");
    if(filterCh) filterCh.addEventListener("change", () => _filterAndRender());

    const headerSave = QS("#rv_header_save");
    if(headerSave) headerSave.addEventListener("click", () => _saveHeaderChanges());

    const acctType = QS("#rv_account_type");
    if(acctType) acctType.addEventListener("change", () => _updateAccountProfile());

    const anonToggle = QS("#rv_anonymize_toggle");
    if(anonToggle) anonToggle.addEventListener("change", () => _updateAccountProfile());
  }

  // ============================================================
  // HELPERS
  // ============================================================

  function _show(id){ const el = QS("#" + id); if(el) el.style.display = ""; }
  function _hide(id){ const el = QS("#" + id); if(el) el.style.display = "none"; }

  // ============================================================
  // PUBLIC
  // ============================================================

  const ReviewManager = {
    _initialized: false,

    async init(){
      if(this._initialized) return;
      this._initialized = true;
      _bindEvents();
    },

    async loadForStatement(statementId){
      if(!this._initialized) this.init();
      await _loadReview(statementId);
    },

    async loadForBatch(statementIds){
      if(!this._initialized) this.init();
      if(!statementIds || statementIds.length === 0) return;
      if(statementIds.length === 1){
        await _loadReview(statementIds[0]);
        return;
      }
      await _loadReviewBatch(statementIds);
    }
  };

  window.ReviewManager = ReviewManager;
})();
