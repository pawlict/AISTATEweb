/**
 * GSM Billing Analysis module.
 *
 * Handles XLSX upload, parsing via /api/gsm/parse, result display,
 * BTS geolocation map, and BTS admin panel.
 */
(function () {
  "use strict";

  const QS = (sel, root = document) => root.querySelector(sel);
  const QSA = (sel, root = document) => root.querySelectorAll(sel);

  /* ── state ─────────────────────────────────────────────── */
  const St = {
    analyzing: false,
    lastResult: null,
    filename: "",
    map: null,          // Leaflet map instance
    mapLayers: {},      // Named layer groups
    leafletLoaded: false,
  };

  /* ── helpers ────────────────────────────────────────────── */
  function _fmt(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString("pl-PL");
  }

  function _dur(sec) {
    if (!sec) return "0s";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function _el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html) e.innerHTML = html;
    return e;
  }

  /* ── log panel ──────────────────────────────────────────── */
  function _addLog(level, msg) {
    const el = QS("#gsm_log_body");
    if (!el) return;
    const card = QS("#gsm_log_card");
    if (card) card.style.display = "";
    const ts = new Date().toLocaleTimeString("pl-PL");
    const cls = level === "error" ? "gsm-log-error" : level === "warn" ? "gsm-log-warn" : "gsm-log-info";
    const div = _el("div", `gsm-log-line ${cls}`, `<span class="gsm-log-ts">${ts}</span> ${msg}`);
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
  }

  /* ── Leaflet loader ────────────────────────────────────── */
  function _loadLeaflet() {
    return new Promise((resolve) => {
      if (St.leafletLoaded || window.L) { St.leafletLoaded = true; resolve(); return; }
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(css);
      const js = document.createElement("script");
      js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      js.onload = () => { St.leafletLoaded = true; resolve(); };
      js.onerror = () => {
        // Fallback: try local tiles API without Leaflet (show placeholder)
        console.warn("Leaflet CDN unavailable — map will use fallback mode");
        resolve();
      };
      document.head.appendChild(js);
    });
  }

  /* ── upload & parse ─────────────────────────────────────── */
  async function _uploadAndParse(file) {
    if (St.analyzing) return;
    St.analyzing = true;
    St.filename = file.name;

    const progress = QS("#gsm_progress");
    const status = QS("#gsm_status");
    const bar = QS("#gsm_bar");
    const results = QS("#gsm_results");

    if (progress) progress.style.display = "";
    if (status) status.textContent = "Wczytywanie pliku…";
    if (bar) bar.style.width = "30%";
    if (results) results.style.display = "none";

    const fd = new FormData();
    fd.append("file", file);

    try {
      if (status) status.textContent = "Parsowanie bilingu…";
      if (bar) bar.style.width = "60%";

      const resp = await fetch("/api/gsm/parse", { method: "POST", body: fd });

      if (bar) bar.style.width = "90%";

      // Handle non-JSON responses (e.g. HTML error pages)
      let data;
      const contentType = resp.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        data = await resp.json();
      } else {
        const text = await resp.text();
        console.error("GSM: non-JSON response:", resp.status, text.slice(0, 500));
        const detail = `HTTP ${resp.status}: ${text.slice(0, 200)}`;
        if (status) status.textContent = `Błąd: ${detail}`;
        _addLog("error", detail);
        St.analyzing = false;
        return;
      }

      if (bar) bar.style.width = "100%";

      if (data.status !== "ok") {
        const detail = data.detail || data.error || data.message || JSON.stringify(data);
        console.error("GSM parse error:", detail);
        if (status) status.textContent = `Błąd: ${detail}`;
        _addLog("error", detail);
        St.analyzing = false;
        return;
      }

      St.lastResult = data;
      if (status) status.textContent = "Gotowe";
      _addLog("info", `Sparsowano ${data.record_count} rekordów (${data.operator || "?"})`);

      setTimeout(() => {
        if (progress) progress.style.display = "none";
      }, 800);

      _renderResults(data);
    } catch (e) {
      console.error("GSM parse error:", e);
      const msg = e.message || String(e);
      if (status) status.textContent = `Błąd: ${msg}`;
      _addLog("error", msg);
    } finally {
      St.analyzing = false;
    }
  }

  /* ── render ─────────────────────────────────────────────── */
  function _renderResults(data) {
    const wrap = QS("#gsm_results");
    if (!wrap) return;
    wrap.style.display = "";

    // Hide empty state
    const empty = QS("#gsm_empty_state");
    if (empty) empty.style.display = "none";

    _renderInfo(data);
    _renderSummary(data.summary);
    _renderAnalysis(data.analysis);
    _renderRecords(data.records, data.records_truncated, data.record_count);
    _renderSpecialNumbers(data.analysis ? data.analysis.special_numbers : []);
    _renderActivityCharts(data.analysis);
    _renderMap(data.geolocation);
    _renderWarnings(data.warnings);
  }

  function _renderInfo(data) {
    const grid = QS("#gsm_info_grid");
    if (!grid) return;

    const sub = data.subscriber || {};
    const meta = sub.extra || {};

    const imeiVal = sub.imei
      ? (sub.device && sub.device.display_name
          ? `${sub.imei} <span class="gsm-device-badge">${sub.device.display_name}</span>`
          : sub.imei)
      : "—";

    const rows = [
      ["Plik", data.filename],
      ["Operator", data.operator],
      ["MSISDN", sub.msisdn || "—"],
      ["IMSI", sub.imsi || "—"],
      ["IMEI", imeiVal],
    ];
    if (meta.signature) rows.push(["Sygnatura", meta.signature]);
    if (meta.order_id) rows.push(["Nr zlecenia", meta.order_id]);
    if (meta.query_name) rows.push(["Zapytanie", meta.query_name]);

    grid.innerHTML = rows
      .map(([k, v]) => `<div class="gsm-info-label">${k}</div><div class="gsm-info-value">${v || "—"}</div>`)
      .join("");
  }

  function _renderSummary(s) {
    const el = QS("#gsm_summary_grid");
    if (!el || !s) return;

    el.innerHTML = `
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.total_records)}</div>
        <div class="gsm-stat-label">Rekordy</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.calls_out + s.calls_in)}</div>
        <div class="gsm-stat-label">Połączenia (${_fmt(s.calls_out)}↑ ${_fmt(s.calls_in)}↓)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.sms_out + s.sms_in)}</div>
        <div class="gsm-stat-label">SMS (${_fmt(s.sms_out)}↑ ${_fmt(s.sms_in)}↓)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.mms_out + s.mms_in)}</div>
        <div class="gsm-stat-label">MMS</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.data_sessions)}</div>
        <div class="gsm-stat-label">Sesje danych</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_dur(s.total_duration_seconds)}</div>
        <div class="gsm-stat-label">Czas rozmów</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.unique_contacts)}</div>
        <div class="gsm-stat-label">Unikalne kontakty</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${s.period_from || "—"}</div>
        <div class="gsm-stat-label">Okres od</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${s.period_to || "—"}</div>
        <div class="gsm-stat-label">Okres do</div>
      </div>
      ${s.roaming_records ? `<div class="gsm-stat-card"><div class="gsm-stat-value">${_fmt(s.roaming_records)}</div><div class="gsm-stat-label">Roaming</div></div>` : ""}
    `;
  }

  function _renderAnalysis(a) {
    const el = QS("#gsm_analysis_body");
    if (!el || !a) return;

    let html = "";

    // Top contacts
    if (a.top_contacts && a.top_contacts.length) {
      html += `<div class="gsm-section"><div class="h3">Top kontakty</div><table class="gsm-table"><thead><tr>
        <th>Numer</th><th>Interakcje</th><th>Rozmowy ↑</th><th>Rozmowy ↓</th><th>SMS ↑</th><th>SMS ↓</th><th>Czas rozmów</th><th>Aktywne dni</th>
      </tr></thead><tbody>`;
      for (const c of a.top_contacts.slice(0, 20)) {
        html += `<tr>
          <td><code>${c.number}</code></td>
          <td>${_fmt(c.total_interactions)}</td>
          <td>${_fmt(c.calls_out)}</td><td>${_fmt(c.calls_in)}</td>
          <td>${_fmt(c.sms_out)}</td><td>${_fmt(c.sms_in)}</td>
          <td>${_dur(c.total_duration_seconds)}</td>
          <td>${c.active_days}</td>
        </tr>`;
      }
      html += "</tbody></table></div>";
    }

    // Anomalies
    if (a.anomalies && a.anomalies.length) {
      html += `<div class="gsm-section"><div class="h3">Anomalie</div>`;
      for (const an of a.anomalies) {
        const sev = an.severity || "info";
        html += `<div class="gsm-anomaly gsm-anomaly-${sev}">
          <strong>${an.type || ""}</strong>: ${an.description || ""}
        </div>`;
      }
      html += "</div>";
    }

    // Stats
    if (a.avg_call_duration || a.longest_call_seconds) {
      html += `<div class="gsm-section"><div class="h3">Statystyki połączeń</div><div class="gsm-stats-row">`;
      html += `<span>Śr. czas: <b>${_dur(Math.round(a.avg_call_duration || 0))}</b></span>`;
      html += `<span>Mediana: <b>${_dur(Math.round(a.median_call_duration || 0))}</b></span>`;
      html += `<span>Najdłuższe: <b>${_dur(a.longest_call_seconds || 0)}</b> (${a.longest_call_contact || "—"})</span>`;
      if (a.busiest_date) html += `<span>Najaktywniejszy dzień: <b>${a.busiest_date}</b> (${a.busiest_date_count} zdarzeń)</span>`;
      html += `</div></div>`;
    }

    // Devices (IMEI identification)
    if (a.devices && a.devices.length) {
      html += `<div class="gsm-section"><div class="h3">Urządzenia</div><table class="gsm-table"><thead><tr>
        <th>IMEI</th><th>Urządzenie</th><th>Typ</th><th>Rekordy</th><th>Okres</th>
      </tr></thead><tbody>`;
      for (const d of a.devices) {
        const name = d.display_name || '<span class="muted">nieznane</span>';
        const typeMap = { smartphone: "Smartfon", tablet: "Tablet", modem: "Modem", feature_phone: "Telefon", smartwatch: "Smartwatch" };
        const typeName = typeMap[d.type] || d.type || "—";
        const period = d.first_seen ? (d.first_seen === d.last_seen ? d.first_seen : `${d.first_seen} – ${d.last_seen}`) : "—";
        html += `<tr>
          <td><code>${d.imei || "?"}</code></td>
          <td>${d.known ? `<strong>${name}</strong>` : name}</td>
          <td>${typeName}</td>
          <td>${_fmt(d.record_count)}</td>
          <td>${period}</td>
        </tr>`;
      }
      html += "</tbody></table></div>";
    }

    // IMEI changes
    if (a.imei_changes && a.imei_changes.length) {
      html += `<div class="gsm-section"><div class="h3">Zmiany IMEI</div>`;
      for (const ch of a.imei_changes) {
        const oldDev = ch.old_device ? ` (${ch.old_device})` : "";
        const newDev = ch.new_device ? ` (${ch.new_device})` : "";
        html += `<div class="gsm-anomaly gsm-anomaly-medium">${ch.date || ""}: ${ch.old_imei || "?"}${oldDev} → ${ch.new_imei || "?"}${newDev}</div>`;
      }
      html += "</div>";
    }

    el.innerHTML = html || '<div class="small muted">Brak danych do analizy.</div>';
  }

  function _renderRecords(records, truncated, totalCount) {
    const el = QS("#gsm_records_body");
    if (!el) return;

    if (!records || !records.length) {
      el.innerHTML = '<div class="small muted">Brak rekordów.</div>';
      return;
    }

    const countLabel = QS("#gsm_records_count");
    if (countLabel) {
      countLabel.textContent = truncated ? `${records.length} z ${_fmt(totalCount)}` : _fmt(totalCount);
    }

    let html = `<table class="gsm-table"><thead><tr>
      <th>Data i czas</th><th>Typ</th><th>Kierunek</th><th>Numer</th><th>Czas</th><th>Lokalizacja</th><th>Sieć</th>
    </tr></thead><tbody>`;

    for (const r of records) {
      const extra = r.extra || {};
      const typeLabel = _typeLabel(r.record_type);
      const dir = extra.direction || "";
      html += `<tr>
        <td>${r.datetime || ""}</td>
        <td><span class="gsm-type gsm-type-${r.record_type}">${typeLabel}</span></td>
        <td>${dir}</td>
        <td><code>${r.callee || "—"}</code></td>
        <td>${r.duration_seconds ? _dur(r.duration_seconds) : (r.data_volume_kb ? _fmt(Math.round(r.data_volume_kb)) + " KB" : "—")}</td>
        <td>${r.location || "—"}</td>
        <td>${r.network || "—"}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    if (truncated) {
      html += `<div class="small muted" style="margin-top:8px">Pokazano ${records.length} z ${_fmt(totalCount)} rekordów.</div>`;
    }
    el.innerHTML = html;
  }

  /* ── special numbers ──────────────────────────────────── */
  function _renderSpecialNumbers(specials) {
    const el = QS("#gsm_special_numbers_body");
    if (!el) return;
    const card = el.closest(".card");

    if (!specials || !specials.length) {
      if (card) card.style.display = "none";
      return;
    }
    if (card) card.style.display = "";

    const catLabels = {
      voicemail: "Poczta głosowa",
      service: "Usługa operatora",
      emergency: "Nr alarmowy",
      premium: "Nr premium",
      toll_free: "Nr bezpłatny",
      short_code: "Kod krótki",
      international: "Zagraniczny",
      info: "Informacja",
    };
    const catCls = {
      voicemail: "gsm-sn-voicemail",
      service: "gsm-sn-service",
      emergency: "gsm-sn-emergency",
      premium: "gsm-sn-premium",
      toll_free: "gsm-sn-tollfree",
      short_code: "gsm-sn-short",
      international: "gsm-sn-intl",
      info: "gsm-sn-info",
    };

    let html = `<table class="gsm-table"><thead><tr>
      <th>Numer</th><th>Kategoria</th><th>Opis</th><th>Interakcje</th><th>Czas rozmów</th><th>Okres</th>
    </tr></thead><tbody>`;

    for (const s of specials) {
      const cat = catLabels[s.category] || s.category;
      const cls = catCls[s.category] || "";
      const period = s.first_date
        ? (s.first_date === s.last_date ? s.first_date : `${s.first_date} – ${s.last_date}`)
        : "—";
      html += `<tr>
        <td><code>${s.number}</code></td>
        <td><span class="gsm-sn-badge ${cls}">${cat}</span></td>
        <td>${s.label || "—"}</td>
        <td>${_fmt(s.interactions)}</td>
        <td>${_dur(s.total_duration_seconds || 0)}</td>
        <td>${period}</td>
      </tr>`;
    }
    html += "</tbody></table>";
    el.innerHTML = html;
  }

  /* ── activity charts — grouped bars (Rozmowy / SMS / Dane) ── */

  function _buildGroupedBars(groups) {
    const allVals = groups.flatMap(g => [g.calls || 0, g.sms || 0, g.data || 0]);
    const maxVal = Math.max(1, ...allVals);
    let html = '';
    for (const g of groups) {
      const c = g.calls || 0, s = g.sms || 0, d = g.data || 0;
      const pctC = Math.round((c / maxVal) * 100);
      const pctS = Math.round((s / maxVal) * 100);
      const pctD = Math.round((d / maxVal) * 100);
      html += `<div class="gsm-bar-group">
        <div class="gsm-bar-group-bars">
          <div class="gsm-bar-wrap"><div class="gsm-bar gsm-bar-calls" style="height:${Math.max(pctC, 3)}%" title="${g.label} Rozmowy: ${c}"><span class="gsm-bar-val">${c || ''}</span></div></div>
          <div class="gsm-bar-wrap"><div class="gsm-bar gsm-bar-sms" style="height:${Math.max(pctS, 3)}%" title="${g.label} SMS/MMS: ${s}"><span class="gsm-bar-val">${s || ''}</span></div></div>
          <div class="gsm-bar-wrap"><div class="gsm-bar gsm-bar-data" style="height:${Math.max(pctD, 3)}%" title="${g.label} Dane: ${d}"><span class="gsm-bar-val">${d || ''}</span></div></div>
        </div>
        <div class="gsm-bar-label">${g.label}</div>
      </div>`;
    }
    return html;
  }

  function _buildAnomalies(anomalies) {
    if (!anomalies || !anomalies.length) return '';
    const items = anomalies.filter(a => a.period_type !== "summary");
    const summaries = anomalies.filter(a => a.period_type === "summary");
    let html = '';
    if (items.length) {
      html += '<div class="gsm-chart-anomalies">';
      for (const a of items) {
        const icon = a.ratio > 1 ? '&#9650;' : '&#9660;';
        const cls = a.ratio > 1 ? 'gsm-anomaly-up' : 'gsm-anomaly-down';
        html += `<div class="gsm-chart-anomaly-item ${cls}"><span class="gsm-chart-anomaly-icon">${icon}</span> ${a.description}</div>`;
      }
      html += '</div>';
    }
    if (summaries.length) {
      html += '<div class="gsm-chart-summary-block">';
      for (const s of summaries) html += `<div>${s.description}</div>`;
      html += '</div>';
    }
    return html;
  }

  function _nightTotalBars(d) {
    const hours = [22, 23, 0, 1, 2, 3, 4, 5];
    const hc = d.hourly_calls || {}, hs = d.hourly_sms || {}, hd = d.hourly_data || {};
    return _buildGroupedBars(hours.map(h => ({
      label: `${String(h).padStart(2, "0")}:00`,
      calls: hc[h] || 0, sms: hs[h] || 0, data: hd[h] || 0,
    })));
  }

  function _weekendTotalBars(d) {
    const sc = d.seg_calls || {}, ss = d.seg_sms || {}, sd = d.seg_data || {};
    return _buildGroupedBars([
      { label: "Pt wieczór", calls: sc.fri_evening || 0, sms: ss.fri_evening || 0, data: sd.fri_evening || 0 },
      { label: "Sobota",     calls: sc.saturday || 0,    sms: ss.saturday || 0,    data: sd.saturday || 0 },
      { label: "Niedziela",  calls: sc.sunday || 0,      sms: ss.sunday || 0,      data: sd.sunday || 0 },
      { label: "Pn rano",    calls: sc.mon_morning || 0, sms: ss.mon_morning || 0, data: sd.mon_morning || 0 },
    ]);
  }

  function _bucketTypeBars(bucket) {
    return _buildGroupedBars([{
      label: "Łącznie",
      calls: bucket.calls || 0,
      sms: bucket.sms || 0,
      data: bucket.data || 0,
    }]);
  }

  function _renderActivityCharts(analysis) {
    const wrap = QS("#gsm_activity_charts");
    if (!wrap || !analysis) { if (wrap) wrap.style.display = "none"; return; }

    const night = analysis.night_activity;
    const weekend = analysis.weekend_activity;

    if ((!night || !night.total_records) && (!weekend || !weekend.total_records)) {
      wrap.style.display = "none";
      return;
    }
    wrap.style.display = "";

    let html = '<div class="gsm-charts-row">';

    if (night && night.total_records) {
      html += _renderOneChart("night", "Aktywność nocna", "22:00–6:00", night, _nightTotalBars);
    }
    if (weekend && weekend.total_records) {
      html += _renderOneChart("weekend", "Aktywność weekendowa", "Pt 20:00–Pn 6:00", weekend, _weekendTotalBars);
    }

    html += "</div>";
    wrap.innerHTML = html;

    QSA(".gsm-period-select", wrap).forEach(sel => {
      sel.onchange = () => _onPeriodChange(sel, analysis);
    });
  }

  function _renderOneChart(id, title, subtitle, d, buildTotalBars) {
    const weeklyKeys = Object.keys(d.weekly || {});
    const monthlyKeys = Object.keys(d.monthly || {});

    let html = `<div class="gsm-chart-card" data-chart-id="${id}">
      <div class="gsm-chart-header">
        <div class="h3">${title} <span class="small muted">(${subtitle})</span></div>
        <select class="gsm-period-select" data-chart="${id}">
          <option value="total" selected>Łącznie</option>`;
    if (weeklyKeys.length > 1) {
      html += `<optgroup label="Tygodnie">`;
      for (const k of weeklyKeys) html += `<option value="week:${k}">Tyg. ${k} (${d.weekly[k].records})</option>`;
      html += `</optgroup>`;
    }
    if (monthlyKeys.length > 1) {
      html += `<optgroup label="Miesiące">`;
      for (const k of monthlyKeys) html += `<option value="month:${k}">${k} (${d.monthly[k].records})</option>`;
      html += `</optgroup>`;
    }
    html += `</select></div>`;

    html += `<div class="gsm-chart-legend">
      <span class="gsm-legend-item"><span class="gsm-legend-dot gsm-bar-calls"></span>Rozmowy</span>
      <span class="gsm-legend-item"><span class="gsm-legend-dot gsm-bar-sms"></span>SMS/MMS</span>
      <span class="gsm-legend-item"><span class="gsm-legend-dot gsm-bar-data"></span>Dane</span>
    </div>`;

    html += `<div class="gsm-bar-chart" data-bars="${id}">${buildTotalBars(d)}</div>`;
    html += _buildAnomalies(d.anomalies);
    html += `</div>`;
    return html;
  }

  function _onPeriodChange(selectEl, analysis) {
    const chartId = selectEl.dataset.chart;
    const val = selectEl.value;
    const card = selectEl.closest(".gsm-chart-card");
    const barContainer = QS(`[data-bars="${chartId}"]`, card);
    if (!barContainer) return;

    const src = chartId === "night" ? analysis.night_activity : analysis.weekend_activity;
    if (!src) return;

    if (val === "total") {
      barContainer.innerHTML = chartId === "night" ? _nightTotalBars(src) : _weekendTotalBars(src);
      return;
    }

    let bucket = null;
    if (val.startsWith("week:")) bucket = (src.weekly || {})[val.slice(5)];
    else if (val.startsWith("month:")) bucket = (src.monthly || {})[val.slice(6)];
    if (!bucket) return;

    if (chartId === "night" && bucket.hourly_calls) {
      const hours = [22, 23, 0, 1, 2, 3, 4, 5];
      const hc = bucket.hourly_calls || {}, hs = bucket.hourly_sms || {}, hd = bucket.hourly_data || {};
      barContainer.innerHTML = _buildGroupedBars(hours.map(h => ({
        label: `${String(h).padStart(2, "0")}:00`,
        calls: hc[h] || hc[String(h)] || 0,
        sms: hs[h] || hs[String(h)] || 0,
        data: hd[h] || hd[String(h)] || 0,
      })));
    } else if (chartId === "weekend" && bucket.fri_evening != null) {
      const sc = bucket.seg_calls || {}, ss = bucket.seg_sms || {}, sd = bucket.seg_data || {};
      barContainer.innerHTML = _buildGroupedBars([
        { label: "Pt wieczór", calls: sc.fri_evening || 0, sms: ss.fri_evening || 0, data: sd.fri_evening || 0 },
        { label: "Sobota",     calls: sc.saturday || 0,    sms: ss.saturday || 0,    data: sd.saturday || 0 },
        { label: "Niedziela",  calls: sc.sunday || 0,      sms: ss.sunday || 0,      data: sd.sunday || 0 },
        { label: "Pn rano",    calls: sc.mon_morning || 0, sms: ss.mon_morning || 0, data: sd.mon_morning || 0 },
      ]);
    } else {
      barContainer.innerHTML = _bucketTypeBars(bucket);
    }
  }

  /* ── BTS Map ─────────────────────────────────────────────── */

  async function _renderMap(geo) {
    const card = QS("#gsm_map_card");
    if (!card) return;

    // Show debug info in log
    if (geo && geo.debug) {
      const d = geo.debug;
      _addLog("info", `[Geolokalizacja] Rekordy: ${geo.total_records}, ` +
        `z koordynatami BTS: ${d.has_direct_coords}, ` +
        `z LAC/CID: ${d.has_lac_cid}, ` +
        `bez danych: ${d.no_location_data}`);
      _addLog("info", `[Geolokalizacja] Zlokalizowane: ${geo.geolocated_records} ` +
        `(z bilingu: ${d.resolved_billing}, z bazy BTS: ${d.resolved_bts_db}, ` +
        `nieznalezione w bazie: ${d.lookup_miss})`);
      if (d.lookup_miss > 0 && d.resolved_bts_db === 0 && d.has_lac_cid > 0) {
        _addLog("warn", `[Geolokalizacja] Żaden rekord z LAC/CID nie znalazł dopasowania w bazie BTS! ` +
          `Sprawdź czy baza OpenCelliD jest pobrana. Przykładowe LAC/CID: ${(d.sample_lac_cid || []).join(", ")}`);
      }
    }

    if (!geo || !geo.geolocated_records || geo.geolocated_records === 0) {
      // Show card with diagnostic message if we have debug info
      if (geo && geo.debug && geo.debug.has_lac_cid > 0) {
        card.style.display = "";
        const container = QS("#gsm_map_container");
        if (container) {
          const d = geo.debug;
          container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">
            <div style="text-align:center;max-width:500px">
              <div style="font-size:24px;margin-bottom:8px">Brak danych lokalizacyjnych</div>
              <div class="small" style="margin-bottom:8px">Znaleziono ${d.has_lac_cid} rekordów z LAC/CID, ale żaden nie pasuje do bazy BTS.</div>
              <div class="small">Pobierz bazę OpenCelliD w <a href="/bts-settings" style="color:var(--accent)">ustawieniach BTS</a>, aby umożliwić geolokalizację.</div>
              ${d.sample_lac_cid && d.sample_lac_cid.length ? `<div class="small muted" style="margin-top:8px;font-family:monospace;font-size:11px">Przykładowe: ${d.sample_lac_cid.join(", ")}</div>` : ""}
            </div>
          </div>`;
        }
      } else {
        card.style.display = "none";
      }
      return;
    }

    card.style.display = "";
    const statsEl = QS("#gsm_map_stats");
    if (statsEl) {
      statsEl.textContent = `${geo.geolocated_records}/${geo.total_records} zlokalizowanych, ${geo.unique_cells} komórek`;
    }

    await _loadLeaflet();

    if (!window.L) {
      // Fallback — no Leaflet
      const container = QS("#gsm_map_container");
      if (container) {
        container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">
          <div style="text-align:center">
            <div style="font-size:24px;margin-bottom:8px">Mapa niedostępna</div>
            <div class="small">Nie udało się załadować biblioteki Leaflet. Sprawdź połączenie internetowe lub dodaj mapę offline (MBTiles).</div>
          </div>
        </div>`;
      }
      return;
    }

    await _initMap(geo);
    _renderClusters(geo);

    // Layer switcher
    const layerSelect = QS("#gsm_map_layer_select");
    if (layerSelect) {
      layerSelect.onchange = () => _switchMapLayer(layerSelect.value, geo);
    }
  }

  async function _initMap(geo) {
    const container = QS("#gsm_map_container");
    if (!container || !window.L) return;

    // Destroy existing map
    if (St.map) {
      try { St.map.remove(); } catch(e) { /* ignore */ }
      St.map = null;
    }

    const map = L.map(container, {
      zoomControl: true,
      attributionControl: true,
    });
    St.map = map;

    // Load tiles first, then add markers
    await _addTileLayer(map);

    // Add markers
    _addAllPoints(map, geo);
  }

  async function _addTileLayer(map) {
    // Check for offline tiles
    try {
      const resp = await fetch("/api/gsm/tiles/info");
      const info = await resp.json();
      if (info.available) {
        const fmt = info.format || "pbf";
        if (fmt === "png" || fmt === "jpg" || fmt === "jpeg") {
          L.tileLayer("/api/gsm/tiles/{z}/{x}/{y}", {
            maxZoom: parseInt(info.maxzoom) || 18,
            minZoom: parseInt(info.minzoom) || 0,
            attribution: "Offline map | OpenStreetMap",
          }).addTo(map);
          _addLog("info", "Używam mapy offline (MBTiles)");
          return;
        }
      }
    } catch (e) {
      // Ignore — use online fallback
    }

    // Fallback: OpenStreetMap online tiles
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
  }

  function _addAllPoints(map, geo) {
    const points = (geo.geo_records || []).filter(r => r.point && (r.point.lat || r.point.lon));

    console.log("[GSM Map] geo_records total:", (geo.geo_records || []).length,
                "with valid points:", points.length);

    if (!points.length) {
      _addLog("warn", `Mapa: brak punktów do wyświetlenia (geo_records: ${(geo.geo_records || []).length})`);
      return;
    }

    // Clear existing layers
    Object.values(St.mapLayers).forEach(lg => { if (map.hasLayer(lg)) map.removeLayer(lg); });
    St.mapLayers = {};

    // All points layer
    const allGroup = L.layerGroup();
    const typeColors = {
      CALL_OUT: "#3b82f6",
      CALL_IN: "#22c55e",
      SMS_OUT: "#a855f7",
      SMS_IN: "#ec4899",
      DATA: "#f97316",
      VOICEMAIL: "#6b7280",
      OTHER: "#6b7280",
    };

    for (const r of points) {
      const p = r.point;
      const color = typeColors[r.record_type] || "#6b7280";
      const marker = L.circleMarker([p.lat, p.lon], {
        radius: 5,
        fillColor: color,
        color: "#fff",
        weight: 1,
        fillOpacity: 0.8,
      });

      const popupHtml = `<b>${r.datetime}</b><br>
        ${_typeLabel(r.record_type)} ${r.callee ? `→ ${r.callee}` : ""}<br>
        ${r.duration_seconds ? _dur(r.duration_seconds) : ""}
        ${p.city ? `<br>${p.city}${p.street ? ", " + p.street : ""}` : ""}
        ${p.azimuth != null ? `<br>Azymut: ${p.azimuth}°` : ""}
        <br><span class="small">LAC: ${p.lac}, CID: ${p.cid}</span>`;
      marker.bindPopup(popupHtml);
      allGroup.addLayer(marker);
    }
    St.mapLayers.all = allGroup;
    allGroup.addTo(map);

    // Path layer
    const pathGroup = L.layerGroup();
    if (geo.path && geo.path.length) {
      const pathCoords = [];
      for (const seg of geo.path) {
        pathCoords.push([seg.from_point.lat, seg.from_point.lon]);
        pathCoords.push([seg.to_point.lat, seg.to_point.lon]);
      }
      if (pathCoords.length >= 2) {
        L.polyline(pathCoords, {
          color: "#3b82f6",
          weight: 2,
          opacity: 0.7,
          dashArray: "5, 10",
        }).addTo(pathGroup);
      }
    }
    St.mapLayers.path = pathGroup;

    // Clusters layer
    const clusterGroup = L.layerGroup();
    if (geo.clusters && geo.clusters.length) {
      for (const c of geo.clusters) {
        const color = c.label === "dom" ? "#22c55e" : c.label === "praca" ? "#3b82f6" : "#f97316";
        const label = c.label === "dom" ? "DOM" : c.label === "praca" ? "PRACA" : `Klaster (${c.record_count})`;

        L.circle([c.lat, c.lon], {
          radius: c.radius_m || 500,
          fillColor: color,
          color: color,
          weight: 2,
          fillOpacity: 0.15,
        }).addTo(clusterGroup);

        L.marker([c.lat, c.lon], {
          icon: L.divIcon({
            className: "gsm-cluster-icon",
            html: `<div style="background:${color};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;white-space:nowrap">${label}</div>`,
            iconSize: null,
          }),
        }).bindPopup(`<b>${label}</b><br>
          ${c.city || ""}${c.street ? ", " + c.street : ""}<br>
          Rekordy: ${c.record_count}<br>
          Unikalne dni: ${c.unique_days}<br>
          Okres: ${c.first_seen} — ${c.last_seen}<br>
          Godziny: ${(c.hours_active || []).join(", ")}
        `).addTo(clusterGroup);
      }
    }
    St.mapLayers.clusters = clusterGroup;

    // Fit bounds
    const allCoords = points.map(r => [r.point.lat, r.point.lon]);
    if (allCoords.length) {
      map.fitBounds(allCoords, { padding: [30, 30], maxZoom: 14 });
    }
  }

  function _switchMapLayer(layer, geo) {
    if (!St.map) return;
    const map = St.map;

    // Remove all custom layers
    Object.values(St.mapLayers).forEach(lg => {
      if (map.hasLayer(lg)) map.removeLayer(lg);
    });

    if (layer === "all" || layer === "heatmap") {
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
    if (layer === "path") {
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
      if (St.mapLayers.path) St.mapLayers.path.addTo(map);
    }
    if (layer === "clusters") {
      if (St.mapLayers.clusters) St.mapLayers.clusters.addTo(map);
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
  }

  function _renderClusters(geo) {
    const wrap = QS("#gsm_cluster_info");
    const list = QS("#gsm_cluster_list");
    if (!wrap || !list) return;

    if (!geo.clusters || !geo.clusters.length) {
      wrap.style.display = "none";
      return;
    }
    wrap.style.display = "";

    let html = '<div style="display:flex;gap:12px;flex-wrap:wrap">';
    for (const c of geo.clusters.slice(0, 10)) {
      const color = c.label === "dom" ? "#22c55e" : c.label === "praca" ? "#3b82f6" : "#f97316";
      const label = c.label === "dom" ? "DOM" : c.label === "praca" ? "PRACA" : "Lokalizacja";
      html += `<div style="border:2px solid ${color};border-radius:12px;padding:10px 14px;min-width:160px">
        <div style="color:${color};font-weight:bold;margin-bottom:4px">${label}</div>
        <div class="small">${c.city || "—"}${c.street ? ", " + c.street : ""}</div>
        <div class="small muted">${c.record_count} rekordów, ${c.unique_days} dni</div>
        <div class="small muted">${c.first_seen} — ${c.last_seen}</div>
      </div>`;
    }
    html += '</div>';

    if (geo.home_cluster) {
      html += `<div class="small" style="margin-top:8px"><b style="color:#22c55e">DOM:</b> ${geo.home_cluster.city || ""}${geo.home_cluster.street ? ", " + geo.home_cluster.street : ""}</div>`;
    }
    if (geo.work_cluster) {
      html += `<div class="small"><b style="color:#3b82f6">PRACA:</b> ${geo.work_cluster.city || ""}${geo.work_cluster.street ? ", " + geo.work_cluster.street : ""}</div>`;
    }

    list.innerHTML = html;
  }

  function _renderWarnings(warnings) {
    const el = QS("#gsm_warnings_body");
    if (!el) return;
    if (!warnings || !warnings.length) {
      el.parentElement.style.display = "none";
      return;
    }
    el.parentElement.style.display = "";
    el.innerHTML = warnings.map(w => `<div class="gsm-warning">${w}</div>`).join("");
  }

  function _typeLabel(t) {
    const map = {
      CALL_OUT: "Rozmowa ↑", CALL_IN: "Rozmowa ↓", CALL_FORWARDED: "Przekierowanie",
      SMS_OUT: "SMS ↑", SMS_IN: "SMS ↓", MMS_OUT: "MMS ↑", MMS_IN: "MMS ↓",
      DATA: "Dane", USSD: "USSD", VOICEMAIL: "Poczta gł.", OTHER: "Inne",
    };
    return map[t] || t;
  }

  /* ── bindings ───────────────────────────────────────────── */
  function _bind() {
    const fileInput = QS("#gsm_file_input");
    const uploadBtn = QS("#gsm_add_file_toolbar_btn");

    if (uploadBtn) {
      uploadBtn.onclick = () => { if (fileInput) fileInput.click(); };
    }
    if (fileInput) {
      fileInput.onchange = () => {
        if (fileInput.files && fileInput.files.length > 0) {
          _uploadAndParse(fileInput.files[0]);
          fileInput.value = "";
        }
      };
    }

    // Clear log button
    const clearLogBtn = QS("#gsm_log_clear");
    if (clearLogBtn) {
      clearLogBtn.onclick = () => {
        const body = QS("#gsm_log_body");
        if (body) body.innerHTML = "";
        const card = QS("#gsm_log_card");
        if (card) card.style.display = "none";
      };
    }

    // Empty state upload button
    const emptyBtn = QS("#gsm_upload_empty_btn");
    if (emptyBtn) {
      emptyBtn.onclick = () => { if (fileInput) fileInput.click(); };
    }

    // New analysis button
    const newBtn = QS("#gsm_new_analysis");
    if (newBtn) {
      newBtn.onclick = () => {
        St.lastResult = null;
        if (St.map) { St.map.remove(); St.map = null; }
        const results = QS("#gsm_results");
        const empty = QS("#gsm_empty_state");
        if (results) results.style.display = "none";
        if (empty) empty.style.display = "";
        if (fileInput) fileInput.click();
      };
    }

  }

  /* ── public manager ─────────────────────────────────────── */
  window.GsmManager = {
    _initialized: false,
    async init() {
      if (this._initialized) return;
      this._initialized = true;
      _bind();
    },
  };
})();
