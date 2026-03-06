/**
 * GSM Billing Analysis module.
 *
 * Handles XLSX upload, parsing via /api/gsm/parse, and result display.
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

  /* ── activity charts ──────────────────────────────────── */

  /** Build bars HTML from an array of {label, value} */
  function _buildBars(items, cssBarClass) {
    const maxVal = Math.max(1, ...items.map(i => i.value));
    let html = '';
    for (const item of items) {
      const pct = Math.round((item.value / maxVal) * 100);
      html += `<div class="gsm-bar-col${item.wide ? ' gsm-bar-col-wide' : ''}">
        <div class="gsm-bar-value">${item.value}</div>
        <div class="gsm-bar-wrap">
          <div class="gsm-bar ${cssBarClass}" style="height:${Math.max(pct, 4)}%" title="${item.label}: ${item.value}"></div>
        </div>
        <div class="gsm-bar-label">${item.label}</div>
      </div>`;
    }
    return html;
  }

  /** Build anomaly descriptions + overall summary HTML */
  function _buildAnomalies(anomalies) {
    if (!anomalies || !anomalies.length) return '';

    // Separate anomalies from summary
    const items = anomalies.filter(a => a.period_type !== "summary");
    const summaries = anomalies.filter(a => a.period_type === "summary");

    let html = '';

    // Per-period anomalies
    if (items.length) {
      html += '<div class="gsm-chart-anomalies">';
      for (const a of items) {
        const icon = a.ratio > 1 ? '&#9650;' : '&#9660;';
        const cls = a.ratio > 1 ? 'gsm-anomaly-up' : 'gsm-anomaly-down';
        html += `<div class="gsm-chart-anomaly-item ${cls}">
          <span class="gsm-chart-anomaly-icon">${icon}</span> ${a.description}
        </div>`;
      }
      html += '</div>';
    }

    // Overall summary block
    if (summaries.length) {
      html += '<div class="gsm-chart-summary-block">';
      for (const s of summaries) {
        html += `<div>${s.description}</div>`;
      }
      html += '</div>';
    }

    return html;
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

    // --- Night activity ---
    if (night && night.total_records) {
      html += _renderOneActivityChart({
        id: "night",
        title: "Aktywność nocna",
        subtitle: "22:00–6:00",
        data: night,
        barClass: "gsm-bar-night",
        buildTotalBars: () => {
          const hourly = night.hourly || {};
          const hours = [22, 23, 0, 1, 2, 3, 4, 5];
          return _buildBars(
            hours.map(h => ({ label: `${String(h).padStart(2, "0")}:00`, value: hourly[h] || 0 })),
            "gsm-bar-night"
          );
        },
      });
    }

    // --- Weekend activity ---
    if (weekend && weekend.total_records) {
      html += _renderOneActivityChart({
        id: "weekend",
        title: "Aktywność weekendowa",
        subtitle: "Pt 20:00–Pn 6:00",
        data: weekend,
        barClass: "gsm-bar-weekend",
        buildTotalBars: () => {
          const segs = weekend.segments || {};
          return _buildBars([
            { label: "Pt wieczór", value: segs.fri_evening || 0, wide: true },
            { label: "Sobota", value: segs.saturday || 0, wide: true },
            { label: "Niedziela", value: segs.sunday || 0, wide: true },
            { label: "Pn rano", value: segs.mon_morning || 0, wide: true },
          ], "gsm-bar-weekend");
        },
      });
    }

    html += "</div>";
    wrap.innerHTML = html;

    // Bind period selectors
    QSA(".gsm-period-select", wrap).forEach(sel => {
      sel.onchange = () => _onPeriodChange(sel, analysis);
    });
  }

  function _renderOneActivityChart(cfg) {
    const d = cfg.data;
    const weeklyKeys = Object.keys(d.weekly || {});
    const monthlyKeys = Object.keys(d.monthly || {});

    let html = `<div class="gsm-chart-card" data-chart-id="${cfg.id}">
      <div class="gsm-chart-header">
        <div class="h3">${cfg.title} <span class="small muted">(${cfg.subtitle})</span></div>
        <select class="gsm-period-select" data-chart="${cfg.id}">
          <option value="total" selected>Łącznie</option>`;

    // Weekly options
    if (weeklyKeys.length > 1) {
      html += `<optgroup label="Tygodnie">`;
      for (const k of weeklyKeys) {
        const bucket = d.weekly[k];
        html += `<option value="week:${k}">Tydzień ${k} (${bucket.records} rek.)</option>`;
      }
      html += `</optgroup>`;
    }

    // Monthly options
    if (monthlyKeys.length > 1) {
      html += `<optgroup label="Miesiące">`;
      for (const k of monthlyKeys) {
        const bucket = d.monthly[k];
        html += `<option value="month:${k}">Miesiąc ${k} (${bucket.records} rek.)</option>`;
      }
      html += `</optgroup>`;
    }

    html += `</select></div>`;

    // Summary stats
    html += `<div class="gsm-chart-summary">
      <span><b>${_fmt(d.total_records)}</b> rekordów (${d.percentage}% całości)</span>
      <span>Rozmowy: <b>${_fmt(d.calls)}</b></span>
      <span>SMS/MMS: <b>${_fmt(d.sms)}</b></span>
      <span>Dane: <b>${_fmt(d.data)}</b></span>
      <span>Czas: <b>${_dur(d.total_duration_seconds)}</b></span>
    </div>`;

    // Bar chart
    html += `<div class="gsm-bar-chart" data-bars="${cfg.id}">${cfg.buildTotalBars()}</div>`;

    // Anomaly descriptions (below chart)
    html += _buildAnomalies(d.anomalies);

    html += `</div>`;
    return html;
  }

  function _onPeriodChange(selectEl, analysis) {
    const chartId = selectEl.dataset.chart;
    const val = selectEl.value;
    const card = selectEl.closest(".gsm-chart-card");
    const barContainer = QS(`[data-bars="${chartId}"]`, card);
    const summaryEl = QS(".gsm-chart-summary", card);
    if (!barContainer) return;

    const src = chartId === "night" ? analysis.night_activity : analysis.weekend_activity;
    if (!src) return;

    let bucket = null;
    let periodLabel = "Łącznie";

    if (val === "total") {
      bucket = src;
    } else if (val.startsWith("week:")) {
      const key = val.slice(5);
      bucket = (src.weekly || {})[key];
      periodLabel = `Tydzień ${key}`;
    } else if (val.startsWith("month:")) {
      const key = val.slice(6);
      bucket = (src.monthly || {})[key];
      periodLabel = `Miesiąc ${key}`;
    }

    if (!bucket) return;

    // Update summary
    if (summaryEl) {
      const recs = val === "total" ? bucket.total_records : bucket.records;
      const dur = val === "total" ? bucket.total_duration_seconds : (bucket.duration_sec || 0);
      summaryEl.innerHTML = `
        <span><b>${_fmt(recs)}</b> rekordów${val === "total" ? ` (${bucket.percentage}% całości)` : ` — ${periodLabel}`}</span>
        <span>Rozmowy: <b>${_fmt(bucket.calls)}</b></span>
        <span>SMS/MMS: <b>${_fmt(bucket.sms)}</b></span>
        <span>Dane: <b>${_fmt(bucket.data)}</b></span>
        <span>Czas: <b>${_dur(dur)}</b></span>`;
    }

    // Update bars
    if (chartId === "night") {
      if (val === "total") {
        const hourly = src.hourly || {};
        const hours = [22, 23, 0, 1, 2, 3, 4, 5];
        barContainer.innerHTML = _buildBars(
          hours.map(h => ({ label: `${String(h).padStart(2, "0")}:00`, value: hourly[h] || 0 })),
          "gsm-bar-night"
        );
      } else {
        // For week/month — show single summary bar with breakdown
        barContainer.innerHTML = _buildBars([
          { label: "Rozmowy", value: bucket.calls || 0 },
          { label: "SMS/MMS", value: bucket.sms || 0 },
          { label: "Dane", value: bucket.data || 0 },
          { label: "Inne", value: bucket.other || 0 },
        ], "gsm-bar-night");
      }
    } else {
      // Weekend
      if (val === "total") {
        const segs = src.segments || {};
        barContainer.innerHTML = _buildBars([
          { label: "Pt wieczór", value: segs.fri_evening || 0, wide: true },
          { label: "Sobota", value: segs.saturday || 0, wide: true },
          { label: "Niedziela", value: segs.sunday || 0, wide: true },
          { label: "Pn rano", value: segs.mon_morning || 0, wide: true },
        ], "gsm-bar-weekend");
      } else {
        barContainer.innerHTML = _buildBars([
          { label: "Pt wieczór", value: bucket.fri_evening || 0, wide: true },
          { label: "Sobota", value: bucket.saturday || 0, wide: true },
          { label: "Niedziela", value: bucket.sunday || 0, wide: true },
          { label: "Pn rano", value: bucket.mon_morning || 0, wide: true },
        ], "gsm-bar-weekend");
      }
    }
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
