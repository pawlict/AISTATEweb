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
    try { return (new URLSearchParams(window.location.search)).get("project") || localStorage.getItem("aistate_current_project") || ""; }
    catch (_) { return ""; }
  }

  /* ------------------------------------------------------------------ */
  /*  State                                                             */
  /* ------------------------------------------------------------------ */

  let _lastResult = null;
  let _chartInstances = {};
  let _cyInstance = null;
  let _llmRunning = false;

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
        _hide("crypto_empty_state");
        _renderResults(data.result);
      }
    } catch (e) {
      console.warn("[Crypto] Auto-load failed:", e);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Render results — dual mode                                        */
  /* ------------------------------------------------------------------ */

  function _renderResults(r) {
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
      _renderWallets(r);
    }

    _renderTransactions(r, isExchange);
    _renderCharts(r, isExchange);
    _renderGraph(r);
  }

  /* -- Summary grid -------------------------------------------------- */

  function _renderSummary(r, isExchange) {
    const items = [];

    if (isExchange) {
      const em = r.exchange_meta || {};
      items.push(
        ["Giełda", em.exchange_name || r.source || "—"],
        ["Plik", r.filename || "—"],
        ["Transakcje", r.tx_count || 0],
        ["Okres", (r.date_from || "?").slice(0, 10) + " — " + (r.date_to || "?").slice(0, 10)],
        ["Tokeny krypto", (em.crypto_tokens || []).join(", ") || "—"],
        ["Waluty fiat", (em.fiat_tokens || []).join(", ") || "—"],
        ["Konta", (em.account_types || []).join(", ") || "—"],
        ["Wpłaty (dep.)", (r.total_received || 0).toFixed(4)],
        ["Wypłaty (wd.)", (r.total_sent || 0).toFixed(4)],
        ["Czas analizy", (r.elapsed_sec || 0).toFixed(1) + "s"],
      );
    } else {
      items.push(
        ["Źródło", r.source || "—"],
        ["Blockchain", r.chain || "—"],
        ["Plik", r.filename || "—"],
        ["Transakcje", r.tx_count || 0],
        ["Portfele", r.wallet_count || 0],
        ["Kontrahenci", r.counterparty_count || 0],
        ["Okres", (r.date_from || "?").slice(0, 10) + " — " + (r.date_to || "?").slice(0, 10)],
        ["Wpłaty", (r.total_received || 0).toFixed(8) + " " + (Object.keys(r.tokens || {})[0] || "BTC")],
        ["Wypłaty", (r.total_sent || 0).toFixed(8) + " " + (Object.keys(r.tokens || {})[0] || "BTC")],
        ["Czas analizy", (r.elapsed_sec || 0).toFixed(1) + "s"],
      );
    }

    let html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px">';
    for (const [label, val] of items) {
      html += `<div style="padding:8px 12px;background:var(--bg-input,#0f172a);border-radius:6px">
        <div class="small" style="color:var(--text-muted,#94a3b8)">${_esc(label)}</div>
        <div style="font-weight:600">${_esc(String(val))}</div>
      </div>`;
    }
    html += "</div>";
    _html("crypto_summary_grid", html);
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

    const riskColors = { critical: "#ef4444", high: "#f97316", medium: "#eab308", low: "#22c55e" };
    let html = "";
    for (const a of alerts) {
      const c = riskColors[a.risk] || "#94a3b8";
      html += `<div style="padding:8px 12px;margin-bottom:6px;border-left:3px solid ${c};background:var(--bg-input,#0f172a);border-radius:4px">
        <strong style="color:${c}">${_esc(a.pattern || "?")}</strong>: ${_esc(a.description || "")}
      </div>`;
    }
    _html("crypto_alerts_body", html);
  }

  /* -- Wallets table (blockchain only) -------------------------------- */

  function _renderWallets(r) {
    const wallets = r.wallets || [];
    if (!wallets.length) { _hide("crypto_wallets_card"); return; }
    _show("crypto_wallets_card");

    const riskColors = { critical: "#ef4444", high: "#f97316", medium: "#eab308", low: "#22c55e", unknown: "#94a3b8" };
    let html = '<table class="data-table" style="width:100%;font-size:13px"><thead><tr>' +
      "<th>Adres</th><th>Etykieta</th><th>TX</th><th>Otrzymane</th><th>Wysłane</th><th>Ryzyko</th>" +
      "</tr></thead><tbody>";
    for (const w of wallets.slice(0, 50)) {
      const rc = riskColors[w.risk_level] || "#94a3b8";
      html += `<tr>
        <td style="font-family:monospace;font-size:11px" title="${_esc(w.address)}">${_esc(_shorten(w.address))}</td>
        <td>${_esc(w.label || "—")}</td>
        <td>${w.tx_count}</td>
        <td>${(w.total_received || 0).toFixed(8)}</td>
        <td>${(w.total_sent || 0).toFixed(8)}</td>
        <td style="color:${rc};font-weight:600">${_esc(w.risk_level)}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    if (wallets.length > 50) html += `<div class="small" style="margin-top:4px;color:var(--text-muted)">Pokazano 50 z ${wallets.length}</div>`;
    _html("crypto_wallets_body", html);
  }

  /* -- Transactions table -------------------------------------------- */

  function _renderTransactions(r, isExchange) {
    const txs = r.transactions || [];
    const totalCount = r.transactions_total || txs.length;
    _text("crypto_tx_count_label", `${totalCount} transakcji`);

    if (!txs.length) { _hide("crypto_tx_card"); return; }
    _show("crypto_tx_card");

    let html;
    const show = txs.slice(0, 200);

    if (isExchange) {
      html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
        "<th>Data</th><th>Konto</th><th>Operacja</th><th>Token</th><th>Kwota</th><th>Typ</th><th>Tagi</th>" +
        "</tr></thead><tbody>";
      for (const tx of show) {
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

        html += `<tr>
          <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16).replace("T", " "))}</td>
          <td>${_esc(raw.account || "—")}</td>
          <td>${_esc(tx.category || raw.operation || tx.tx_type || "—")}</td>
          <td style="font-weight:600">${_esc(tx.token || "")}</td>
          <td style="text-align:right;color:${amtColor};font-weight:500">${isNeg ? "-" : "+"}${amt.toFixed(4)}</td>
          <td>${_esc(tx.tx_type || "")}</td>
          <td style="color:${tagColor};font-size:11px">${_esc(tags || "—")}</td>
        </tr>`;
      }
    } else {
      html = '<table class="data-table" style="width:100%;font-size:12px"><thead><tr>' +
        "<th>Data</th><th>Od</th><th>Do</th><th>Kwota</th><th>Token</th><th>Typ</th><th>Ryzyko</th>" +
        "</tr></thead><tbody>";
      for (const tx of show) {
        const tags = (tx.risk_tags || []).join(", ");
        const tagColor = tags.includes("sanctioned") ? "#ef4444" :
          tags.includes("mixer") ? "#f97316" :
            tags.includes("high_value") ? "#eab308" : "";
        html += `<tr>
          <td style="white-space:nowrap">${_esc((tx.timestamp || "").slice(0, 16))}</td>
          <td style="font-family:monospace;font-size:10px" title="${_esc(tx.from || "")}">${_esc(_shorten(tx.from || "—"))}</td>
          <td style="font-family:monospace;font-size:10px" title="${_esc(tx.to || "")}">${_esc(_shorten(tx.to || "—"))}</td>
          <td style="text-align:right">${(tx.amount || 0).toFixed(8)}</td>
          <td>${_esc(tx.token || "")}</td>
          <td>${_esc(tx.tx_type || "")}</td>
          <td style="color:${tagColor};font-size:11px">${_esc(tags || "—")}</td>
        </tr>`;
      }
    }

    html += "</tbody></table>";
    const totalTx = r.transactions_total || txs.length;
    if (show.length < totalTx) {
      html += `<div class="small" style="margin-top:4px;color:var(--text-muted)">Pokazano ${show.length} z ${totalTx} transakcji</div>`;
    }
    _html("crypto_tx_body", html);
  }

  /* ------------------------------------------------------------------ */
  /*  Charts (Chart.js) — dual mode                                     */
  /* ------------------------------------------------------------------ */

  async function _renderCharts(r, isExchange) {
    try {
      await _ensureChartJS();
    } catch (e) {
      console.warn("[Crypto] Chart.js load failed:", e);
      return;
    }

    const charts = r.charts || {};
    _destroyCharts();

    // Common dark theme
    const gridColor = "rgba(148,163,184,0.15)";
    const tickColor = "#94a3b8";
    const palette = ["#3b82f6", "#22c55e", "#f97316", "#ef4444", "#8b5cf6", "#06b6d4", "#eab308",
                     "#ec4899", "#14b8a6", "#a855f7", "#f43f5e", "#84cc16"];

    // 1. Balance timeline
    const bal = charts.balance_timeline;
    const balCanvas = QS("#crypto_chart_balance");
    if (bal && balCanvas) {
      if (bal.datasets && bal.datasets.length) {
        // Exchange: multi-token balance lines
        const datasets = bal.datasets.map((ds, i) => ({
          label: ds.token,
          data: ds.data,
          borderColor: palette[i % palette.length],
          backgroundColor: palette[i % palette.length] + "22",
          fill: false,
          tension: 0.3,
          pointRadius: bal.labels.length > 50 ? 0 : 3,
        }));
        _chartInstances.balance = new Chart(balCanvas, {
          type: "line",
          data: { labels: bal.labels, datasets },
          options: _chartOpts(gridColor, tickColor),
        });
      } else if (bal.labels && bal.labels.length) {
        // Blockchain: single balance line
        _chartInstances.balance = new Chart(balCanvas, {
          type: "line",
          data: {
            labels: bal.labels,
            datasets: [{
              label: bal.label || "Saldo",
              data: bal.data,
              borderColor: "#3b82f6",
              backgroundColor: "rgba(59,130,246,0.1)",
              fill: true,
              tension: 0.3,
              pointRadius: bal.labels.length > 50 ? 0 : 3,
            }],
          },
          options: _chartOpts(gridColor, tickColor),
        });
      }
    }

    // 2. Monthly volume
    const vol = charts.monthly_volume;
    if (vol && vol.labels && vol.labels.length) {
      _chartInstances.volume = new Chart(QS("#crypto_chart_volume"), {
        type: "bar",
        data: {
          labels: vol.labels,
          datasets: [
            { label: "Otrzymane", data: vol.received, backgroundColor: "rgba(34,197,94,0.7)" },
            { label: "Wysłane", data: vol.sent, backgroundColor: "rgba(239,68,68,0.7)" },
          ],
        },
        options: _chartOpts(gridColor, tickColor),
      });
    }

    // 3. Daily tx count
    const daily = charts.daily_tx_count;
    if (daily && daily.labels && daily.labels.length) {
      _chartInstances.daily = new Chart(QS("#crypto_chart_daily"), {
        type: "bar",
        data: {
          labels: daily.labels,
          datasets: [{
            label: "Liczba TX",
            data: daily.data,
            backgroundColor: "rgba(139,92,246,0.7)",
          }],
        },
        options: _chartOpts(gridColor, tickColor),
      });
    }

    // 4. TX type distribution (doughnut)
    const types = charts.tx_type_distribution;
    if (types && types.labels && types.labels.length) {
      _chartInstances.types = new Chart(QS("#crypto_chart_types"), {
        type: "doughnut",
        data: {
          labels: types.labels,
          datasets: [{
            data: types.data,
            backgroundColor: types.labels.map((_, i) => palette[i % palette.length]),
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { position: "bottom", labels: { color: tickColor } } },
        },
      });
    }

    // 5a. Top counterparties (blockchain) or Fiat flow (exchange)
    if (isExchange) {
      // Fiat flow chart
      const fiat = charts.fiat_flow;
      const fiatCanvas = QS("#crypto_chart_counterparties");
      if (fiat && fiat.labels && fiat.labels.length && fiatCanvas) {
        _chartInstances.fiatFlow = new Chart(fiatCanvas, {
          type: "bar",
          data: {
            labels: fiat.labels,
            datasets: [
              { label: "Wpłaty fiat", data: fiat.deposits, backgroundColor: "rgba(34,197,94,0.7)" },
              { label: "Wypłaty fiat", data: fiat.withdrawals, backgroundColor: "rgba(239,68,68,0.7)" },
            ],
          },
          options: _chartOpts(gridColor, tickColor),
        });
      }

      // Token breakdown (extra chart for exchange)
      const tokBr = charts.token_breakdown;
      const tokCanvas = QS("#crypto_chart_token_breakdown");
      if (tokBr && tokBr.labels && tokBr.labels.length && tokCanvas) {
        _chartInstances.tokenBreakdown = new Chart(tokCanvas, {
          type: "bar",
          data: {
            labels: tokBr.labels,
            datasets: [{
              label: "Wolumen",
              data: tokBr.data,
              backgroundColor: tokBr.labels.map((_, i) => palette[i % palette.length]),
            }],
          },
          options: {
            ..._chartOpts(gridColor, tickColor),
            indexAxis: "y",
          },
        });
      }

      // Operations breakdown
      const ops = charts.top_operations;
      const opsCanvas = QS("#crypto_chart_operations");
      if (ops && ops.labels && ops.labels.length && opsCanvas) {
        _chartInstances.operations = new Chart(opsCanvas, {
          type: "doughnut",
          data: {
            labels: ops.labels,
            datasets: [{
              data: ops.data,
              backgroundColor: ops.labels.map((_, i) => palette[i % palette.length]),
            }],
          },
          options: {
            responsive: true,
            plugins: { legend: { position: "bottom", labels: { color: tickColor } } },
          },
        });
      }
    } else {
      // Blockchain: top counterparties
      const cp = charts.top_counterparties;
      if (cp && cp.labels && cp.labels.length) {
        _chartInstances.counterparties = new Chart(QS("#crypto_chart_counterparties"), {
          type: "bar",
          data: {
            labels: cp.labels,
            datasets: [{
              label: "Wolumen",
              data: cp.data,
              backgroundColor: "rgba(59,130,246,0.7)",
            }],
          },
          options: {
            ..._chartOpts(gridColor, tickColor),
            indexAxis: "y",
          },
        });
      }
    }

    // Show/hide exchange-only chart cards
    const exChartCards = ["crypto_chart_token_breakdown_card", "crypto_chart_operations_card"];
    for (const cardId of exChartCards) {
      if (isExchange) _show(cardId); else _hide(cardId);
    }

    // Relabel counterparties card for exchange
    const cpTitle = QS("#crypto_chart_counterparties_title");
    if (cpTitle) {
      cpTitle.textContent = isExchange ? "Przepływy fiatowe" : "Top kontrahenci";
    }
  }

  function _chartOpts(gridColor, tickColor) {
    return {
      responsive: true,
      plugins: {
        legend: { labels: { color: tickColor } },
      },
      scales: {
        x: { ticks: { color: tickColor, maxRotation: 45 }, grid: { color: gridColor } },
        y: { ticks: { color: tickColor }, grid: { color: gridColor } },
      },
    };
  }

  function _destroyCharts() {
    for (const key of Object.keys(_chartInstances)) {
      try { _chartInstances[key].destroy(); } catch (_) {}
    }
    _chartInstances = {};
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

    const riskColors = {
      critical: "#ef4444",
      high: "#f97316",
      medium: "#eab308",
      low: "#22c55e",
    };

    const elements = [];

    // Nodes
    for (const node of graphData.nodes) {
      const d = node.data;
      const color = riskColors[d.risk_level] || "#64748b";
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
          label: (d.amount || 0).toFixed(4) + " " + (d.token || ""),
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
    if (!addr) return "—";
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
