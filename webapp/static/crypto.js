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

  async function _ensureHtml2Canvas() {
    if (window.html2canvas) return;
    await _loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
  }

  /* ------------------------------------------------------------------ */
  /*  Card screenshot with watermark (mirrors GSM implementation)       */
  /* ------------------------------------------------------------------ */

  const _CRYPTO_SCREENSHOT_HIDE = ".crypto-card-screenshot-btn, .crypto-screenshot-hide, .crypto-chart-zoom-bar, select.input";

  /**
   * Draw a watermark footer below the source canvas.
   * "AISTATEweb" in brand gradient + timestamp.
   */
  function _cryptoDrawWatermark(srcCanvas, extraParts) {
    const w = srcCanvas.width;
    const barH = Math.round(Math.max(32, w * 0.032));
    const fontSize = Math.round(barH * 0.44);
    const totalH = srcCanvas.height + barH;

    const out = document.createElement("canvas");
    out.width = w;
    out.height = totalH;
    const ctx = out.getContext("2d");

    // Draw source content
    ctx.drawImage(srcCanvas, 0, 0);

    // White background for watermark row
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, srcCanvas.height, w, barH);

    // Subtle separator
    ctx.fillStyle = "rgba(0,0,0,0.08)";
    ctx.fillRect(0, srcCanvas.height, w, 1);

    ctx.textBaseline = "middle";
    const cy = srcCanvas.height + barH / 2;
    const pad = Math.round(barH * 0.45);

    // "AI" in navy, "STATE" in brand-blue, "web" in sky
    const parts = [
      { text: "AI", color: "#0d1350" },
      { text: "STATE", color: "#2946b7" },
      { text: "web", color: "#1096f4" },
    ];
    let lx = pad;
    ctx.font = `bold ${fontSize}px system-ui, -apple-system, sans-serif`;
    for (const p of parts) {
      ctx.fillStyle = p.color;
      ctx.fillText(p.text, lx, cy);
      lx += ctx.measureText(p.text).width;
    }

    const now = new Date();
    const dateStr = now.toLocaleString("pl-PL", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    const grayColor = "rgba(0,0,0,0.38)";
    ctx.font = `${fontSize}px system-ui, -apple-system, sans-serif`;
    ctx.fillStyle = grayColor;

    if (extraParts && extraParts.length) {
      for (const part of extraParts) {
        ctx.fillText(`  |  ${part}`, lx, cy);
        lx += ctx.measureText(`  |  ${part}`).width;
      }
    }

    const dateW = ctx.measureText(dateStr).width;
    ctx.fillText(dateStr, w - pad - dateW, cy);

    return out;
  }

  async function _takeCryptoCardScreenshot(btn) {
    const targetSel = btn.dataset.target;
    const name = btn.dataset.name || "screenshot";
    const card = document.querySelector(targetSel);
    if (!card) return;
    btn.disabled = true;

    try {
      await _ensureHtml2Canvas();

      const cardCanvas = await window.html2canvas(card, {
        useCORS: true,
        allowTaint: true,
        backgroundColor: "#ffffff",
        scale: 2,
        logging: false,
        onclone: (_doc, clonedCard) => {
          // Hide buttons/selects in clone
          clonedCard.querySelectorAll(_CRYPTO_SCREENSHOT_HIDE).forEach(el => {
            el.style.display = "none";
          });
          // Force light background on graph container in clone
          const graphEl = clonedCard.querySelector("#crypto_graph_container");
          if (graphEl) graphEl.style.background = "#ffffff";
        },
      });

      const extra = ["Crypto Analysis"];
      const out = _cryptoDrawWatermark(cardCanvas, extra);

      out.toBlob((blob) => {
        if (!blob) return;
        const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
        const filename = `Crypto_${name}_${ts}.png`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, "image/png");
    } catch (e) {
      console.error("[Crypto] Screenshot failed:", e);
    } finally {
      btn.disabled = false;
    }
  }

  function _bindCryptoScreenshotButtons() {
    document.querySelectorAll(".crypto-card-screenshot-btn").forEach(btn => {
      if (btn._screenshotBound) return;
      btn._screenshotBound = true;
      btn.onclick = (e) => {
        e.stopPropagation();
        _takeCryptoCardScreenshot(btn);
      };
    });
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

    // Account owner — right after summary (Binance XLSX or any source with account_info)
    const isBinance = (r.source === "binance_xlsx");
    if (isBinance || (r.forensic_report && r.forensic_report.account_info)) {
      _renderAccountInfo(r);
    } else {
      _hide("crypto_account_card");
    }

    _renderBehaviorProfile(r);
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

    // Phone numbers (all sources)
    _renderPhones(r);

    // Binance XLSX forensic cards
    if (isBinance) {
      _renderCounterparties(r);
      _renderPayC2C(r);
      _renderExtAddresses(r);
      _renderPassThrough(r);
      _renderPrivacyCoins(r);
      _renderAccessLogs(r);
      _renderCardTimeline(r);
      // New forensic cards (v3.7.1)
      _renderTemporal(r);
      _renderConversionChains(r);
      _renderStructuring(r);
      _renderWashTrading(r);
      _renderFiatRamp(r);
      _renderP2PAnalysis(r);
      _renderVelocity(r);
      _renderFeeAnalysis(r);
      _renderNetworkAnalysis(r);
      _renderExtSecurity(r);
    } else {
      _hide("crypto_counterparties_card");
      _hide("crypto_pay_c2c_card");
      _hide("crypto_ext_addresses_card");
      _hide("crypto_passthrough_card");
      _hide("crypto_privacy_card");
      _hide("crypto_access_card");
      _hide("crypto_card_timeline_card");
      _hide("crypto_temporal_card");
      _hide("crypto_conversion_card");
      _hide("crypto_structuring_card");
      _hide("crypto_wash_card");
      _hide("crypto_fiat_ramp_card");
      _hide("crypto_p2p_card");
      _hide("crypto_velocity_card");
      _hide("crypto_fee_card");
      _hide("crypto_network_card");
      _hide("crypto_ext_security_card");
    }

    _renderReviewTable(r, isExchange);
    _renderAnomalies(r, isExchange);

    // Ensure Chart.js is loaded before rendering any charts
    try { await _ensureChartJS(); } catch (e) { console.warn("[Crypto] Chart.js load failed:", e); }
    _renderCharts(r, isExchange);
    _renderSmallCharts(r, isExchange);

    _renderGraph(r);
    if (!isExchange) _renderWallets(r);

    // Bind screenshot buttons after all cards are rendered
    _bindCryptoScreenshotButtons();
  }

  /* -- Summary (light fields like AML/GSM) ----------------------------- */

  function _renderSummary(r, isExchange) {
    // Brief file/period/stats summary — personal data moved to Account Owner card
    const infoGrid = document.getElementById("crypto_info_grid");
    if (infoGrid) {
      let html = "";
      if (isExchange) {
        const em = r.exchange_meta || {};
        const meta = r.metadata || {};
        const ai = ((r.forensic_report || {}).account_info) || {};
        const holder = ai.holder_name || meta.account_holder;
        if (holder) html += `<div class="crypto-info-row"><b>Właściciel:</b> ${_esc(holder)}</div>`;
        const street = ai.physical_address || meta.street;
        const city = ai.city || meta.city;
        const zip = ai.zip_code || meta.postal_code;
        const country = ai.country || meta.country;
        const addrParts = [street, zip, city, country].filter(Boolean);
        if (addrParts.length) html += `<div class="crypto-info-row"><b>Adres:</b> ${_esc(addrParts.join(", "))}</div>`;
        if (em.exchange_name || r.source) html += `<div class="crypto-info-row"><b>Giełda:</b> ${_esc(em.exchange_name || r.source)}</div>`;
        if (r.filename) html += `<div class="crypto-info-row"><b>Plik:</b> ${_esc(r.filename)}</div>`;
        const dateFrom = (r.date_from || "").slice(0, 10);
        const dateTo = (r.date_to || "").slice(0, 10);
        if (dateFrom || dateTo) html += `<div class="crypto-info-row"><b>Okres:</b> ${_esc(dateFrom)} \u2014 ${_esc(dateTo)}</div>`;
        if (r.tx_count) html += `<div class="crypto-info-row"><b>Transakcje:</b> ${r.tx_count}</div>`;
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
        if (r.tx_count) html += `<div class="crypto-info-row"><b>Transakcje:</b> ${r.tx_count}</div>`;
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
    const card = document.getElementById("crypto_token_breakdown_card");
    if (!card) return;
    _show("crypto_token_breakdown_card");

    // Build token portfolio table with descriptions from token_classification
    const tokens = r.tokens || {};
    const tc = r.token_classification || {};
    const syms = Object.keys(tokens);
    if (!syms.length) return;

    // Sort by tx count desc, then alphabetically
    syms.sort((a, b) => (tokens[b].count || 0) - (tokens[a].count || 0) || a.localeCompare(b));

    const alertColors = {
      "CRITICAL": "#dc2626", "HIGH": "#f97316", "MEDIUM": "#eab308", "NORMAL": "#22c55e"
    };

    let html = '<div class="h2">Portfel tokenów</div>';
    html += '<table class="data-table" style="width:100%;font-size:12px;margin-bottom:16px"><thead><tr>';
    html += '<th>Symbol</th><th>Nazwa</th><th>Rank</th><th>Kategoria</th>';
    html += '<th style="text-align:right">TX</th><th style="text-align:right">Otrzymano</th><th style="text-align:right">Wysłano</th>';
    html += '<th>Alert</th><th>Opis</th>';
    html += '</tr></thead><tbody>';

    for (const sym of syms) {
      const t = tokens[sym] || {};
      const info = tc[sym] || {};
      const name = info.name || "—";
      const rank = info.rank ? `#${info.rank}` : "—";
      const cat = info.category || "—";
      const alert = info.alert_level || "NORMAL";
      const ac = alertColors[alert] || "#94a3b8";
      const desc = info.description || (info.known === false ? "Token spoza bazy TOP 200" : "");
      const riskNote = info.risk_note || "";
      const tooltip = riskNote ? ` title="${_esc(riskNote)}"` : "";

      html += `<tr>`;
      html += `<td><b>${_esc(sym)}</b></td>`;
      html += `<td>${_esc(name)}</td>`;
      html += `<td style="text-align:center">${_esc(rank)}</td>`;
      html += `<td><span style="font-size:11px;padding:1px 6px;border-radius:3px;background:rgba(100,116,139,.1)">${_esc(cat)}</span></td>`;
      html += `<td style="text-align:right">${t.count || 0}</td>`;
      html += `<td style="text-align:right">${(t.received || 0).toFixed(4)}</td>`;
      html += `<td style="text-align:right">${(t.sent || 0).toFixed(4)}</td>`;
      html += `<td${tooltip}><span style="color:${ac};font-weight:600;font-size:11px">${_esc(alert)}</span></td>`;
      html += `<td style="font-size:11px;color:var(--text-muted,#64748b);max-width:300px">${_esc(desc)}</td>`;
      html += `</tr>`;
    }

    html += '</tbody></table>';
    card.innerHTML = html;
    // Actual chart is rendered in _renderCharts
  }

  /* -- User behavior profile ----------------------------------------- */

  function _renderBehaviorProfile(r) {
    const bp = r.behavior_profile;
    if (!bp || !bp.profiles || !bp.profiles.length) { _hide("crypto_behavior_card"); return; }
    _show("crypto_behavior_card");

    const profiles = bp.profiles;
    const primary = profiles[0];

    let html = '';

    // Primary profile — large display
    const confColor = primary.score >= 70 ? "#22c55e" : primary.score >= 40 ? "#eab308" : "#94a3b8";
    html += `<div style="display:flex;align-items:center;gap:16px;margin-bottom:16px;padding:12px 16px;background:rgba(37,99,235,.04);border-radius:10px;border:1px solid rgba(37,99,235,.12)">
      <div style="font-size:40px;line-height:1">${_esc(primary.icon)}</div>
      <div style="flex:1">
        <div style="font-size:20px;font-weight:700">${_esc(primary.label)}</div>
        <div class="small muted" style="margin-top:2px">${_esc(primary.desc)}</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:28px;font-weight:700;color:${confColor}">${primary.score}<span style="font-size:14px;color:var(--text-muted)">%</span></div>
        <div class="small muted">pewność</div>
      </div>
    </div>`;

    // Primary reasons
    if (primary.reasons && primary.reasons.length) {
      html += '<div style="margin-bottom:16px"><b>Dlaczego ten profil:</b></div>';
      html += '<ul style="margin:0 0 12px;padding-left:20px;font-size:13px">';
      for (const reason of primary.reasons) {
        html += `<li style="margin-bottom:3px">${_esc(reason)}</li>`;
      }
      html += '</ul>';
    }

    // Alternative profiles (score >= 20)
    const alts = profiles.slice(1).filter(p => p.score >= 20);
    if (alts.length) {
      html += '<div style="margin-bottom:8px"><b>Profile alternatywne:</b></div>';
      html += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">';
      for (const alt of alts) {
        const altColor = alt.score >= 50 ? "#f59e0b" : "#94a3b8";
        html += `<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;cursor:pointer;transition:background .15s" class="crypto-alt-profile" data-profile="${_esc(alt.type)}">
          <span style="font-size:20px">${_esc(alt.icon)}</span>
          <div>
            <div style="font-weight:600">${_esc(alt.label)} <span style="color:${altColor};font-weight:700">${alt.score}%</span></div>
            <div class="small muted">${_esc(alt.desc)}</div>
          </div>
        </div>`;
      }
      html += '</div>';
    }

    // Expandable detail for alternative profiles
    html += '<div id="crypto_behavior_alt_detail" style="display:none;margin-bottom:12px;padding:10px;border:1px solid var(--border);border-radius:8px;font-size:13px"></div>';

    // Key metrics
    const met = bp.metrics || {};
    const metricItems = [];
    if (met.tx_per_day != null) metricItems.push(["TX/dzień", met.tx_per_day.toFixed(2)]);
    if (met.span_days != null) metricItems.push(["Okres (dni)", met.span_days]);
    if (met.active_days != null) metricItems.push(["Aktywne dni", met.active_days]);
    if (met.unique_tokens != null) metricItems.push(["Unikalne tokeny", met.unique_tokens]);
    if (met.swap_count != null) metricItems.push(["Transakcje handlowe", met.swap_count]);
    if (met.total_volume != null) metricItems.push(["Wolumen", met.total_volume.toFixed(2)]);
    if (met.avg_holding_hours != null) metricItems.push(["Śr. czas trzymania", (met.avg_holding_hours / 24).toFixed(1) + " dni"]);
    if (met.uses_leverage) metricItems.push(["Dźwignia", "Tak"]);
    if (met.large_tx_count) metricItems.push(["Duże TX", met.large_tx_count]);
    if (met.rapid_sequence_count) metricItems.push(["Szybkie sekwencje", met.rapid_sequence_count]);
    if (met.privacy_coin_tx_count) metricItems.push(["Privacy coins TX", met.privacy_coin_tx_count]);
    if (met.internal_transfer_count) metricItems.push(["Transfery wewnętrzne", met.internal_transfer_count]);

    if (metricItems.length) {
      html += '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--text-muted)">📐 Metryki bazowe</summary>';
      html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:6px 16px;margin-top:8px;font-size:12px">';
      for (const [label, val] of metricItems) {
        html += `<div><span class="muted">${_esc(label)}:</span> <b>${_esc(String(val))}</b></div>`;
      }
      html += '</div></details>';
    }

    _html("crypto_behavior_body", html);

    // Click handler for alternative profiles — show reasons
    document.querySelectorAll(".crypto-alt-profile").forEach(el => {
      el.addEventListener("click", function() {
        const type = this.dataset.profile;
        const prof = profiles.find(p => p.type === type);
        if (!prof) return;
        const detail = document.getElementById("crypto_behavior_alt_detail");
        if (!detail) return;
        if (detail.style.display !== "none" && detail.dataset.currentType === type) {
          detail.style.display = "none";
          return;
        }
        detail.dataset.currentType = type;
        let dHtml = `<div style="margin-bottom:6px"><b>${_esc(prof.icon)} ${_esc(prof.label)}</b> — dlaczego pasuje (${prof.score}%):</div>`;
        if (prof.reasons && prof.reasons.length) {
          dHtml += '<ul style="margin:0;padding-left:18px">';
          for (const r of prof.reasons) {
            dHtml += `<li>${_esc(r)}</li>`;
          }
          dHtml += '</ul>';
        } else {
          dHtml += '<div class="muted">Brak szczegółowych wskaźników.</div>';
        }
        detail.innerHTML = dHtml;
        detail.style.display = "";
      });
      el.addEventListener("mouseenter", function() { this.style.background = "rgba(37,99,235,.05)"; });
      el.addEventListener("mouseleave", function() { this.style.background = ""; });
    });
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
        const rawVals = tx.raw ? Object.values(tx.raw).map(v => String(v)) : [];
        const haystack = [tx.from, tx.to, tx.hash, tx.token, tx.tx_type, tx.category, tx.counterparty, ...(tx.risk_tags || []), ...rawVals].join(" ").toLowerCase();
        if (!haystack.includes(searchLow)) return false;
      }

      return true;
    });

    _text("crypto_rv_tx_count", `${filtered.length} z ${txs.length} transakcji`);

    const wrap = document.getElementById("crypto_rv_table_wrap");
    if (!wrap) return;

    const show = filtered;
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

    wrap.innerHTML = html;
    wrap.style.maxHeight = "700px";
    wrap.style.overflowY = "auto";

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
        // Same fiat-aware logic as detection
        const _fv = tx => { const v = parseFloat((tx.raw || {}).fiat_value); return (!isNaN(v) && v > 0) ? v : 0; };
        const fiatVals = txs.map(_fv).filter(v => v > 0);
        const hasFiat = fiatVals.length > txs.length * 0.3;
        if (hasFiat) {
          const fiatMean = fiatVals.reduce((s, v) => s + v, 0) / (fiatVals.length || 1);
          const fiatThreshold = Math.max(fiatMean * 3, 2000);
          return tx => _fv(tx) > fiatThreshold;
        }
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
        // Use backend token_classification — same logic as anomaly detection
        const tc = (_lastResult || {}).token_classification || {};
        const tcKeys = Object.keys(tc);
        let knownTokens;
        if (tcKeys.length) {
          knownTokens = new Set(tcKeys.filter(s => tc[s] && tc[s].known).map(s => s.toUpperCase()));
        } else {
          knownTokens = new Set(["BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "MATIC", "AVAX", "LINK", "DAI", "BUSD", "EUR", "USD", "PLN", "GBP"]);
        }
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

    // 2. High value transactions — use fiat value when available
    {
      // Extract fiat value from raw data; fall back to token amount
      const _fiatVal = (tx) => {
        const raw = tx.raw || {};
        const fv = parseFloat(raw.fiat_value);
        if (!isNaN(fv) && fv > 0) return fv;
        return 0; // no fiat data
      };
      // Collect fiat values where available
      const fiatValues = txs.map(_fiatVal).filter(v => v > 0);
      const hasFiat = fiatValues.length > txs.length * 0.3; // at least 30% have fiat

      let highValueTxs;
      if (hasFiat) {
        // Fiat-based threshold (e.g. PLN/USD) — use mean * 3 with min 2000
        const fiatMean = fiatValues.reduce((s, v) => s + v, 0) / (fiatValues.length || 1);
        const fiatThreshold = Math.max(fiatMean * 3, 2000);
        highValueTxs = txs.filter(tx => _fiatVal(tx) > fiatThreshold);
      } else {
        // Fallback: token amount based (old behavior)
        const amounts = txs.map(tx => Math.abs(tx.amount || 0)).filter(a => a > 0);
        const mean = amounts.reduce((s, v) => s + v, 0) / (amounts.length || 1);
        const threshold = Math.max(mean * 5, 1000);
        highValueTxs = txs.filter(tx => Math.abs(tx.amount || 0) > threshold);
      }

      result.high_value_tx = highValueTxs.map(tx => {
        const raw = tx.raw || {};
        const fv = parseFloat(raw.fiat_value);
        const fc = raw.fiat_currency || "";
        const fiatStr = (!isNaN(fv) && fv > 0) ? ` (${fv.toFixed(2)} ${fc})` : "";
        return {
          text: `${(tx.timestamp || "").slice(0, 16)} | ${_fmtCrypto(tx.amount, tx.token)} | ${tx.tx_type || ""}`,
          html: `${_esc((tx.timestamp || "").slice(0, 16).replace("T"," "))} — <b>${_fmtCrypto(tx.amount, tx.token || "")}</b><span style="color:#ef4444;font-weight:600">${_esc(fiatStr)}</span> (${_esc(tx.tx_type || "")})`,
          severity: "warning",
          _fiatValue: fv || 0,
        };
      });
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

    // 6. New / unknown tokens — use backend token_classification if available
    {
      const tc = r.token_classification || {};
      const tcKeys = Object.keys(tc);
      let knownTokens;
      if (tcKeys.length) {
        // Backend classified tokens — use that (known=true means recognized)
        knownTokens = new Set(tcKeys.filter(s => tc[s] && tc[s].known).map(s => s.toUpperCase()));
      } else {
        // Fallback — hardcoded minimal set
        knownTokens = new Set(["BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "MATIC", "AVAX", "LINK", "DAI", "BUSD", "EUR", "USD", "PLN", "GBP"]);
      }
      const unknownTxs = txs.filter(tx => tx.token && !knownTokens.has(tx.token.toUpperCase()));
      const byToken = {};
      for (const tx of unknownTxs) {
        const tok = tx.token.toUpperCase();
        if (!byToken[tok]) byToken[tok] = { count: 0, total: 0 };
        byToken[tok].count++;
        byToken[tok].total += Math.abs(tx.amount || 0);
      }
      result.new_token = Object.entries(byToken).map(([tok, d]) => {
        const info = tc[tok] || {};
        const nameStr = info.name ? ` (${_esc(info.name)})` : "";
        return {
          html: `Token <b>${_esc(tok)}</b>${nameStr}: ${d.count} transakcji, wolumen ${d.total.toFixed(4)}`,
          severity: "info",
        };
      });
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
    for (const w of wallets) {
      const rc = RISK_COLORS[w.risk_level] || "#94a3b8";
      html += `<tr>
        <td style="font-family:monospace;font-size:11px;word-break:break-all" title="${_esc(w.address)}">${_esc(_shorten(w.address))}</td>
        <td>${_esc(w.label || "\u2014")}</td>
        <td>${w.tx_count}</td>
        <td>${_fmtCrypto(w.total_received, "")}</td>
        <td>${_fmtCrypto(w.total_sent, "")}</td>
        <td style="color:${rc};font-weight:600">${_esc(w.risk_level)}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    const wBody = document.getElementById("crypto_wallets_body");
    if (wBody) { wBody.innerHTML = html; wBody.style.maxHeight = "600px"; wBody.style.overflowY = "auto"; }
  }

  /* -- Detected phone numbers (all sources) -------------------------- */

  function _renderPhones(r) {
    const phones = r.detected_phones || [];
    if (!phones.length) { _hide("crypto_phones_card"); return; }
    _show("crypto_phones_card");

    let html = `<div style="margin-bottom:8px;font-size:13px">Znaleziono <b>${phones.length}</b> unikalnych numerów telefonów w danych transakcyjnych.</div>`;
    html += `<div style="margin-bottom:6px;font-size:11px;color:#64748b">💡 Kliknij 2× na wiersz, aby przefiltrować transakcje po tym numerze.</div>`;
    html += '<div style="max-height:600px;overflow-y:auto"><table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>Numer</th><th>Kraj</th><th>ISO</th><th>Wystąpienia</th><th>Kontekst</th></tr></thead><tbody>';
    for (const p of phones) {
      const flag = p.country_iso ? _countryFlag(p.country_iso) + " " : "";
      let ctxHtml = "";
      if (p.contexts && p.contexts.length) {
        const ctx = p.contexts[0];
        ctxHtml = `${_esc(ctx.tx_type)} ${_esc(ctx.token)} ${_esc(ctx.timestamp)} (pole: ${_esc(ctx.field)})`;
      }
      html += `<tr style="cursor:pointer" data-phone-filter="${_esc(p.number)}">
        <td style="font-family:monospace;font-weight:600;white-space:nowrap">${_esc(p.number)}</td>
        <td>${flag}${_esc(p.country_name || "—")}</td>
        <td>${_esc(p.country_iso || "—")}</td>
        <td>${p.occurrences}</td>
        <td style="font-size:11px">${ctxHtml}</td>
      </tr>`;
    }
    html += '</tbody></table></div>';
    _html("crypto_phones_body", html);

    // Bind double-click: filter review table by this phone number
    const phonesBody = document.getElementById("crypto_phones_body");
    if (phonesBody) {
      phonesBody.querySelectorAll("tr[data-phone-filter]").forEach(row => {
        row.addEventListener("dblclick", () => {
          const phone = row.getAttribute("data-phone-filter");
          if (!phone) return;
          // Set search field and trigger filter
          const searchInput = QS("#crypto_rv_search");
          if (searchInput) {
            searchInput.value = phone;
            searchInput.dispatchEvent(new Event("input"));
          }
          // Scroll to the review card
          const reviewCard = document.getElementById("crypto_review_card");
          if (reviewCard) reviewCard.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });
    }
  }

  function _countryFlag(iso) {
    if (!iso || iso.length !== 2) return "";
    const codePoints = [...iso.toUpperCase()].map(c => 0x1F1E6 + c.charCodeAt(0) - 65);
    try { return String.fromCodePoint(...codePoints); } catch (_) { return ""; }
  }

  /* ------------------------------------------------------------------ */
  /*  Binance XLSX forensic cards                                       */
  /* ------------------------------------------------------------------ */

  function _renderAccountInfo(r) {
    const fr = r.forensic_report || {};
    const ai = fr.account_info || {};
    // Show card only if at least one field has real data
    const hasAny = Object.values(ai).some(v => v && String(v).trim());
    if (!hasAny) { _hide("crypto_account_card"); return; }
    _show("crypto_account_card");

    // Render as vertical table — each field on its own row, label: value
    const fields = [
      ["User ID", ai.user_id],
      ["Imię i nazwisko", ai.holder_name],
      ["Imię", ai.first_name],
      ["Nazwisko", ai.last_name],
      ["Email", ai.email],
      ["Telefon", ai.phone],
      ["Data urodzenia", ai.date_of_birth],
      ["Płeć", ai.gender],
      ["Kraj zamieszkania", ai.country],
      ["Narodowość", ai.nationality],
      ["Adres", ai.physical_address],
      ["Miasto", ai.city],
      ["Województwo/Stan", ai.state],
      ["Kod pocztowy", ai.zip_code],
      ["Poziom KYC", ai.kyc_level],
      ["Poziom VIP", ai.vip_level],
      ["Data rejestracji", ai.registration_date],
      ["Status konta", ai.account_status],
      ["Typ dokumentu", ai.id_type],
      ["Nr dokumentu", ai.id_number],
      ["ID polecającego", ai.referral_id],
      ["ID agenta", ai.agent_id],
      ["Sub-konto", ai.sub_account],
      ["Margin", ai.margin_enabled],
      ["Futures", ai.futures_enabled],
      ["API Trading", ai.api_trading],
      ["Kod anti-phishing", ai.anti_phishing_code],
    ];

    let html = '<table class="data-table" style="width:100%;max-width:600px;font-size:13px"><tbody>';
    for (const [label, val] of fields) {
      if (val && String(val).trim()) {
        html += `<tr><th style="width:180px;text-align:left;padding:4px 12px 4px 0;white-space:nowrap">${_esc(label)}</th><td style="padding:4px 0;word-break:break-all">${_esc(String(val))}</td></tr>`;
      }
    }
    html += '</tbody></table>';

    // Show any remaining unknown fields from account_info
    const knownKeys = new Set([
      "user_id","holder_name","first_name","last_name","email","phone",
      "date_of_birth","gender","country","nationality","physical_address",
      "city","state","zip_code","kyc_level","vip_level","registration_date",
      "account_status","id_type","id_number","referral_id","agent_id",
      "sub_account","margin_enabled","futures_enabled","api_trading",
      "anti_phishing_code"
    ]);
    const extra = Object.entries(ai).filter(([k,v]) => !knownKeys.has(k) && v && String(v).trim());
    if (extra.length) {
      html += '<table class="data-table" style="width:100%;max-width:600px;font-size:13px;margin-top:8px"><tbody>';
      for (const [k, v] of extra) {
        html += `<tr><th style="width:180px;text-align:left;padding:4px 12px 4px 0">${_esc(k)}</th><td style="padding:4px 0">${_esc(String(v))}</td></tr>`;
      }
      html += '</tbody></table>';
    }

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

    let html = '<div style="max-height:600px;overflow-y:auto"><table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>User ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th><th>Źródło</th><th>Okres</th></tr></thead><tbody>';
    const sorted = keys.sort((a, b) => cps[b].tx_count - cps[a].tx_count);
    for (const k of sorted) {
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
    html += '</tbody></table></div>';

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

    let html = '<div style="max-height:600px;overflow-y:auto"><table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>Binance ID</th><th>Wallet ID</th><th>TX</th><th>Wpływy</th><th>Wypływy</th><th>Tokeny</th><th>Okres</th></tr></thead><tbody>';
    const sorted = keys.sort((a, b) => pcs[b].count - pcs[a].count);
    for (const k of sorted) {
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
    html += '</tbody></table></div>';
    _html("crypto_pay_c2c_body", html);
  }

  function _renderExtAddresses(r) {
    const fr = r.forensic_report || {};
    const src = fr.external_source_addresses || [];
    const dst = fr.external_dest_addresses || [];
    if (!src.length && !dst.length) { _hide("crypto_ext_addresses_card"); return; }
    _show("crypto_ext_addresses_card");

    // Merge src and dst by address — avoid duplicates (case-insensitive for EVM)
    function _normAddr(addr) {
      const a = (addr || "").trim();
      return (a.startsWith("0x") || a.startsWith("0X")) ? a.toLowerCase() : a;
    }
    const addrMap = {};
    for (const a of src) {
      const key = _normAddr(a.address);
      if (addrMap[key]) {
        const m = addrMap[key];
        m.dep_count += (a.count || 0);
        m.dep_total += (a.total || 0);
        (a.tokens || []).forEach(t => m.tokens.add(t));
        (a.networks || []).forEach(n => m.networks.add(n));
      } else {
        addrMap[key] = {
          address: a.address,
          dep_count: a.count || 0, dep_total: a.total || 0,
          wd_count: 0, wd_total: 0,
          tokens: new Set(a.tokens || []),
          networks: new Set(a.networks || []),
        };
      }
    }
    for (const a of dst) {
      const key = _normAddr(a.address);
      if (addrMap[key]) {
        const m = addrMap[key];
        m.wd_count += (a.count || 0);
        m.wd_total += (a.total || 0);
        (a.tokens || []).forEach(t => m.tokens.add(t));
        (a.networks || []).forEach(n => m.networks.add(n));
      } else {
        addrMap[key] = {
          address: a.address,
          dep_count: 0, dep_total: 0,
          wd_count: a.count || 0, wd_total: a.total || 0,
          tokens: new Set(a.tokens || []),
          networks: new Set(a.networks || []),
        };
      }
    }

    // Sort by total volume (deposits + withdrawals)
    const merged = Object.values(addrMap).sort((a, b) =>
      (b.dep_total + b.wd_total) - (a.dep_total + a.wd_total)
    );

    // Count how many are deposit-only, withdrawal-only, or both
    const bothCount = merged.filter(a => a.dep_count > 0 && a.wd_count > 0).length;
    const depOnly = merged.filter(a => a.dep_count > 0 && a.wd_count === 0).length;
    const wdOnly = merged.filter(a => a.dep_count === 0 && a.wd_count > 0).length;

    let html = `<div style="margin-bottom:8px;font-size:13px">Łącznie <b>${merged.length}</b> unikalnych adresów zewnętrznych`;
    if (bothCount > 0) html += ` (w tym <b>${bothCount}</b> używanych dwukierunkowo)`;
    html += `</div>`;

    html += '<div style="max-height:600px;overflow-y:auto"><table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
      '<th>Adres</th><th>Kierunek</th><th>Dep. TX</th><th>Dep. suma</th><th>Wyp. TX</th><th>Wyp. suma</th><th>Tokeny</th><th>Sieci</th></tr></thead><tbody>';
    for (const a of merged) {
      const dir = (a.dep_count > 0 && a.wd_count > 0) ? "📥📤"
                : a.dep_count > 0 ? "📥" : "📤";
      html += `<tr>
        <td style="font-family:monospace;font-size:11px;word-break:break-all">${_esc(a.address)}</td>
        <td style="text-align:center">${dir}</td>
        <td>${a.dep_count || "—"}</td>
        <td style="text-align:right">${a.dep_count ? a.dep_total.toFixed(4) : "—"}</td>
        <td>${a.wd_count || "—"}</td>
        <td style="text-align:right">${a.wd_count ? a.wd_total.toFixed(4) : "—"}</td>
        <td>${_esc([...a.tokens].join(", "))}</td>
        <td>${_esc([...a.networks].join(", "))}</td>
      </tr>`;
    }
    html += '</tbody></table></div>';
    _html("crypto_ext_addresses_body", html);
  }

  function _renderPassThrough(r) {
    const fr = r.forensic_report || {};
    const pts = fr.pass_through_detection || [];
    const ptCount = fr.pass_through_count || pts.length;
    if (!pts.length) { _hide("crypto_passthrough_card"); return; }
    _show("crypto_passthrough_card");

    let html = `<div style="margin-bottom:8px;font-size:13px">⚠️ Wykryto <b>${ptCount}</b> potencjalnych przepływów tranzytowych (depozyt → wypłata w ciągu 24h)</div>`;
    html += '<div style="max-height:600px;overflow-y:auto"><table class="data-table" style="width:100%;font-size:11px"><thead><tr>' +
      '<th>Depozyt (czas)</th><th>Kwota</th><th>Token</th><th>Od</th>' +
      '<th>Wypłata (czas)</th><th>Kwota</th><th>Token</th><th>Do</th><th>Opóźn.</th></tr></thead><tbody>';
    for (const pt of pts) {
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
    html += '</tbody></table></div>';
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
      for (const m of mining) {
        html += `<tr>
          <td style="font-family:monospace;font-size:11px;word-break:break-all" title="${_esc(m.address)}">${_esc(_shorten(m.address))}</td>
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
      for (const g of geoKeys) {
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
      for (const ip of ipKeys) {
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
      for (const d of mid) {
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
      for (const f of fl) {
        html += `<tr>
          <td>${_esc((f.timestamp || "").replace("T", " "))}</td>
          <td>${_esc(f.geo || "")}</td>
          <td style="font-family:monospace">${_esc(f.ip || "")}</td>
          <td style="font-size:10px">${_esc(f.client || "")}</td>
          <td>${_esc(f.operation || "")}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    const accBody = document.getElementById("crypto_access_body");
    if (accBody) { accBody.innerHTML = html; accBody.style.maxHeight = "700px"; accBody.style.overflowY = "auto"; }
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
      for (const m of sortedM) {
        html += `<tr><td>${_esc(m)}</td><td style="text-align:right">${merchants[m].toFixed(2)}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    // Transaction timeline
    if (timeline.length) {
      html += '<div style="margin-bottom:8px"><b>📍 Oś czasu transakcji kartą (geolokalizacja):</b></div>';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr>' +
        '<th>Data/czas</th><th>Merchant</th><th>Kwota</th><th>Waluta</th><th>Status</th></tr></thead><tbody>';
      for (const t of timeline) {
        html += `<tr>
          <td>${_esc((t.timestamp || "").replace("T", " "))}</td>
          <td>${_esc(t.merchant || "")}</td>
          <td style="text-align:right">${(t.amount || 0).toFixed(2)}</td>
          <td>${_esc(t.currency || "")}</td>
          <td>${_esc(t.status || "")}</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }

    const ctBody = document.getElementById("crypto_card_timeline_body");
    if (ctBody) { ctBody.innerHTML = html; ctBody.style.maxHeight = "700px"; ctBody.style.overflowY = "auto"; }
  }

  /* ------------------------------------------------------------------ */
  /*  NEW FORENSIC CARDS (v3.7.1) — 10 additional analysis cards        */
  /* ------------------------------------------------------------------ */

  // ── 1. Temporal Analysis ──
  function _renderTemporal(r) {
    const fr = r.forensic_report || {};
    const ta = fr.temporal_analysis;
    if (!ta) { _hide("crypto_temporal_card"); return; }
    _show("crypto_temporal_card");
    let html = '';

    // Summary stats
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px">';
    if (ta.active_span_days) html += `<div class="stat-box"><small>Okres aktywności</small><b>${ta.active_span_days} dni</b></div>`;
    if (ta.active_days) html += `<div class="stat-box"><small>Aktywne dni</small><b>${ta.active_days} (${ta.activity_density || 0}%)</b></div>`;
    if (ta.peak_hour != null) html += `<div class="stat-box"><small>Szczytowa godzina</small><b>${ta.peak_hour}:00 (${ta.peak_hour_count} tx)</b></div>`;
    html += `<div class="stat-box"><small>Aktywność nocna (0-5)</small><b>${ta.night_activity_count || 0} (${ta.night_activity_ratio || 0}%)</b></div>`;
    html += `<div class="stat-box"><small>Weekend / tygodniowo</small><b>${ta.weekend_count || 0} / ${ta.weekday_count || 0} (${ta.weekend_ratio || 0}%)</b></div>`;
    html += '</div>';

    // Hourly distribution bar chart
    const hd = ta.hourly_distribution || {};
    const maxH = Math.max(1, ...Object.values(hd));
    html += '<div style="margin-bottom:6px"><b>📊 Rozkład godzinowy:</b></div>';
    html += '<div style="display:flex;align-items:flex-end;gap:2px;height:120px;margin-bottom:4px;padding:4px 0;border-bottom:1px solid #e2e8f0">';
    for (let h = 0; h < 24; h++) {
      const v = hd[h] || 0;
      const pct = Math.max(1, v / maxH * 100);
      const color = (h >= 0 && h < 6) ? '#ef4444' : '#3b82f6';
      html += `<div title="${h}:00 — ${v} tx" style="flex:1;background:${color};height:${pct.toFixed(0)}%;border-radius:2px 2px 0 0"></div>`;
    }
    html += '</div>';
    html += '<div style="display:flex;gap:2px;font-size:9px;color:#94a3b8;margin-bottom:20px">';
    for (let h = 0; h < 24; h++) html += `<div style="flex:1;text-align:center">${h}</div>`;
    html += '</div>';

    // Day of week
    const dow = ta.dow_distribution || {};
    const dowNames = ['Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'Sb', 'Nd'];
    const maxD = Math.max(1, ...Object.values(dow));
    html += '<div style="margin-bottom:6px"><b>📅 Rozkład dni tygodnia:</b></div>';
    html += '<div style="display:flex;align-items:flex-end;gap:6px;height:80px;max-width:400px;padding:4px 0;border-bottom:1px solid #e2e8f0">';
    for (let d = 0; d < 7; d++) {
      const v = dow[d] || 0;
      const pct = Math.max(1, v / maxD * 100);
      const color = d >= 5 ? '#f59e0b' : '#3b82f6';
      html += `<div title="${dowNames[d]} — ${v} tx" style="flex:1;background:${color};height:${pct.toFixed(0)}%;border-radius:2px 2px 0 0"></div>`;
    }
    html += '</div>';
    html += '<div style="display:flex;gap:6px;max-width:400px;margin-bottom:16px">';
    for (let d = 0; d < 7; d++) {
      const v = dow[d] || 0;
      html += `<div style="flex:1;text-align:center;font-size:10px;color:#64748b;margin-top:2px">${dowNames[d]}<br><span style="font-size:9px">${v}</span></div>`;
    }
    html += '</div>';

    // Burst days
    if (ta.burst_days && ta.burst_days.length) {
      html += '<div style="margin-top:14px"><b>⚡ Dni z nagłą aktywnością (&gt;50 tx):</b></div>';
      html += '<table class="data-table" style="width:auto;font-size:11px;margin-top:4px"><thead><tr><th>Data</th><th>TX</th></tr></thead><tbody>';
      for (const b of ta.burst_days) html += `<tr><td>${_esc(b.date)}</td><td style="text-align:right;font-weight:bold;color:#dc2626">${b.tx_count}</td></tr>`;
      html += '</tbody></table>';
    }

    // Dormancy periods
    if (ta.dormancy_periods && ta.dormancy_periods.length) {
      html += '<div style="margin-top:14px"><b>😴 Okresy uśpienia (&gt;7 dni):</b></div>';
      html += '<table class="data-table" style="width:auto;font-size:11px;margin-top:4px"><thead><tr><th>Od</th><th>Do</th><th>Dni</th></tr></thead><tbody>';
      for (const d of ta.dormancy_periods) html += `<tr><td>${_esc(d.from)}</td><td>${_esc(d.to)}</td><td style="text-align:right">${d.days}</td></tr>`;
      html += '</tbody></table>';
    }

    _html("crypto_temporal_body", html);
  }

  // ── 2. Conversion Chains ──
  function _renderConversionChains(r) {
    const fr = r.forensic_report || {};
    const cc = fr.conversion_chains;
    if (!cc || !cc.edges || !cc.edges.length) { _hide("crypto_conversion_card"); return; }
    _show("crypto_conversion_card");
    let html = '';

    html += `<div style="margin-bottom:10px"><b>Unikalne pary konwersji:</b> ${cc.unique_swap_pairs || 0}`;
    if (cc.fiat_entry_tokens && cc.fiat_entry_tokens.length) html += ` &nbsp;|&nbsp; <b>Waluty fiat wejściowe:</b> ${_esc(cc.fiat_entry_tokens.join(', '))}`;
    if (cc.withdrawal_tokens && cc.withdrawal_tokens.length) html += ` &nbsp;|&nbsp; <b>Tokeny wypłacane:</b> ${_esc(cc.withdrawal_tokens.join(', '))}`;
    html += '</div>';

    html += '<div style="max-height:600px;overflow-y:auto">';
    html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Z tokenu</th><th>→</th><th>Na token</th><th>Wolumen</th></tr></thead><tbody>';
    for (const e of cc.edges) {
      html += `<tr><td><b>${_esc(e.from)}</b></td><td style="text-align:center">→</td><td><b>${_esc(e.to)}</b></td><td style="text-align:right">${e.volume.toFixed(4)}</td></tr>`;
    }
    html += '</tbody></table></div>';
    _html("crypto_conversion_body", html);
  }

  // ── 3. Structuring Detection ──
  function _renderStructuring(r) {
    const fr = r.forensic_report || {};
    const sd = fr.structuring_detection;
    if (!sd) { _hide("crypto_structuring_card"); return; }
    const alerts = sd.alerts || [];
    const freq = sd.frequent_amounts || [];
    if (!alerts.length && !freq.length) { _hide("crypto_structuring_card"); return; }
    _show("crypto_structuring_card");
    let html = '';

    if (alerts.length) {
      html += `<div style="margin-bottom:8px;color:#dc2626;font-weight:bold">⚠️ Wykryto ${sd.alert_count || alerts.length} potencjalnych przypadków structuringu</div>`;
      html += '<div style="max-height:500px;overflow-y:auto">';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Data</th><th>Typ</th><th>Próg</th><th>Ilość tx</th><th>Kwoty</th><th>Suma dzienna</th></tr></thead><tbody>';
      for (const a of alerts) {
        html += `<tr><td>${_esc(a.date)}</td><td>${_esc(a.type)}</td><td>${a.threshold}</td><td>${a.count}</td><td style="font-size:10px">${(a.amounts || []).join(', ')}</td><td style="text-align:right;font-weight:bold">${a.daily_total.toFixed(2)}</td></tr>`;
      }
      html += '</tbody></table></div>';
    }

    if (freq.length) {
      html += '<div style="margin-top:12px"><b>📊 Najczęściej używane kwoty (zaokrąglone do 100):</b></div>';
      html += '<table class="data-table" style="width:auto;font-size:11px;margin-top:4px"><thead><tr><th>Kwota</th><th>Wystąpienia</th></tr></thead><tbody>';
      for (const f of freq) html += `<tr><td style="text-align:right">${f.amount.toFixed(0)}</td><td style="text-align:right">${f.count}</td></tr>`;
      html += '</tbody></table>';
    }

    _html("crypto_structuring_body", html);
  }

  // ── 4. Wash Trading Detection ──
  function _renderWashTrading(r) {
    const fr = r.forensic_report || {};
    const wt = fr.wash_trading;
    if (!wt) { _hide("crypto_wash_card"); return; }
    const reversals = wt.rapid_reversals || [];
    const zeroNet = wt.zero_net_markets || [];
    if (!reversals.length && !zeroNet.length) { _hide("crypto_wash_card"); return; }
    _show("crypto_wash_card");
    let html = '';

    if (zeroNet.length) {
      html += `<div style="margin-bottom:8px;color:#f97316;font-weight:bold">⚠️ Rynki z zerową pozycją netto (podejrzenie wash tradingu):</div>`;
      html += '<div style="max-height:400px;overflow-y:auto">';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Rynek</th><th>Wolumen brutto</th><th>Pozycja netto</th><th>Net ratio %</th><th>Kupno</th><th>Sprzedaż</th></tr></thead><tbody>';
      for (const m of zeroNet) {
        html += `<tr><td><b>${_esc(m.market)}</b></td><td style="text-align:right">${m.gross_volume.toFixed(4)}</td><td style="text-align:right;color:#dc2626">${m.net_position.toFixed(4)}</td><td style="text-align:right;color:#dc2626">${m.net_ratio}%</td><td style="text-align:right">${m.buys.toFixed(4)}</td><td style="text-align:right">${m.sells.toFixed(4)}</td></tr>`;
      }
      html += '</tbody></table></div>';
    }

    if (reversals.length) {
      html += `<div style="margin-top:12px"><b>🔄 Szybkie odwrócenia (kupno↔sprzedaż &lt;5min) — ${wt.rapid_reversal_count || reversals.length} wykrytych:</b></div>`;
      html += '<div style="max-height:500px;overflow-y:auto">';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Rynek</th><th>Czas 1</th><th>Strona</th><th>Kwota</th><th>Czas 2</th><th>Strona</th><th>Kwota</th><th>Opóźn.(s)</th></tr></thead><tbody>';
      for (const w of reversals) {
        html += `<tr><td>${_esc(w.market)}</td><td>${_esc((w.time1 || '').replace('T', ' '))}</td><td>${_esc(w.side1)}</td><td style="text-align:right">${w.amount1}</td><td>${_esc((w.time2 || '').replace('T', ' '))}</td><td>${_esc(w.side2)}</td><td style="text-align:right">${w.amount2}</td><td style="text-align:right">${w.delay_sec}</td></tr>`;
      }
      html += '</tbody></table></div>';
    }

    _html("crypto_wash_body", html);
  }

  // ── 5. Fiat On/Off Ramp Analysis ──
  function _renderFiatRamp(r) {
    const fr = r.forensic_report || {};
    const fa = fr.fiat_ramp_analysis;
    if (!fa || (fa.fiat_deposit_count === 0 && fa.fiat_withdrawal_count === 0)) { _hide("crypto_fiat_ramp_card"); return; }
    _show("crypto_fiat_ramp_card");
    let html = '';

    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px">';
    html += `<div class="stat-box"><small>Wpłaty fiat</small><b>${fa.fiat_deposit_count || 0}</b></div>`;
    html += `<div class="stat-box"><small>Wypłaty fiat</small><b>${fa.fiat_withdrawal_count || 0}</b></div>`;
    html += `<div class="stat-box"><small>Łącznie fiat IN</small><b>${(fa.total_fiat_in || 0).toFixed(2)}</b></div>`;
    html += `<div class="stat-box"><small>Łącznie fiat OUT</small><b>${(fa.total_fiat_out || 0).toFixed(2)}</b></div>`;
    const nf = fa.net_fiat_flow || 0;
    const nfColor = nf >= 0 ? '#22c55e' : '#dc2626';
    html += `<div class="stat-box"><small>Saldo netto fiat</small><b style="color:${nfColor}">${nf.toFixed(2)}</b></div>`;
    html += '</div>';

    // Fiat currencies
    const ci = fa.currencies_in || {};
    const co = fa.currencies_out || {};
    if (Object.keys(ci).length || Object.keys(co).length) {
      html += '<table class="data-table" style="width:auto;font-size:11px"><thead><tr><th>Waluta</th><th>Wpłaty</th><th>Wypłaty</th></tr></thead><tbody>';
      const allCurr = new Set([...Object.keys(ci), ...Object.keys(co)]);
      for (const c of allCurr) {
        html += `<tr><td><b>${_esc(c)}</b></td><td style="text-align:right">${(ci[c] || 0).toFixed(2)}</td><td style="text-align:right">${(co[c] || 0).toFixed(2)}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    // Fiat-to-crypto withdrawal timing
    if (fa.fiat_to_crypto_wd_hours != null) {
      const h = fa.fiat_to_crypto_wd_hours;
      const color = h < 24 ? '#dc2626' : (h < 72 ? '#f97316' : '#64748b');
      html += `<div style="margin-top:10px"><b>⏱️ Czas od pierwszej wpłaty fiat do pierwszej wypłaty krypto:</b> <span style="color:${color};font-weight:bold">${h.toFixed(1)} godz.</span>`;
      if (h < 24) html += ' <span style="color:#dc2626">⚠️ Szybki pipeline fiat→crypto</span>';
      html += '</div>';
    }

    if (fa.p2p_transaction_count > 0) {
      html += `<div style="margin-top:6px"><b>P2P jako rampa:</b> ${fa.p2p_transaction_count} transakcji P2P</div>`;
    }

    _html("crypto_fiat_ramp_body", html);
  }

  // ── 6. P2P Analysis ──
  function _renderP2PAnalysis(r) {
    const fr = r.forensic_report || {};
    const p2p = fr.p2p_analysis;
    if (!p2p || !p2p.total_count) { _hide("crypto_p2p_card"); return; }
    _show("crypto_p2p_card");
    let html = '';

    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-bottom:14px">';
    html += `<div class="stat-box"><small>Transakcje P2P</small><b>${p2p.total_count}</b></div>`;
    html += `<div class="stat-box"><small>% całkowitej aktywności</small><b>${p2p.total_pct || 0}%</b></div>`;
    html += `<div class="stat-box"><small>Wolumen</small><b>${(p2p.total_volume || 0).toFixed(2)}</b></div>`;
    html += `<div class="stat-box"><small>Unikalni kontrahenci</small><b>${p2p.unique_counterparties || 0}</b></div>`;
    html += '</div>';

    // Payment methods
    const pm = p2p.payment_methods || {};
    if (Object.keys(pm).length) {
      html += '<div style="margin-bottom:6px"><b>💳 Metody płatności:</b></div>';
      html += '<table class="data-table" style="width:auto;font-size:11px"><thead><tr><th>Metoda</th><th>Transakcje</th></tr></thead><tbody>';
      for (const [m, c] of Object.entries(pm)) html += `<tr><td>${_esc(m)}</td><td style="text-align:right">${c}</td></tr>`;
      html += '</tbody></table>';
    }

    // Top counterparties
    const tops = p2p.top_counterparties || [];
    if (tops.length) {
      html += '<div style="margin-top:10px"><b>👥 Top kontrahenci P2P:</b></div>';
      html += '<div style="max-height:400px;overflow-y:auto">';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>ID</th><th>TX</th><th>Wolumen</th><th>Tokeny</th></tr></thead><tbody>';
      for (const cp of tops) {
        html += `<tr><td><code>${_esc(cp.id)}</code></td><td style="text-align:right">${cp.count}</td><td style="text-align:right">${cp.volume.toFixed(4)}</td><td>${_esc((cp.tokens || []).join(', '))}</td></tr>`;
      }
      html += '</tbody></table></div>';
    }

    _html("crypto_p2p_body", html);
  }

  // ── 7. Velocity Analysis ──
  function _renderVelocity(r) {
    const fr = r.forensic_report || {};
    const va = fr.velocity_analysis;
    if (!va) { _hide("crypto_velocity_card"); return; }
    _show("crypto_velocity_card");
    let html = '';

    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px">';
    html += `<div class="stat-box"><small>Wpłaty / Wypłaty</small><b>${va.deposit_count || 0} / ${va.withdrawal_count || 0}</b></div>`;
    html += `<div class="stat-box"><small>Stosunek DEP/WD</small><b>${va.dep_wd_ratio || 0}</b></div>`;
    if (va.has_hot_wallet_behavior) html += `<div class="stat-box" style="border-color:#dc2626"><small>🔥 Hot wallet</small><b style="color:#dc2626">TAK</b></div>`;
    html += '</div>';

    // Hot wallet indicators
    if (va.hot_wallet_indicators && va.hot_wallet_indicators.length) {
      html += '<div style="margin-bottom:8px;color:#dc2626;font-weight:bold">⚠️ Tokeny z zachowaniem "hot wallet" (śr. trzymanie &lt;1h):</div>';
      html += '<table class="data-table" style="width:auto;font-size:11px"><thead><tr><th>Token</th><th>Średni czas (godz.)</th></tr></thead><tbody>';
      for (const h of va.hot_wallet_indicators) html += `<tr><td><b>${_esc(h.token)}</b></td><td style="text-align:right;color:#dc2626">${h.avg_hold_hours}</td></tr>`;
      html += '</tbody></table>';
    }

    // Token velocities
    const tv = va.token_velocities || [];
    if (tv.length) {
      html += '<div style="margin-top:10px"><b>⏱️ Czas trzymania per token:</b></div>';
      html += '<div style="max-height:500px;overflow-y:auto">';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Token</th><th>Śr. czas (godz.)</th><th>Min czas (godz.)</th><th>Wpłaty</th><th>Wypłaty</th></tr></thead><tbody>';
      for (const t of tv) {
        const color = t.avg_hold_hours < 1 ? '#dc2626' : (t.avg_hold_hours < 24 ? '#f97316' : '#64748b');
        html += `<tr><td><b>${_esc(t.token)}</b></td><td style="text-align:right;color:${color}">${t.avg_hold_hours}</td><td style="text-align:right">${t.min_hold_hours}</td><td style="text-align:right">${t.deposit_count}</td><td style="text-align:right">${t.withdrawal_count}</td></tr>`;
      }
      html += '</tbody></table></div>';
    }

    _html("crypto_velocity_body", html);
  }

  // ── 8. Fee Analysis ──
  function _renderFeeAnalysis(r) {
    const fr = r.forensic_report || {};
    const fa = fr.fee_analysis;
    if (!fa || !fa.fee_paying_tx_count) { _hide("crypto_fee_card"); return; }
    _show("crypto_fee_card");
    let html = '';

    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px">';
    html += `<div class="stat-box"><small>TX z opłatami</small><b>${fa.fee_paying_tx_count}</b></div>`;
    html += `<div class="stat-box"><small>Opłaty w BNB</small><b>${fa.bnb_fee_count} (${fa.bnb_fee_ratio}%)</b></div>`;
    html += '</div>';

    const fees = fa.total_fees_by_token || {};
    if (Object.keys(fees).length) {
      html += '<table class="data-table" style="width:auto;font-size:11px"><thead><tr><th>Token opłaty</th><th>Suma opłat</th></tr></thead><tbody>';
      for (const [tok, val] of Object.entries(fees)) {
        html += `<tr><td><b>${_esc(tok)}</b></td><td style="text-align:right">${Number(val).toFixed(8)}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    _html("crypto_fee_body", html);
  }

  // ── 9. Network Analysis ──
  function _renderNetworkAnalysis(r) {
    const fr = r.forensic_report || {};
    const na = fr.network_analysis;
    if (!na || !na.networks || !na.networks.length) { _hide("crypto_network_card"); return; }
    _show("crypto_network_card");
    let html = '';

    html += `<div style="margin-bottom:10px"><b>Unikalne sieci:</b> ${na.unique_networks || 0}`;
    if (na.high_risk_networks && na.high_risk_networks.length) {
      html += ` &nbsp;|&nbsp; <span style="color:#dc2626;font-weight:bold">⚠️ Sieci wysokiego ryzyka: ${na.high_risk_networks.map(n => n.network).join(', ')}</span>`;
    }
    html += '</div>';

    html += '<div style="max-height:500px;overflow-y:auto">';
    html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Sieć</th><th>Wpłaty</th><th>Wypłaty</th><th>Łącznie TX</th><th>Wol. wpłat</th><th>Wol. wypłat</th></tr></thead><tbody>';
    const _HR = new Set(["TRX", "TRON", "TRC20", "BSC", "BEP20", "BEP2"]);
    for (const n of na.networks) {
      const isHR = _HR.has((n.network || '').toUpperCase());
      const style = isHR ? 'background:#fef2f2' : '';
      html += `<tr style="${style}"><td><b>${_esc(n.network)}</b>${isHR ? ' ⚠️' : ''}</td><td style="text-align:right">${n.deposits}</td><td style="text-align:right">${n.withdrawals}</td><td style="text-align:right;font-weight:bold">${n.total_tx}</td><td style="text-align:right">${n.dep_volume.toFixed(4)}</td><td style="text-align:right">${n.wd_volume.toFixed(4)}</td></tr>`;
    }
    html += '</tbody></table></div>';

    _html("crypto_network_body", html);
  }

  // ── 10. Extended Security Analysis ──
  function _renderExtSecurity(r) {
    const fr = r.forensic_report || {};
    const es = fr.extended_security;
    if (!es) { _hide("crypto_ext_security_card"); return; }
    _show("crypto_ext_security_card");
    let html = '';

    html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px">';
    html += `<div class="stat-box"><small>Kraje logowań</small><b>${es.login_country_count || 0}</b></div>`;
    if (es.vpn_suspect_days > 0) html += `<div class="stat-box" style="border-color:#dc2626"><small>Podejrzane dni VPN</small><b style="color:#dc2626">${es.vpn_suspect_days}</b></div>`;
    html += `<div class="stat-box"><small>API Trading</small><b>${es.api_trading_enabled ? '✅ Włączone' : '❌ Wyłączone'}</b></div>`;
    html += `<div class="stat-box"><small>Sub-konto</small><b>${es.has_sub_account ? '✅ Tak' : '❌ Nie'}</b></div>`;
    html += '</div>';

    // Login countries
    if (es.login_countries && es.login_countries.length) {
      html += `<div style="margin-bottom:6px"><b>🌍 Kraje logowań:</b> ${_esc(es.login_countries.join(', '))}</div>`;
    }

    // VPN suspects
    const vpn = es.vpn_suspects || [];
    if (vpn.length) {
      html += '<div style="margin-top:10px;color:#dc2626;font-weight:bold">⚠️ Podejrzenie VPN/proxy — wiele krajów w jednym dniu:</div>';
      html += '<div style="max-height:400px;overflow-y:auto">';
      html += '<table class="data-table" style="width:100%;font-size:11px"><thead><tr><th>Data</th><th>Kraje</th><th>Ilość krajów</th><th>Loginy</th></tr></thead><tbody>';
      for (const v of vpn) {
        html += `<tr><td>${_esc(v.date)}</td><td>${_esc((v.countries || []).join(', '))}</td><td style="text-align:right;color:#dc2626;font-weight:bold">${v.country_count}</td><td style="text-align:right">${v.login_count}</td></tr>`;
      }
      html += '</tbody></table></div>';
    }

    _html("crypto_ext_security_body", html);
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
            "color": "#1e293b",
            "font-size": "10px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            "width": "data(size)",
            "height": "data(size)",
            "shape": "data(shape)",
            "border-width": 1,
            "border-color": "#94a3b8",
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
    // Show full address — use CSS word-break for overflow
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

    // Report save — each format triggers a separate request
    const reportSaveBtn = QS("#crypto_report_save_btn");
    if (reportSaveBtn) {
      reportSaveBtn.onclick = () => {
        const checked = document.querySelectorAll('input[name="crypto_report_fmt"]:checked');
        const formats = Array.from(checked).map(cb => cb.value);
        if (!formats.length) { alert("Nie wybrano formatu raportu."); return; }
        const pid = _getProjectId();
        if (!pid) { alert("Brak projektu — zapisz analizę, aby wygenerować raport."); return; }
        if (!_lastResult) { alert("Brak danych do raportu. Wczytaj dane crypto."); return; }
        for (const fmt of formats) {
          const url = "/api/crypto/report?project_id=" + encodeURIComponent(pid) + "&formats=" + encodeURIComponent(fmt);
          // All formats — download as file
          const a = document.createElement("a");
          a.href = url;
          a.download = "crypto_report." + fmt;
          a.style.display = "none";
          document.body.appendChild(a);
          a.click();
          setTimeout(() => a.remove(), 1000);
        }
      };
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
