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
      if (d.coord_rejected) {
        _addLog("warn", `[Geolokalizacja] Odrzucono ${d.coord_rejected} współrzędnych (poza zakresem)`);
      }
      if (d.sample_raw_bts && d.sample_raw_bts.length) {
        _addLog("info", `[Geolokalizacja] Surowe BTS X/Y: ${d.sample_raw_bts.join("; ")}`);
      }
      if (d.sample_coords && d.sample_coords.length) {
        _addLog("info", `[Geolokalizacja] Przykładowe koordynaty: ${d.sample_coords.join("; ")}`);
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

    const typeColors = {
      CALL_OUT: "#3b82f6",
      CALL_IN: "#22c55e",
      SMS_OUT: "#a855f7",
      SMS_IN: "#ec4899",
      DATA: "#f97316",
      VOICEMAIL: "#6b7280",
      OTHER: "#6b7280",
    };

    // ── Group points by unique BTS location ──
    // Many records share the same BTS (lat/lon). Group them to avoid
    // rendering 20k+ overlapping markers.
    const locationMap = new Map(); // key: "lat,lon" → { lat, lon, records: [], ... }
    for (const r of points) {
      const p = r.point;
      // Round to ~10m precision for grouping (4 decimal places)
      const key = `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`;
      if (!locationMap.has(key)) {
        locationMap.set(key, {
          lat: p.lat, lon: p.lon,
          city: p.city || "", street: p.street || "",
          azimuth: p.azimuth,
          lac: p.lac, cid: p.cid,
          records: [],
          types: {},
        });
      }
      const loc = locationMap.get(key);
      loc.records.push(r);
      loc.types[r.record_type] = (loc.types[r.record_type] || 0) + 1;
    }

    const uniqueLocations = Array.from(locationMap.values());
    _addLog("info", `Mapa: ${points.length} rekordów → ${uniqueLocations.length} unikalnych lokalizacji BTS`);

    // ── Unique locations layer (main view) ──
    const allGroup = L.layerGroup();
    for (const loc of uniqueLocations) {
      const count = loc.records.length;
      // Size based on record count: min 4, max 14
      const radius = Math.min(14, Math.max(4, 3 + Math.log2(count) * 2));
      // Dominant type determines color
      const dominantType = Object.entries(loc.types)
        .sort((a, b) => b[1] - a[1])[0][0];
      const color = typeColors[dominantType] || "#6b7280";

      const marker = L.circleMarker([loc.lat, loc.lon], {
        radius: radius,
        fillColor: color,
        color: "#fff",
        weight: 1.5,
        fillOpacity: 0.75,
      });

      // Build popup with summary of all records at this location
      const typeList = Object.entries(loc.types)
        .map(([t, n]) => `${_typeLabel(t)}: ${n}`)
        .join(", ");
      const firstDt = loc.records[0].datetime;
      const lastDt = loc.records[loc.records.length - 1].datetime;

      const popupHtml = `<b>${loc.city || "BTS"}${loc.street ? ", " + loc.street : ""}</b><br>
        <b>${count}</b> rekordów (${typeList})<br>
        ${firstDt} — ${lastDt}
        ${loc.azimuth != null ? `<br>Azymut: ${loc.azimuth}°` : ""}
        <br><span class="small muted">LAC: ${loc.lac}, CID: ${loc.cid}<br>
        ${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}</span>`;
      marker.bindPopup(popupHtml);
      allGroup.addLayer(marker);
    }
    St.mapLayers.all = allGroup;
    allGroup.addTo(map);

    // ── Path / route layer ──
    // Build chronological route from all geolocated records
    const pathGroup = L.layerGroup();

    // Use chronological route from geo_records (already sorted by datetime)
    const routeCoords = [];
    let prevLat = null, prevLon = null;
    for (const r of points) {
      const p = r.point;
      // Avoid duplicate consecutive coords
      if (p.lat !== prevLat || p.lon !== prevLon) {
        routeCoords.push([p.lat, p.lon]);
        prevLat = p.lat;
        prevLon = p.lon;
      }
    }

    if (routeCoords.length >= 2) {
      L.polyline(routeCoords, {
        color: "#3b82f6",
        weight: 2.5,
        opacity: 0.6,
        smoothFactor: 1.5,
      }).addTo(pathGroup);
      _addLog("info", `Trasa: ${routeCoords.length} punktów`);
    }

    // Also add path segments from analysis (> 200m movements)
    if (geo.path && geo.path.length) {
      for (const seg of geo.path) {
        const dist_km = (seg.distance_m / 1000).toFixed(1);
        L.polyline(
          [[seg.from_point.lat, seg.from_point.lon],
           [seg.to_point.lat, seg.to_point.lon]],
          { color: "#ef4444", weight: 3, opacity: 0.5 }
        ).bindPopup(`<b>Przemieszczenie</b><br>${dist_km} km<br>${seg.from_datetime} → ${seg.to_datetime}`)
         .addTo(pathGroup);
      }
    }
    St.mapLayers.path = pathGroup;
    pathGroup.addTo(map); // Show path by default

    // ── Clusters layer ──
    const clusterGroup = L.layerGroup();
    if (geo.clusters && geo.clusters.length) {
      for (const c of geo.clusters) {
        const color = c.label === "dom" ? "#22c55e" : c.label === "praca" ? "#3b82f6" : "#f97316";
        const cityTag = c.city ? ` (${c.city})` : "";
        const label = c.label === "dom" ? `DOM${cityTag}` : c.label === "praca" ? `PRACA${cityTag}` : `Lokalizacja${cityTag || ` (${c.record_count})`}`;

        L.circle([c.lat, c.lon], {
          radius: c.radius_m || 500,
          fillColor: color,
          color: color,
          weight: 2,
          fillOpacity: 0.15,
        }).addTo(clusterGroup);

        // Popup with enhanced info
        const wdNames = ["Pn","Wt","Śr","Cz","Pt","Sb","Nd"];
        let wdInfo = "";
        if (c.weekday_counts) {
          const parts = [];
          for (let d = 0; d < 7; d++) {
            const v = c.weekday_counts[d] || c.weekday_counts[String(d)] || 0;
            if (v > 0) parts.push(`${wdNames[d]}:${v}`);
          }
          if (parts.length) wdInfo = `<br>Dni tyg.: ${parts.join(", ")}`;
        }

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
          ${wdInfo}
        `).addTo(clusterGroup);
      }
    }
    St.mapLayers.clusters = clusterGroup;

    // ── Trips layer (inter-city travel arrows) ──
    const tripsGroup = L.layerGroup();
    if (geo.trips && geo.trips.length && geo.clusters && geo.clusters.length) {
      // Aggregate trips by from→to pair for cleaner display
      const tripPairs = {};
      for (const t of geo.trips) {
        const key = `${t.from_cluster_idx}_${t.to_cluster_idx}`;
        if (!tripPairs[key]) tripPairs[key] = { trips: [], from: t.from_cluster_idx, to: t.to_cluster_idx };
        tripPairs[key].trips.push(t);
      }

      for (const pair of Object.values(tripPairs)) {
        const fromC = geo.clusters.find(c => c.cluster_idx === pair.from);
        const toC = geo.clusters.find(c => c.cluster_idx === pair.to);
        if (!fromC || !toC) continue;

        const count = pair.trips.length;
        const avgDist = pair.trips.reduce((s, t) => s + t.distance_km, 0) / count;

        // Draw polyline with arrow-like dash
        const line = L.polyline(
          [[fromC.lat, fromC.lon], [toC.lat, toC.lon]],
          { color: "#8b5cf6", weight: 3, opacity: 0.7, dashArray: "12 6" }
        );

        // Popup with trip details — including travel mode and estimates
        const modeCounts = {};
        pair.trips.forEach(t => { if (t.travel_mode) modeCounts[t.travel_mode] = (modeCounts[t.travel_mode]||0)+1; });
        const modeStr = Object.entries(modeCounts).map(([m,n]) => `${_travelModeIcon(m)} ${_travelModeLabel(m)}: ${n}`).join(", ");
        const sampleTrip = pair.trips[0];
        const estCarStr = sampleTrip.est_car_minutes ? `${_formatHours(sampleTrip.est_car_minutes / 60)}` : "";
        const estFlightStr = sampleTrip.est_flight_minutes ? `${_formatHours(sampleTrip.est_flight_minutes / 60)}` : "";

        let popupHtml = `<b>Podróż: ${fromC.city || "?"} → ${toC.city || "?"}</b><br>
          ${count} ${count === 1 ? "podróż" : "podróży"}, ~${avgDist.toFixed(0)} km<br>`;
        if (modeStr) popupHtml += `${modeStr}<br>`;
        if (estCarStr) popupHtml += `Szac. samochód: ~${estCarStr}`;
        if (estFlightStr) popupHtml += ` | Szac. lot: ~${estFlightStr}`;
        if (estCarStr || estFlightStr) popupHtml += `<br>`;
        for (const t of pair.trips.slice(0, 5)) {
          const icon = _travelModeIcon(t.travel_mode);
          popupHtml += `<div class="small muted">${icon} ${t.depart_datetime} → ${t.arrive_datetime} (${t.distance_km} km, ${t.duration_minutes} min)</div>`;
        }
        if (pair.trips.length > 5) {
          popupHtml += `<div class="small muted">...i ${pair.trips.length - 5} więcej</div>`;
        }
        line.bindPopup(popupHtml);
        tripsGroup.addLayer(line);

        // Arrow marker at midpoint
        const midLat = (fromC.lat + toC.lat) / 2;
        const midLon = (fromC.lon + toC.lon) / 2;
        const arrowIcon = L.divIcon({
          className: "gsm-trip-arrow-icon",
          html: `<div style="background:#8b5cf6;color:#fff;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:bold;white-space:nowrap">${count}×</div>`,
          iconSize: null,
        });
        L.marker([midLat, midLon], { icon: arrowIcon }).addTo(tripsGroup);
      }
      _addLog("info", `Podróże: ${geo.trips.length} między klastrami (${Object.keys(tripPairs).length} unikalnych tras)`);
    }
    St.mapLayers.trips = tripsGroup;

    // ── Border crossings layer ──
    const borderGroup = L.layerGroup();
    if (geo.border_crossings && geo.border_crossings.length) {
      for (const bc of geo.border_crossings) {
        // Try to find cluster locations for departure/return
        const depCity = bc.last_domestic_city;
        const retCity = bc.first_return_city;
        const depCluster = depCity ? geo.clusters.find(c => c.city === depCity) : null;
        const retCluster = retCity ? geo.clusters.find(c => c.city === retCity) : null;

        if (depCluster) {
          L.circleMarker([depCluster.lat, depCluster.lon], {
            radius: 8, fillColor: "#ef4444", color: "#fff", weight: 2, fillOpacity: 0.9,
          }).bindPopup(`<b>Wyjazd za granicę</b><br>${bc.last_domestic_datetime}<br>${depCity}`)
            .addTo(borderGroup);
        }
        if (retCluster) {
          L.circleMarker([retCluster.lat, retCluster.lon], {
            radius: 8, fillColor: "#22c55e", color: "#fff", weight: 2, fillOpacity: 0.9,
          }).bindPopup(`<b>Powrót</b><br>${bc.first_return_datetime}<br>${retCity}`)
            .addTo(borderGroup);
        }
        if (depCluster && retCluster) {
          L.polyline(
            [[depCluster.lat, depCluster.lon], [retCluster.lat, retCluster.lon]],
            { color: "#ef4444", weight: 2, opacity: 0.5, dashArray: "6 4" }
          ).addTo(borderGroup);
        }
      }
    }
    St.mapLayers.border = borderGroup;

    // Fit bounds using unique locations (much smaller than all points)
    const boundsCoords = uniqueLocations.map(loc => [loc.lat, loc.lon]);
    if (boundsCoords.length) {
      map.fitBounds(boundsCoords, { padding: [30, 30], maxZoom: 14 });
    }
  }

  function _switchMapLayer(layer, geo) {
    if (!St.map) return;
    const map = St.map;

    // Remove all custom layers
    Object.values(St.mapLayers).forEach(lg => {
      if (map.hasLayer(lg)) map.removeLayer(lg);
    });

    if (layer === "all") {
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
      if (St.mapLayers.path) St.mapLayers.path.addTo(map);
    }
    if (layer === "path") {
      if (St.mapLayers.path) St.mapLayers.path.addTo(map);
    }
    if (layer === "clusters") {
      if (St.mapLayers.clusters) St.mapLayers.clusters.addTo(map);
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
    if (layer === "trips") {
      if (St.mapLayers.trips) St.mapLayers.trips.addTo(map);
      if (St.mapLayers.clusters) St.mapLayers.clusters.addTo(map);
    }
    if (layer === "border") {
      if (St.mapLayers.border) St.mapLayers.border.addTo(map);
      if (St.mapLayers.clusters) St.mapLayers.clusters.addTo(map);
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
    if (layer === "heatmap") {
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
  }

  /* ── Hour mini-bar chart (for cluster tiles) ── */
  function _hourMiniChart(hour_counts) {
    if (!hour_counts || !Object.keys(hour_counts).length) return "";
    const maxVal = Math.max(1, ...Object.values(hour_counts));
    let bars = "";
    for (let h = 0; h < 24; h++) {
      const v = hour_counts[h] || hour_counts[String(h)] || 0;
      const pct = Math.round((v / maxVal) * 100);
      const isNight = [22,23,0,1,2,3,4,5,6].includes(h);
      const isWork = [8,9,10,11,12,13,14,15,16].includes(h);
      const barColor = isNight ? "#22c55e" : isWork ? "#3b82f6" : "#f97316";
      bars += `<div title="${String(h).padStart(2,'0')}:00 — ${v}" style="width:${100/24}%;height:${Math.max(pct,4)}%;background:${barColor};opacity:0.7;border-radius:1px"></div>`;
    }
    return `<div style="display:flex;align-items:flex-end;height:28px;gap:1px;margin-top:6px" title="Rozkład godzinowy">${bars}</div>`;
  }

  /* ── Weekday pattern label ── */
  function _weekdayLabel(weekday_counts) {
    if (!weekday_counts || !Object.keys(weekday_counts).length) return "";
    const dayNames = ["Pn","Wt","Śr","Cz","Pt","Sb","Nd"];
    let weekdayTotal = 0, weekendTotal = 0;
    for (let d = 0; d < 7; d++) {
      const v = weekday_counts[d] || weekday_counts[String(d)] || 0;
      if (d < 5) weekdayTotal += v; else weekendTotal += v;
    }
    const total = weekdayTotal + weekendTotal;
    if (!total) return "";
    const wdRatio = weekdayTotal / total;
    if (wdRatio > 0.85) return `<span class="small muted" style="display:block;margin-top:2px">głównie Pn–Pt</span>`;
    if (wdRatio < 0.4) return `<span class="small muted" style="display:block;margin-top:2px">głównie weekendy</span>`;
    // Show day distribution
    const topDays = [];
    for (let d = 0; d < 7; d++) {
      const v = weekday_counts[d] || weekday_counts[String(d)] || 0;
      if (v > 0) topDays.push({d, v, name: dayNames[d]});
    }
    topDays.sort((a,b) => b.v - a.v);
    return `<span class="small muted" style="display:block;margin-top:2px">${topDays.slice(0,3).map(x => x.name).join(", ")}</span>`;
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

    // Build trip index: cluster_idx → list of trips from/to
    const tripIndex = {};
    for (const t of (geo.trips || [])) {
      if (!tripIndex[t.from_cluster_idx]) tripIndex[t.from_cluster_idx] = [];
      tripIndex[t.from_cluster_idx].push(t);
    }

    let html = '<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start">';
    const maxTiles = 10;
    const shownClusters = geo.clusters.slice(0, maxTiles);

    for (let ci = 0; ci < shownClusters.length; ci++) {
      const c = shownClusters[ci];
      const color = c.label === "dom" ? "#22c55e" : c.label === "praca" ? "#3b82f6" : "#f97316";
      const cityTag = c.city ? ` (${c.city})` : "";
      const label = c.label === "dom" ? `DOM${cityTag}` : c.label === "praca" ? `PRACA${cityTag}` : `Lokalizacja${cityTag}`;
      const streetStr = c.street || "";

      html += `<div style="border:2px solid ${color};border-radius:12px;padding:10px 14px;min-width:180px;max-width:240px">
        <div style="color:${color};font-weight:bold;margin-bottom:4px">${label}</div>
        ${streetStr ? `<div class="small">${streetStr}</div>` : ""}
        <div class="small muted">${_fmt(c.record_count)} rekordów, ${c.unique_days} dni</div>
        <div class="small muted">${c.first_seen} — ${c.last_seen}</div>
        ${_weekdayLabel(c.weekday_counts)}
        ${_hourMiniChart(c.hour_counts)}
      </div>`;

      // Trip arrows to next clusters
      const tripsFrom = tripIndex[c.cluster_idx] || [];
      if (tripsFrom.length > 0 && ci < shownClusters.length - 1) {
        // Count unique destination clusters, collect travel modes
        const destCounts = {};
        for (const t of tripsFrom) {
          if (!destCounts[t.to_cluster_idx]) destCounts[t.to_cluster_idx] = { count: 0, dist: t.distance_km, city: t.to_city, modes: {} };
          destCounts[t.to_cluster_idx].count++;
          if (t.travel_mode) destCounts[t.to_cluster_idx].modes[t.travel_mode] = (destCounts[t.to_cluster_idx].modes[t.travel_mode] || 0) + 1;
        }
        const destList = Object.values(destCounts);
        const totalTrips = destList.reduce((s, d) => s + d.count, 0);
        // Collect dominant mode icons
        const allModes = {};
        destList.forEach(d => { Object.entries(d.modes).forEach(([m,n]) => { allModes[m] = (allModes[m]||0)+n; }); });
        const modeIcons = Object.keys(allModes).map(m => _travelModeIcon(m)).filter(Boolean).join(" ");
        if (totalTrips > 0) {
          html += `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 4px;color:var(--text-muted)">
            <div style="font-size:18px">${modeIcons || "→"}</div>
            <div class="small" style="white-space:nowrap">${totalTrips} ${totalTrips === 1 ? "podróż" : "podróży"}</div>
          </div>`;
        }
      }
    }
    html += '</div>';

    // Home/work summary
    if (geo.home_cluster) {
      html += `<div class="small" style="margin-top:8px"><b style="color:#22c55e">DOM:</b> ${geo.home_cluster.city || "—"}${geo.home_cluster.street ? ", " + geo.home_cluster.street : ""}</div>`;
    }
    if (geo.work_cluster) {
      html += `<div class="small"><b style="color:#3b82f6">PRACA:</b> ${geo.work_cluster.city || "—"}${geo.work_cluster.street ? ", " + geo.work_cluster.street : ""}</div>`;
    }

    list.innerHTML = html;

    // Render border crossings below clusters
    _renderBorderCrossings(geo);
  }

  /* ── Border crossings section ── */
  function _renderBorderCrossings(geo) {
    let container = QS("#gsm_border_crossings");
    if (!container) {
      // Create container after cluster list if it doesn't exist in template
      const clusterWrap = QS("#gsm_cluster_info");
      if (clusterWrap) {
        container = _el("div", "", "");
        container.id = "gsm_border_crossings";
        clusterWrap.appendChild(container);
      } else return;
    }

    const crossings = geo.border_crossings || [];
    if (!crossings.length) {
      container.style.display = "none";
      return;
    }
    container.style.display = "";

    let html = '<div class="h3" style="margin-top:16px;margin-bottom:8px">Przekroczenia granic / wyjazdy zagraniczne</div>';
    html += '<div style="display:flex;flex-direction:column;gap:8px">';

    for (const bc of crossings) {
      const absence = _formatHours(bc.absence_hours);
      const countries = (bc.roaming_countries || []).map(c => _countryName(c)).join(", ");
      const confirmed = bc.roaming_confirmed
        ? `<span style="color:#22c55e" title="Potwierdzone danymi roamingu">✓ roaming</span>`
        : `<span style="color:#f97316" title="Wykryte na podstawie przerwy w aktywności">⚠ przerwa w aktywności</span>`;

      html += `<div style="border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--bg-secondary)">
        <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">
          <div>
            <span style="color:#ef4444">●</span> <b>Wyjazd:</b> ${bc.last_domestic_datetime || "?"}
            ${bc.last_domestic_city ? `<span class="muted">(${bc.last_domestic_city})</span>` : ""}
          </div>
          <div>
            <span style="color:#22c55e">●</span> <b>Powrót:</b> ${bc.first_return_datetime || "brak danych"}
            ${bc.first_return_city ? `<span class="muted">(${bc.first_return_city})</span>` : ""}
          </div>
        </div>
        <div class="small" style="margin-top:4px">
          Nieobecność: <b>${absence}</b>
          ${countries ? ` · Kraje: <b>${countries}</b>` : ""}
          ${bc.roaming_records ? ` · ${bc.roaming_records} rekordów roamingu` : ""}
          · ${confirmed}
        </div>
      </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
  }

  function _formatHours(h) {
    if (!h || h <= 0) return "—";
    if (h < 1) return `${Math.round(h * 60)} min`;
    const days = Math.floor(h / 24);
    const hrs = Math.round(h % 24);
    if (days > 0) return `${days}d ${hrs}h`;
    return `${hrs}h`;
  }

  /* ── Travel mode label / icon ── */
  function _travelModeLabel(mode) {
    if (mode === "car") return "samochód";
    if (mode === "plane") return "samolot";
    if (mode === "bts_hop") return "przeskok BTS";
    return "";
  }
  function _travelModeIcon(mode) {
    if (mode === "car") return "\uD83D\uDE97";
    if (mode === "plane") return "\u2708\uFE0F";
    return "";
  }

  /* ── Country code → full Polish name mapping ── */
  const _COUNTRY_NAMES = {
    PL:"Polska",DE:"Niemcy",CZ:"Czechy",SK:"Słowacja",UA:"Ukraina",
    BY:"Białoruś",LT:"Litwa",RU:"Rosja",AT:"Austria",CH:"Szwajcaria",
    FR:"Francja",GB:"Wielka Brytania",IT:"Włochy",ES:"Hiszpania",
    NL:"Holandia",BE:"Belgia",DK:"Dania",SE:"Szwecja",NO:"Norwegia",
    FI:"Finlandia",PT:"Portugalia",IE:"Irlandia",HU:"Węgry",RO:"Rumunia",
    BG:"Bułgaria",HR:"Chorwacja",SI:"Słowenia",RS:"Serbia",BA:"Bośnia i Hercegowina",
    ME:"Czarnogóra",MK:"Macedonia Północna",AL:"Albania",GR:"Grecja",TR:"Turcja",
    EE:"Estonia",LV:"Łotwa",LU:"Luksemburg",MT:"Malta",CY:"Cypr",
    IS:"Islandia",MD:"Mołdawia",XK:"Kosowo",US:"USA",CA:"Kanada",
  };
  function _countryName(code) {
    if (!code) return "";
    const up = code.toUpperCase().trim();
    return _COUNTRY_NAMES[up] || up;
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
