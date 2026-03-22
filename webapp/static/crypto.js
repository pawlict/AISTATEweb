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
    try {
      // Prefer AISTATE.projectId (set by projects page), fall back to URL param / localStorage
      if (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId) return String(AISTATE.projectId);
      return (new URLSearchParams(window.location.search)).get("project") || localStorage.getItem("aistate_current_project") || "";
    }
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
  let _detectedAnomalies = {};   // type -> items[]  (kept for anomaly→review filter)
  let _cryptoNotesMgr = null;    // AnalystNotesManager instance
  let _anomalyFilterActive = null; // currently active anomaly filter type

  /* Classification metadata */
  const CLS_META = {
    neutral:    { label: "Neutralny",  color: "#60a5fa", bg: "rgba(96,165,250,.08)" },
    legitimate: { label: "Poprawny",   color: "#15803d", bg: "rgba(21,128,61,.08)" },
    suspicious: { label: "Podejrzany", color: "#dc2626", bg: "rgba(220,38,38,.08)" },
    monitoring: { label: "Obserwacja", color: "#ea580c", bg: "rgba(234,88,12,.08)" },
  };

  const RISK_COLORS = { critical: "#ef4444", high: "#f97316", medium: "#eab308", low: "#22c55e", unknown: "#94a3b8" };

  /* ------------------------------------------------------------------ */
  /*  Icon helpers (GSM-style expand/collapse/+5)                       */
  /* ------------------------------------------------------------------ */

  const _IC_EXPAND   = "/static/icons/akcje/expand_down.svg";
  const _IC_COLLAPSE = "/static/icons/akcje/collapse_up.svg";
  const _IC_PLUS5    = "/static/icons/akcje/plus5.svg";
  const _ICON_SZ     = 20;
  const _makeIcon    = (src, title, cls) =>
    `<img src="${src}" width="${_ICON_SZ}" height="${_ICON_SZ}" title="${title}" class="${cls}" style="cursor:pointer;opacity:.65;transition:opacity .15s" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=.65">`;

  /* ------------------------------------------------------------------ */
  /*  Transaction type dictionary (tooltips for non-crypto users)       */
  /* ------------------------------------------------------------------ */

  const _TX_TYPE_INFO = {
    // Exchange operations
    "deposit":          "Wpłata środków na giełdę z zewnętrznego portfela lub konta bankowego",
    "withdraw":         "Wypłata środków z giełdy na zewnętrzny portfel lub konto bankowe",
    "withdrawal":       "Wypłata środków z giełdy na zewnętrzny portfel lub konto bankowe",
    "buy":              "Zakup kryptowaluty za inną walutę (fiat lub krypto)",
    "sell":             "Sprzedaż kryptowaluty za inną walutę (fiat lub krypto)",
    "swap":             "Wymiana jednej kryptowaluty na inną bezpośrednio, bez pośrednictwa waluty fiat",
    "trade":            "Transakcja handlowa — kupno lub sprzedaż na rynku giełdowym",
    "transfer":         "Przeniesienie środków między własnymi kontami/portfelami na giełdzie",
    "send":             "Wysłanie środków do innego użytkownika lub na zewnętrzny adres",
    "receive":          "Otrzymanie środków od innego użytkownika lub z zewnętrznego adresu",
    "staking":          "Zablokowanie kryptowaluty w celu uzyskania nagród (oprocentowanie)",
    "staking_reward":   "Nagroda otrzymana za udział w stakingu (oprocentowanie krypto)",
    "unstaking":        "Odblokowanie wcześniej zablokowanych środków ze stakingu",
    "earn":             "Program oszczędnościowy/inwestycyjny — odsetki od zdeponowanych środków",
    "distribution":     "Dystrybucja tokenów — airdrop, nagroda lub podział zysku",
    "airdrop":          "Darmowe tokeny otrzymane w ramach promocji lub dystrybucji projektu",
    "fee":              "Opłata transakcyjna pobrana przez giełdę lub sieć blockchain",
    "commission":       "Prowizja pobrana przez giełdę za wykonanie transakcji",
    "funding":          "Opłata za utrzymanie pozycji futures/margin (funding rate)",
    "futures":          "Transakcja na kontrakcie terminowym (futures) — instrumenty pochodne",
    "margin":           "Transakcja z dźwignią finansową (pożyczone środki)",
    "liquidation":      "Przymusowe zamknięcie pozycji z powodu niewystarczającego zabezpieczenia",
    "convert":          "Konwersja jednej kryptowaluty na inną po aktualnym kursie",
    "p2p":              "Transakcja peer-to-peer — bezpośrednia wymiana między użytkownikami",
    "otc":              "Transakcja OTC (Over-The-Counter) — poza rynkiem giełdowym, zwykle duże kwoty",
    "nft":              "Transakcja związana z NFT (Non-Fungible Token) — unikalne tokeny cyfrowe",
    "mint":             "Utworzenie nowego tokena lub NFT na blockchainie",
    "burn":             "Trwałe zniszczenie/usunięcie tokenów z obiegu (zmniejszenie podaży)",
    "bridge":           "Transfer kryptowaluty między różnymi blockchainami przez most (bridge)",
    "wrap":             "Zamiana tokena na jego 'opakowaną' wersję kompatybilną z innym blockchainem (np. BTC→WBTC)",
    "unwrap":           "Zamiana opakowanego tokena z powrotem na oryginał (np. WBTC→BTC)",
    "loan":             "Pożyczka kryptowalutowa — wypożyczenie lub zaciągnięcie pożyczki",
    "repayment":        "Spłata pożyczki kryptowalutowej",
    "collateral":       "Środki zablokowane jako zabezpieczenie pożyczki lub pozycji margin",
    "savings":          "Środki ulokowane w programie oszczędnościowym giełdy",
    "launchpad":        "Udział w sprzedaży nowego tokena (IEO/IDO) na platformie giełdy",
    "referral":         "Premia/nagroda za polecenie giełdy innym użytkownikom",
    "cashback":         "Zwrot części opłaty transakcyjnej lub zakupu",
    "dust_conversion":  "Zamiana niewielkich resztek tokenów (dust) na jedną kryptowalutę (np. BNB)",
    // Blockchain-specific
    "incoming":         "Transakcja przychodząca — środki otrzymane na portfel",
    "outgoing":         "Transakcja wychodząca — środki wysłane z portfela",
    "contract_call":    "Wywołanie smart kontraktu na blockchainie (np. interakcja z DeFi)",
    "approval":         "Udzielenie zgody smart kontraktowi na zarządzanie tokenami",
    "self_transfer":    "Transfer do samego siebie — przeniesienie między własnymi adresami",
  };

  /** Get tooltip HTML for a tx_type string */
  function _txTypeTooltip(txType) {
    if (!txType) return "";
    const key = txType.toLowerCase().replace(/[\s\-]+/g, "_");
    // Try exact match, then partial
    let info = _TX_TYPE_INFO[key];
    if (!info) {
      for (const [k, v] of Object.entries(_TX_TYPE_INFO)) {
        if (key.includes(k) || k.includes(key)) { info = v; break; }
      }
    }
    if (!info) return _esc(txType);
    return `<span class="crypto-tx-type-hint" title="${_esc(info)}" style="border-bottom:1px dotted var(--text-muted,#94a3b8);cursor:help">${_esc(txType)}</span>`;
  }

  /* ------------------------------------------------------------------ */
  /*  Lazy-load external libraries                                      */
  /* ------------------------------------------------------------------ */

  const _scriptPromises = {};
  function _loadScript(url) {
    if (_scriptPromises[url]) return _scriptPromises[url];
    _scriptPromises[url] = new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${url}"]`);
      if (existing) {
        // Script tag exists — wait for it to finish loading
        if (existing._loaded) { resolve(); return; }
        existing.addEventListener("load", () => { existing._loaded = true; resolve(); });
        existing.addEventListener("error", reject);
        return;
      }
      const s = document.createElement("script");
      s.src = url;
      s.onload = () => { s._loaded = true; resolve(); };
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return _scriptPromises[url];
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
        // Remember active analysis tab for project auto-restore
        const pid = _getProjectId();
        if (pid) localStorage.setItem("aistate_analysis_tab_" + pid, "crypto");
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
        // Remember active analysis tab for project auto-restore
        if (pid) localStorage.setItem("aistate_analysis_tab_" + pid, "crypto");
      }
    } catch (e) {
      console.warn("[Crypto] Auto-load failed:", e);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Render results — dual mode                                        */
  /* ------------------------------------------------------------------ */

  async function _renderResults(r) {
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

    // Binance XLSX forensic cards
    const isBinance = (r.source === "binance_xlsx");
    if (isBinance) {
      _renderAccountInfo(r);
      _renderCounterparties(r);
      _renderPayC2C(r);
      _renderExtAddresses(r);
      _renderPassThrough(r);
      _renderPrivacyCoins(r);
      _renderAccessLogs(r);
      _renderCardTimeline(r);
    } else {
      _hide("crypto_account_card");
      _hide("crypto_counterparties_card");
      _hide("crypto_pay_c2c_card");
      _hide("crypto_ext_addresses_card");
      _hide("crypto_passthrough_card");
      _hide("crypto_privacy_card");
      _hide("crypto_access_card");
      _hide("crypto_card_timeline_card");
    }

    _renderReviewTable(r, isExchange);
    _renderAnomalies(r, isExchange);

    // Ensure Chart.js is loaded before rendering any charts
    try { await _ensureChartJS(); } catch (e) { console.warn("[Crypto] Chart.js load failed:", e); }
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
        // Account owner info from forensic report
        const acct = (r.forensic_report && r.forensic_report.account_info) || {};
        if (acct.holder_name) html += `<div class="crypto-info-row"><b>Właściciel:</b> ${_esc(acct.holder_name)}</div>`;
        if (acct.user_id) html += `<div class="crypto-info-row"><b>User ID:</b> ${_esc(acct.user_id)}</div>`;
        if (acct.email) html += `<div class="crypto-info-row"><b>Email:</b> ${_esc(acct.email)}</div>`;
        if (acct.phone) html += `<div class="crypto-info-row"><b>Telefon:</b> ${_esc(acct.phone)}</div>`;
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

    // Load saved classifications from backend, then auto-classify unclassified
    _loadSavedClassifications().then(() => {
      _autoClassifyAll(txs);
      _renderReviewStats(txs);
      _filterAndRenderReview(txs, isExchange);
    });
  }

  /** Load previously saved classifications from backend */
  async function _loadSavedClassifications() {
    const projectId = _currentProjectId();
    if (!projectId) return;
    try {
      const resp = await fetch("/api/crypto/classifications?project_id=" + encodeURIComponent(projectId));
      if (resp.ok) {
        const data = await resp.json();
        if (data.classifications) {
          // Merge saved into current — saved takes priority (manual overrides)
          for (const [txId, cls] of Object.entries(data.classifications)) {
            _txClassifications[txId] = cls;
          }
        }
      }
    } catch (e) {
      console.warn("[Crypto] Failed to load saved classifications:", e);
    }
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

  // Auto-classification mapping: tx_type / category → default classification
  // Mirrors AML's _catAutoCls pattern
  const _CRYPTO_AUTO_CLS = {
    // Legitimate operations
    staking_reward:  "legitimate",
    airdrop:         "legitimate",
    interest:        "legitimate",
    cashback:        "legitimate",
    referral_bonus:  "legitimate",
    mining:          "legitimate",
    earn:            "legitimate",
    savings_interest:"legitimate",
    dust:            "legitimate",
    fee:             "legitimate",
    commission:      "legitimate",
    // Neutral / standard operations
    deposit:         "neutral",
    withdrawal:      "neutral",
    buy:             "neutral",
    sell:            "neutral",
    swap:            "neutral",
    trade:           "neutral",
    transfer:        "neutral",
    convert:         "neutral",
    fiat_deposit:    "neutral",
    fiat_withdrawal: "neutral",
    send:            "neutral",
    receive:         "neutral",
    // Monitoring-worthy
    bridge:          "monitoring",
    cross_chain:     "monitoring",
    wrap:            "monitoring",
    unwrap:          "monitoring",
    nft_purchase:    "monitoring",
    nft_sale:        "monitoring",
    contract_call:   "monitoring",
    // Suspicious indicators
    mixer:           "suspicious",
    tumbler:         "suspicious",
  };

  function _autoClassify(tx) {
    const tags = tx.risk_tags || [];
    // Highest priority: sanctioned / mixer tags
    if (tags.includes("sanctioned") || tags.includes("mixer")) return "suspicious";
    if (tags.includes("privacy_coin")) return "monitoring";

    // Risk score override
    const score = tx.risk_score || 0;
    if (score >= 70) return "suspicious";

    // Category / tx_type mapping (like AML)
    const txType = (tx.tx_type || "").toLowerCase().replace(/[\s-]/g, "_");
    const category = (tx.category || "").toLowerCase().replace(/[\s-]/g, "_");
    if (_CRYPTO_AUTO_CLS[txType]) return _CRYPTO_AUTO_CLS[txType];
    if (_CRYPTO_AUTO_CLS[category]) return _CRYPTO_AUTO_CLS[category];

    // Moderate risk → monitoring
    if (score >= 40 || tags.includes("high_value")) return "monitoring";

    return "neutral";
  }

  /** Classify a single transaction — update DOM + save to backend (like AML review.js) */
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

    // Save to backend (like AML pattern)
    const projectId = _currentProjectId();
    if (projectId) {
      fetch("/api/crypto/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          tx_id: txId,
          classification: classification,
        }),
      }).catch(err => console.warn("[Crypto] classify save error:", err));
    }
  }

  /** Bulk auto-classify all transactions and save to backend */
  function _autoClassifyAll(txs) {
    if (!txs || !txs.length) return;
    const batch = {};
    for (const tx of txs) {
      const txId = tx.hash || tx.id || "";
      if (!txId) continue;
      // Don't override manual classifications
      if (_txClassifications[txId]) continue;
      const cls = _autoClassify(tx);
      _txClassifications[txId] = cls;
      batch[txId] = cls;
    }

    // Bulk save to backend
    const projectId = _currentProjectId();
    if (projectId && Object.keys(batch).length > 0) {
      fetch("/api/crypto/classify-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          classifications: batch,
        }),
      }).catch(err => console.warn("[Crypto] batch classify save error:", err));
    }
  }

  /** Get current project ID from page context (reuses existing _getProjectId) */
  function _currentProjectId() {
    return _getProjectId();
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

    // Note marker helper (like GSM/AML)
    const notesMgr = _cryptoNotesMgr;
    function _noteMarker(txId) {
      const has = notesMgr && notesMgr.hasNote("crypto_transaction", "transaction_id", txId);
      return `<td style="padding:0 2px;text-align:center;width:22px"><span class="analyst-note-marker${has ? " has-note" : ""}" data-note-txid="${_esc(txId)}" title="Notatka (Ctrl+M)"><img src="/static/icons/dokumenty/notes.svg" alt="" width="13" height="13" draggable="false"></span></td>`;
    }

    if (isExchange) {
      html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
        '<th style="width:22px"></th><th>Data</th><th>Konto</th><th>Operacja</th><th>Token</th><th>Kwota</th><th>Typ</th><th>Tagi</th><th>Klasyfikacja</th>' +
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
          ${_noteMarker(txId)}
          <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16).replace("T", " "))}</td>
          <td>${_esc(raw.account || "\u2014")}</td>
          <td>${_txTypeTooltip(tx.category || raw.operation || tx.tx_type || "\u2014")}</td>
          <td style="font-weight:600">${_esc(tx.token || "")}</td>
          <td style="text-align:right;color:${amtColor};font-weight:500">${isNeg ? "-" : "+"}${amt.toFixed(4)}</td>
          <td>${_txTypeTooltip(tx.tx_type || "")}</td>
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
        '<th style="width:22px"></th><th>Data</th><th>Od</th><th>Do</th><th>Kwota</th><th>Token</th><th>Typ</th><th>Ryzyko</th><th>Klasyfikacja</th>' +
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
          ${_noteMarker(txId)}
          <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16))}</td>
          <td style="font-family:monospace;font-size:10px" title="${_esc(tx.from || "")}">${_esc(_shorten(tx.from || "\u2014"))}</td>
          <td style="font-family:monospace;font-size:10px" title="${_esc(tx.to || "")}">${_esc(_shorten(tx.to || "\u2014"))}</td>
          <td style="text-align:right">${_fmtCrypto(tx.amount, "")}</td>
          <td>${_esc(tx.token || "")}</td>
          <td>${_txTypeTooltip(tx.tx_type || "")}</td>
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

    // Bind note markers — open analyst note panel (like GSM/AML)
    if (notesMgr) {
      wrap.querySelectorAll(".analyst-note-marker[data-note-txid]").forEach(marker => {
        marker.addEventListener("click", (e) => {
          e.stopPropagation();
          const txId = marker.getAttribute("data-note-txid");
          if (!txId) return;
          // Find the transaction for snapshot data
          const tx = ((_lastResult || {}).transactions || []).find(t => (t.hash || t.id) === txId);
          const amt = tx ? _fmtCrypto(tx.amount, tx.token || "") : "";
          const typ = tx ? (tx.tx_type || tx.category || "") : "";
          const date = tx ? (tx.timestamp || "").slice(0, 16).replace("T", " ") : "";
          const label = (amt ? amt + " " : "") + (typ ? typ + " " : "") + (date ? "(" + date + ")" : "");
          const ref = {
            type: "crypto_transaction",
            transaction_id: txId,
            snapshot: { amount: amt, type: typ, date: date, token: tx ? tx.token : "" },
          };
          notesMgr.openNoteForElement(label || "Transakcja krypto", "finance", ref);
        });
      });
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Anomalies (like GSM, dedicated to crypto)                         */
  /* ------------------------------------------------------------------ */

  const _CRYPTO_ANOMALY_CATS = [
    { type: "deposits_withdrawals",  label: "Wpłaty i wypłaty środków",         desc: "Wpłaty na giełdę / z zewnątrz i wypłaty na zewnątrz giełdy — chronologicznie" },
    { type: "high_value_tx",         label: "Transakcje dużej wartości",         desc: "Pojedyncze transakcje przekraczające istotny próg wartości" },
    { type: "rapid_movement",        label: "Szybkie przerzuty środków",         desc: "Wpłata + wypłata w krótkim czasie — potencjalne pranie pieniędzy" },
    { type: "privacy_coins",         label: "Privacy coins / mikser",            desc: "Transakcje z użyciem Monero (XMR), Zcash (ZEC), Tornado Cash lub podejrzanych adresów" },
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

    // Detect anomalies and cache for filter
    const detected = _detectCryptoAnomalies(r, txs, isExchange);
    _detectedAnomalies = detected;

    const VISIBLE = 5;
    const SCROLL_THRESHOLD = 50;

    let html = '<div style="display:flex;flex-direction:column;gap:10px">';
    for (const cat of _CRYPTO_ANOMALY_CATS) {
      const items = detected[cat.type] || [];
      const hasItems = items.length > 0;
      const sev = hasItems ? _anomalySeverity(cat.type, items) : "ok";
      const sevColor = sev === "critical" ? "#dc2626" : sev === "warning" ? "#f97316" : sev === "info" ? "#3b82f6" : "#22c55e";
      const sevIcon = sev === "critical" ? "\u2757" : sev === "warning" ? "\u26A0" : sev === "info" ? "\u2139" : "\u2713";

      html += `<div class="gsm-anomaly-card" data-anomaly-type="${cat.type}" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;border-left:3px solid ${sevColor};transition:background .15s,box-shadow .15s">`;

      // ── Top bar: header + action icons ──
      html += `<div class="gsm-anomaly-bar" style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:rgba(${sev === 'critical' ? '220,38,38' : sev === 'warning' ? '249,115,22' : sev === 'info' ? '59,130,246' : '34,197,94'},.04)">`;
      html += `<span style="color:${sevColor};font-size:15px;flex-shrink:0">${sevIcon}</span>`;
      html += `<div style="flex:1;min-width:0">`;
      html += `<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap"><b>${cat.label}</b>`;
      if (!hasItems) {
        html += ` <span class="muted gsm-anom-count">\u2014 brak</span>`;
      } else {
        html += ` <span class="muted gsm-anom-count">(${items.length})</span>`;
      }
      html += `</div>`;
      html += `<div class="small muted" style="margin-top:1px;line-height:1.3">${cat.desc}</div>`;
      html += `</div>`;

      // ── Action icons (like GSM) ──
      html += `<div style="display:flex;align-items:center;gap:2px;flex-shrink:0;border-left:1px solid var(--border);padding-left:8px;margin-left:4px">`;
      // Note marker
      const _hn = _cryptoNotesMgr && _cryptoNotesMgr.hasNote("crypto_anomaly", "anomaly_type", cat.type);
      html += `<span class="analyst-note-marker${_hn ? " has-note" : ""}" data-note-anomaly="${cat.type}" title="Notatka (Ctrl+M)"><img src="/static/icons/dokumenty/notes.svg" alt="" width="16" height="16" draggable="false"></span>`;
      if (hasItems) {
        if (items.length > VISIBLE) {
          html += _makeIcon(_IC_EXPAND, "Rozwiń / zwiń listę", "crypto-anom-toggle") + " ";
        }
        html += _makeIcon(_IC_PLUS5, "Filtruj transakcje tej anomalii", "crypto-anom-filter");
      }
      html += `</div>`;
      html += `</div>`; // end bar

      // ── Items body ──
      if (hasItems) {
        const uid = `crypto_anom_exp_${cat.type}`;
        const collapsedH = VISIBLE * 24;
        const useScroll = items.length > SCROLL_THRESHOLD;
        const maxExpandH = useScroll ? '300px' : 'none';
        const overflowY = useScroll ? 'auto' : 'visible';
        const needCollapse = items.length > VISIBLE;

        html += `<div id="${uid}" data-collapsed-h="${collapsedH}" data-max-h="${maxExpandH}" data-overflow="${overflowY}" `
          + `style="padding:4px 12px 8px;font-size:12px;line-height:1.8;${needCollapse ? 'max-height:' + collapsedH + 'px;overflow:hidden;' : ''}transition:max-height .25s ease">`;
        for (const item of items) {
          const ic = item.severity === "critical" ? "#dc2626" : item.severity === "warning" ? "#f97316" : "#3b82f6";
          html += `<div style="border-left:3px solid ${ic};padding:2px 8px;margin-bottom:2px;background:rgba(${item.severity === "critical" ? "220,38,38" : item.severity === "warning" ? "249,115,22" : "59,130,246"},.04);border-radius:4px">${item.html || _esc(item.text || "")}</div>`;
        }
        html += '</div>';
      }

      html += '</div>'; // end card
    }
    html += '</div>';
    body.innerHTML = html;

    // ── Expand / collapse via icon (GSM pattern) ──
    body.querySelectorAll(".crypto-anom-toggle").forEach(icon => {
      icon.addEventListener("click", function(e) {
        e.stopPropagation();
        const card = this.closest(".gsm-anomaly-card");
        if (!card) return;
        const type = card.dataset.anomalyType;
        const container = document.getElementById(`crypto_anom_exp_${type}`);
        if (!container) return;
        const isExpanded = container.dataset.expanded === "1";
        if (isExpanded) {
          container.style.maxHeight = container.dataset.collapsedH + "px";
          container.style.overflowY = "hidden";
          container.dataset.expanded = "0";
          this.src = _IC_EXPAND;
          this.title = "Rozwiń listę";
        } else {
          const maxH = container.dataset.maxH;
          container.style.maxHeight = maxH === "none" ? container.scrollHeight + "px" : maxH;
          container.style.overflowY = container.dataset.overflow;
          container.dataset.expanded = "1";
          this.src = _IC_COLLAPSE;
          this.title = "Zwiń listę";
        }
      });
    });

    // ── Filter icon → filter review table by anomaly type ──
    body.querySelectorAll(".crypto-anom-filter").forEach(icon => {
      icon.addEventListener("click", function(e) {
        e.stopPropagation();
        const card = this.closest(".gsm-anomaly-card");
        if (!card) return;
        const type = card.dataset.anomalyType;
        const items = _detectedAnomalies[type];
        if (!items || !items.length) return;
        _cryptoAnomalyGroupFilter(type, items);
      });
    });

    // ── Hover effect on cards with items ──
    body.querySelectorAll(".gsm-anomaly-card").forEach(div => {
      const hasData = (detected[div.dataset.anomalyType] || []).length > 0;
      if (!hasData) return;
      div.style.cursor = "pointer";
      div.addEventListener("mouseenter", () => {
        div.style.background = "rgba(31,90,166,.04)";
        div.style.boxShadow = "0 2px 8px rgba(15,23,42,.06)";
      });
      div.addEventListener("mouseleave", () => {
        div.style.background = "";
        div.style.boxShadow = "";
      });
      // Double-click on card also filters
      div.addEventListener("dblclick", (e) => {
        const type = div.dataset.anomalyType;
        const items = _detectedAnomalies[type];
        if (items && items.length) _cryptoAnomalyGroupFilter(type, items);
      });
    });

    // ── Note markers on anomaly cards ──
    body.querySelectorAll(".analyst-note-marker[data-note-anomaly]").forEach(marker => {
      marker.addEventListener("click", function(e) {
        e.stopPropagation();
        const type = this.getAttribute("data-note-anomaly");
        if (!type) return;
        const catDef = _CRYPTO_ANOMALY_CATS.find(c => c.type === type);
        const label = catDef ? "Anomalia: " + catDef.label : "Anomalia: " + type;
        const ref = { type: "crypto_anomaly", anomaly_type: type };
        if (_cryptoNotesMgr) _cryptoNotesMgr.openNoteForElement(label, "warning", ref);
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Anomaly → Review filter (like GSM _anomalyGroupFilter)            */
  /* ------------------------------------------------------------------ */

  function _cryptoAnomalyGroupFilter(type, items) {
    if (!_lastResult) return;
    const txs = _lastResult.transactions || [];
    const isExchange = _lastResult.source_type === "exchange";

    // Build predicate: which transactions match this anomaly?
    const predicate = _cryptoAnomalyPredicate(type, items, txs);
    const filtered = txs.filter(predicate);

    if (_anomalyFilterActive === type) {
      // Toggle off — show all
      _anomalyFilterActive = null;
      _filterAndRenderReview(txs, isExchange);
      _hideAnomalyFilterBar();
      return;
    }

    _anomalyFilterActive = type;
    const catDef = _CRYPTO_ANOMALY_CATS.find(c => c.type === type);
    const filterText = (catDef ? catDef.label : type) + ` — ${filtered.length} transakcji`;

    _showAnomalyFilterBar(filterText, () => {
      _anomalyFilterActive = null;
      _filterAndRenderReview(txs, isExchange);
      _hideAnomalyFilterBar();
    });

    _filterAndRenderReview(filtered, isExchange);

    // Scroll to review card
    const recCard = document.getElementById("crypto_review_card");
    if (recCard) {
      recCard.scrollIntoView({ behavior: "smooth", block: "start" });
      recCard.style.transition = "box-shadow .2s";
      recCard.style.boxShadow = "0 0 0 3px var(--brand-blue,#2563eb)";
      setTimeout(() => { recCard.style.boxShadow = ""; }, 1200);
    }
  }

  function _showAnomalyFilterBar(text, onClear) {
    let bar = document.getElementById("crypto_anomaly_filter_bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "crypto_anomaly_filter_bar";
      bar.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 12px;background:rgba(37,99,235,.08);border:1px solid rgba(37,99,235,.25);border-radius:8px;margin-bottom:8px;font-size:13px";
      const wrap = document.getElementById("crypto_rv_table_wrap");
      if (wrap) wrap.parentNode.insertBefore(bar, wrap);
    }
    bar.style.display = "flex";
    bar.innerHTML = `<span style="flex:1"><b>Filtr anomalii:</b> ${_esc(text)}</span><button class="btn btn-sm" style="padding:2px 10px;font-size:12px">✕ Wyczyść filtr</button>`;
    bar.querySelector("button").onclick = onClear;
  }

  function _hideAnomalyFilterBar() {
    const bar = document.getElementById("crypto_anomaly_filter_bar");
    if (bar) bar.style.display = "none";
  }

  /** Build a predicate for filtering transactions by anomaly type */
  function _cryptoAnomalyPredicate(type, anomalyItems, txs) {
    switch (type) {
      case "deposits_withdrawals":
        return tx => {
          const t = (tx.tx_type || "").toLowerCase();
          const c = (tx.category || "").toLowerCase();
          return t.includes("deposit") || c.includes("deposit") || t === "receive" || t === "incoming"
              || t.includes("withdraw") || c.includes("withdraw") || t === "send" || t === "outgoing";
        };
      case "high_value_tx": {
        const amounts = txs.map(tx => Math.abs(tx.amount || 0)).filter(a => a > 0);
        const mean = amounts.reduce((s, v) => s + v, 0) / (amounts.length || 1);
        const threshold = Math.max(mean * 5, 1000);
        return tx => Math.abs(tx.amount || 0) > threshold;
      }
      case "rapid_movement": {
        // Collect tx hashes that appear in rapid movement items
        const hashes = new Set();
        for (const item of anomalyItems) {
          if (item._txIds) item._txIds.forEach(id => hashes.add(id));
        }
        if (hashes.size) return tx => hashes.has(tx.hash || tx.id);
        // Fallback: deposits+withdrawals
        return tx => {
          const t = (tx.tx_type || "").toLowerCase();
          const c = (tx.category || "").toLowerCase();
          return t.includes("deposit") || c.includes("deposit") || t.includes("withdraw") || c.includes("withdraw");
        };
      }
      case "privacy_coins": {
        const privacyTokens = new Set(["XMR", "ZEC", "DASH", "SCRT"]);
        const mixerTags = ["mixer", "tornado", "privacy_coin"];
        return tx => {
          if (privacyTokens.has((tx.token || "").toUpperCase())) return true;
          return (tx.risk_tags || []).some(t => mixerTags.includes(t));
        };
      }
      case "burst_activity": {
        // Collect hashes from anomaly items
        const hashes = new Set();
        for (const item of anomalyItems) {
          if (item._txIds) item._txIds.forEach(id => hashes.add(id));
        }
        if (hashes.size) return tx => hashes.has(tx.hash || tx.id);
        return () => false;
      }
      case "new_token": {
        const knownTokens = new Set(["BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "MATIC", "AVAX", "LINK", "DAI", "BUSD", "EUR", "USD", "PLN", "GBP"]);
        return tx => tx.token && !knownTokens.has(tx.token.toUpperCase());
      }
      case "cross_chain": {
        const bridgeKeywords = ["bridge", "cross-chain", "swap", "wrap", "unwrap"];
        return tx => {
          const haystack = [tx.tx_type, tx.category, ...(tx.risk_tags || [])].join(" ").toLowerCase();
          return bridgeKeywords.some(kw => haystack.includes(kw));
        };
      }
      case "sanctioned_addr":
        return tx => (tx.risk_tags || []).includes("sanctioned");
      default:
        return () => false;
    }
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
              _txIds: [tx.hash || tx.id, tx2.hash || tx2.id],
            });
          }
          if (diffMin > 30) break;
        }
      }
      result.rapid_movement = items;
    }

    // 4. Privacy coins / mixer
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

    // 5. Burst activity (>10 tx in 1h window)
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
          const burstIds = [];
          for (let k = i; k < i + count && k < sorted.length; k++) {
            burstIds.push(sorted[k].hash || sorted[k].id);
          }
          items.push({
            html: `<b>${count} transakcji</b> w ciągu 1h od ${_esc((sorted[i].timestamp||"").slice(0,16).replace("T"," "))}`,
            severity: "warning",
            _txIds: burstIds,
          });
          i += count - 1; // skip ahead
        }
      }
      result.burst_activity = items;
    }

    // 6. New / unknown tokens
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

    // 7. Cross-chain / bridge
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

    // 8. Sanctioned addresses
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
        // Normalize each token using log-scale relative sizing for visual gradation
        // This preserves proportional visibility while showing "virtual" size differences
        const logMaxPerToken = maxPerToken.map(m => Math.log10(m + 1));
        const logGlobalMax = Math.max(...logMaxPerToken);

        datasets = data.datasets.map((ds, i) => {
          const tokenMax = maxPerToken[i] || 1;
          // Scale factor: log-based relative to global — gives visual gradation
          const logScale = logMaxPerToken[i] / (logGlobalMax || 1);
          // Map to 20–100% range so small tokens are still visible but proportionally smaller
          const ceilingPct = 20 + logScale * 80;
          return {
            label: ds.token + " (skala)",
            data: (ds.data || []).map(v => ((v || 0) / tokenMax) * ceilingPct),
            _rawData: ds.data,
            _tokenMax: tokenMax,
            _ceilingPct: ceilingPct,
            _token: ds.token,
            borderColor: PALETTE[i % PALETTE.length],
            backgroundColor: PALETTE[i % PALETTE.length] + "22",
            fill: false,
            tension: 0.3,
            pointRadius: labels.length > 50 ? 0 : 2,
            pointHoverRadius: 6,
            pointHitRadius: 10,
            borderWidth: Math.max(1, Math.min(3, logScale * 3)),
          };
        });
        scales = {
          x: { ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: _adaptiveTickCount(labels.length) } },
          y: {
            beginAtZero: true,
            max: 105,
            title: { display: true, text: "Skala relatywna (log)" },
            ticks: { callback: v => Math.round(v) + "%" },
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
        interaction: { mode: "nearest", intersect: true, axis: "xy" },
        plugins: {
          legend: { display: datasets.length > 1 },
          tooltip: {
            // Dynamic mode: hovering on x-axis area → show all tokens; hovering on a line → single token
            mode: datasets.length > 1 ? "nearest" : "index",
            intersect: datasets.length > 1,
            callbacks: {
              title: function(items) { return items[0] ? items[0].label : ""; },
              label: function(ctx) {
                const ds = ctx.dataset;
                // If normalized, show real value + scale info in tooltip
                if (ds._rawData) {
                  const realVal = ds._rawData[ctx.dataIndex];
                  const pctOfMax = ds._ceilingPct ? ((ctx.parsed.y / ds._ceilingPct) * 100).toFixed(0) : ctx.parsed.y.toFixed(0);
                  return ds._token + ": " + _fmtCrypto(realVal, "") + " (" + pctOfMax + "% maks., real. wartość)";
                }
                return (ds.label || "Saldo") + ": " + _fmtCrypto(ctx.parsed.y, "");
              },
            },
            // For multi-token charts: when user hovers near x-axis, show all
            filter: function(tooltipItem, data) { return true; },
          },
        },
        onHover: datasets.length > 1 ? function(evt, elements, chart) {
          // When hovering near x-axis (bottom 40px of chart area), switch to "index" mode to show all
          const chartArea = chart.chartArea;
          if (!chartArea) return;
          const yPos = evt.y || (evt.native && evt.native.offsetY) || 0;
          const nearAxis = yPos > (chartArea.bottom - 30);
          const ttOpts = chart.options.plugins.tooltip;
          if (nearAxis) {
            if (ttOpts.mode !== "index") {
              ttOpts.mode = "index";
              ttOpts.intersect = false;
              chart.update("none");
            }
          } else {
            if (ttOpts.mode !== "nearest") {
              ttOpts.mode = "nearest";
              ttOpts.intersect = true;
              chart.update("none");
            }
          }
        } : undefined,
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
  /*  Binance XLSX forensic cards                                       */
  /* ------------------------------------------------------------------ */

  function _renderAccountInfo(r) {
    const fr = r.forensic_report || {};
    const ai = fr.account_info || {};
    if (!ai.user_id && !ai.holder_name) { _hide("crypto_account_card"); return; }
    _show("crypto_account_card");

    let html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 24px;font-size:13px">';
    const fields = [
      ["User ID", ai.user_id], ["Imię i nazwisko", ai.holder_name],
      ["Email", ai.email], ["Telefon", ai.phone],
      ["Kraj", ai.country], ["Narodowość", ai.nationality],
      ["KYC Level", ai.kyc_level], ["Data rejestracji", ai.registration_date],
      ["Status konta", ai.account_status], ["Typ dokumentu", ai.id_type],
      ["Nr dokumentu", ai.id_number],
    ];
    for (const [label, val] of fields) {
      if (val) html += `<div><b>${_esc(label)}:</b> ${_esc(val)}</div>`;
    }
    html += '</div>';

    // User IDs across sheets
    const uids = fr.user_ids_in_file || {};
    if (Object.keys(uids).length) {
      html += '<div style="margin-top:12px"><b>User IDs w pliku:</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-top:4px"><thead><tr><th>Arkusz</th><th>User ID</th></tr></thead><tbody>';
      for (const [sheet, ids] of Object.entries(uids)) {
        html += `<tr><td>${_esc(sheet)}</td><td style="font-family:monospace">${_esc(ids.join(", "))}</td></tr>`;
      }
      html += '</tbody></table>';
    }
    _html("crypto_account_body", html);
  }

  function _renderCounterparties(r) {
    const bs = r.binance_summary || {};
    const cps = bs.counterparties || {};
    const keys = Object.keys(cps);
    if (!keys.length) { _hide("crypto_counterparties_card"); return; }
    _show("crypto_counterparties_card");

    let html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>User ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th><th>Źródło</th><th>Okres</th></tr></thead><tbody>';
    const sorted = keys.sort((a, b) => cps[b].tx_count - cps[a].tx_count);
    for (const k of sorted.slice(0, 50)) {
      const c = cps[k];
      const period = ((c.first_seen || "").slice(0, 10)) + " — " + ((c.last_seen || "").slice(0, 10));
      html += `<tr>
        <td style="font-family:monospace;font-weight:600">${_esc(k)}</td>
        <td>${c.tx_count}</td>
        <td style="text-align:right">${(c.total_in || 0).toFixed(4)}</td>
        <td style="text-align:right">${(c.total_out || 0).toFixed(4)}</td>
        <td>${_esc((c.tokens || []).join(", "))}</td>
        <td>${_esc((c.sources || []).join(", "))}</td>
        <td style="font-size:11px">${_esc(period)}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    if (keys.length > 50) html += `<div class="small muted" style="margin-top:4px">Pokazano 50 z ${keys.length}</div>`;

    // Internal vs external stats
    html += '<div style="margin-top:12px;display:flex;gap:24px;font-size:13px">';
    html += `<span>🔄 Transfery wewnętrzne: <b>${bs.internal_transfer_count || 0}</b></span>`;
    html += `<span>📥 Depozyty zewnętrzne: <b>${bs.external_deposit_count || 0}</b></span>`;
    html += `<span>📤 Wypłaty zewnętrzne: <b>${bs.external_withdrawal_count || 0}</b></span>`;
    html += '</div>';

    _html("crypto_counterparties_body", html);
  }

  function _renderPayC2C(r) {
    const fr = r.forensic_report || {};
    const pcs = fr.binance_pay_counterparties || {};
    const keys = Object.keys(pcs);
    if (!keys.length) { _hide("crypto_pay_c2c_card"); return; }
    _show("crypto_pay_c2c_card");

    let html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>Binance ID</th><th>Wallet ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th><th>Okres</th></tr></thead><tbody>';
    const sorted = keys.sort((a, b) => pcs[b].count - pcs[a].count);
    for (const k of sorted.slice(0, 50)) {
      const c = pcs[k];
      const period = ((c.first || "").slice(0, 10)) + " — " + ((c.last || "").slice(0, 10));
      html += `<tr>
        <td style="font-family:monospace;font-weight:600">${_esc(k)}</td>
        <td style="font-family:monospace;font-size:11px">${_esc(c.wallet_id || "—")}</td>
        <td>${c.count}</td>
        <td style="text-align:right">${(c["in"] || 0).toFixed(4)}</td>
        <td style="text-align:right">${(c["out"] || 0).toFixed(4)}</td>
        <td>${_esc((c.tokens || []).join(", "))}</td>
        <td style="font-size:11px">${_esc(period)}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    _html("crypto_pay_c2c_body", html);
  }

  function _renderExtAddresses(r) {
    const fr = r.forensic_report || {};
    const src = fr.external_source_addresses || [];
    const dst = fr.external_dest_addresses || [];
    if (!src.length && !dst.length) { _hide("crypto_ext_addresses_card"); return; }
    _show("crypto_ext_addresses_card");

    let html = '';
    if (src.length) {
      html += '<div style="margin-bottom:8px"><b>📥 Adresy źródłowe depozytów (zewnętrzne):</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:16px"><thead><tr>' +
        '<th>Adres</th><th>TX</th><th>Suma</th><th>Tokeny</th><th>Sieci</th></tr></thead><tbody>';
      for (const a of src.slice(0, 30)) {
        html += `<tr>
          <td style="font-family:monospace;font-size:11px" title="${_esc(a.address)}">${_esc(_shorten(a.address))}</td>
          <td>${a.count}</td>
          <td style="text-align:right">${(a.total || 0).toFixed(4)}</td>
          <td>${_esc((a.tokens || []).join(", "))}</td>
          <td>${_esc((a.networks || []).join(", "))}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      if (src.length > 30) html += `<div class="small muted">Pokazano 30 z ${src.length}</div>`;
    }
    if (dst.length) {
      html += '<div style="margin-bottom:8px"><b>📤 Adresy docelowe wypłat (zewnętrzne):</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
        '<th>Adres</th><th>TX</th><th>Suma</th><th>Tokeny</th><th>Sieci</th></tr></thead><tbody>';
      for (const a of dst.slice(0, 30)) {
        html += `<tr>
          <td style="font-family:monospace;font-size:11px" title="${_esc(a.address)}">${_esc(_shorten(a.address))}</td>
          <td>${a.count}</td>
          <td style="text-align:right">${(a.total || 0).toFixed(4)}</td>
          <td>${_esc((a.tokens || []).join(", "))}</td>
          <td>${_esc((a.networks || []).join(", "))}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      if (dst.length > 30) html += `<div class="small muted">Pokazano 30 z ${dst.length}</div>`;
    }
    _html("crypto_ext_addresses_body", html);
  }

  function _renderPassThrough(r) {
    const fr = r.forensic_report || {};
    const pts = fr.pass_through_detection || [];
    const ptCount = fr.pass_through_count || pts.length;
    if (!pts.length) { _hide("crypto_passthrough_card"); return; }
    _show("crypto_passthrough_card");

    let html = `<div style="margin-bottom:8px;font-size:13px">⚠️ Wykryto <b>${ptCount}</b> potencjalnych przepływów tranzytowych (depozyt → wypłata w ciągu 24h)</div>`;
    html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr>' +
      '<th>Depozyt (czas)</th><th>Kwota</th><th>Token</th><th>Od</th>' +
      '<th>Wypłata (czas)</th><th>Kwota</th><th>Token</th><th>Do</th><th>Opóźn.</th></tr></thead><tbody>';
    for (const pt of pts.slice(0, 30)) {
      html += `<tr>
        <td>${_esc((pt.deposit_time || "").slice(0, 16).replace("T", " "))}</td>
        <td style="text-align:right">${(pt.deposit_amount || 0).toFixed(4)}</td>
        <td>${_esc(pt.deposit_token || "")}</td>
        <td style="font-size:10px">${_esc(pt.deposit_from || "—")}</td>
        <td>${_esc((pt.withdrawal_time || "").slice(0, 16).replace("T", " "))}</td>
        <td style="text-align:right">${(pt.withdrawal_amount || 0).toFixed(4)}</td>
        <td>${_esc(pt.withdrawal_token || "")}</td>
        <td style="font-size:10px">${_esc(pt.withdrawal_to || "—")}</td>
        <td>${pt.delay_hours}h</td>
      </tr>`;
    }
    html += '</tbody></table>';
    if (pts.length > 30) html += `<div class="small muted" style="margin-top:4px">Pokazano 30 z ${pts.length}</div>`;
    _html("crypto_passthrough_body", html);
  }

  function _renderPrivacyCoins(r) {
    const fr = r.forensic_report || {};
    const priv = fr.privacy_coin_usage || {};
    const coins = Object.keys(priv);
    if (!coins.length) { _hide("crypto_privacy_card"); return; }
    _show("crypto_privacy_card");

    let html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>Moneta</th><th>Depozyty</th><th>Kwota dep.</th><th>Wypłaty</th><th>Kwota wyp.</th>' +
      '<th>Transakcje</th><th>Kwota</th><th>Unik. adresy źr.</th></tr></thead><tbody>';
    for (const coin of coins) {
      const p = priv[coin];
      html += `<tr>
        <td style="font-weight:600;color:#f59e0b">${_esc(coin)}</td>
        <td>${p.deposits || 0}</td>
        <td style="text-align:right">${(p.deposit_amount || 0).toFixed(4)}</td>
        <td>${p.withdrawals || 0}</td>
        <td style="text-align:right">${(p.withdrawal_amount || 0).toFixed(4)}</td>
        <td>${p.trades || 0}</td>
        <td style="text-align:right">${(p.trade_amount || 0).toFixed(4)}</td>
        <td style="font-weight:600;color:${(p.unique_source_addresses || 0) > 10 ? '#ef4444' : '#22c55e'}">${p.unique_source_addresses || 0}</td>
      </tr>`;
    }
    html += '</tbody></table>';

    // Mining patterns
    const mining = fr.mining_patterns || [];
    if (mining.length) {
      html += `<div style="margin-top:16px"><b>⛏️ Wzorce górnicze (powtarzające się małe depozyty z tego samego adresu):</b></div>`;
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-top:4px"><thead><tr>' +
        '<th>Adres</th><th>Token</th><th>TX</th><th>Suma</th><th>Średnia</th></tr></thead><tbody>';
      for (const m of mining.slice(0, 20)) {
        html += `<tr>
          <td style="font-family:monospace;font-size:11px" title="${_esc(m.address)}">${_esc(_shorten(m.address))}</td>
          <td>${_esc(m.token)}</td>
          <td>${m.count}</td>
          <td style="text-align:right">${(m.total || 0).toFixed(8)}</td>
          <td style="text-align:right">${(m.avg || 0).toFixed(8)}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    _html("crypto_privacy_body", html);
  }

  function _renderAccessLogs(r) {
    const fr = r.forensic_report || {};
    const al = fr.access_log_analysis || {};
    const devs = fr.device_fingerprints || [];
    if (!al.total_entries && !devs.length) { _hide("crypto_access_card"); return; }
    _show("crypto_access_card");

    let html = '';
    // Summary
    if (al.total_entries) {
      html += '<div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13px;margin-bottom:12px">';
      html += `<span>📊 Łącznie wpisów: <b>${al.total_entries}</b></span>`;
      html += `<span>🌐 Unikalne IP: <b>${al.unique_ips || 0}</b></span>`;
      if (al.first_login) html += `<span>📅 Pierwszy login: <b>${_esc(al.first_login.slice(0, 10))}</b></span>`;
      if (al.last_login) html += `<span>📅 Ostatni login: <b>${_esc(al.last_login.slice(0, 10))}</b></span>`;
      if (al.foreign_login_count) html += `<span style="color:#ef4444">🚨 Zagraniczne loginy: <b>${al.foreign_login_count}</b></span>`;
      html += '</div>';
    }

    // Geolocations
    const geos = al.geolocations || {};
    const geoKeys = Object.keys(geos);
    if (geoKeys.length) {
      html += '<div style="margin-bottom:8px"><b>📍 Geolokalizacje:</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px"><thead><tr><th>Lokalizacja</th><th>Loginy</th></tr></thead><tbody>';
      for (const g of geoKeys.slice(0, 15)) {
        html += `<tr><td>${_esc(g)}</td><td>${geos[g]}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    // Top IPs
    const ips = al.top_ips || {};
    const ipKeys = Object.keys(ips);
    if (ipKeys.length) {
      html += '<div style="margin-bottom:8px"><b>🌐 Najczęstsze adresy IP:</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px"><thead><tr><th>IP</th><th>Loginy</th></tr></thead><tbody>';
      for (const ip of ipKeys.slice(0, 10)) {
        html += `<tr><td style="font-family:monospace">${_esc(ip)}</td><td>${ips[ip]}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    // Devices
    if (devs.length) {
      html += '<div style="margin-bottom:8px"><b>📱 Zatwierdzone urządzenia:</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px"><thead><tr>' +
        '<th>Urządzenie</th><th>Klient</th><th>IP</th><th>Geo</th><th>Ostatnie użycie</th><th>Status</th></tr></thead><tbody>';
      for (const d of devs) {
        html += `<tr>
          <td>${_esc(d.device || "")}</td>
          <td style="font-size:11px">${_esc(d.client || "")}</td>
          <td style="font-family:monospace">${_esc(d.ip || "")}</td>
          <td>${_esc(d.geo || "")}</td>
          <td>${_esc((d.last_used || "").slice(0, 10))}</td>
          <td>${_esc(d.status || "")}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    // Multi-IP days
    const mid = al.multi_ip_days || [];
    if (mid.length) {
      html += '<div style="margin-bottom:8px"><b>⚠️ Dni z wieloma IP (podejrzane jednoczesne użycie):</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px"><thead><tr><th>Data</th><th>Unikalne IP</th></tr></thead><tbody>';
      for (const d of mid.slice(0, 10)) {
        html += `<tr><td>${_esc(d.date)}</td><td style="font-weight:600;color:#f59e0b">${d.unique_ips}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    // Foreign logins
    const fl = al.foreign_login_timeline || [];
    if (fl.length) {
      html += `<div style="margin-top:12px;margin-bottom:8px"><b>🚨 Zagraniczne loginy (poza ${_esc(al.primary_country || "?")}):</b></div>`;
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr>' +
        '<th>Czas</th><th>Geolokalizacja</th><th>IP</th><th>Klient</th><th>Operacja</th></tr></thead><tbody>';
      for (const f of fl.slice(0, 30)) {
        html += `<tr>
          <td>${_esc((f.timestamp || "").replace("T", " "))}</td>
          <td>${_esc(f.geo || "")}</td>
          <td style="font-family:monospace">${_esc(f.ip || "")}</td>
          <td style="font-size:10px">${_esc(f.client || "")}</td>
          <td>${_esc(f.operation || "")}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      if (fl.length > 30) html += `<div class="small muted" style="margin-top:4px">Pokazano 30 z ${fl.length}</div>`;
    }

    _html("crypto_access_body", html);
  }

  function _renderCardTimeline(r) {
    const fr = r.forensic_report || {};
    const cards = fr.card_info || [];
    const timeline = fr.card_geo_timeline || [];
    const bs = r.binance_summary || {};
    const merchants = bs.card_merchants || {};
    const spending = bs.card_spending || {};

    if (!cards.length && !timeline.length && !Object.keys(spending).length) {
      _hide("crypto_card_timeline_card"); return;
    }
    _show("crypto_card_timeline_card");

    let html = '';

    // Card info
    if (cards.length) {
      html += '<div style="margin-bottom:8px"><b>💳 Karty Binance:</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px"><thead><tr>' +
        '<th>Numer karty</th><th>Typ</th><th>Status</th><th>Data utworzenia</th></tr></thead><tbody>';
      for (const c of cards) {
        html += `<tr>
          <td style="font-family:monospace">${_esc(c.card_number || "")}</td>
          <td>${_esc(c.card_type || "")}</td>
          <td>${_esc(c.status || "")}</td>
          <td>${_esc((c.created || "").slice(0, 10))}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    // Spending totals
    const spKeys = Object.keys(spending);
    if (spKeys.length) {
      html += '<div style="display:flex;gap:24px;font-size:13px;margin-bottom:12px">';
      for (const k of spKeys) {
        html += `<span>Wydatki ${_esc(k)}: <b>${spending[k].toFixed(2)}</b></span>`;
      }
      html += '</div>';
    }

    // Top merchants
    const mKeys = Object.keys(merchants);
    if (mKeys.length) {
      html += '<div style="margin-bottom:8px"><b>🏪 Merchants (TOP wydatki):</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:12px"><thead><tr><th>Merchant</th><th>Kwota</th></tr></thead><tbody>';
      const sortedM = mKeys.sort((a, b) => merchants[b] - merchants[a]);
      for (const m of sortedM.slice(0, 15)) {
        html += `<tr><td>${_esc(m)}</td><td style="text-align:right">${merchants[m].toFixed(2)}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    // Transaction timeline
    if (timeline.length) {
      html += '<div style="margin-bottom:8px"><b>📍 Oś czasu transakcji kartą (geolokalizacja):</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr>' +
        '<th>Data/czas</th><th>Merchant</th><th>Kwota</th><th>Waluta</th><th>Status</th></tr></thead><tbody>';
      for (const t of timeline.slice(0, 50)) {
        html += `<tr>
          <td>${_esc((t.timestamp || "").replace("T", " "))}</td>
          <td>${_esc(t.merchant || "")}</td>
          <td style="text-align:right">${(t.amount || 0).toFixed(2)}</td>
          <td>${_esc(t.currency || "")}</td>
          <td>${_esc(t.status || "")}</td>
        </tr>`;
      }
      html += '</tbody></table>';
      if (timeline.length > 50) html += `<div class="small muted" style="margin-top:4px">Pokazano 50 z ${timeline.length}</div>`;
    }

    _html("crypto_card_timeline_body", html);
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

      // Initialize analyst notes panel
      if (window.AnalystNotesManager) {
        const pid = _getProjectId();
        _cryptoNotesMgr = new AnalystNotesManager({
          mode: "crypto",
          projectId: pid,
          onNavigate: function(ref) {
            if (!ref) return;
            if (ref.type === "crypto_anomaly" && ref.anomaly_type) {
              // Scroll to anomaly card
              const card = document.querySelector(`.gsm-anomaly-card[data-anomaly-type="${ref.anomaly_type}"]`);
              if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
            } else if (ref.type === "crypto_transaction" && ref.txId) {
              // Scroll to transaction row
              const row = document.querySelector(`tr[data-txid="${ref.txId}"]`);
              if (row) {
                row.scrollIntoView({ behavior: "smooth", block: "center" });
                row.style.transition = "box-shadow .2s";
                row.style.boxShadow = "inset 0 0 0 2px var(--brand-blue,#2563eb)";
                setTimeout(() => { row.style.boxShadow = ""; }, 1500);
              }
            }
          },
          getContext: function() {
            // Return context of currently selected/hovered element
            return null; // basic — Ctrl+M opens empty modal
          },
          onNoteChange: function() {
            // Re-render anomaly note markers
            if (_lastResult) {
              const isEx = _lastResult.source_type === "exchange";
              _renderAnomalies(_lastResult, isEx);
            }
          },
        });
        window._cryptoNotesMgr = _cryptoNotesMgr;
        await _cryptoNotesMgr.init();
      }

      // Auto-load saved analysis
      try {
        await _loadFromProject();
      } catch (e) {
        console.warn("[Crypto] Auto-load failed:", e);
      }
    },
  };
})();
