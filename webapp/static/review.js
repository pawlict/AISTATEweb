// Transaction Review UI module (AISTATEweb)
// Tab "Przeglad transakcji" — columnar view with classification, header blocks, account profiles

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
    neutral:    {label:"Neutralny",  color:"#6b7280", icon:"\u25CB", bg:"rgba(107,114,128,.08)"},
    legitimate: {label:"Poprawny",   color:"#15803d", icon:"\u2713", bg:"rgba(21,128,61,.08)"},
    suspicious: {label:"Podejrzany", color:"#b91c1c", icon:"\u26A0", bg:"rgba(185,28,28,.08)"},
    monitoring: {label:"Obserwacja", color:"#d97706", icon:"\uD83D\uDC41", bg:"rgba(217,119,6,.08)"},
  };

  // ============================================================
  // STATE
  // ============================================================

  const St = {
    statementId: null,
    transactions: [],
    filteredTx: [],
    header: null,
    classifications: {},  // tx_id -> classification
    profile: null,
    allStatements: [],
    headerDirty: {},      // field -> new value
  };

  // ============================================================
  // INIT & LOAD
  // ============================================================

  async function _loadStatementList(){
    const data = await _safeApi("/api/aml/history?limit=50");
    if(data && Array.isArray(data.items)){
      St.allStatements = data.items;
    }
    _fillStatementSelect();
  }

  function _fillStatementSelect(){
    const sel = QS("#rv_statement_select");
    if(!sel) return;
    sel.innerHTML = '<option value="">-- Wybierz wyciag --</option>';
    for(const s of St.allStatements){
      const label = [s.bank_name, s.period_from, "\u2014", s.period_to, `(${s.tx_count || 0} tx)`].filter(Boolean).join(" ");
      sel.innerHTML += `<option value="${_esc(s.statement_id)}">${_esc(label)}</option>`;
    }
  }

  async function _loadReview(statementId){
    if(!statementId) return;
    St.statementId = statementId;

    const data = await _safeApi("/api/aml/review/" + encodeURIComponent(statementId));
    if(!data) return;

    St.transactions = data.transactions || [];
    St.header = data.header || null;

    // Build classification map
    St.classifications = {};
    for(const tx of St.transactions){
      St.classifications[tx.id] = tx.classification || "neutral";
    }

    // Load account profile
    const profileData = await _safeApi("/api/aml/accounts/for-statement/" + encodeURIComponent(statementId));
    St.profile = profileData ? profileData.profile : null;

    // Show all sections
    _show("rv_account_card");
    _show("rv_header_card");
    _show("rv_stats_card");
    _show("rv_table_card");
    _show("rv_rules_card");
    _show("rv_accounts_card");

    _renderAccountProfile();
    _renderHeader();
    _renderStats();
    _fillChannelFilter();
    _filterAndRender();
    _loadFieldRules();
    _loadAccountsList();
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
      const typeIcon = b.type === "amount" ? "💰" : b.type === "date" ? "📅" : b.type === "iban" ? "🏦" : "";
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
        warningsEl.innerHTML = warnings.map(w =>
          `<div class="small" style="color:var(--danger);margin:2px 0">\u26A0 ${_esc(w)}</div>`
        ).join("");
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
    _loadFieldRules();
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
    if(countEl) countEl.textContent = filtered.length + " / " + St.transactions.length;

    _renderTable(filtered);
  }

  function _renderTable(transactions){
    const wrap = QS("#rv_table_wrap");
    if(!wrap) return;

    if(!transactions.length){
      wrap.innerHTML = '<div class="small muted" style="padding:10px">Brak transakcji</div>';
      return;
    }

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

    for(const tx of transactions){
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
    if(!St.statementId || !txId) return;

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

    // Save to backend
    await _safeApi("/api/aml/review/" + encodeURIComponent(St.statementId) + "/classify", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({tx_id: txId, classification: classification}),
    });
  }

  // ============================================================
  // FIELD RULES
  // ============================================================

  async function _loadFieldRules(){
    const bankId = _getBlock("bank_id");
    const list = QS("#rv_rules_list");
    if(!list) return;

    const data = await _safeApi("/api/aml/field-rules" + (bankId ? "?bank_id=" + encodeURIComponent(bankId) : ""));
    if(!data || !data.rules || !data.rules.length){
      list.innerHTML = '<div class="small muted">Brak regul mapowania.</div>';
      return;
    }

    list.innerHTML = data.rules.map(r => `
      <div class="rv-rule-row">
        <span class="rv-rule-bank">${_esc(r.bank_id)}</span>
        <span class="rv-rule-type">${_esc(r.rule_type)}</span>
        <span class="rv-rule-fields">${_esc(r.source_field)} \u2192 ${_esc(r.target_field)}</span>
        <span class="rv-rule-note small muted">${_esc(r.note || "")}</span>
        <button class="rv-rule-del" data-id="${_esc(r.id)}" title="Usun">\u2715</button>
      </div>
    `).join("");

    QSA(".rv-rule-del", list).forEach(btn => {
      btn.addEventListener("click", async () => {
        await _safeApi("/api/aml/field-rules/" + encodeURIComponent(btn.getAttribute("data-id")), {method:"DELETE"});
        _loadFieldRules();
      });
    });
  }

  // ============================================================
  // ACCOUNTS LIST
  // ============================================================

  async function _loadAccountsList(){
    const list = QS("#rv_accounts_list");
    if(!list) return;

    const data = await _safeApi("/api/aml/accounts");
    if(!data || !data.profiles || !data.profiles.length){
      list.innerHTML = '<div class="small muted">Brak profili kont.</div>';
      return;
    }

    list.innerHTML = data.profiles.map(p => {
      const typeLabel = p.account_type === "business" ? "Firmowe" : "Prywatne";
      const typeClass = p.account_type === "business" ? "rv-acct-business" : "rv-acct-private";
      return `<div class="rv-acct-row ${typeClass}">
        <span class="rv-acct-label">${_esc(p.owner_label || p.display_name)}</span>
        <span class="rv-acct-bank">${_esc(p.bank_name || "")}</span>
        <span class="rv-acct-type">${typeLabel}</span>
        <span class="small muted">${p.statement_count || 0} wyciag(ow)</span>
        <select class="rv-acct-type-sel" data-id="${_esc(p.id)}" title="Typ konta">
          <option value="private" ${p.account_type === "private" ? "selected" : ""}>Prywatne</option>
          <option value="business" ${p.account_type === "business" ? "selected" : ""}>Firmowe</option>
        </select>
      </div>`;
    }).join("");

    QSA(".rv-acct-type-sel", list).forEach(sel => {
      sel.addEventListener("change", async () => {
        const profileId = sel.getAttribute("data-id");
        const newType = sel.value;
        const isAnon = newType === "private" ? true : false;
        await _safeApi("/api/aml/accounts/" + encodeURIComponent(profileId), {
          method:"PATCH",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({account_type: newType, is_anonymized: isAnon}),
        });
        _loadAccountsList();
        _renderAccountProfile();
      });
    });
  }

  // ============================================================
  // BIND UI
  // ============================================================

  function _bindEvents(){
    const sel = QS("#rv_statement_select");
    if(sel){
      sel.addEventListener("change", () => {
        if(sel.value) _loadReview(sel.value);
      });
    }

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

    const rulesRefresh = QS("#rv_rules_refresh");
    if(rulesRefresh) rulesRefresh.addEventListener("click", () => _loadFieldRules());
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
      await _loadStatementList();
    }
  };

  window.ReviewManager = ReviewManager;
})();
