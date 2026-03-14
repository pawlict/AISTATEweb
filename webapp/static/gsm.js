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
    /* Identification lookup: normalised MSISDN → {label, type, name, ...} */
    idMap: {},
    /* Timeline state — v4 */
    tlAllRecords: [],     // all valid geo_records sorted by datetime
    tlAllWaypoints: [],   // global waypoints across all days
    tlDays: [],           // sorted unique dates
    tlDayBoundaries: [],  // [{day, startIdx, endIdx}] for each day
    tlIdx: 0,             // current position in tlAllWaypoints
    tlPlaying: false,
    tlSpeed: 1,           // 1×, 2×, 5×, 10×
    tlTimer: null,        // fallback timer handle
    tlAnimFrame: null,    // requestAnimationFrame handle
    tlMarker: null,       // Leaflet marker (divIcon with mode emoji)
    tlVisitedTrail: null, // faint visited path polyline
    tlFullRoute: null,    // full route polyline (gray dashed)
    tlRouteDots: null,    // layerGroup for waypoint dots
    tlFadeSegments: [],   // fading trail segments (Marauder's Map)
    tlTrailCoords: [],    // accumulated [lat,lon] for visited trail
    tlSavedZoom: null,    // zoom level before timeline play
    /* Heatmap state */
    hmData: null,          // {grid, months, maxTotal}
    hmActiveCell: null,    // {hour, dow} — active filter cell
    hmMonth: "all",        // selected month filter
    hmType: "all",         // selected type filter: all, calls, sms, data
    /* Column & filter state */
    columnOrder: null,       // array of column keys (user-ordered); null = use defaults
    columnHidden: {},        // { colKey: true } for hidden columns
    columnFilters: {},       // { colKey: { mode, value, ... } } active filters
    columnSort: null,        // { key, dir } — current sort column
    /* Area selection state */
    areaSelectMode: null,     // null | "circle" | "rect"
    areaSelectLayer: null,    // temporary Leaflet shape while drawing
    areaSelectOrigin: null,   // L.LatLng — mousedown start point
    areaHighlights: null,     // L.layerGroup with highlighted markers
    areaShape: null,          // persistent Leaflet shape (circle/rect) after selection
    areaLocations: [],        // cached uniqueLocations for selection queries
    overlayMilitary: null,    // L.layerGroup — military overlay markers
    overlayAirports: null,    // L.layerGroup — civilian airport overlay markers
    overlayDiplomacy: null,   // L.layerGroup — diplomatic posts overlay
    overlayMilitaryData: null,// cached JSON data
    overlayAirportsData: null,// cached JSON data
    overlayDiplomacyData: null,// cached JSON data
  };

  /* ── Column definitions ─────────────────────────────────── */

  /**
   * Each column definition:
   *  key         — unique id matching BillingRecord field path
   *  label       — display name (Polish)
   *  type        — "text" | "categorical" | "numeric" | "boolean"
   *  defaultVisible — shown by default
   *  getValue    — fn(record) → raw value for filtering / sorting
   *  renderCell  — fn(record) → HTML string for table cell
   *  categoryValues — fn(records) → [{value,label,count}] for categorical
   *  unit        — optional unit label for numeric columns
   */
  const _COL_DEFS = [
    {
      key: "context_label", label: "Kontekst", type: "categorical", defaultVisible: false,
      getValue: r => {
        const hl = St._anomalyHighlight;
        if (!hl) return "";
        if (hl.anomalyRecords && hl.anomalyRecords.has(r)) return "ANOMALIA";
        if (hl.contextRecords && hl.contextRecords.has(r)) return "KONTEKST";
        return "";
      },
      renderCell: r => {
        const hl = St._anomalyHighlight;
        if (!hl) return "";
        if (hl.anomalyRecords && hl.anomalyRecords.has(r))
          return '<span style="font-size:9px;font-weight:700;color:rgba(220,38,38,.7);letter-spacing:.5px;text-transform:uppercase">ANOMALIA</span>';
        if (hl.contextRecords && hl.contextRecords.has(r))
          return '<span style="font-size:9px;font-weight:700;color:rgba(37,99,235,.65);letter-spacing:.5px;text-transform:uppercase">KONTEKST</span>';
        return "";
      },
      categoryValues: recs => {
        const vals = ["ANOMALIA", "KONTEKST"];
        return vals.map(v => ({ value: v, label: v, count: recs.filter(r => {
          const hl = St._anomalyHighlight;
          if (!hl) return false;
          if (v === "ANOMALIA") return hl.anomalyRecords && hl.anomalyRecords.has(r);
          return hl.contextRecords && hl.contextRecords.has(r);
        }).length }));
      },
    },
    {
      key: "datetime", label: "Data i czas", type: "text", defaultVisible: true,
      getValue: r => r.datetime || "",
      renderCell: r => r.datetime || "",
    },
    {
      key: "date", label: "Data", type: "text", defaultVisible: false,
      getValue: r => r.date || "",
      renderCell: r => r.date || "",
    },
    {
      key: "time", label: "Godzina", type: "text", defaultVisible: false,
      getValue: r => r.time || "",
      renderCell: r => r.time || "",
    },
    {
      key: "record_type", label: "Typ", type: "categorical", defaultVisible: true,
      getValue: r => r.record_type || "",
      renderCell: r => {
        const t = r.record_type || "";
        return `<span class="gsm-type gsm-type-${t}">${_typeLabel(t)}</span>`;
      },
      categoryValues: recs => {
        const counts = {};
        for (const r of recs) { const v = r.record_type || ""; counts[v] = (counts[v] || 0) + 1; }
        return Object.keys(counts).sort().map(v => ({ value: v, label: _typeLabel(v), count: counts[v] }));
      },
    },
    {
      key: "direction", label: "Kierunek", type: "categorical", defaultVisible: true,
      getValue: r => (r.extra || {}).direction || "",
      renderCell: r => (r.extra || {}).direction || "",
      categoryValues: recs => {
        const counts = {};
        for (const r of recs) { const v = (r.extra || {}).direction || ""; if (v) counts[v] = (counts[v] || 0) + 1; }
        return Object.keys(counts).sort().map(v => ({ value: v, label: v, count: counts[v] }));
      },
    },
    {
      key: "callee", label: "Numer (MSISDN B)", type: "text", defaultVisible: true,
      getValue: r => r.callee || "",
      renderCell: r => r.callee ? `<code>${r.callee}</code>` : "—",
    },
    {
      key: "caller", label: "Numer dzwoniącego", type: "text", defaultVisible: false,
      getValue: r => r.caller || "",
      renderCell: r => r.caller ? `<code>${r.caller}</code>` : "—",
    },
    {
      key: "identification", label: "Identyfikacja", type: "text", defaultVisible: true,
      getValue: r => { const info = _idLookup(r.callee); return info ? info.label : ""; },
      renderCell: r => _idCell(r.callee),
    },
    {
      key: "duration_seconds", label: "Czas trwania", type: "numeric", defaultVisible: true, unit: "s",
      getValue: r => r.duration_seconds || 0,
      renderCell: r => r.duration_seconds ? _dur(r.duration_seconds) : "—",
    },
    {
      key: "data_volume_kb", label: "Dane (KB)", type: "numeric", defaultVisible: false, unit: "KB",
      getValue: r => r.data_volume_kb || 0,
      renderCell: r => r.data_volume_kb ? _fmt(Math.round(r.data_volume_kb)) + " KB" : "—",
    },
    {
      key: "location", label: "Lokalizacja", type: "text", defaultVisible: true,
      getValue: r => r.location || "",
      renderCell: r => r.location || "—",
    },
    {
      key: "location_lac", label: "LAC", type: "text", defaultVisible: false,
      getValue: r => r.location_lac || "",
      renderCell: r => r.location_lac || "—",
    },
    {
      key: "location_cell_id", label: "Cell ID", type: "text", defaultVisible: false,
      getValue: r => r.location_cell_id || "",
      renderCell: r => r.location_cell_id || "—",
    },
    {
      key: "network", label: "Sieć", type: "categorical", defaultVisible: true,
      getValue: r => r.network || "",
      renderCell: r => r.network || "—",
      categoryValues: recs => {
        const counts = {};
        for (const r of recs) { const v = r.network || ""; if (v) counts[v] = (counts[v] || 0) + 1; }
        return Object.keys(counts).sort().map(v => ({ value: v, label: v, count: counts[v] }));
      },
    },
    {
      key: "roaming", label: "Roaming", type: "boolean", defaultVisible: false,
      getValue: r => r.roaming ? "Tak" : "Nie",
      renderCell: r => r.roaming ? "Tak" : "Nie",
      categoryValues: () => [
        { value: "Tak", label: "Tak", count: 0 },
        { value: "Nie", label: "Nie", count: 0 },
      ],
    },
    {
      key: "roaming_country", label: "Kraj roamingu", type: "text", defaultVisible: false,
      getValue: r => r.roaming_country || "",
      renderCell: r => r.roaming_country || "—",
    },
    {
      key: "imsi", label: "IMSI", type: "text", defaultVisible: false,
      getValue: r => r.imsi || "",
      renderCell: r => r.imsi ? `<code>${r.imsi}</code>` : "—",
    },
    {
      key: "imei", label: "IMEI", type: "text", defaultVisible: false,
      getValue: r => r.imei || "",
      renderCell: r => r.imei ? `<code>${r.imei}</code>` : "—",
    },
  ];

  const _COL_MAP = {};
  for (const c of _COL_DEFS) _COL_MAP[c.key] = c;

  /** Get visible columns in current order. */
  function _visibleColumns() {
    const order = St.columnOrder || _COL_DEFS.map(c => c.key);
    return order.filter(k => !St.columnHidden[k] && _COL_MAP[k]).map(k => _COL_MAP[k]);
  }

  /** Initialize column order + visibility from defaults (called once). */
  function _initColumns() {
    if (!St.columnOrder) {
      St.columnOrder = _COL_DEFS.map(c => c.key);
      St.columnHidden = {};
      for (const c of _COL_DEFS) {
        if (!c.defaultVisible) St.columnHidden[c.key] = true;
      }
    }
  }

  /* ── Filter engine ──────────────────────────────────────── */

  /** Text filter modes. */
  const _TEXT_FILTERS = [
    { id: "contains",    label: "Fragment",     desc: "grep -i \"tekst\"" },
    { id: "exact",       label: "Zgodność",     desc: "grep -x \"wartość\"" },
    { id: "exclude",     label: "Odrzucenie",   desc: "grep -xv \"wartość\"" },
    { id: "not_contains",label: "Wykluczenie",  desc: "grep -vi \"tekst\"" },
    { id: "starts",      label: "Początek",     desc: "grep \"^tekst\"" },
    { id: "ends",        label: "Zakończenie",  desc: "grep \"tekst$\"" },
    { id: "regex",       label: "Wzorzec",      desc: "grep -E \"regex\"" },
  ];

  /** Numeric filter modes. */
  const _NUM_FILTERS = [
    { id: "eq",    label: "Równe (=)",          symbol: "=" },
    { id: "neq",   label: "Różne od (≠)",       symbol: "≠" },
    { id: "gt",    label: "Większe niż (>)",     symbol: ">" },
    { id: "lt",    label: "Mniejsze niż (<)",    symbol: "<" },
    { id: "gte",   label: "Większe lub równe (≥)", symbol: "≥" },
    { id: "lte",   label: "Mniejsze lub równe (≤)", symbol: "≤" },
    { id: "range", label: "Zakres (od — do)",    symbol: "↔" },
    { id: "regex", label: "Wzorzec (grep)",      symbol: "~" },
  ];

  /**
   * Test a single value against a filter.
   * @param {string|number} val — raw value from getValue()
   * @param {object} filter — { mode, value, value2?, ignoreCase?, checkedValues? }
   * @param {object} colDef — column definition
   * @returns {boolean}
   */
  function _testFilter(val, filter, colDef) {
    // Categorical / boolean checkbox filter
    if (filter.checkedValues) {
      const sv = String(val);
      // If using categoryValues from colDef, match against value; for display match against label
      return filter.checkedValues.has(sv);
    }

    const fv = filter.value || "";
    if (!fv && filter.mode !== "range") return true; // empty filter = pass

    // Numeric filters
    if (colDef.type === "numeric" && filter.mode !== "regex") {
      const numVal = typeof val === "number" ? val : parseFloat(val);
      if (isNaN(numVal)) return false;
      const numFv = parseFloat(fv);
      switch (filter.mode) {
        case "eq":  return numVal === numFv;
        case "neq": return numVal !== numFv;
        case "gt":  return numVal > numFv;
        case "lt":  return numVal < numFv;
        case "gte": return numVal >= numFv;
        case "lte": return numVal <= numFv;
        case "range": {
          const lo = parseFloat(fv);
          const hi = parseFloat(filter.value2 || "");
          if (isNaN(lo) || isNaN(hi)) return true;
          return numVal >= lo && numVal <= hi;
        }
        default: return true;
      }
    }

    // Text filters
    const sv = String(val);
    const ic = filter.ignoreCase !== false;
    const a = ic ? sv.toLowerCase() : sv;
    const b = ic ? fv.toLowerCase() : fv;
    switch (filter.mode) {
      case "exact":        return a === b;
      case "exclude":      return a !== b;
      case "contains":     return a.includes(b);
      case "not_contains": return !a.includes(b);
      case "starts":       return a.startsWith(b);
      case "ends":         return a.endsWith(b);
      case "regex": {
        try {
          const rx = new RegExp(fv, ic ? "i" : "");
          return rx.test(sv);
        } catch (_) { return true; }
      }
      default: return true;
    }
  }

  /** Apply all active column filters to records. Returns filtered array. */
  function _applyColumnFilters(records) {
    const keys = Object.keys(St.columnFilters);
    if (!keys.length) return records;
    return records.filter(r => {
      for (const k of keys) {
        const colDef = _COL_MAP[k];
        if (!colDef) continue;
        const val = colDef.getValue(r);
        if (!_testFilter(val, St.columnFilters[k], colDef)) return false;
      }
      return true;
    });
  }

  /** Count active column filters. */
  function _activeFilterCount() {
    return Object.keys(St.columnFilters).length;
  }

  /* ── Column Filter Dropdown UI ──────────────────────────── */

  let _openFilterDropdown = null; // reference to open dropdown element

  function _closeFilterDropdown() {
    if (_openFilterDropdown) {
      _openFilterDropdown.remove();
      _openFilterDropdown = null;
    }
    document.removeEventListener("mousedown", _onFilterOutsideClick, true);
  }

  function _onFilterOutsideClick(e) {
    if (_openFilterDropdown && !_openFilterDropdown.contains(e.target)) {
      // Don't close if clicking on the header that opened it
      if (e.target.closest && e.target.closest(".gsm-col-filter-btn")) return;
      _closeFilterDropdown();
    }
  }

  /**
   * Open a filter dropdown for a column.
   * @param {string} colKey — column key
   * @param {HTMLElement} anchor — the th element to anchor below
   */
  function _openColFilter(colKey, anchor) {
    _closeFilterDropdown();
    _closeColumnPanel();

    const colDef = _COL_MAP[colKey];
    if (!colDef) return;

    const drop = document.createElement("div");
    drop.className = "gsm-filter-dropdown";

    const existing = St.columnFilters[colKey] || null;
    const records = St.lastResult ? St.lastResult.records : [];

    if (colDef.type === "categorical" || colDef.type === "boolean") {
      _buildCategoryFilterUI(drop, colDef, existing, records);
    } else if (colDef.type === "numeric") {
      _buildNumericFilterUI(drop, colDef, existing);
    } else {
      _buildTextFilterUI(drop, colDef, existing);
    }

    document.body.appendChild(drop);
    _openFilterDropdown = drop;

    // Position
    const rect = anchor.getBoundingClientRect();
    let left = rect.left;
    let top = rect.bottom + 4;
    // Keep within viewport
    const dw = drop.offsetWidth;
    if (left + dw > window.innerWidth - 8) left = window.innerWidth - dw - 8;
    if (left < 4) left = 4;
    drop.style.left = left + "px";
    drop.style.top = top + "px";

    setTimeout(() => document.addEventListener("mousedown", _onFilterOutsideClick, true), 0);
  }

  /** Build text filter UI inside dropdown. */
  function _buildTextFilterUI(drop, colDef, existing) {
    const mode = existing ? existing.mode : "contains";
    const val = existing ? (existing.value || "") : "";
    const ic = existing ? existing.ignoreCase !== false : true;

    drop.innerHTML = `
      <div class="gsm-fd-header">Filtr: ${colDef.label}<button class="gsm-fd-close" title="Zamknij">✕</button></div>
      <div class="gsm-fd-body">
        <label class="gsm-fd-label">Typ filtra</label>
        <div class="gsm-fd-modes">${_TEXT_FILTERS.map(f =>
          `<label class="gsm-fd-radio"><input type="radio" name="fmode" value="${f.id}" ${f.id === mode ? "checked" : ""}><span>${f.label}</span><span class="gsm-fd-grep">${f.desc}</span></label>`
        ).join("")}</div>
        <label class="gsm-fd-label" style="margin-top:8px">Wartość</label>
        <input type="text" class="gsm-fd-input" value="${_escAttr(val)}" placeholder="Wpisz wartość...">
        <label class="gsm-fd-check"><input type="checkbox" ${ic ? "checked" : ""}> Ignoruj wielkość liter</label>
      </div>
      <div class="gsm-fd-footer">
        <button class="gsm-fd-apply">Zastosuj</button>
        <button class="gsm-fd-clear">Wyczyść</button>
      </div>`;

    drop.querySelector(".gsm-fd-close").onclick = () => _closeFilterDropdown();
    drop.querySelector(".gsm-fd-apply").onclick = () => {
      const selMode = drop.querySelector('input[name="fmode"]:checked').value;
      const selVal = drop.querySelector(".gsm-fd-input").value;
      const selIc = drop.querySelector(".gsm-fd-check input").checked;
      if (selVal.trim()) {
        St.columnFilters[colDef.key] = { mode: selMode, value: selVal, ignoreCase: selIc };
      } else {
        delete St.columnFilters[colDef.key];
      }
      _closeFilterDropdown();
      _refilterRecords();
    };
    drop.querySelector(".gsm-fd-clear").onclick = () => {
      delete St.columnFilters[colDef.key];
      _closeFilterDropdown();
      _refilterRecords();
    };
    // Auto-focus input
    setTimeout(() => drop.querySelector(".gsm-fd-input").focus(), 50);
  }

  /** Build numeric filter UI inside dropdown. */
  function _buildNumericFilterUI(drop, colDef, existing) {
    const mode = existing ? existing.mode : "gt";
    const val = existing ? (existing.value || "") : "";
    const val2 = existing ? (existing.value2 || "") : "";
    const unit = colDef.unit || "";

    drop.innerHTML = `
      <div class="gsm-fd-header">Filtr: ${colDef.label}<button class="gsm-fd-close" title="Zamknij">✕</button></div>
      <div class="gsm-fd-body">
        <label class="gsm-fd-label">Typ filtra</label>
        <div class="gsm-fd-modes">${_NUM_FILTERS.map(f =>
          `<label class="gsm-fd-radio"><input type="radio" name="fmode" value="${f.id}" ${f.id === mode ? "checked" : ""}><span>${f.label}</span></label>`
        ).join("")}</div>
        <label class="gsm-fd-label" style="margin-top:8px">Wartość ${unit ? "(" + unit + ")" : ""}</label>
        <div class="gsm-fd-num-row">
          <input type="number" class="gsm-fd-input gsm-fd-num1" value="${_escAttr(val)}" placeholder="Wartość" step="any">
          <input type="number" class="gsm-fd-input gsm-fd-num2" value="${_escAttr(val2)}" placeholder="Do" step="any" style="display:${mode === "range" ? "" : "none"}">
        </div>
      </div>
      <div class="gsm-fd-footer">
        <button class="gsm-fd-apply">Zastosuj</button>
        <button class="gsm-fd-clear">Wyczyść</button>
      </div>`;

    // Show/hide range second input
    drop.querySelectorAll('input[name="fmode"]').forEach(radio => {
      radio.onchange = () => {
        drop.querySelector(".gsm-fd-num2").style.display = radio.value === "range" ? "" : "none";
      };
    });

    drop.querySelector(".gsm-fd-close").onclick = () => _closeFilterDropdown();
    drop.querySelector(".gsm-fd-apply").onclick = () => {
      const selMode = drop.querySelector('input[name="fmode"]:checked').value;
      const selVal = drop.querySelector(".gsm-fd-num1").value;
      const selVal2 = drop.querySelector(".gsm-fd-num2").value;
      if (selMode === "regex") {
        if (selVal.trim()) {
          St.columnFilters[colDef.key] = { mode: "regex", value: selVal, ignoreCase: true };
        } else {
          delete St.columnFilters[colDef.key];
        }
      } else if (selVal.trim() || (selMode === "range" && selVal2.trim())) {
        St.columnFilters[colDef.key] = { mode: selMode, value: selVal, value2: selVal2 };
      } else {
        delete St.columnFilters[colDef.key];
      }
      _closeFilterDropdown();
      _refilterRecords();
    };
    drop.querySelector(".gsm-fd-clear").onclick = () => {
      delete St.columnFilters[colDef.key];
      _closeFilterDropdown();
      _refilterRecords();
    };
    setTimeout(() => drop.querySelector(".gsm-fd-num1").focus(), 50);
  }

  /** Build categorical / boolean filter UI inside dropdown. */
  function _buildCategoryFilterUI(drop, colDef, existing, records) {
    // Compute category values from actual data
    let cats = [];
    if (colDef.categoryValues) {
      cats = colDef.categoryValues(records);
    }
    // For boolean with real counts
    if (colDef.type === "boolean" && cats.length) {
      const counts = { Tak: 0, Nie: 0 };
      for (const r of records) {
        const v = colDef.getValue(r);
        counts[v] = (counts[v] || 0) + 1;
      }
      cats = [
        { value: "Tak", label: "Tak", count: counts["Tak"] || 0 },
        { value: "Nie", label: "Nie", count: counts["Nie"] || 0 },
      ];
    }

    const checkedSet = existing && existing.checkedValues ? existing.checkedValues : null;
    const allChecked = !checkedSet; // all checked by default when no filter

    // Also allow text filter below checkboxes
    const textMode = existing && existing.mode ? existing.mode : "";
    const textVal = existing && existing.value && !existing.checkedValues ? existing.value : "";

    drop.innerHTML = `
      <div class="gsm-fd-header">Filtr: ${colDef.label}<button class="gsm-fd-close" title="Zamknij">✕</button></div>
      <div class="gsm-fd-body">
        <label class="gsm-fd-check gsm-fd-select-all"><input type="checkbox" ${allChecked ? "checked" : ""}> Zaznacz wszystkie</label>
        <div class="gsm-fd-cats">${cats.map(c => {
          const chk = allChecked || (checkedSet && checkedSet.has(c.value));
          return `<label class="gsm-fd-check gsm-fd-cat-item"><input type="checkbox" value="${_escAttr(c.value)}" ${chk ? "checked" : ""}><span>${c.label}</span><span class="gsm-fd-cat-count">(${c.count})</span></label>`;
        }).join("")}</div>
        <div class="gsm-fd-separator">— lub wyszukaj tekstowo —</div>
        <div class="gsm-fd-modes gsm-fd-modes-sm">${_TEXT_FILTERS.filter(f => ["starts","ends","regex"].includes(f.id)).map(f =>
          `<label class="gsm-fd-radio"><input type="radio" name="fmode" value="${f.id}" ${f.id === textMode ? "checked" : ""}><span>${f.label}</span></label>`
        ).join("")}</div>
        <input type="text" class="gsm-fd-input gsm-fd-cat-text" value="${_escAttr(textVal)}" placeholder="Wpisz wartość...">
      </div>
      <div class="gsm-fd-footer">
        <button class="gsm-fd-apply">Zastosuj</button>
        <button class="gsm-fd-clear">Wyczyść</button>
      </div>`;

    // Select all toggle
    const selAll = drop.querySelector(".gsm-fd-select-all input");
    const catBoxes = drop.querySelectorAll(".gsm-fd-cat-item input");
    selAll.onchange = () => {
      catBoxes.forEach(cb => cb.checked = selAll.checked);
    };
    catBoxes.forEach(cb => {
      cb.onchange = () => {
        const total = catBoxes.length;
        const checked = [...catBoxes].filter(x => x.checked).length;
        selAll.checked = checked === total;
        selAll.indeterminate = checked > 0 && checked < total;
      };
    });

    drop.querySelector(".gsm-fd-close").onclick = () => _closeFilterDropdown();
    drop.querySelector(".gsm-fd-apply").onclick = () => {
      const textInput = drop.querySelector(".gsm-fd-cat-text").value.trim();
      const modeRadio = drop.querySelector('input[name="fmode"]:checked');

      if (textInput && modeRadio) {
        // Text filter mode takes precedence
        St.columnFilters[colDef.key] = { mode: modeRadio.value, value: textInput, ignoreCase: true };
      } else {
        // Checkbox mode
        const checked = [...catBoxes].filter(x => x.checked).map(x => x.value);
        if (checked.length === catBoxes.length || checked.length === 0) {
          // All or none = no filter
          delete St.columnFilters[colDef.key];
        } else {
          St.columnFilters[colDef.key] = { checkedValues: new Set(checked) };
        }
      }
      _closeFilterDropdown();
      _refilterRecords();
    };
    drop.querySelector(".gsm-fd-clear").onclick = () => {
      delete St.columnFilters[colDef.key];
      _closeFilterDropdown();
      _refilterRecords();
    };
  }

  function _escAttr(s) { return String(s).replace(/"/g, "&quot;").replace(/</g, "&lt;"); }

  /* ── Column Visibility Panel ────────────────────────────── */

  let _openColumnPanel = null;

  function _closeColumnPanel() {
    if (_openColumnPanel) {
      _openColumnPanel.remove();
      _openColumnPanel = null;
    }
    document.removeEventListener("mousedown", _onColPanelOutsideClick, true);
  }

  function _onColPanelOutsideClick(e) {
    if (_openColumnPanel && !_openColumnPanel.contains(e.target)) {
      if (e.target.closest && e.target.closest("#gsm_columns_btn")) return;
      _closeColumnPanel();
    }
  }

  function _openColumnsPanel(anchor) {
    _closeColumnPanel();
    _closeFilterDropdown();
    _initColumns();

    const panel = document.createElement("div");
    panel.className = "gsm-col-panel";

    const order = St.columnOrder || _COL_DEFS.map(c => c.key);

    let html = `<div class="gsm-fd-header">Widoczne kolumny<button class="gsm-fd-close" title="Zamknij">✕</button></div>`;
    html += `<div class="gsm-col-panel-list">`;
    for (const k of order) {
      const col = _COL_MAP[k];
      if (!col) continue;
      const visible = !St.columnHidden[k];
      html += `<div class="gsm-col-panel-item" draggable="true" data-key="${k}">
        <span class="gsm-col-drag-handle" title="Przeciągnij">☰</span>
        <label class="gsm-col-panel-check"><input type="checkbox" data-key="${k}" ${visible ? "checked" : ""}> ${col.label}</label>
      </div>`;
    }
    html += `</div>`;
    html += `<div class="gsm-fd-footer"><button class="gsm-col-show-all">Pokaż wszystkie</button><button class="gsm-col-defaults">Domyślne</button></div>`;
    panel.innerHTML = html;

    document.body.appendChild(panel);
    _openColumnPanel = panel;

    // Position
    const rect = anchor.getBoundingClientRect();
    let left = rect.left;
    let top = rect.bottom + 4;
    const pw = panel.offsetWidth;
    if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
    if (left < 4) left = 4;
    panel.style.left = left + "px";
    panel.style.top = top + "px";

    // Close button
    panel.querySelector(".gsm-fd-close").onclick = () => _closeColumnPanel();

    // Checkbox changes
    panel.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.onchange = () => {
        const key = cb.dataset.key;
        if (cb.checked) {
          delete St.columnHidden[key];
        } else {
          St.columnHidden[key] = true;
        }
        _refilterRecords();
      };
    });

    // Show all
    panel.querySelector(".gsm-col-show-all").onclick = () => {
      St.columnHidden = {};
      panel.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
      _refilterRecords();
    };

    // Defaults
    panel.querySelector(".gsm-col-defaults").onclick = () => {
      St.columnOrder = _COL_DEFS.map(c => c.key);
      St.columnHidden = {};
      for (const c of _COL_DEFS) { if (!c.defaultVisible) St.columnHidden[c.key] = true; }
      _closeColumnPanel();
      _refilterRecords();
    };

    // Drag & drop reordering
    let dragKey = null;
    const listEl = panel.querySelector(".gsm-col-panel-list");
    listEl.addEventListener("dragstart", e => {
      const item = e.target.closest(".gsm-col-panel-item");
      if (!item) return;
      dragKey = item.dataset.key;
      item.classList.add("gsm-col-dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    listEl.addEventListener("dragend", e => {
      const item = e.target.closest(".gsm-col-panel-item");
      if (item) item.classList.remove("gsm-col-dragging");
      dragKey = null;
      listEl.querySelectorAll(".gsm-col-panel-item").forEach(el => el.classList.remove("gsm-col-drag-over"));
    });
    listEl.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const target = e.target.closest(".gsm-col-panel-item");
      if (target) {
        listEl.querySelectorAll(".gsm-col-panel-item").forEach(el => el.classList.remove("gsm-col-drag-over"));
        target.classList.add("gsm-col-drag-over");
      }
    });
    listEl.addEventListener("drop", e => {
      e.preventDefault();
      const target = e.target.closest(".gsm-col-panel-item");
      if (!target || !dragKey) return;
      const targetKey = target.dataset.key;
      if (dragKey === targetKey) return;
      // Reorder in St.columnOrder
      const order = St.columnOrder;
      const fromIdx = order.indexOf(dragKey);
      const toIdx = order.indexOf(targetKey);
      if (fromIdx === -1 || toIdx === -1) return;
      order.splice(fromIdx, 1);
      order.splice(toIdx, 0, dragKey);
      // Reorder DOM
      const dragEl = listEl.querySelector(`.gsm-col-panel-item[data-key="${dragKey}"]`);
      if (fromIdx < toIdx) {
        target.after(dragEl);
      } else {
        target.before(dragEl);
      }
      listEl.querySelectorAll(".gsm-col-panel-item").forEach(el => el.classList.remove("gsm-col-drag-over"));
      _refilterRecords();
    });

    setTimeout(() => document.addEventListener("mousedown", _onColPanelOutsideClick, true), 0);
  }

  /* ── Filter Chips Bar ───────────────────────────────────── */

  function _renderFilterChips() {
    const bar = QS("#gsm_filter_chips");
    if (!bar) return;
    const keys = Object.keys(St.columnFilters);
    if (!keys.length) {
      bar.style.display = "none";
      return;
    }
    bar.style.display = "";
    let html = '<span class="gsm-fc-label">Filtry kolumn:</span>';
    for (const k of keys) {
      const colDef = _COL_MAP[k];
      if (!colDef) continue;
      const f = St.columnFilters[k];
      let desc = "";
      if (f.checkedValues) {
        const vals = [...f.checkedValues];
        desc = vals.length <= 2 ? vals.join(", ") : vals.slice(0, 2).join(", ") + "…";
      } else if (f.mode === "range") {
        desc = `${f.value || "?"} — ${f.value2 || "?"}`;
      } else {
        const modeLabel = [..._TEXT_FILTERS, ..._NUM_FILTERS].find(m => m.id === f.mode);
        desc = (modeLabel ? (modeLabel.symbol || modeLabel.label) + " " : "") + `"${f.value || ""}"`;
      }
      html += `<span class="gsm-fc-chip" data-key="${k}">${colDef.label}: ${desc} <button class="gsm-fc-remove" data-key="${k}" title="Usuń filtr">✕</button></span>`;
    }
    html += `<button class="gsm-fc-clear-all" title="Wyczyść wszystkie filtry kolumn">Wyczyść ▿</button>`;
    bar.innerHTML = html;

    // Bind chip remove buttons
    bar.querySelectorAll(".gsm-fc-remove").forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        delete St.columnFilters[btn.dataset.key];
        _refilterRecords();
      };
    });
    bar.querySelector(".gsm-fc-clear-all").onclick = () => {
      St.columnFilters = {};
      _refilterRecords();
    };
  }

  /* ── Re-filter and re-render records ────────────────────── */

  /** The "source" records currently fed into the table (may already be pre-filtered by heatmap/map/analysis). */
  let _currentSourceRecords = null;
  let _currentSourceTruncated = false;
  let _currentSourceTotal = 0;

  /** Central re-filter: apply column filters over current source and re-render. */
  function _refilterRecords() {
    const src = _currentSourceRecords || (St.lastResult ? St.lastResult.records : []);
    const filtered = _applyColumnFilters(src);
    const total = _currentSourceTotal || (St.lastResult ? St.lastResult.record_count : 0);

    _renderFilterChips();
    _renderRecordsTable(filtered, false, filtered.length);
  }

  /* ── helpers ────────────────────────────────────────────── */
  function _fmt(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString("pl-PL");
  }

  function _dur(sec) {
    if (!sec) return "0s";
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (d > 0 || h >= 100) {
      const totalD = Math.floor(sec / 86400);
      const remH = Math.floor((sec % 86400) / 3600);
      return `${totalD}d ${remH}h ${m}m ${s}s`;
    }
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

  /* ── Pinned BTS cards system ──────────────────────────── */

  /** All currently pinned cards. Each entry: { id, card, tether, latlng, loc } */
  const _pinnedCards = [];
  let _pinnedCardIdCounter = 0;
  let _pinnedAutoFilter = true; // auto-filter Records when single card open

  /** SVG icons for card buttons */
  const _PIN_SVG = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v10"/><path d="M18 8l-2.6 2.6a2 2 0 0 0-.5 1V14a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1v-2.4a2 2 0 0 0-.5-1L6 8"/><path d="M12 15v7"/></svg>`;
  const _CLOSE_SVG = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

  /**
   * Build record detail rows HTML for a pinned card.
   * Shows date, phone number, and interaction type+direction.
   */
  function _buildRecordRows(records) {
    if (!records || !records.length) return '<div class="small muted">Brak rekordów.</div>';

    let html = '';
    for (const r of records) {
      const dt = r.datetime || r.date || "";
      const num = r.callee || "—";
      const label = _typeLabel(r.record_type);
      html += `<div class="gsm-pc-rec">` +
        `<span class="gsm-pc-dt">${dt}</span>` +
        `<span class="gsm-pc-num">${num}</span>` +
        `<span class="gsm-pc-type"><span class="gsm-type gsm-type-${r.record_type}">${label}</span></span>` +
        `</div>`;
    }
    return html;
  }

  /**
   * Create and show a pinned card for a BTS location.
   *
   * @param {L.LatLng|{lat,lon}} latlng  BTS coordinates
   * @param {Object} loc                 Location data (city, street, records, types, etc.)
   * @param {Object} [opts]              Extra options
   * @param {boolean} [opts.pinned=false] Start pinned
   */
  function _openPinnedCard(latlng, loc, opts = {}) {
    if (!St.map) return;
    const map = St.map;
    const container = map.getContainer();
    const id = ++_pinnedCardIdCounter;

    // Convert latlng to Leaflet LatLng if needed
    const ll = latlng.lat !== undefined && latlng.lng !== undefined
      ? latlng : L.latLng(latlng.lat, latlng.lon || latlng.lng);

    // ── Build card DOM ──
    const card = document.createElement("div");
    card.className = "gsm-pinned-card";
    card.dataset.pcId = id;

    // Header
    const header = document.createElement("div");
    header.className = "gsm-pinned-card-header";

    const title = document.createElement("span");
    title.className = "gsm-pinned-card-title";
    title.textContent = `${loc.city || "BTS"}${loc.street ? ", " + loc.street : ""}`;

    const pinBtn = document.createElement("button");
    pinBtn.className = "gsm-pinned-card-btn";
    pinBtn.innerHTML = _PIN_SVG;
    pinBtn.title = "Przypnij kartę";

    const closeBtn = document.createElement("button");
    closeBtn.className = "gsm-pinned-card-btn";
    closeBtn.innerHTML = _CLOSE_SVG;
    closeBtn.title = "Zamknij";

    header.appendChild(title);
    header.appendChild(pinBtn);
    header.appendChild(closeBtn);

    // Body
    const body = document.createElement("div");
    body.className = "gsm-pinned-card-body";

    // Summary section
    const count = loc.records ? loc.records.length : 0;
    const typeList = loc.types
      ? Object.entries(loc.types).map(([t, n]) => `${_typeLabel(t)}: ${n}`).join(", ")
      : "";
    const firstDt = loc.records && loc.records.length ? loc.records[0].datetime : "";
    const lastDt = loc.records && loc.records.length ? loc.records[loc.records.length - 1].datetime : "";

    let summaryHtml = `<div class="gsm-pc-summary">`;
    summaryHtml += `<b>${count}</b> rekordów${typeList ? ` (${typeList})` : ""}<br>`;
    if (firstDt) summaryHtml += `${firstDt} — ${lastDt}<br>`;
    if (loc.azimuth != null) summaryHtml += `Azymut: ${loc.azimuth}° `;
    if (loc.radio) summaryHtml += `${loc.radio} `;
    if (loc.range_m) summaryHtml += `${(loc.range_m / 1000).toFixed(1)} km `;
    summaryHtml += `<br><span class="small muted">LAC: ${loc.lac || "?"}, CID: ${loc.cid || "?"}</span>`;
    summaryHtml += `</div>`;

    // Record detail rows
    summaryHtml += _buildRecordRows(loc.records || []);

    body.innerHTML = summaryHtml;

    // Resize handle
    const resizeHandle = document.createElement("div");
    resizeHandle.className = "gsm-pinned-card-resize";

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(resizeHandle);

    // Position card near the point on screen
    const point = map.latLngToContainerPoint(ll);
    let cardX = point.x + 18;
    let cardY = point.y - 40;
    // Clamp within container
    const cRect = container.getBoundingClientRect();
    if (cardX + 260 > cRect.width) cardX = point.x - 270;
    if (cardY < 10) cardY = 10;
    card.style.left = cardX + "px";
    card.style.top = cardY + "px";
    // Default width for body scroll
    card.style.width = "300px";
    card.style.maxHeight = "340px";

    // Track offset from marker so card moves with the map
    let _cardOffsetX = cardX - point.x;
    let _cardOffsetY = cardY - point.y;

    container.appendChild(card);

    // ── Tether line (SVG overlay) ──
    let tetherSvg = container.querySelector(".gsm-pinned-tether-svg");
    if (!tetherSvg) {
      tetherSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      tetherSvg.classList.add("gsm-pinned-tether-svg");
      tetherSvg.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:999;overflow:visible";
      container.appendChild(tetherSvg);
    }
    const tetherLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    tetherLine.setAttribute("stroke", "#64748b");
    tetherLine.setAttribute("stroke-width", "1.5");
    tetherLine.setAttribute("stroke-dasharray", "5 4");
    tetherLine.dataset.pcId = id;
    tetherSvg.appendChild(tetherLine);

    function _updateTether() {
      const pt = map.latLngToContainerPoint(ll);
      const cx = parseFloat(card.style.left) + card.offsetWidth / 2;
      const cy = parseFloat(card.style.top) + card.offsetHeight / 2;
      tetherLine.setAttribute("x1", pt.x);
      tetherLine.setAttribute("y1", pt.y);
      tetherLine.setAttribute("x2", cx);
      tetherLine.setAttribute("y2", cy);
    }
    _updateTether();

    // Move card with the map (maintain geo-relative offset)
    const _onMapMove = () => {
      const pt = map.latLngToContainerPoint(ll);
      card.style.left = (pt.x + _cardOffsetX) + "px";
      card.style.top = (pt.y + _cardOffsetY) + "px";
      _updateTether();
    };
    map.on("move", _onMapMove);

    // ── Card state ──
    const entry = {
      id,
      card,
      tetherLine,
      latlng: ll,
      loc,
      pinned: !!opts.pinned,
      _onMapMove,
    };
    _pinnedCards.push(entry);

    // Update pin button visual
    function _updatePinVisual() {
      pinBtn.classList.toggle("active", entry.pinned);
      pinBtn.title = entry.pinned ? "Odepnij kartę" : "Przypnij kartę";
    }
    _updatePinVisual();

    // ── Pin button ──
    pinBtn.onclick = (e) => {
      e.stopPropagation();
      entry.pinned = !entry.pinned;
      _updatePinVisual();
      _syncPinnedFilter();
    };

    // ── Close button ──
    closeBtn.onclick = (e) => {
      e.stopPropagation();
      _closePinnedCard(id);
    };

    // ── Drag (header) ──
    let dragOx, dragOy;
    header.addEventListener("mousedown", (e) => {
      if (e.target.closest(".gsm-pinned-card-btn")) return;
      e.preventDefault();
      e.stopPropagation();
      dragOx = e.clientX - parseFloat(card.style.left);
      dragOy = e.clientY - parseFloat(card.style.top);
      function onMove(ev) {
        card.style.left = (ev.clientX - dragOx) + "px";
        card.style.top = (ev.clientY - dragOy) + "px";
        _updateTether();
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        // Recalculate offset so card keeps new position on map pan
        const pt = map.latLngToContainerPoint(ll);
        _cardOffsetX = parseFloat(card.style.left) - pt.x;
        _cardOffsetY = parseFloat(card.style.top) - pt.y;
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // ── Resize (bottom-right handle) ──
    resizeHandle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const startW = card.offsetWidth;
      const startH = card.offsetHeight;
      const startX = e.clientX;
      const startY = e.clientY;
      function onMove(ev) {
        card.style.width = Math.max(200, startW + ev.clientX - startX) + "px";
        card.style.maxHeight = Math.max(80, startH + ev.clientY - startY) + "px";
        _updateTether();
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // Prevent map interactions when interacting with card
    card.addEventListener("mousedown", (e) => e.stopPropagation());
    card.addEventListener("dblclick", (e) => e.stopPropagation());
    card.addEventListener("wheel", (e) => e.stopPropagation());

    // If this is the only card and not pinned yet, auto-filter Records
    if (_pinnedCards.length === 1 && _pinnedAutoFilter) {
      _filterRecordsByPinnedCards();
    }
    _syncPinnedFilter();

    return entry;
  }

  /** Close and remove a pinned card by id */
  function _closePinnedCard(id) {
    const idx = _pinnedCards.findIndex(c => c.id === id);
    if (idx === -1) return;
    const entry = _pinnedCards[idx];

    // Remove DOM
    entry.card.remove();
    entry.tetherLine.remove();

    // Remove map listener — use stored map ref or fall back to St.map
    const mapRef = entry._mapRef || St.map;
    if (mapRef) mapRef.off("move", entry._onMapMove);

    _pinnedCards.splice(idx, 1);

    // Clean up tether SVG if no more cards on this map container
    if (!_pinnedCards.length) {
      const svg = mapRef && mapRef.getContainer().querySelector(".gsm-pinned-tether-svg");
      if (svg) svg.remove();
    }

    _syncPinnedFilter();
  }

  /** Close all pinned cards */
  function _closeAllPinnedCards() {
    while (_pinnedCards.length) {
      _closePinnedCard(_pinnedCards[0].id);
    }
  }

  /** Sync record table filter based on pinned cards */
  function _syncPinnedFilter() {
    const pinned = _pinnedCards.filter(c => c.pinned);
    if (pinned.length > 0) {
      _filterRecordsByPinnedCards();
    } else if (_pinnedCards.length === 1) {
      // Single unpinned card — light filter
      _filterRecordsByPinnedCards();
    } else if (_pinnedCards.length === 0) {
      // No cards — clear filter
      _clearRecordsFilter();
      if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    }
  }

  /** Filter the main Records table to show only records from pinned/open card locations */
  function _filterRecordsByPinnedCards() {
    const cards = _pinnedCards.filter(c => c.pinned);
    const active = cards.length ? cards : _pinnedCards;
    if (!active.length || !St.lastResult) return;

    // Collect all raw_row IDs from active cards
    const rowSet = new Set();
    for (const entry of active) {
      if (entry.loc && entry.loc.records) {
        for (const r of entry.loc.records) {
          if (r.raw_row != null) rowSet.add(r.raw_row);
        }
      }
    }

    const allRecs = St.lastResult.records || [];
    const filtered = allRecs.filter(r => rowSet.has(r.raw_row));
    const labels = active.map(c => c.loc.city || "BTS").join(" + ");
    const filterText = `📌 ${labels} — ${filtered.length} rek.`;

    _setRecordsFilter(filterText, () => {
      _clearRecordsFilter();
      if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    });
    _renderRecords(filtered, false, filtered.length);
  }

  /**
   * Open a pinned card for a BTS marker click. Replaces the default Leaflet popup.
   * If clicked BTS already has an open card, close it (toggle).
   */
  function _handleBtsClick(latlng, loc) {
    // Check if card for this location already exists
    const existing = _pinnedCards.find(c =>
      c.latlng.lat === (latlng.lat || latlng.lat) &&
      c.latlng.lng === (latlng.lng || latlng.lon)
    );
    if (existing) {
      // If unpinned and only card, close it
      if (!existing.pinned && _pinnedCards.length === 1) {
        _closePinnedCard(existing.id);
        return;
      }
      // If pinned, just unpin and close
      _closePinnedCard(existing.id);
      return;
    }

    // If there's already an unpinned card, close it before opening new one
    const unpinned = _pinnedCards.filter(c => !c.pinned);
    for (const u of unpinned) {
      _closePinnedCard(u.id);
    }

    _openPinnedCard(latlng, loc);
  }

  /**
   * Open a pinned card for an overlay marker click (military, airports, diplomacy, KML, user points).
   * Uses the same pinned-card infrastructure as BTS cards.
   *
   * @param {L.LatLng|{lat,lon}} latlng  Marker coordinates
   * @param {Object} info                Overlay data: { name, desc, type, color, icon, layer, lat, lon, extra }
   * @param {L.Map} [mapInst]            Map instance (defaults to St.map)
   */
  function _openOverlayPinnedCard(latlng, info, mapInst) {
    const map = mapInst || St.map;
    if (!map) return;
    const container = map.getContainer();
    const id = ++_pinnedCardIdCounter;

    const ll = latlng.lat !== undefined && latlng.lng !== undefined
      ? latlng : L.latLng(latlng.lat, latlng.lon || latlng.lng);

    // ── Build card DOM ──
    const card = document.createElement("div");
    card.className = "gsm-pinned-card";
    card.dataset.pcId = id;

    // Header
    const header = document.createElement("div");
    header.className = "gsm-pinned-card-header";

    const title = document.createElement("span");
    title.className = "gsm-pinned-card-title";
    title.textContent = info.name || "Lokalizacja";
    if (info.color) title.style.color = info.color;

    const pinBtn = document.createElement("button");
    pinBtn.className = "gsm-pinned-card-btn";
    pinBtn.innerHTML = _PIN_SVG;
    pinBtn.title = "Przypnij kartę";

    const closeBtn = document.createElement("button");
    closeBtn.className = "gsm-pinned-card-btn";
    closeBtn.innerHTML = _CLOSE_SVG;
    closeBtn.title = "Zamknij";

    header.appendChild(title);
    header.appendChild(pinBtn);
    header.appendChild(closeBtn);

    // Body
    const body = document.createElement("div");
    body.className = "gsm-pinned-card-body";

    let html = '<div class="gsm-pc-summary">';
    if (info.type) html += `<span class="gsm-type" style="display:inline-block;margin-bottom:4px">${info.type}</span><br>`;
    if (info.desc) html += `<span>${info.desc}</span><br>`;
    html += `<span class="small muted">${ll.lat.toFixed(6)}, ${ll.lng.toFixed(6)}</span>`;
    if (info.layer) html += `<br><span class="small muted">Warstwa: ${info.layer}</span>`;
    if (info.extra) html += `<br>${info.extra}`;
    html += '</div>';

    body.innerHTML = html;

    // Resize handle
    const resizeHandle = document.createElement("div");
    resizeHandle.className = "gsm-pinned-card-resize";

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(resizeHandle);

    // Position
    const point = map.latLngToContainerPoint(ll);
    let cardX = point.x + 18;
    let cardY = point.y - 40;
    const cRect = container.getBoundingClientRect();
    if (cardX + 260 > cRect.width) cardX = point.x - 270;
    if (cardY < 10) cardY = 10;
    card.style.left = cardX + "px";
    card.style.top = cardY + "px";
    card.style.width = "280px";
    card.style.maxHeight = "300px";

    let _cardOffsetX = cardX - point.x;
    let _cardOffsetY = cardY - point.y;

    container.appendChild(card);

    // ── Tether line ──
    let tetherSvg = container.querySelector(".gsm-pinned-tether-svg");
    if (!tetherSvg) {
      tetherSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      tetherSvg.classList.add("gsm-pinned-tether-svg");
      tetherSvg.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:999;overflow:visible";
      container.appendChild(tetherSvg);
    }
    const tetherLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    tetherLine.setAttribute("stroke", info.color || "#64748b");
    tetherLine.setAttribute("stroke-width", "1.5");
    tetherLine.setAttribute("stroke-dasharray", "5 4");
    tetherLine.dataset.pcId = id;
    tetherSvg.appendChild(tetherLine);

    function _updateTether() {
      const pt = map.latLngToContainerPoint(ll);
      const cx = parseFloat(card.style.left) + card.offsetWidth / 2;
      const cy = parseFloat(card.style.top) + card.offsetHeight / 2;
      tetherLine.setAttribute("x1", pt.x);
      tetherLine.setAttribute("y1", pt.y);
      tetherLine.setAttribute("x2", cx);
      tetherLine.setAttribute("y2", cy);
    }
    _updateTether();

    const _onMapMove = () => {
      const pt = map.latLngToContainerPoint(ll);
      card.style.left = (pt.x + _cardOffsetX) + "px";
      card.style.top = (pt.y + _cardOffsetY) + "px";
      _updateTether();
    };
    map.on("move", _onMapMove);

    // ── Card state ──
    const entry = {
      id, card, tetherLine, latlng: ll,
      loc: { city: info.name || "Lokalizacja" },  // for _syncPinnedFilter label
      pinned: false, _onMapMove, _isOverlay: true, _mapRef: map,
    };
    _pinnedCards.push(entry);

    function _updatePinVisual() {
      pinBtn.classList.toggle("active", entry.pinned);
      pinBtn.title = entry.pinned ? "Odepnij kartę" : "Przypnij kartę";
    }
    _updatePinVisual();

    pinBtn.onclick = (e) => { e.stopPropagation(); entry.pinned = !entry.pinned; _updatePinVisual(); };
    closeBtn.onclick = (e) => { e.stopPropagation(); _closePinnedCard(id); };

    // Drag
    let dragOx, dragOy;
    header.addEventListener("mousedown", (e) => {
      if (e.target.closest(".gsm-pinned-card-btn")) return;
      e.preventDefault(); e.stopPropagation();
      dragOx = e.clientX - parseFloat(card.style.left);
      dragOy = e.clientY - parseFloat(card.style.top);
      function onMove(ev) {
        card.style.left = (ev.clientX - dragOx) + "px";
        card.style.top = (ev.clientY - dragOy) + "px";
        _updateTether();
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        const pt = map.latLngToContainerPoint(ll);
        _cardOffsetX = parseFloat(card.style.left) - pt.x;
        _cardOffsetY = parseFloat(card.style.top) - pt.y;
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // Resize
    resizeHandle.addEventListener("mousedown", (e) => {
      e.preventDefault(); e.stopPropagation();
      const startW = card.offsetWidth, startH = card.offsetHeight;
      const startX = e.clientX, startY = e.clientY;
      function onMove(ev) {
        card.style.width = Math.max(180, startW + ev.clientX - startX) + "px";
        card.style.maxHeight = Math.max(60, startH + ev.clientY - startY) + "px";
        _updateTether();
      }
      function onUp() { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    card.addEventListener("mousedown", (e) => e.stopPropagation());
    card.addEventListener("dblclick", (e) => e.stopPropagation());
    card.addEventListener("wheel", (e) => e.stopPropagation());

    return entry;
  }

  /**
   * Handle overlay marker click — toggle pinned card (like BTS).
   */
  function _handleOverlayClick(latlng, info, mapInst) {
    const ll = latlng.lat !== undefined && latlng.lng !== undefined
      ? latlng : L.latLng(latlng.lat, latlng.lon || latlng.lng);

    const existing = _pinnedCards.find(c =>
      Math.abs(c.latlng.lat - ll.lat) < 0.00001 &&
      Math.abs(c.latlng.lng - ll.lng) < 0.00001
    );
    if (existing) {
      _closePinnedCard(existing.id);
      return;
    }

    // Close unpinned overlay cards before opening a new one
    const unpinned = _pinnedCards.filter(c => !c.pinned && c._isOverlay);
    for (const u of unpinned) _closePinnedCard(u.id);

    _openOverlayPinnedCard(latlng, info, mapInst);
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

  /* ── OSRM road routing helper ─────────────────────────── */
  async function _fetchOSRMRoute(fromLat, fromLon, toLat, toLon) {
    // Uses the free OSRM demo server to get real road geometry
    // Returns array of [lat, lon] or null on failure
    try {
      const url = `https://router.project-osrm.org/route/v1/driving/${fromLon},${fromLat};${toLon},${toLat}?overview=full&geometries=geojson`;
      const resp = await fetch(url);
      if (!resp.ok) return null;
      const data = await resp.json();
      if (data.code !== "Ok" || !data.routes || !data.routes.length) return null;
      const coords = data.routes[0].geometry.coordinates;
      // GeoJSON: [lon, lat] → Leaflet: [lat, lon]
      return coords.map(c => [c[1], c[0]]);
    } catch (e) {
      console.warn("[OSRM] Route fetch failed:", e);
      return null;
    }
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

  /* ── smart import ──────────────────────────────────────── */

  /**
   * Smart import: upload file(s), auto-detect billing/identification/ZIP.
   * Replaces old _uploadAndParse + _uploadIdentification.
   */
  async function _smartImport(files) {
    if (St.analyzing || !files || !files.length) return;
    St.analyzing = true;

    const fileNames = Array.from(files).map(f => f.name);
    St.filename = fileNames[0];

    const progress = QS("#gsm_progress");
    const status = QS("#gsm_status");
    const bar = QS("#gsm_bar");
    const results = QS("#gsm_results");

    if (progress) progress.style.display = "";
    if (status) status.textContent = `Wczytywanie ${files.length} pliku(ów)…`;
    if (bar) bar.style.width = "20%";
    if (results) results.style.display = "none";

    const fd = new FormData();
    for (const f of files) {
      fd.append("files", f);
    }

    try {
      if (status) status.textContent = "Skanowanie i klasyfikacja plików…";
      if (bar) bar.style.width = "40%";

      const resp = await fetch("/api/gsm/import", { method: "POST", body: fd });

      if (bar) bar.style.width = "80%";

      // Handle non-JSON responses
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
        console.error("GSM import error:", detail);
        if (status) status.textContent = `Błąd: ${detail}`;
        _addLog("error", detail);
        St.analyzing = false;
        return;
      }

      // Log scan results
      const sc = data.scan || {};
      _addLog("info", `Skanowanie: ${sc.total_files || 0} plików — `
        + `${sc.billing_count || 0} bilingów, `
        + `${sc.identification_count || 0} identyfikacji, `
        + `${sc.unknown_count || 0} nierozpoznanych`
        + (sc.zips_extracted ? `, ${sc.zips_extracted} ZIP rozp.` : ""));

      // Log each scanned file
      for (const sf of (sc.files || [])) {
        const icon = sf.file_type === "billing" ? "📊" :
                     sf.file_type === "identification" ? "🔍" :
                     sf.file_type === "skipped" ? "⏭" : "❓";
        _addLog("info", `  ${icon} ${sf.filename}: ${sf.detail || sf.file_type}`);
      }

      // Process identification data
      if (data.identification && data.identification.lookup) {
        Object.assign(St.idMap, data.identification.lookup);
        const idCount = data.identification.total_records || 0;
        _addLog("info", `Identyfikacja: ${idCount} rekordów załadowanych`);
      }

      // Process billing data
      if (data.billing) {
        const bd = data.billing;
        if (bd.status === "ok") {
          St.lastResult = bd;
          St.filename = bd.filename || St.filename;
          if (status) status.textContent = "Gotowe";
          _addLog("info", `Biling: ${bd.record_count || 0} rekordów (${bd.operator || "?"})`);
          await _renderResults(bd);
        } else {
          const detail = bd.detail || "Błąd parsowania bilingu";
          _addLog("error", `Biling: ${detail}`);
          if (status) status.textContent = `Błąd bilingu: ${detail}`;
        }
      } else if (!data.identification) {
        // No billing and no identification found
        if (status) status.textContent = "Nie znaleziono bilingów ani identyfikacji";
        _addLog("warn", "Nie znaleziono plików bilingów ani identyfikacji w przesłanych danych");
      } else {
        // Only identification, no billing
        if (status) status.textContent = "Załadowano identyfikację (brak bilingu)";
        // Re-render if we already had billing loaded
        if (St.lastResult) {
          _renderDevices(St.lastResult.analysis ? St.lastResult.analysis.devices : [], St.lastResult.analysis ? St.lastResult.analysis.imei_changes : [], St.lastResult.records, St.lastResult.subscriber);
          _renderAnalysis(St.lastResult.analysis);
          _renderAnomalies(St.lastResult.analysis);
          _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
        }
      }

      // Extra billings warning
      if (data.extra_billings && data.extra_billings.length) {
        _addLog("warn", `Dodatkowe bilingi (nie przetworzone): ${data.extra_billings.join(", ")}`);
      }

      setTimeout(() => {
        if (progress) progress.style.display = "none";
      }, 800);

      // Auto-save to project (awaited to ensure it completes before navigation)
      await _saveToProject();

    } catch (e) {
      console.error("GSM import error:", e);
      const msg = e.message || String(e);
      if (status) status.textContent = `Błąd: ${msg}`;
      _addLog("error", msg);
    } finally {
      St.analyzing = false;
    }
  }

  /* ── identification lookup helpers ─────────────────────── */

  /**
   * Normalise a phone number to 11-digit format (48XXXXXXXXX) to match
   * the backend normalisation used by IdentificationStore.
   */
  function _normMsisdn(raw) {
    if (!raw) return "";
    let d = raw.replace(/\D/g, "");
    if (d.length === 9) d = "48" + d;
    if (d.length > 11 && d.startsWith("48")) d = d.slice(0, 11);
    return d;
  }

  /**
   * Look up a phone number in the identification map.
   * Returns an object { label, type, css } or null.
   */
  function _idLookup(number) {
    if (!number || !Object.keys(St.idMap).length) return null;
    const n = _normMsisdn(number);
    const rec = St.idMap[n];
    if (!rec) return null;
    const cssMap = {
      person: "gsm-id-person",
      company: "gsm-id-company",
      other_operator: "gsm-id-other",
      not_found: "gsm-id-notfound",
      unknown: "gsm-id-unknown",
    };
    return {
      label: rec.label || "",
      type: rec.type || "unknown",
      css: cssMap[rec.type] || "gsm-id-unknown",
    };
  }

  /**
   * Render an identification cell value.
   */
  function _idCell(number) {
    const info = _idLookup(number);
    if (!info) return '<span class="muted">—</span>';
    return `<span class="${info.css}" title="${info.type}">${info.label}</span>`;
  }

  /* ── render ─────────────────────────────────────────────── */
  async function _renderResults(data) {
    const wrap = QS("#gsm_results");
    if (!wrap) return;
    wrap.style.display = "";

    // Hide empty state
    const empty = QS("#gsm_empty_state");
    if (empty) empty.style.display = "none";

    _renderInfo(data);
    _renderSummary(data.summary);
    _renderDevices(data.analysis ? data.analysis.devices : [], data.analysis ? data.analysis.imei_changes : [], data.records, data.subscriber);
    _renderAnalysis(data.analysis);
    _renderAnomalies(data.analysis);
    _renderRecords(data.records, data.records_truncated, data.record_count);
    _renderSpecialNumbers(data.analysis ? data.analysis.special_numbers : []);
    _renderActivityCharts(data.analysis);
    // Heatmap: hour × day-of-week
    St.hmActiveCell = null;
    _buildHeatmapData(data.records);
    _renderHeatmap();
    // Map is async (loads Leaflet) — must finish before travel sections
    await _renderMap(data.geolocation);
    _renderOvernightStays(data.analysis);
    _renderWarnings(data.warnings);
    _bindCardScreenshotButtons();
  }

  function _renderInfo(data) {
    const grid = QS("#gsm_info_grid");
    if (!grid) return;

    const sub = data.subscriber || {};
    const meta = sub.extra || {};

    const rows = [
      ["Plik", data.filename],
      ["Operator", data.operator],
      ["MSISDN", sub.msisdn || "—"],
    ];
    if (meta.signature) rows.push(["Sygnatura", meta.signature]);
    if (meta.order_id) rows.push(["Nr zlecenia", meta.order_id]);
    if (meta.query_name) rows.push(["Zapytanie", meta.query_name]);

    grid.innerHTML = rows
      .map(([k, v]) => `<div class="gsm-info-label">${k}</div><div class="gsm-info-value">${v || "—"}</div>`)
      .join("");
  }

  function _dataSize(kb) {
    if (!kb) return "0 KB";
    if (kb < 1024) return kb.toFixed(1) + " KB";
    const mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + " MB";
    return (mb / 1024).toFixed(2) + " GB";
  }

  function _renderSummary(s) {
    const el = QS("#gsm_summary_grid");
    if (!el || !s) return;

    // Use call-only duration if available, fall back to total for older data
    const callDur = s.call_duration_seconds != null ? s.call_duration_seconds : s.total_duration_seconds;

    el.innerHTML = `
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.total_records)}</div>
        <div class="gsm-stat-label">Rekordy</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.calls_out + s.calls_in)}</div>
        <div class="gsm-stat-label">Po\u0142\u0105czenia (${_fmt(s.calls_out)}\u2191 ${_fmt(s.calls_in)}\u2193)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_dur(callDur)}</div>
        <div class="gsm-stat-label">Czas rozm\u00f3w (${_fmt(s.calls_out)}\u2191 ${_fmt(s.calls_in)}\u2193)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.sms_out + s.sms_in)}</div>
        <div class="gsm-stat-label">SMS (${_fmt(s.sms_out)}\u2191 ${_fmt(s.sms_in)}\u2193)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.mms_out + s.mms_in)}</div>
        <div class="gsm-stat-label">MMS (${_fmt(s.mms_out)}\u2191 ${_fmt(s.mms_in)}\u2193)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_dataSize(s.total_data_kb)}</div>
        <div class="gsm-stat-label">Dane (${_fmt(s.data_sessions)} sesji)</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${_fmt(s.unique_contacts)}</div>
        <div class="gsm-stat-label">Unikalne kontakty</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${s.period_from || "\u2014"}</div>
        <div class="gsm-stat-label">Okres od</div>
      </div>
      <div class="gsm-stat-card">
        <div class="gsm-stat-value">${s.period_to || "\u2014"}</div>
        <div class="gsm-stat-label">Okres do</div>
      </div>
      ${s.roaming_records ? `<div class="gsm-stat-card"><div class="gsm-stat-value">${_fmt(s.roaming_records)}</div><div class="gsm-stat-label">Roaming</div></div>` : ""}
    `;
  }

  /* ── Devices card (IMEI / IMSI analysis) ────────────────── */

  function _renderDevices(devices, imeiChanges, records, subscriber) {
    const card = QS("#gsm_devices_card");
    const el   = QS("#gsm_devices_body");
    if (!el) return;

    const sub = subscriber || {};
    const devList = devices || [];

    // ── Build IMEI ↔ IMSI map from individual records ──
    const imeiImsiMap = {};   // imei → Set of imsi
    const imsiImeiMap = {};   // imsi → Set of imei
    if (records && records.length) {
      for (const r of records) {
        const imei = (r.imei || "").trim();
        const imsi = (r.imsi || "").trim();
        if (!imei) continue;
        if (!imeiImsiMap[imei]) imeiImsiMap[imei] = new Set();
        if (imsi) imeiImsiMap[imei].add(imsi);
        if (imsi) {
          if (!imsiImeiMap[imsi]) imsiImeiMap[imsi] = new Set();
          imsiImeiMap[imsi].add(imei);
        }
      }
    }

    // ── Collect all known IMEI / IMSI (from records + subscriber header) ──
    const allImeis = new Set(devList.map(d => d.imei).filter(Boolean));
    if (sub.imei) allImeis.add(sub.imei.trim());

    const allImsis = new Set();
    for (const s of Object.values(imeiImsiMap)) s.forEach(v => allImsis.add(v));
    if (sub.imsi) allImsis.add(sub.imsi.trim());

    // Nothing at all → hide card
    if (allImeis.size === 0 && allImsis.size === 0) {
      if (card) card.style.display = "none";
      return;
    }
    if (card) card.style.display = "";

    const typeMap = { smartphone: "Smartfon", tablet: "Tablet", modem: "Modem", feature_phone: "Telefon", smartwatch: "Smartwatch" };
    let html = "";

    // ── Devices table (if we have device analysis data) ──
    if (devList.length) {
      html += `<table class="gsm-table"><thead><tr>
        <th>IMEI</th><th>IMSI</th><th>Urządzenie</th><th>Typ</th><th>Rekordy</th><th>Okres</th>
      </tr></thead><tbody>`;
      for (const d of devList) {
        const name = d.display_name || '<span class="muted">nieznane</span>';
        const typeName = typeMap[d.type] || d.type || "—";
        const period = d.first_seen ? (d.first_seen === d.last_seen ? d.first_seen : `${d.first_seen} – ${d.last_seen}`) : "—";
        const imsis = imeiImsiMap[d.imei];
        const imsiStr = imsis && imsis.size ? [...imsis].map(s => `<code>${s}</code>`).join(", ") : (sub.imsi ? `<code>${sub.imsi}</code>` : '<span class="muted">—</span>');
        html += `<tr>
          <td><code>${d.imei || "?"}</code></td>
          <td>${imsiStr}</td>
          <td>${d.known ? `<strong>${name}</strong>` : name}</td>
          <td>${typeName}</td>
          <td>${_fmt(d.record_count)}</td>
          <td>${period}</td>
        </tr>`;
      }
      html += "</tbody></table>";
    } else {
      // No device analysis — show subscriber-level IMEI/IMSI
      html += `<div class="gsm-info-grid" style="margin-bottom:8px">`;
      if (sub.imei) {
        const devName = sub.device && sub.device.display_name ? ` <span class="gsm-device-badge">${sub.device.display_name}</span>` : "";
        html += `<div class="gsm-info-label">IMEI</div><div class="gsm-info-value"><code>${sub.imei}</code>${devName}</div>`;
      }
      if (sub.imsi) {
        html += `<div class="gsm-info-label">IMSI</div><div class="gsm-info-value"><code>${sub.imsi}</code></div>`;
      }
      html += `</div>`;
    }

    // ── IMEI changes timeline ──
    if (imeiChanges && imeiChanges.length) {
      html += `<div style="margin-top:12px"><div class="h3" style="margin-bottom:6px">Zmiany IMEI</div>`;
      for (const ch of imeiChanges) {
        const oldDev = ch.old_device ? ` (${ch.old_device})` : "";
        const newDev = ch.new_device ? ` (${ch.new_device})` : "";
        html += `<div class="gsm-anomaly gsm-anomaly-medium">${ch.date || ""}: ${ch.old_imei || "?"}${oldDev} → ${ch.new_imei || "?"}${newDev}</div>`;
      }
      html += "</div>";
    }

    // ── IMEI / IMSI relationship analysis ──
    const nImei = allImeis.size;
    const nImsi = allImsis.size;
    const findings = [];

    // Multiple IMEIs for one IMSI → phone changes (same SIM, different phones)
    for (const [imsi, imeis] of Object.entries(imsiImeiMap)) {
      if (imeis.size > 1) {
        findings.push({
          type: "phone_change",
          msg: `IMSI <code>${imsi}</code> — wykryto <strong>${imeis.size} różnych IMEI</strong> (${[...imeis].map(i => `<code>${i}</code>`).join(", ")}). Abonent zmieniał telefony korzystając z tej samej karty SIM.`
        });
      }
    }
    // One IMEI with multiple IMSIs → SIM changes (same phone, different SIMs)
    for (const [imei, imsis] of Object.entries(imeiImsiMap)) {
      if (imsis.size > 1) {
        findings.push({
          type: "sim_change",
          msg: `IMEI <code>${imei}</code> — wykryto <strong>${imsis.size} różnych IMSI</strong> (${[...imsis].map(s => `<code>${s}</code>`).join(", ")}). W tym urządzeniu zmieniano karty SIM.`
        });
      }
    }

    html += `<div style="margin-top:12px"><div class="h3" style="margin-bottom:6px">Analiza IMEI / IMSI</div>`;
    html += `<div style="margin-bottom:8px;font-size:13px">Unikalne IMEI: <strong>${nImei}</strong> &nbsp;|&nbsp; Unikalne IMSI: <strong>${nImsi}</strong></div>`;

    if (findings.length) {
      for (const f of findings) {
        const cls = f.type === "phone_change" ? "gsm-anomaly-medium" : "gsm-anomaly-high";
        html += `<div class="gsm-anomaly ${cls}" style="margin-bottom:4px">${f.msg}</div>`;
      }
    } else {
      html += `<div class="gsm-anomaly gsm-anomaly-low" style="margin-bottom:4px">Brak zmian — w całym okresie używano ${nImei === 1 ? "jednego urządzenia" : nImei + " urządzeń"} z ${nImsi === 1 ? "jedną kartą SIM" : nImsi + " kartami SIM"}. Nie wykryto zmian telefonów ani kart SIM.</div>`;
    }
    html += "</div>";

    el.innerHTML = html;
  }

  function _renderAnalysis(a) {
    const el = QS("#gsm_analysis_body");
    if (!el || !a) return;

    let html = "";

    // Top contacts
    if (a.top_contacts && a.top_contacts.length) {
      html += `<div class="gsm-section"><div class="h3">Top kontakty</div><table class="gsm-table"><thead><tr>
        <th>Numer</th><th>Identyfikacja</th><th>Interakcje</th><th>Rozmowy ↑</th><th>Rozmowy ↓</th><th>SMS ↑</th><th>SMS ↓</th><th>Czas rozmów</th><th>Aktywne dni</th>
      </tr></thead><tbody>`;
      for (const c of a.top_contacts.slice(0, 20)) {
        html += `<tr>
          <td><code>${c.number}</code></td>
          <td>${_idCell(c.number)}</td>
          <td>${_fmt(c.total_interactions)}</td>
          <td>${_fmt(c.calls_out)}</td><td>${_fmt(c.calls_in)}</td>
          <td>${_fmt(c.sms_out)}</td><td>${_fmt(c.sms_in)}</td>
          <td>${_dur(c.total_duration_seconds)}</td>
          <td>${c.active_days}</td>
        </tr>`;
      }
      html += "</tbody></table>";
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

    el.innerHTML = html || '<div class="small muted">Brak danych do analizy.</div>';

    // Render contact relationship graph (SVG) — separate card
    const graphCard = QS("#gsm_graph_card");
    if (a.top_contacts && a.top_contacts.length && graphCard) {
      graphCard.style.display = "";
      St._graphContacts = a.top_contacts;
      const msisdn = (St.lastResult && St.lastResult.subscriber)
        ? St.lastResult.subscriber.msisdn || "" : "";
      St._graphMsisdn = msisdn;
      const topN = parseInt(QS("#gsm_graph_top_n")?.value || "10");
      _renderContactGraph(a.top_contacts.slice(0, topN), msisdn);

      // Wire top-N selector
      const topSel = QS("#gsm_graph_top_n");
      if (topSel) topSel.onchange = () => {
        const n = parseInt(topSel.value);
        QS("#gsm_graph_filter").value = "all";
        // Reset manual resize so auto-scaling can adapt to new count
        const gc = QS("#gsm_graph_card");
        if (gc) { delete gc.dataset.userResized; gc.style.height = ""; }
        _renderContactGraph(St._graphContacts.slice(0, n), St._graphMsisdn);
      };
      // Wire type filter
      const filtSel = QS("#gsm_graph_filter");
      if (filtSel) filtSel.onchange = () => _applyGraphFilter(filtSel.value);
    } else if (graphCard) {
      graphCard.style.display = "none";
    }
  }

  /* ── Anomalies card ──────────────────────────────────────── */

  // Canonical category definitions — always shown, always in this order
  const _ANOMALY_CATS = [
    { type: "long_call",        label: "D\u0142ugie po\u0142\u0105czenia",               desc: "Po\u0142\u0105czenia trwaj\u0105ce ponad 1 godzin\u0119" },
    { type: "late_night_calls", label: "Po\u0142\u0105czenia g\u0142osowe w nocy",       desc: "Rozmowy telefoniczne mi\u0119dzy 00:00 a 05:00 (d\u0142u\u017Csze ni\u017C 10 sek.)" },
    { type: "night_activity",   label: "Wysoka aktywno\u015B\u0107 nocna",          desc: "Ponad 30% wszystkich zdarze\u0144 (po\u0142\u0105czenia, SMS, dane) przypada na godziny 23:00\u201305:00" },
    { type: "night_movement",   label: "Przemieszczanie nocne",           desc: "Zmiana stacji BTS mi\u0119dzy kolejnymi zdarzeniami nocnymi (23:00\u201305:00) \u2014 wskazuje na ruch urz\u0105dzenia w nocy" },
    { type: "burst_activity",   label: "Nag\u0142y wzrost aktywno\u015Bci",         desc: "Co najmniej 20 rekord\u00F3w (po\u0142\u0105czenia/SMS) w ci\u0105gu 30 minut \u2014 mo\u017Ce wskazywa\u0107 na masowe wysy\u0142anie SMS, automatyczne systemy lub intensywn\u0105 komunikacj\u0119" },
    { type: "premium_number",   label: "Numery premium / p\u0142atne",        desc: "Kontakty z numerami o podwy\u017Cszonej op\u0142acie (70x, 80x)" },
    { type: "roaming",          label: "Aktywno\u015B\u0107 w sieciach zagranicznych", desc: "Rekordy z flag\u0105 roamingu lub z sieci\u0105 zagraniczn\u0105. Szczeg\u00F3\u0142y wyjazd\u00F3w \u2014 patrz sekcja \u201EPrzekroczenia granic\u201D" },
    { type: "one_time_contacts",label: "Jednorazowe kontakty",            desc: "Numery telefon\u00F3w z kt\u00F3rymi by\u0142 dok\u0142adnie jeden kontakt w ca\u0142ym okresie bilingu" },
    { type: "satellite_numbers",label: "Numery satelitarne",              desc: "Po\u0142\u0105czenia z numerami telefon\u00F3w satelitarnych (Iridium, Inmarsat, Thuraya, Globalstar i in.)" },
    { type: "social_media",     label: "Konta spo\u0142eczno\u015Bciowe / komunikatory", desc: "Nazwy komunikator\u00F3w i platform spo\u0142eczno\u015Bciowych wykryte w polach bilingu (WhatsApp, Telegram, Viber, Facebook, VKontakte, WeChat i in.)" },
    { type: "inactivity_gap",   label: "Brak aktywno\u015Bci >12 godzin", desc: "Okresy powy\u017Cej 12 godzin bez \u017Cadnego zdarzenia (po\u0142\u0105czenia, SMS, dane). Podano ostatni i pierwszy kontakt." },
  ];

  function _renderAnomalies(a) {
    const card = QS("#gsm_anomalies_card");
    const body = QS("#gsm_anomalies_body");
    if (!card || !body) return;

    const raw = (a && a.anomalies) || [];
    if (!raw.length) { card.style.display = "none"; return; }
    card.style.display = "";

    // Detect old flat format (entries without items array) and convert
    const isOldFormat = raw.length > 0 && !raw[0].items && (raw[0].description || raw[0].contact);
    const groupMap = {};
    if (isOldFormat) {
      for (const entry of raw) {
        const t = entry.type || "unknown";
        if (!groupMap[t]) groupMap[t] = { items: [], severity: entry.severity || "info" };
        groupMap[t].items.push(entry);
        if (entry.severity === "warning") groupMap[t].severity = "warning";
      }
    } else {
      for (const g of raw) {
        groupMap[g.type] = { items: g.items || [], severity: g.severity || "ok" };
      }
    }

    // Icon paths
    const _IC_EXPAND = "/static/icons/akcje/expand_down.svg";
    const _IC_COLLAPSE = "/static/icons/akcje/collapse_up.svg";
    const _IC_PLUS5 = "/static/icons/akcje/plus5.svg";
    const _ICON_SZ = 20;
    const _makeIcon = (src, title, cls) =>
      `<img src="${src}" width="${_ICON_SZ}" height="${_ICON_SZ}" title="${title}" class="${cls}" style="cursor:pointer;opacity:.65;transition:opacity .15s" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=.65">`;

    const VISIBLE = 5;
    const SCROLL_THRESHOLD = 50;

    // Render ALL categories in canonical order
    let html = '<div style="display:flex;flex-direction:column;gap:10px">';
    for (const cat of _ANOMALY_CATS) {
      const data = groupMap[cat.type] || { items: [], severity: "ok" };
      const items = data.items;
      const hasItems = items.length > 0;
      const sev = hasItems ? (data.severity || "info") : "ok";
      const sevColor = sev === "warning" ? "#f97316" : sev === "info" ? "#3b82f6" : "#22c55e";
      const sevIcon = sev === "warning" ? "\u26A0" : sev === "info" ? "\u2139" : "\u2713";

      // ── Card container ──
      html += `<div class="gsm-anomaly-card" data-anomaly-type="${cat.type}" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;border-left:3px solid ${sevColor};transition:background .15s,box-shadow .15s">`;

      // ── Top bar: header row with name + count + action icons ──
      html += `<div class="gsm-anomaly-bar" style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:rgba(${sev === 'warning' ? '249,115,22' : sev === 'info' ? '59,130,246' : '34,197,94'},.04)">`;
      html += `<span style="color:${sevColor};font-size:15px;flex-shrink:0">${sevIcon}</span>`;
      html += `<div style="flex:1;min-width:0">`;
      html += `<div style="display:flex;align-items:center;gap:5px"><b>${cat.label}</b>`;
      if (!hasItems) {
        html += ` <span class="muted">\u2014 brak</span>`;
      } else {
        html += ` <span class="muted">(${items.length})</span>`;
      }
      html += `</div>`;
      html += `<div class="small muted" style="margin-top:1px;line-height:1.3">${cat.desc}</div>`;
      html += `</div>`; // end text block

      // ── Action icons (only if has data) ──
      if (hasItems) {
        html += `<div style="display:flex;align-items:center;gap:2px;flex-shrink:0;border-left:1px solid var(--border);padding-left:8px;margin-left:4px">`;
        // Expand / collapse (only if >5 items)
        if (items.length > VISIBLE) {
          html += _makeIcon(_IC_EXPAND, "Rozwiń / zwiń listę", "gsm-anom-toggle") + " ";
        }
        // +5 context
        html += _makeIcon(_IC_PLUS5, "+5 rekordów kontekstu", "gsm-anom-plus5");
        html += `</div>`;
      }
      html += `</div>`; // end bar

      // ── Items body ──
      if (hasItems) {
        const rendered = isOldFormat
          ? _renderOldAnomalyItems(items)
          : _renderAnomalyItems(cat.type, items);
        const uid = `anom_exp_${cat.type}`;
        const collapsedH = VISIBLE * 22;
        const useScroll = items.length > SCROLL_THRESHOLD;
        const maxExpandH = useScroll ? '300px' : 'none';
        const overflowY = useScroll ? 'auto' : 'visible';
        const needCollapse = items.length > VISIBLE;

        html += `<div id="${uid}" data-collapsed-h="${collapsedH}" data-max-h="${maxExpandH}" data-overflow="${overflowY}" `
          + `style="padding:4px 12px 8px;${needCollapse ? 'max-height:' + collapsedH + 'px;overflow:hidden;' : ''}transition:max-height .25s ease">`;
        html += rendered;
        html += `</div>`;
      }

      html += `</div>`; // end card
    }
    html += '</div>';
    body.innerHTML = html;

    // ── Expand / collapse via icon ──
    body.querySelectorAll(".gsm-anom-toggle").forEach(icon => {
      icon.addEventListener("click", function(e) {
        e.stopPropagation();
        const card = this.closest(".gsm-anomaly-card");
        if (!card) return;
        const type = card.dataset.anomalyType;
        const container = document.getElementById(`anom_exp_${type}`);
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

    // ── +5 context records via icon ──
    body.querySelectorAll(".gsm-anom-plus5").forEach(icon => {
      icon.addEventListener("click", function(e) {
        e.stopPropagation();
        const card = this.closest(".gsm-anomaly-card");
        if (!card) return;
        const type = card.dataset.anomalyType;
        const data = groupMap[type];
        if (!data || !data.items.length) return;
        _anomalyContextFilter(type, data.items);
      });
    });

    // ── Hover effect on anomaly cards with items ──
    body.querySelectorAll(".gsm-anomaly-card").forEach(div => {
      const hasData = (groupMap[div.dataset.anomalyType] || {items:[]}).items.length > 0;
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
    });

    // ── Double-click on anomaly category → filter Records (unchanged) ──
    body.addEventListener("dblclick", function(e) {
      // Ignore clicks on action icons
      if (e.target.closest(".gsm-anom-toggle, .gsm-anom-plus5")) return;
      const div = e.target.closest("[data-anomaly-type]");
      if (!div) return;
      const type = div.dataset.anomalyType;
      const data = groupMap[type];
      if (!data || !data.items.length) return;
      _anomalyGroupFilter(type, data.items);
    });
  }

  /** Filter Records by anomaly group — invoked on double-click. */
  function _anomalyGroupFilter(type, items) {
    St._anomalyHighlight = null;  // clear +5 highlighting
    const records = St.lastResult ? St.lastResult.records : [];
    let filtered = [];
    let filterText = "";

    switch (type) {
      case "long_call":
        filtered = records.filter(r => r.duration_seconds > 3600 && (r.record_type || "").includes("CALL"));
        filterText = `Długie połączenia (>1h) — ${filtered.length} rek.`;
        break;
      case "late_night_calls":
        filtered = records.filter(r => {
          if (!r.time || !(r.record_type || "").includes("CALL")) return false;
          const h = parseInt(r.time.split(":")[0], 10);
          return h >= 0 && h < 5;
        });
        filterText = `Połączenia nocne (00:00–05:00) — ${filtered.length} rek.`;
        break;
      case "night_activity":
        filtered = records.filter(r => {
          if (!r.time) return false;
          const h = parseInt(r.time.split(":")[0], 10);
          return h >= 23 || h < 5;
        });
        filterText = `Aktywność nocna (23:00–05:00) — ${filtered.length} rek.`;
        break;
      case "night_movement":
        filtered = records.filter(r => {
          if (!r.time) return false;
          const h = parseInt(r.time.split(":")[0], 10);
          return h >= 23 || h < 5;
        });
        filterText = `Przemieszczanie nocne — ${filtered.length} rek.`;
        break;
      case "burst_activity":
        if (items.length > 0) {
          const b = items[0];
          filtered = records.filter(r => {
            if (r.date !== b.date) return false;
            if (!b.time || !r.time) return true;
            try {
              const bp = b.time.split(":"), rp = r.time.split(":");
              const bm = parseInt(bp[0]) * 60 + parseInt(bp[1]);
              const rm = parseInt(rp[0]) * 60 + parseInt(rp[1]);
              return rm >= bm && rm <= bm + (b.window_min || 30);
            } catch (_) { return false; }
          });
          filterText = `Skok aktywności (${b.date} ${b.time}) — ${filtered.length} rek.`;
        }
        break;
      case "premium_number": {
        const nums = new Set(items.map(it => it.contact));
        filtered = records.filter(r => nums.has(r.callee) || nums.has(r.caller));
        filterText = `Numery premium — ${filtered.length} rek.`;
        break;
      }
      case "roaming":
        filtered = records.filter(r => r.roaming);
        if (!filtered.length) {
          filtered = records.filter(r => r.roaming || (r.network && !/orange|play|plus|t-mobile|polkomtel|p4|heyah/i.test(r.network)));
        }
        filterText = `Roaming — ${filtered.length} rek.`;
        break;
      case "one_time_contacts": {
        const otNums = new Set(items.map(it => it.contact));
        filtered = records.filter(r => otNums.has(r.callee) || otNums.has(r.caller));
        filterText = `Jednorazowe kontakty — ${filtered.length} rek.`;
        break;
      }
      case "satellite_numbers": {
        const satNums = new Set(items.map(it => it.contact));
        filtered = records.filter(r => satNums.has(r.callee) || satNums.has(r.caller));
        filterText = `Numery satelitarne — ${filtered.length} rek.`;
        break;
      }
      case "social_media": {
        // Build a set of platform patterns to search in record fields
        const smPlatforms = items.map(it => it.platform.toLowerCase());
        filtered = records.filter(r => {
          const txt = [r.callee, r.caller, r.network, r.raw_text || ""].join(" ").toLowerCase();
          return smPlatforms.some(p => txt.includes(p));
        });
        filterText = `Konta społecznościowe — ${filtered.length} rek.`;
        break;
      }
      default:
        filtered = records;
        filterText = `${type} — ${filtered.length} rek.`;
    }

    // Clear heatmap filter state
    St.hmActiveCell = null;
    const hmBar = QS("#gsm_hm_filter_bar");
    if (hmBar) hmBar.style.display = "none";

    _setRecordsFilter(filterText, () => {
      _clearRecordsFilter();
      if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    });
    _renderRecords(filtered, false, filtered.length);

    const recCard = QS("#gsm_records_card");
    if (recCard) {
      recCard.scrollIntoView({ behavior: "smooth", block: "start" });
      recCard.style.transition = "box-shadow .2s";
      recCard.style.boxShadow = "0 0 0 3px var(--brand-blue,#2563eb)";
      setTimeout(() => { recCard.style.boxShadow = ""; }, 1200);
    }
  }

  /**
   * Build a predicate function that tests whether a record matches
   * the given anomaly type. Returns a function(record) → boolean.
   */
  function _anomalyPredicate(type, anomalyItems) {
    switch (type) {
      case "long_call":
        return r => r.duration_seconds > 3600 && (r.record_type || "").includes("CALL");
      case "late_night_calls":
        return r => {
          if (!r.time || !(r.record_type || "").includes("CALL")) return false;
          const h = parseInt(r.time.split(":")[0], 10);
          return h >= 0 && h < 5;
        };
      case "night_activity":
        return r => {
          if (!r.time) return false;
          const h = parseInt(r.time.split(":")[0], 10);
          return h >= 23 || h < 5;
        };
      case "night_movement":
        return r => {
          if (!r.time) return false;
          const h = parseInt(r.time.split(":")[0], 10);
          return h >= 23 || h < 5;
        };
      case "burst_activity": {
        if (!anomalyItems.length) return () => false;
        const b = anomalyItems[0];
        return r => {
          if (r.date !== b.date) return false;
          if (!b.time || !r.time) return true;
          try {
            const bp = b.time.split(":"), rp = r.time.split(":");
            const bm = parseInt(bp[0]) * 60 + parseInt(bp[1]);
            const rm = parseInt(rp[0]) * 60 + parseInt(rp[1]);
            return rm >= bm && rm <= bm + (b.window_min || 30);
          } catch (_) { return false; }
        };
      }
      case "premium_number": {
        const nums = new Set(anomalyItems.map(it => it.contact));
        return r => nums.has(r.callee) || nums.has(r.caller);
      }
      case "roaming":
        return r => r.roaming || (r.network && !/orange|play|plus|t-mobile|polkomtel|p4|heyah/i.test(r.network));
      case "one_time_contacts": {
        const otNums = new Set(anomalyItems.map(it => it.contact));
        return r => otNums.has(r.callee) || otNums.has(r.caller);
      }
      case "satellite_numbers": {
        const satNums = new Set(anomalyItems.map(it => it.contact));
        return r => satNums.has(r.callee) || satNums.has(r.caller);
      }
      case "social_media": {
        const smPlatforms = anomalyItems.map(it => it.platform.toLowerCase());
        return r => {
          const txt = [r.callee, r.caller, r.network, r.raw_text || ""].join(" ").toLowerCase();
          return smPlatforms.some(p => txt.includes(p));
        };
      }
      default:
        return () => false;
    }
  }

  /**
   * +5 context filter: show anomaly records plus 5 records before/after each,
   * with color coding (red = anomaly, blue = context).
   */
  function _anomalyContextFilter(type, anomalyItems) {
    const allRecords = St.lastResult ? St.lastResult.records : [];
    if (!allRecords.length) return;

    const isAnomaly = _anomalyPredicate(type, anomalyItems);

    // Step 1: Find anomaly indices by running predicate on every record
    const anomalyIndices = new Set();
    for (let i = 0; i < allRecords.length; i++) {
      if (isAnomaly(allRecords[i])) {
        anomalyIndices.add(i);
      }
    }

    if (!anomalyIndices.size) return;

    // Step 2: Collect context indices (+5 before, +5 after each anomaly)
    const contextIndices = new Set();
    for (const idx of anomalyIndices) {
      for (let d = 1; d <= 5; d++) {
        const before = idx - d;
        const after = idx + d;
        if (before >= 0 && !anomalyIndices.has(before)) contextIndices.add(before);
        if (after < allRecords.length && !anomalyIndices.has(after)) contextIndices.add(after);
      }
    }

    // Step 3: Merge, sort by original position, build result
    const allIndices = [...anomalyIndices, ...contextIndices].sort((a, b) => a - b);
    const resultRecords = allIndices.map(i => allRecords[i]);

    // Step 4: Build highlighting sets keyed by record object reference.
    // .filter() and [...].sort() preserve object references, so WeakSet works.
    const anomalyRecords = new Set();
    const contextRecords = new Set();
    for (const idx of allIndices) {
      if (anomalyIndices.has(idx)) {
        anomalyRecords.add(allRecords[idx]);
      } else {
        contextRecords.add(allRecords[idx]);
      }
    }

    St._anomalyHighlight = {
      anomalyRecords: anomalyRecords,
      contextRecords: contextRecords,
    };

    // Auto-show context_label column
    if (St.columnHidden) St.columnHidden["context_label"] = false;
    // Ensure it's in the column order
    if (St.columnOrder && !St.columnOrder.includes("context_label")) {
      St.columnOrder.unshift("context_label");
    }

    const anomCount = anomalyIndices.size;
    const ctxCount = contextIndices.size;
    const filterText = `+5 kontekst: ${anomCount} anomalii + ${ctxCount} kontekstu = ${resultRecords.length} rek.`;

    // Clear heatmap filter state
    St.hmActiveCell = null;
    const hmBar = QS("#gsm_hm_filter_bar");
    if (hmBar) hmBar.style.display = "none";

    _setRecordsFilter(filterText, () => {
      St._anomalyHighlight = null;
      // Auto-hide context_label column
      if (St.columnHidden) St.columnHidden["context_label"] = true;
      _clearRecordsFilter();
      if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    });
    _renderRecords(resultRecords, false, resultRecords.length);

    const recCard = QS("#gsm_records_card");
    if (recCard) {
      recCard.scrollIntoView({ behavior: "smooth", block: "start" });
      recCard.style.transition = "box-shadow .2s";
      recCard.style.boxShadow = "0 0 0 3px var(--brand-blue,#2563eb)";
      setTimeout(() => { recCard.style.boxShadow = ""; }, 1200);
    }
  }

  /** Render old-format anomaly items (just description text). */
  function _renderOldAnomalyItems(items) {
    let html = '<div style="display:flex;flex-direction:column;gap:3px;font-size:13px">';
    for (const it of items) {
      html += `<div>${it.description || ""}</div>`;
    }
    html += '</div>';
    return html;
  }

  function _renderAnomalyItems(type, items) {
    let html = '<div style="display:flex;flex-direction:column;gap:3px;font-size:13px">';

    if (type === "long_call") {
      for (const it of items) {
        html += `<div><code>${it.contact}</code> — ${it.duration_min} min (${it.date} ${it.time})</div>`;
      }
    } else if (type === "late_night_calls") {
      for (const it of items) {
        html += `<div><code>${it.contact}</code> — ${it.direction}, ${it.duration_min} min (${it.date} ${it.time})</div>`;
      }
    } else if (type === "night_activity") {
      for (const it of items) {
        html += `<div>${it.ratio_pct}% zdarzeń w godzinach 23:00–05:00</div>`;
      }
    } else if (type === "night_movement") {
      for (const it of items) {
        html += `<div>${it.date} ${it.time_from} → ${it.time_to}: <span class="muted">${it.bts_from} → ${it.bts_to}</span>`;
        if (it.contact) html += ` (kontakt: <code>${it.contact}</code>)`;
        html += `</div>`;
      }
    } else if (type === "burst_activity") {
      for (const it of items) {
        html += `<div>${it.count} rekordów w ${it.window_min} min — ${it.date} od ${it.time}</div>`;
      }
    } else if (type === "premium_number") {
      for (const it of items) {
        html += `<div><code>${it.contact}</code> — ${it.count}× (${it.dates.join(", ")})</div>`;
      }
    } else if (type === "roaming") {
      for (const it of items) {
        const nets = it.networks && it.networks.length ? ` [${it.networks.join(", ")}]` : "";
        const name = _countryName(it.country) || it.country;
        // Show country name; if country code differs from displayed name, show raw code
        const raw = (it.country && it.country !== name) ? ` <span class="muted">(${it.country})</span>` : "";
        // Show MCC:MNC codes if available
        const mcc = it.mcc_mnc && it.mcc_mnc.length ? ` <span class="muted">MCC:MNC ${it.mcc_mnc.join(", ")}</span>` : "";
        html += `<div><b>${name}</b>${raw} \u2014 ${it.count} rekord\u00F3w, ${it.period}${nets}${mcc}</div>`;
      }
    } else if (type === "one_time_contacts") {
      for (const it of items) {
        const typeLabel = (it.record_type || "").replace(/_/g, " ");
        html += `<div><code>${it.contact}</code> — ${typeLabel} (${it.date})</div>`;
      }
    } else if (type === "satellite_numbers") {
      for (const it of items) {
        const confBadge = it.confidence === "high" ? "\u{1F7E2}" : it.confidence === "medium" ? "\u{1F7E1}" : "\u{1F534}";
        const dates = it.dates && it.dates.length ? ` (${it.dates.join(", ")})` : "";
        html += `<div>${confBadge} <code>${it.contact}</code> — <b>${it.operator || "?"}</b> [${it.confidence || "?"}] ${it.count}\u00D7${dates}</div>`;
      }
    } else if (type === "social_media") {
      for (const it of items) {
        const catShort = (it.category || "").replace(/\s*\/\s*/g, "/");
        const dates = it.dates && it.dates.length > 0 ? it.dates.join(", ") : "";
        const types = it.record_types && it.record_types.length ? it.record_types.map(t => t.replace(/_/g, " ")).join(", ") : "";
        const contacts = it.unique_contacts > 0 ? `, ${it.unique_contacts} kontakt${it.unique_contacts === 1 ? "" : it.unique_contacts < 5 ? "y" : "\u00F3w"}` : "";
        html += `<div><b>${it.platform}</b> <span class="muted">[${catShort}]</span> — ${it.count}\u00D7${contacts}`;
        if (types) html += ` <span class="muted">(${types})</span>`;
        if (dates) html += `<div class="small muted" style="margin-left:12px">${dates}</div>`;
        html += `</div>`;
      }
    } else if (type === "inactivity_gap") {
      for (const it of items) {
        const lastType = (it.last_type || "").replace(/_/g, " ");
        const firstType = (it.first_type || "").replace(/_/g, " ");
        html += `<div style="margin-bottom:4px">`;
        html += `<b>${it.gap_hours}h</b> przerwy: `;
        html += `ostatni \u2014 ${it.last_date} ${it.last_time} <code>${it.last_contact}</code> <span class="muted">(${lastType})</span>`;
        html += ` \u2192 pierwszy \u2014 ${it.first_date} ${it.first_time} <code>${it.first_contact}</code> <span class="muted">(${firstType})</span>`;
        html += `</div>`;
      }
    } else {
      for (const it of items) {
        html += `<div>${it.description || JSON.stringify(it)}</div>`;
      }
    }

    html += '</div>';
    return html;
  }

  /* ── Contact relationship graph (SVG) ──────────────────── */

  function _renderContactGraph(contacts, msisdn) {
    const wrap = QS("#gsm_contact_graph");
    if (!wrap || !contacts || !contacts.length) return;

    const N = contacts.length;
    const trunc = (s, max) => s.length > max ? s.slice(0, max - 1) + "\u2026" : s;

    // ── Layout: two rows of cards (top + bottom) around centered subscriber ──
    const topN = Math.ceil(N / 2);
    const botN = N - topN;
    const maxPerRow = Math.max(topN, botN);
    const CW = 115, CH = 82, CGAP = 10;
    const W = Math.max(maxPerRow * (CW + CGAP) - CGAP + 30, 460);

    // Auto-scale card width — capped at 1/3 of Records card width
    const graphCard = QS("#gsm_graph_card");
    if (graphCard && !graphCard.dataset.userResized) {
      const recordsCard = QS("#gsm_records_card");
      const maxW = recordsCard ? Math.round(recordsCard.offsetWidth / 3) : Infinity;
      const pct = Math.min(100, Math.max(33, maxPerRow * 11 + 2));
      graphCard.style.width = pct + "%";
      if (maxW < Infinity) graphCard.style.maxWidth = maxW + "px";
    }
    const CARD_Y_TOP = 22;
    const SUB_Y = CARD_Y_TOP + CH + 70;
    const CARD_Y_BOT = SUB_Y + 70;
    const H = botN > 0 ? CARD_Y_BOT + CH + 8 : SUB_Y + 60;
    const CX = W / 2;

    // SVG icons (compact)
    const personIcon = `<circle cx="0" cy="-5" r="3.8" fill="none" stroke-width="1.2"/>
      <path d="M-6.5 5 Q-6.5 0 0 -0.5 Q6.5 0 6.5 5" fill="none" stroke-width="1.2"/>`;
    const companyIcon = `<rect x="-5" y="-7" width="10" height="13" rx="1" fill="none" stroke-width="1.1"/>
      <line x1="-2.5" y1="-3" x2="-2.5" y2="-1" stroke-width="0.9"/>
      <line x1="0" y1="-3" x2="0" y2="-1" stroke-width="0.9"/>
      <line x1="2.5" y1="-3" x2="2.5" y2="-1" stroke-width="0.9"/>
      <line x1="-2.5" y1="1.5" x2="-2.5" y2="3.5" stroke-width="0.9"/>
      <line x1="0" y1="1.5" x2="0" y2="3.5" stroke-width="0.9"/>
      <line x1="2.5" y1="1.5" x2="2.5" y2="3.5" stroke-width="0.9"/>`;
    const subscriberIcon = `<circle cx="-3" cy="-5" r="4.2" fill="none" stroke-width="1.4"/>
      <path d="M-9 6 Q-9 0 -3 -0.5 Q3 0 3 6" fill="none" stroke-width="1.4"/>
      <rect x="6" y="-7" width="5" height="10" rx="1.2" fill="none" stroke-width="1.1"/>
      <circle cx="8.5" cy="0.5" r="0.7" fill="currentColor"/>`;

    let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
      style="width:100%;height:auto;font-family:system-ui,-apple-system,sans-serif">`;

    svg += `<defs>
      <marker id="gsm_arrow_out" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto" markerUnits="userSpaceOnUse">
        <path d="M0.5,0.5 L6,2.5 L0.5,4.5" fill="#34c759" stroke="none"/>
      </marker>
      <marker id="gsm_arrow_in" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto" markerUnits="userSpaceOnUse">
        <path d="M0.5,0.5 L6,2.5 L0.5,4.5" fill="#ff4d4f" stroke="none"/>
      </marker>
      <filter id="gsm_card_shadow" x="-4%" y="-4%" width="108%" height="116%">
        <feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-opacity="0.07"/>
      </filter>
    </defs>`;

    // Legend (top-right)
    const legX = W - 175;
    svg += `<line x1="${legX}" y1="10" x2="${legX + 18}" y2="10" stroke="#34c759" stroke-width="1.5" stroke-linecap="round" marker-end="url(#gsm_arrow_out)"/>
    <text x="${legX + 23}" y="13" font-size="7.5" fill="var(--text-muted,#64748b)">Wychodz\u0105ce</text>
    <line x1="${legX + 82}" y1="10" x2="${legX + 100}" y2="10" stroke="#ff4d4f" stroke-width="1.5" stroke-linecap="round" marker-end="url(#gsm_arrow_in)"/>
    <text x="${legX + 105}" y="13" font-size="7.5" fill="var(--text-muted,#64748b)">Przychodz\u0105ce</text>`;

    // Card positions helper
    const cardPositions = (count, y) => {
      const totalW = count * CW + (count - 1) * CGAP;
      const startX = (W - totalW) / 2;
      return Array.from({ length: count }, (_, i) => ({ x: startX + i * (CW + CGAP), y }));
    };
    const topCards = cardPositions(topN, CARD_Y_TOP);
    const botCards = cardPositions(botN, CARD_Y_BOT);
    const allCards = [...topCards.map((p, i) => ({ ...p, i, c: contacts[i], isTop: true })),
                      ...botCards.map((p, j) => ({ ...p, i: topN + j, c: contacts[topN + j], isTop: false }))];

    // ── Subscriber card dimensions (rectangular, wider than contact cards) ──
    const SUB_W = 180, SUB_H = 82;
    const SUB_X = CX - SUB_W / 2;
    // Compute total OUT/IN across all displayed contacts
    let subTotalOut = 0, subTotalIn = 0;
    let subCallsOut = 0, subCallsIn = 0, subSmsOut = 0, subSmsIn = 0;
    for (const card of allCards) {
      subCallsOut += card.c.calls_out || 0;
      subSmsOut   += card.c.sms_out   || 0;
      subCallsIn  += card.c.calls_in  || 0;
      subSmsIn    += card.c.sms_in    || 0;
    }
    subTotalOut = subCallsOut + subSmsOut;
    subTotalIn  = subCallsIn  + subSmsIn;

    // ── Straight-line arrows — behind cards ──
    const EDGE_GAP = 6;
    const SEP = 3;

    for (const card of allCards) {
      const c = card.c, idx = card.i;
      const cardCX = card.x + CW / 2;
      const cardEdgeY = card.isTop ? card.y + CH : card.y;
      const outAll = (c.calls_out || 0) + (c.sms_out || 0);
      const outCalls = c.calls_out || 0, outSms = c.sms_out || 0;
      const inAll = (c.calls_in || 0) + (c.sms_in || 0);
      const inCalls = c.calls_in || 0, inSms = c.sms_in || 0;

      // Direction from subscriber to card & perpendicular
      const dx = cardCX - CX, dy = cardEdgeY - SUB_Y;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const nx = dx / len, ny = dy / len;
      const perpX = -ny, perpY = nx;

      // Endpoints: A near subscriber rect edge, B near card edge
      // Clamp to subscriber rectangle boundary
      const _clampToRect = (cx, cy, rw, rh, tgtX, tgtY) => {
        const ddx = tgtX - cx, ddy = tgtY - cy;
        const hw = rw / 2, hh = rh / 2;
        if (ddx === 0 && ddy === 0) return { x: cx, y: cy - hh };
        const sx = Math.abs(ddx) > 0.01 ? hw / Math.abs(ddx) : 1e9;
        const sy = Math.abs(ddy) > 0.01 ? hh / Math.abs(ddy) : 1e9;
        const s = Math.min(sx, sy);
        return { x: cx + ddx * s, y: cy + ddy * s };
      };
      const subEdge = _clampToRect(CX, SUB_Y, SUB_W + 4, SUB_H + 4, cardCX, cardEdgeY);
      const ax = subEdge.x, ay = subEdge.y;
      const bx = cardCX - nx * EDGE_GAP, by = cardEdgeY - ny * EDGE_GAP;

      // OUT: A→B shifted +perp (green, arrow at card end)
      if (outAll > 0) {
        const x1 = ax + perpX * SEP, y1 = ay + perpY * SEP;
        const x2 = bx + perpX * SEP, y2 = by + perpY * SEP;
        svg += `<line class="gsm-graph-edge" data-edge="out" data-idx="${idx}" data-number="${c.number}"
          x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
          stroke="#34c759" stroke-width="1.5" stroke-linecap="round" opacity="0.7"
          marker-end="url(#gsm_arrow_out)"
          data-all="${outAll}" data-calls="${outCalls}" data-sms="${outSms}"/>`;
      }
      // IN: B→A shifted −perp (red, arrow at subscriber end)
      if (inAll > 0) {
        const x1 = bx - perpX * SEP, y1 = by - perpY * SEP;
        const x2 = ax - perpX * SEP, y2 = ay - perpY * SEP;
        svg += `<line class="gsm-graph-edge" data-edge="in" data-idx="${idx}" data-number="${c.number}"
          x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
          stroke="#ff4d4f" stroke-width="1.5" stroke-linecap="round" opacity="0.7"
          marker-end="url(#gsm_arrow_in)"
          data-all="${inAll}" data-calls="${inCalls}" data-sms="${inSms}"/>`;
      }
    }

    // ── Contact cards ──
    for (const card of allCards) {
      const c = card.c, idx = card.i;
      const info = _idLookup(c.number);
      const isCompany = info && info.type === "company";
      const icon = isCompany ? companyIcon : personIcon;
      const color = isCompany ? "#7c3aed" : "#64748b";
      const idLabel = info && info.label ? trunc(info.label, 16) : "";
      const outAll = (c.calls_out || 0) + (c.sms_out || 0);
      const outCalls = c.calls_out || 0, outSms = c.sms_out || 0;
      const inAll = (c.calls_in || 0) + (c.sms_in || 0);
      const inCalls = c.calls_in || 0, inSms = c.sms_in || 0;
      const bw = CW - 8;
      const icx = card.x + CW / 2;

      svg += `<g class="gsm-graph-node" data-idx="${idx}" data-number="${c.number}" style="cursor:pointer"
        title="2\u00d7LPM \u2192 filtruj rekordy">`;
      svg += `<rect class="gsm-graph-node-bg" x="${card.x}" y="${card.y}" width="${CW}" height="${CH}"
        rx="7" fill="var(--bg-card,#fff)" stroke="var(--border,#e2e8f0)" stroke-width="0.8" filter="url(#gsm_card_shadow)"/>`;
      // Icon
      svg += `<g transform="translate(${icx},${card.y + 13})" stroke="${color}" fill="none" color="${color}">${icon}</g>`;
      // Full phone number
      svg += `<text x="${icx}" y="${card.y + 30}" text-anchor="middle" font-size="7.5" font-weight="500" fill="var(--text,#334155)">${c.number}</text>`;
      // Identification label (or editable placeholder)
      if (idLabel) {
        svg += `<text class="gsm-graph-id-label gsm-graph-id-edit" data-number="${c.number}" x="${icx}" y="${card.y + 39}" text-anchor="middle" font-size="6.5" fill="${isCompany ? '#7c3aed' : '#2563eb'}" font-style="italic" style="cursor:text">${idLabel}</text>`;
      } else {
        svg += `<text class="gsm-graph-id-label gsm-graph-id-empty" data-number="${c.number}" x="${icx}" y="${card.y + 39}" text-anchor="middle" font-size="6.5" fill="var(--text-muted,#94a3b8)" font-style="italic" style="cursor:text">\u270E dodaj nazw\u0119</text>`;
      }
      // OUT badge
      const by1 = card.y + 46;
      svg += `<g data-elabel="out" data-idx="${idx}" data-all="${outAll}" data-calls="${outCalls}" data-sms="${outSms}"
        ${outAll === 0 ? 'style="display:none"' : ""}>
        <rect x="${card.x + 4}" y="${by1}" width="${bw}" height="12" rx="3" fill="#dcfce7"/>
        <text x="${card.x + 9}" y="${by1 + 9}" font-size="6.5" font-weight="700" fill="#16a34a">OUT</text>
        <text x="${card.x + CW - 6}" y="${by1 + 9}" font-size="7.5" font-weight="600" fill="#16a34a" text-anchor="end">${outAll}</text>
      </g>`;
      // IN badge
      const by2 = card.y + 60;
      svg += `<g data-elabel="in" data-idx="${idx}" data-all="${inAll}" data-calls="${inCalls}" data-sms="${inSms}"
        ${inAll === 0 ? 'style="display:none"' : ""}>
        <rect x="${card.x + 4}" y="${by2}" width="${bw}" height="12" rx="3" fill="#fee2e2"/>
        <text x="${card.x + 9}" y="${by2 + 9}" font-size="6.5" font-weight="700" fill="#dc2626">IN</text>
        <text x="${card.x + CW - 6}" y="${by2 + 9}" font-size="7.5" font-weight="600" fill="#dc2626" text-anchor="end">${inAll}</text>
      </g>`;
      svg += `</g>`;
    }

    // ── Subscriber node (rectangular card, centered between rows) ──
    const subLabel = msisdn || "Abonent";
    const subInfo = msisdn ? _idLookup(msisdn) : null;
    const subIdLabel = subInfo && subInfo.label ? trunc(subInfo.label, 22) : "";
    const subBw = SUB_W - 10;

    svg += `<g style="cursor:default">`;
    // Card background
    svg += `<rect x="${SUB_X}" y="${SUB_Y - SUB_H / 2}" width="${SUB_W}" height="${SUB_H}"
      rx="8" fill="var(--bg-card,#fff)" stroke="#2563eb" stroke-width="1.8" filter="url(#gsm_card_shadow)"/>`;
    // Subscriber icon (top-left area)
    svg += `<g transform="translate(${SUB_X + 16},${SUB_Y - SUB_H / 2 + 16})" stroke="#2563eb" fill="none" color="#2563eb">${subscriberIcon}</g>`;
    // Phone number
    svg += `<text x="${SUB_X + 32}" y="${SUB_Y - SUB_H / 2 + 14}" font-size="8.5" font-weight="600" fill="var(--text,#334155)">${subLabel}</text>`;
    // Identification label
    if (subIdLabel) {
      svg += `<text class="gsm-graph-sub-id" x="${SUB_X + 32}" y="${SUB_Y - SUB_H / 2 + 24}" font-size="7" font-weight="500" fill="#2563eb" font-style="italic">${subIdLabel}</text>`;
    } else if (msisdn) {
      svg += `<text class="gsm-graph-sub-id gsm-graph-sub-id-empty" data-number="${msisdn}" x="${SUB_X + 32}" y="${SUB_Y - SUB_H / 2 + 24}" font-size="7" fill="var(--text-muted,#94a3b8)" font-style="italic" style="cursor:text">\u270E dodaj nazw\u0119</text>`;
    } else {
      svg += `<text x="${SUB_X + 32}" y="${SUB_Y - SUB_H / 2 + 24}" font-size="7" fill="var(--text-muted,#64748b)">Abonent</text>`;
    }
    // OUT badge
    const sby1 = SUB_Y - SUB_H / 2 + 32;
    svg += `<g data-sub-label="out" data-all="${subTotalOut}" data-calls="${subCallsOut}" data-sms="${subSmsOut}">
      <rect x="${SUB_X + 5}" y="${sby1}" width="${subBw}" height="14" rx="3" fill="#dcfce7"/>
      <text x="${SUB_X + 10}" y="${sby1 + 10}" font-size="7" font-weight="700" fill="#16a34a">OUT</text>
      <text x="${SUB_X + SUB_W - 8}" y="${sby1 + 10}" font-size="8" font-weight="600" fill="#16a34a" text-anchor="end">${subTotalOut}</text>
    </g>`;
    // IN badge
    const sby2 = SUB_Y - SUB_H / 2 + 48;
    svg += `<g data-sub-label="in" data-all="${subTotalIn}" data-calls="${subCallsIn}" data-sms="${subSmsIn}">
      <rect x="${SUB_X + 5}" y="${sby2}" width="${subBw}" height="14" rx="3" fill="#fee2e2"/>
      <text x="${SUB_X + 10}" y="${sby2 + 10}" font-size="7" font-weight="700" fill="#dc2626">IN</text>
      <text x="${SUB_X + SUB_W - 8}" y="${sby2 + 10}" font-size="8" font-weight="600" fill="#dc2626" text-anchor="end">${subTotalIn}</text>
    </g>`;
    svg += `</g>`;

    svg += "</svg>";
    wrap.innerHTML = svg;

    // ── Hover highlight ──
    wrap.querySelectorAll(".gsm-graph-node").forEach(g => {
      g.addEventListener("mouseenter", () => {
        const idx = g.dataset.idx;
        const bg = g.querySelector(".gsm-graph-node-bg");
        if (bg) { bg.setAttribute("stroke", "var(--primary,#2563eb)"); bg.setAttribute("stroke-width", "1.8"); }
        wrap.querySelectorAll(`.gsm-graph-edge[data-idx="${idx}"]`).forEach(e => {
          e.dataset._origSw = e.getAttribute("stroke-width");
          e.dataset._origOp = e.getAttribute("opacity");
          e.setAttribute("opacity", "1"); e.setAttribute("stroke-width", "2.5");
        });
      });
      g.addEventListener("mouseleave", () => {
        const idx = g.dataset.idx;
        const bg = g.querySelector(".gsm-graph-node-bg");
        if (bg) { bg.setAttribute("stroke", "var(--border,#e2e8f0)"); bg.setAttribute("stroke-width", "0.8"); }
        wrap.querySelectorAll(`.gsm-graph-edge[data-idx="${idx}"]`).forEach(e => {
          e.setAttribute("opacity", e.dataset._origOp || "0.7");
          if (e.dataset._origSw) e.setAttribute("stroke-width", e.dataset._origSw);
        });
      });
      // Double-click → filter Records
      g.addEventListener("dblclick", () => {
        const num = g.dataset.number;
        if (!num) return;
        const allRecs = St.lastResult ? St.lastResult.records : [];
        const filtered = allRecs.filter(r => r.callee === num);
        const info = _idLookup(num);
        const label = info && info.label ? info.label : num;
        _setRecordsFilter(`${label} \u2014 ${filtered.length} rek.`, () => {
          _clearRecordsFilter();
          if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
        });
        _renderRecords(filtered, false, filtered.length);
        QS("#gsm_records_card")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    // ── Inline editing helper — overlays <input> on SVG text element ──
    function _startInlineEdit(textEl, number) {
      if (!wrap || !number) return;
      // Remove any existing inline input
      wrap.querySelectorAll(".gsm-inline-input").forEach(el => el.remove());
      wrap.style.position = "relative";

      const wrapRect = wrap.getBoundingClientRect();
      const textRect = textEl.getBoundingClientRect();
      const existing = _idLookup(number);
      const currentVal = existing && existing.label ? existing.label : "";

      const input = document.createElement("input");
      input.type = "text";
      input.value = currentVal;
      input.placeholder = "Wpisz nazw\u0119\u2026";
      input.className = "gsm-inline-input";
      const inputW = Math.max(textRect.width + 30, 110);
      input.style.cssText = `
        position:absolute;
        left:${textRect.left - wrapRect.left - (inputW - textRect.width) / 2}px;
        top:${textRect.top - wrapRect.top - 3}px;
        width:${inputW}px; height:20px;
        font-size:11px; text-align:center;
        border:1.5px solid var(--primary,#2563eb); border-radius:5px;
        outline:none; background:var(--bg-card,#fff); color:var(--text,#334155);
        padding:0 6px; z-index:10;
        box-shadow:0 2px 10px rgba(0,0,0,0.18);
      `;
      wrap.appendChild(input);
      input.focus();
      if (currentVal) input.select();

      let saved = false;
      const save = () => {
        if (saved) return; saved = true;
        const name = input.value.trim();
        if (input.parentNode) input.remove();
        if (!name) return;
        const norm = _normMsisdn(number);
        St.idMap[norm] = { label: name, type: St.idMap[norm]?.type || "person" };
        _saveToProject();
        const topSel = QS("#gsm_graph_top_n");
        const n = parseInt(topSel?.value || "10");
        _renderContactGraph(St._graphContacts.slice(0, n), St._graphMsisdn);
      };
      const cancel = () => { saved = true; if (input.parentNode) input.remove(); };

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); save(); }
        if (e.key === "Escape") { e.preventDefault(); cancel(); }
      });
      input.addEventListener("blur", () => setTimeout(save, 80));
    }

    // ── Click on contact label (empty or existing) → inline edit ──
    wrap.querySelectorAll(".gsm-graph-id-empty, .gsm-graph-id-edit").forEach(txt => {
      txt.addEventListener("click", (e) => {
        e.stopPropagation();
        const num = txt.dataset.number;
        if (num) _startInlineEdit(txt, num);
      });
    });

    // ── Click on subscriber label (empty or existing) → inline edit ──
    wrap.querySelectorAll(".gsm-graph-sub-id").forEach(txt => {
      txt.style.cursor = "text";
      txt.addEventListener("click", (e) => {
        e.stopPropagation();
        const num = txt.dataset.number || msisdn;
        if (num) _startInlineEdit(txt, num);
      });
    });
  }

  /** Apply type filter (all/calls/sms) to the contact graph arrows + labels. */
  function _applyGraphFilter(mode) {
    const wrap = QS("#gsm_contact_graph");
    if (!wrap) return;
    // Update arrow visibility & thickness
    wrap.querySelectorAll("[data-edge]").forEach(path => {
      const val = parseInt(path.dataset[mode] || "0");
      path.style.display = val > 0 ? "" : "none";
      // Keep stroke-width in the 1.2–2px range
      const sw = Math.min(2, Math.max(1.2, 1.2 + Math.log2(Math.max(val, 1)) * 0.15));
      path.setAttribute("stroke-width", sw.toFixed(1));
    });
    // Update card badges (<g data-elabel> with two <text> children: label + number)
    wrap.querySelectorAll("[data-elabel]").forEach(badge => {
      const val = parseInt(badge.dataset[mode] || "0");
      badge.style.display = val > 0 ? "" : "none";
      // Update the LAST text child (the number), keep the first ("OUT"/"IN")
      const texts = badge.querySelectorAll("text");
      if (texts.length >= 2) texts[texts.length - 1].textContent = val;
      else if (texts.length === 1) texts[0].textContent = val;
    });
    // Update subscriber OUT/IN badges (sum visible contacts)
    wrap.querySelectorAll("[data-sub-label]").forEach(badge => {
      const val = parseInt(badge.dataset[mode] || "0");
      badge.style.display = val > 0 ? "" : "none";
      const texts = badge.querySelectorAll("text");
      if (texts.length >= 2) texts[texts.length - 1].textContent = val;
    });
  }

  /**
   * Main entry point for rendering records.
   * Stores source records, applies column filters, and renders.
   */
  function _renderRecords(records, truncated, totalCount) {
    _initColumns();
    _currentSourceRecords = records;
    _currentSourceTruncated = truncated;
    _currentSourceTotal = totalCount;

    const filtered = _applyColumnFilters(records || []);
    _renderFilterChips();
    _renderRecordsTable(filtered, truncated && !Object.keys(St.columnFilters).length, Object.keys(St.columnFilters).length ? filtered.length : totalCount);
  }

  /**
   * Low-level table renderer (called by _renderRecords and _refilterRecords).
   */
  function _renderRecordsTable(records, truncated, totalCount) {
    const el = QS("#gsm_records_body");
    if (!el) return;

    if (!records || !records.length) {
      el.innerHTML = '<div class="small muted">Brak rekordów.</div>';
      const countLabel = QS("#gsm_records_count");
      if (countLabel) countLabel.textContent = _activeFilterCount() ? "0 (filtr)" : "";
      return;
    }

    const countLabel = QS("#gsm_records_count");
    if (countLabel) {
      if (_activeFilterCount()) {
        countLabel.textContent = `${_fmt(records.length)} (filtr kolumn)`;
      } else {
        countLabel.textContent = truncated ? `${records.length} z ${_fmt(totalCount)}` : _fmt(totalCount);
      }
    }

    const cols = _visibleColumns();

    // Sort if active
    let sorted = records;
    if (St.columnSort) {
      const colDef = _COL_MAP[St.columnSort.key];
      if (colDef) {
        sorted = [...records].sort((a, b) => {
          let va = colDef.getValue(a), vb = colDef.getValue(b);
          if (colDef.type === "numeric") {
            va = typeof va === "number" ? va : parseFloat(va) || 0;
            vb = typeof vb === "number" ? vb : parseFloat(vb) || 0;
            return St.columnSort.dir === "asc" ? va - vb : vb - va;
          }
          va = String(va).toLowerCase();
          vb = String(vb).toLowerCase();
          const cmp = va < vb ? -1 : va > vb ? 1 : 0;
          return St.columnSort.dir === "asc" ? cmp : -cmp;
        });
      }
    }

    let html = `<table class="gsm-table gsm-table-adv"><thead><tr>`;
    for (const col of cols) {
      const hasFilter = !!St.columnFilters[col.key];
      const sortDir = St.columnSort && St.columnSort.key === col.key ? St.columnSort.dir : null;
      const sortIcon = sortDir === "asc" ? " ↑" : sortDir === "desc" ? " ↓" : "";
      html += `<th class="${hasFilter ? "gsm-th-filtered" : ""}" data-col="${col.key}">
        <span class="gsm-th-content">
          <span class="gsm-th-label" title="Kliknij aby sortować">${col.label}${sortIcon}</span>
          <button class="gsm-col-filter-btn${hasFilter ? " active" : ""}" data-col="${col.key}" title="Filtruj kolumnę">▿</button>
        </span>
      </th>`;
    }
    html += `</tr></thead><tbody>`;

    const hl = St._anomalyHighlight || null;
    for (const r of sorted) {
      let rowStyle = "";
      if (hl) {
        if (hl.anomalyRecords && hl.anomalyRecords.has(r)) {
          rowStyle = ' style="background:rgba(239,68,68,.12)"';
        } else if (hl.contextRecords && hl.contextRecords.has(r)) {
          rowStyle = ' style="background:rgba(59,130,246,.10)"';
        }
      }
      html += `<tr${rowStyle}>`;
      for (const col of cols) {
        html += `<td>${col.renderCell(r)}</td>`;
      }
      html += `</tr>`;
    }
    html += "</tbody></table>";
    if (truncated) {
      html += `<div class="small muted" style="margin-top:8px">Pokazano ${records.length} z ${_fmt(totalCount)} rekordów.</div>`;
    }
    el.innerHTML = html;

    // Bind header interactions
    el.querySelectorAll(".gsm-col-filter-btn").forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const colKey = btn.dataset.col;
        const th = btn.closest("th");
        _openColFilter(colKey, th);
      };
    });
    el.querySelectorAll(".gsm-th-label").forEach(label => {
      label.onclick = () => {
        const colKey = label.closest("th").dataset.col;
        if (St.columnSort && St.columnSort.key === colKey) {
          St.columnSort.dir = St.columnSort.dir === "asc" ? "desc" : "asc";
        } else {
          St.columnSort = { key: colKey, dir: "asc" };
        }
        _refilterRecords();
      };
      label.style.cursor = "pointer";
    });

    // Bind column drag-and-drop reordering on headers
    _bindColumnDragDrop(el);
  }

  /* ── Column drag & drop (custom mouse events) ────────── */

  let _colDrag = null; // active drag state

  function _bindColumnDragDrop(container) {
    const ths = container.querySelectorAll("thead th[data-col]");
    ths.forEach(th => {
      th.addEventListener("mousedown", e => _colDragStart(e, th, container));
      th.style.cursor = "grab";
    });
  }

  function _colDragStart(e, th, container) {
    // Ignore right-click, filter button clicks
    if (e.button !== 0) return;
    if (e.target.closest(".gsm-col-filter-btn")) return;

    const startX = e.clientX;
    const startY = e.clientY;
    const colKey = th.dataset.col;
    const THRESHOLD = 5;
    let dragging = false;

    function onMove(ev) {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;

      if (!dragging) {
        if (Math.abs(dx) < THRESHOLD && Math.abs(dy) < THRESHOLD) return;
        // Start drag
        dragging = true;
        _colDragBegin(th, colKey, container, startX);
      }
      _colDragMove(ev.clientX);
    }

    function onUp(ev) {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (dragging) {
        _colDragEnd();
      }
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  function _colDragBegin(th, colKey, container, startX) {
    // Collect header rects
    const thead = container.querySelector("thead");
    const allThs = Array.from(thead.querySelectorAll("th[data-col]"));
    const rects = allThs.map(el => ({ el, key: el.dataset.col, rect: el.getBoundingClientRect() }));

    // Ghost element
    const ghost = document.createElement("div");
    ghost.className = "gsm-col-drag-ghost";
    ghost.textContent = th.textContent.replace(/[▿↑↓]/g, "").trim();
    const thRect = th.getBoundingClientRect();
    ghost.style.width = thRect.width + "px";
    ghost.style.left = thRect.left + "px";
    ghost.style.top = (thRect.top - 4) + "px";
    document.body.appendChild(ghost);

    // Drop indicator line
    const indicator = document.createElement("div");
    indicator.className = "gsm-col-drop-indicator";
    document.body.appendChild(indicator);

    // Dim source column
    th.classList.add("gsm-th-dragging");

    _colDrag = {
      colKey,
      th,
      ghost,
      indicator,
      container,
      rects,
      allThs,
      startX,
      offsetX: startX - thRect.left,
      dropIndex: -1,
    };

    document.body.style.cursor = "grabbing";
    document.body.style.userSelect = "none";
  }

  function _colDragMove(clientX) {
    if (!_colDrag) return;
    const { ghost, indicator, rects, colKey, offsetX } = _colDrag;

    // Move ghost
    ghost.style.left = (clientX - offsetX) + "px";

    // Find drop position
    let dropIdx = -1;
    let indicatorLeft = 0;
    const sourceIdx = rects.findIndex(r => r.key === colKey);

    for (let i = 0; i < rects.length; i++) {
      const r = rects[i].rect;
      const mid = r.left + r.width / 2;
      if (clientX < mid) {
        dropIdx = i;
        indicatorLeft = r.left - 2;
        break;
      }
    }
    if (dropIdx === -1) {
      // After last column
      dropIdx = rects.length;
      const last = rects[rects.length - 1].rect;
      indicatorLeft = last.right - 2;
    }

    // Don't show indicator if drop would result in no change
    if (dropIdx === sourceIdx || dropIdx === sourceIdx + 1) {
      indicator.style.display = "none";
    } else {
      const headerTop = rects[0].rect.top;
      const headerBottom = rects[0].rect.bottom;
      indicator.style.display = "";
      indicator.style.left = indicatorLeft + "px";
      indicator.style.top = (headerTop - 4) + "px";
      indicator.style.height = (headerBottom - headerTop + 8) + "px";
    }

    _colDrag.dropIndex = dropIdx;
  }

  function _colDragEnd() {
    if (!_colDrag) return;
    const { colKey, ghost, indicator, th, dropIndex, rects } = _colDrag;

    // Cleanup DOM
    ghost.remove();
    indicator.remove();
    th.classList.remove("gsm-th-dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";

    const sourceIdx = rects.findIndex(r => r.key === colKey);

    // Apply reorder if position changed
    if (dropIndex !== -1 && dropIndex !== sourceIdx && dropIndex !== sourceIdx + 1) {
      const visibleKeys = rects.map(r => r.key);
      // Remove from old position
      visibleKeys.splice(sourceIdx, 1);
      // Insert at new position (adjust index if after source)
      const insertAt = dropIndex > sourceIdx ? dropIndex - 1 : dropIndex;
      visibleKeys.splice(insertAt, 0, colKey);

      // Rebuild full columnOrder: keep hidden columns in their relative positions,
      // but reorder visible ones according to new order
      const hiddenKeys = (St.columnOrder || []).filter(k => St.columnHidden[k]);
      // Merge: visible in new order, hidden appended at end
      St.columnOrder = [...visibleKeys, ...hiddenKeys];

      _refilterRecords();
    }

    _colDrag = null;
  }

  /* ── special numbers ──────────────────────────────────── */

  const _SN_CAT_LABELS = {
    voicemail: "Poczta g\u0142osowa",
    service: "Us\u0142uga operatora",
    emergency: "Nr alarmowy",
    premium: "Nr premium",
    toll_free: "Nr bezp\u0142atny",
    short_code: "Kod kr\u00F3tki",
    international: "Zagraniczny",
    info: "Informacja",
    operator_sms: "SMS operatora",
    commercial_sms: "SMS komercyjny",
    alphanumeric: "ID alfanumeryczny",
    ussd: "Kod steruj\u0105cy",
  };
  const _SN_CAT_CLS = {
    voicemail: "gsm-sn-voicemail",
    service: "gsm-sn-service",
    emergency: "gsm-sn-emergency",
    premium: "gsm-sn-premium",
    toll_free: "gsm-sn-tollfree",
    short_code: "gsm-sn-short",
    international: "gsm-sn-intl",
    info: "gsm-sn-info",
    operator_sms: "gsm-sn-operator",
    commercial_sms: "gsm-sn-commercial",
    alphanumeric: "gsm-sn-alpha",
    ussd: "gsm-sn-ussd",
  };

  // State for special numbers filtering
  let _snAllData = [];
  let _snFilterCat = "";  // "" = all
  let _snFilterText = "";

  function _renderSpecialNumbers(specials) {
    const el = QS("#gsm_special_numbers_body");
    if (!el) return;
    const card = el.closest(".card");

    if (!specials || !specials.length) {
      if (card) card.style.display = "none";
      return;
    }
    if (card) card.style.display = "";

    _snAllData = specials;
    _snFilterCat = "";
    _snFilterText = "";

    // Collect unique categories present in data
    const cats = [...new Set(specials.map(s => s.category))].sort();

    // Build filter bar
    let filterHtml = `<div class="gsm-sn-filters" style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">`;
    filterHtml += `<select id="gsm_sn_cat_filter" style="font-size:12px;padding:4px 8px;border:1px solid var(--border,#e2e8f0);border-radius:6px;background:var(--bg-secondary,#f8fafc);color:var(--text,#334155);cursor:pointer">`;
    filterHtml += `<option value="">Wszystkie kategorie (${specials.length})</option>`;
    for (const c of cats) {
      const cnt = specials.filter(s => s.category === c).length;
      filterHtml += `<option value="${c}">${_SN_CAT_LABELS[c] || c} (${cnt})</option>`;
    }
    filterHtml += `</select>`;
    filterHtml += `<input id="gsm_sn_text_filter" type="text" placeholder="Szukaj numeru lub opisu\u2026" style="font-size:12px;padding:4px 8px;border:1px solid var(--border,#e2e8f0);border-radius:6px;flex:1;min-width:140px;max-width:280px;background:var(--bg-secondary,#f8fafc);color:var(--text,#334155)">`;
    filterHtml += `<span id="gsm_sn_count" class="gsm-sn-count" style="margin:0">\u0141\u0105cznie: ${specials.length}</span>`;
    filterHtml += `</div>`;

    el.innerHTML = filterHtml + `<div id="gsm_sn_table_wrap" class="gsm-sn-container"></div>`;

    _snRebuildTable(specials);

    // Wire up filter events
    const catSel = QS("#gsm_sn_cat_filter");
    const textInp = QS("#gsm_sn_text_filter");
    if (catSel) catSel.addEventListener("change", _snApplyFilters);
    if (textInp) textInp.addEventListener("input", _snApplyFilters);
  }

  function _snApplyFilters() {
    const catSel = QS("#gsm_sn_cat_filter");
    const textInp = QS("#gsm_sn_text_filter");
    _snFilterCat = catSel ? catSel.value : "";
    _snFilterText = textInp ? textInp.value.trim().toLowerCase() : "";

    let filtered = _snAllData;
    if (_snFilterCat) {
      filtered = filtered.filter(s => s.category === _snFilterCat);
    }
    if (_snFilterText) {
      filtered = filtered.filter(s =>
        (s.number || "").toLowerCase().includes(_snFilterText) ||
        (s.label || "").toLowerCase().includes(_snFilterText) ||
        (_SN_CAT_LABELS[s.category] || "").toLowerCase().includes(_snFilterText)
      );
    }
    const countEl = QS("#gsm_sn_count");
    if (countEl) countEl.textContent = `Wynik: ${filtered.length} z ${_snAllData.length}`;
    _snRebuildTable(filtered);
  }

  function _snRebuildTable(items) {
    const wrap = QS("#gsm_sn_table_wrap");
    if (!wrap) return;

    if (!items.length) {
      wrap.innerHTML = `<div style="padding:12px;color:var(--text-muted);font-size:13px">Brak wynik\u00F3w dla wybranych filtr\u00F3w</div>`;
      return;
    }

    let tbl = `<table class="gsm-table"><thead><tr>
      <th>Numer</th><th>Kategoria</th><th>Opis</th><th>Interakcje</th><th>Czas rozm\u00F3w</th><th>Okres</th>
    </tr></thead><tbody>`;

    for (const s of items) {
      const cat = _SN_CAT_LABELS[s.category] || s.category;
      const cls = _SN_CAT_CLS[s.category] || "";
      const period = s.first_date
        ? (s.first_date === s.last_date ? s.first_date : `${s.first_date} \u2013 ${s.last_date}`)
        : "\u2014";
      tbl += `<tr>
        <td><code>${s.number}</code></td>
        <td><span class="gsm-sn-badge ${cls}">${cat}</span></td>
        <td>${s.label || "\u2014"}</td>
        <td>${_fmt(s.interactions)}</td>
        <td>${_dur(s.total_duration_seconds || 0)}</td>
        <td>${period}</td>
      </tr>`;
    }
    tbl += "</tbody></table>";
    wrap.innerHTML = tbl;
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
    const row = QS("#gsm_activity_row");
    if (!row) return;

    // Remove previously injected night/weekend chart cards (keep heatmap card)
    row.querySelectorAll("[data-chart-id]").forEach(el => el.remove());

    if (!analysis) return;

    const night = analysis.night_activity;
    const weekend = analysis.weekend_activity;

    if (night && night.total_records) {
      row.insertAdjacentHTML("beforeend",
        _renderOneChart("night", "Aktywność nocna", "22:00–6:00", night, _nightTotalBars));
    }
    if (weekend && weekend.total_records) {
      row.insertAdjacentHTML("beforeend",
        _renderOneChart("weekend", "Aktywność weekendowa", "Pt 20:00–Pn 6:00", weekend, _weekendTotalBars));
    }

    // Wire period selectors (only for night/weekend, not heatmap selects)
    row.querySelectorAll("[data-chart-id] .gsm-period-select").forEach(sel => {
      sel.onchange = () => _onPeriodChange(sel, analysis);
    });

    _bindCardScreenshotButtons(row);
  }

  function _renderOneChart(id, title, subtitle, d, buildTotalBars) {
    const weeklyKeys = Object.keys(d.weekly || {});
    const monthlyKeys = Object.keys(d.monthly || {});

    const camSvg = `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><defs><linearGradient id="cam-g-${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#1096f4"/><stop offset="100%" stop-color="#8426a4"/></linearGradient></defs><path d="M4 8h3l2-3h6l2 3h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z" stroke="url(#cam-g-${id})" fill="none"/><circle cx="12" cy="14" r="4" stroke="url(#cam-g-${id})" fill="none"/></svg>`;
    let html = `<div class="gsm-chart-card" data-chart-id="${id}">
      <div class="gsm-chart-header">
        <div class="h3" style="display:inline-flex;align-items:center;gap:6px">${title} <span class="small muted">(${subtitle})</span>
          <button class="btn btn-icon gsm-map-screenshot-btn gsm-card-screenshot-btn" data-target="[data-chart-id='${id}']" data-name="${id}" title="Zrób zrzut">
            ${camSvg}
          </button>
        </div>
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
    _initTimeline(geo);

    // Screenshot button
    const screenshotBtn = QS("#gsm_map_screenshot_btn");
    if (screenshotBtn) screenshotBtn.onclick = () => _takeMapScreenshot();

    // Area selection buttons (circle / rectangle)
    const selectCircleBtn = QS("#gsm_select_circle_btn");
    const selectRectBtn = QS("#gsm_select_rect_btn");
    if (selectCircleBtn) selectCircleBtn.onclick = () => _enterAreaSelectMode("circle");
    if (selectRectBtn) selectRectBtn.onclick = () => _enterAreaSelectMode("rect");

    // ── Floating layer panel ──
    const coverageOpts = QS("#gsm_coverage_opts");
    const covBillingCb = QS("#gsm_cov_billing");
    const covOtherCb = QS("#gsm_cov_other");

    // Build exclude list once from billing data
    _otherBtsExcludeSet = _buildExcludeSet(geo);

    // Panel collapse/expand toggle
    const layerPanel = QS("#gsm_layer_panel");
    const lpToggle = QS("#gsm_lp_header_toggle");
    if (lpToggle && layerPanel) {
      lpToggle.onclick = () => layerPanel.classList.toggle("collapsed");
    }

    // Layer radio buttons (replace old select)
    const layerRadios = document.querySelectorAll('input[name="gsm_map_layer"]');
    for (const radio of layerRadios) {
      radio.onchange = () => {
        if (!radio.checked) return;
        const layer = radio.value;
        _closeAllPinnedCards();
        _switchMapLayer(layer, geo);
        // Update active class on items
        for (const item of document.querySelectorAll(".gsm-lp-item[data-layer]")) {
          item.classList.toggle("active", item.dataset.layer === layer);
        }
        // Show/hide coverage sub-options
        if (coverageOpts) coverageOpts.style.display = layer === "coverage" ? "" : "none";
        // Disable other BTS when switching away from coverage
        if (layer !== "coverage") {
          _otherBtsEnabled = false;
          _removeOtherBts();
        } else if (covOtherCb && covOtherCb.checked) {
          _otherBtsEnabled = true;
          _loadOtherBts();
        }
      };
    }

    // Coverage billing checkbox — toggle billing coverage layer
    if (covBillingCb) {
      covBillingCb.onchange = () => {
        if (!St.map || !St.mapLayers.coverage) return;
        if (covBillingCb.checked) {
          St.mapLayers.coverage.addTo(St.map);
        } else {
          St.map.removeLayer(St.mapLayers.coverage);
        }
      };
    }

    // Coverage other BTS checkbox — toggle dynamic nearby BTS
    if (covOtherCb) {
      covOtherCb.onchange = () => {
        _otherBtsEnabled = covOtherCb.checked;
        if (_otherBtsEnabled) {
          _loadOtherBts();
        } else {
          _removeOtherBts();
        }
      };
    }

    // ── Map overlay checkboxes (military / airports / diplomacy) ──
    const milCb = QS("#gsm_overlay_military");
    const airCb = QS("#gsm_overlay_airports");
    const dipCb = QS("#gsm_overlay_diplomacy");
    if (milCb) milCb.onchange = () => _toggleOverlay("military", milCb.checked);
    if (airCb) airCb.onchange = () => _toggleOverlay("airports", airCb.checked);
    if (dipCb) dipCb.onchange = () => _toggleOverlay("diplomacy", dipCb.checked);

    // Load KML user overlays into layer panel
    _loadKmlOverlayCheckboxes();

    // Reload other BTS on map move/zoom (debounced)
    if (St.map) {
      St.map.on("moveend", () => {
        if (_otherBtsEnabled) _scheduleOtherBtsReload();
      });
    }
  }

  /* ── Map screenshot ──────────────────────────────────── */

  let _html2canvasLoaded = false;

  async function _ensureHtml2Canvas() {
    if (_html2canvasLoaded || window.html2canvas) {
      _html2canvasLoaded = true;
      return;
    }
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
      s.onload = () => { _html2canvasLoaded = true; resolve(); };
      s.onerror = () => reject(new Error("Nie udało się załadować html2canvas"));
      document.head.appendChild(s);
    });
  }

  /**
   * Draw a transparent watermark line below the source canvas.
   * "AISTATEweb" in brand gradient, extra parts + date in gray.
   * No background bar — suitable for print and Word embedding.
   * @param {HTMLCanvasElement} srcCanvas
   * @param {string[]} [extraParts] - additional text segments after the brand name
   * @returns {HTMLCanvasElement} final canvas with watermark row appended
   */
  function _drawWatermark(srcCanvas, extraParts) {
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

    // White background for watermark row (print-friendly)
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, srcCanvas.height, w, barH);

    // Subtle top separator
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

    // Date (always present)
    const now = new Date();
    const dateStr = now.toLocaleString("pl-PL", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    const grayColor = "rgba(0,0,0,0.38)";

    ctx.font = `${fontSize}px system-ui, -apple-system, sans-serif`;
    ctx.fillStyle = grayColor;

    // Extra parts (layer name, copyright, etc.)
    if (extraParts && extraParts.length) {
      for (const part of extraParts) {
        ctx.fillText(`  |  ${part}`, lx, cy);
        lx += ctx.measureText(`  |  ${part}`).width;
      }
    }

    // Date on the right
    const dateW = ctx.measureText(dateStr).width;
    ctx.fillText(dateStr, w - pad - dateW, cy);

    return out;
  }

  /**
   * Compose a map screenshot directly from Leaflet internals.
   * html2canvas cannot reliably capture cross-origin tile <img> elements,
   * so we manually draw tiles, then overlay canvas/SVG layers on top.
   */
  async function _takeMapScreenshot() {
    const container = QS("#gsm_map_container");
    if (!container || !St.map) return;
    const btn = QS("#gsm_map_screenshot_btn");
    if (btn) btn.disabled = true;

    try {
      const map = St.map;
      const scale = 2;
      const size = map.getSize();
      const w = size.x * scale;
      const h = size.y * scale;

      // ── 0. Wait for all visible tiles to load before capturing ──
      await _waitForTilesToLoad(map, 3000);

      const out = document.createElement("canvas");
      out.width = w;
      out.height = h;
      const ctx = out.getContext("2d");

      // ── 1. Fill background (matches container bg) ──
      ctx.fillStyle = "#e8e8e8";
      ctx.fillRect(0, 0, w, h);

      // ── 2. Draw tile images ──
      // Use getBoundingClientRect for correct positioning — accounts for ALL
      // nested transforms (tilePane → tile-container → tile img).
      // Re-fetch tiles via fetch() to avoid tainted-canvas from cached tiles.
      const containerRect = map.getContainer().getBoundingClientRect();
      const tilePane = map.getPane("tilePane");
      if (tilePane) {
        const tileImgs = tilePane.querySelectorAll("img.leaflet-tile");
        const tilePromises = [];
        for (const img of tileImgs) {
          if (!img.src) continue;
          const rect = img.getBoundingClientRect();
          const x = (rect.left - containerRect.left) * scale;
          const y = (rect.top - containerRect.top) * scale;
          const tw = rect.width * scale;
          const th = rect.height * scale;
          tilePromises.push(
            _fetchImageBitmap(img.src)
              .then(bmp => ({ bmp, x, y, tw, th }))
              .catch(() => null)
          );
        }
        const tiles = await Promise.all(tilePromises);
        for (const tile of tiles) {
          if (!tile) continue;
          ctx.drawImage(tile.bmp, tile.x, tile.y, tile.tw, tile.th);
          tile.bmp.close();
        }
      }

      // ── 3. Draw MapLibre GL canvas (for PBF vector tiles) ──
      // MapLibre renders to a WebGL canvas inside a .maplibregl-map container.
      // Requires preserveDrawingBuffer:true (set in _addPbfVectorLayer).
      if (St._maplibreLayer) {
        try {
          const glMap = St._maplibreLayer.getMaplibreMap();
          if (glMap) {
            // Force a synchronous repaint so the WebGL buffer contains current frame
            glMap.triggerRepaint();
            // Wait one animation frame for the repaint to complete
            await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

            const glCanvas = glMap.getCanvas();
            if (glCanvas) {
              const mlRect = glCanvas.getBoundingClientRect();
              const cRect = map.getContainer().getBoundingClientRect();
              const mlX = (mlRect.left - cRect.left) * scale;
              const mlY = (mlRect.top - cRect.top) * scale;
              const mlW = mlRect.width * scale;
              const mlH = mlRect.height * scale;
              ctx.drawImage(glCanvas, mlX, mlY, mlW, mlH);
            }
          }
        } catch (e) {
          _addLog("warn", "Nie udało się skopiować canvasu MapLibre: " + e.message);
        }
      } else {
        // Fallback: try to find any MapLibre canvas in the DOM
        const maplibreCanvas = container.querySelector(".maplibregl-canvas, .mapboxgl-canvas");
        if (maplibreCanvas) {
          try {
            const mlRect = maplibreCanvas.getBoundingClientRect();
            const cRect = map.getContainer().getBoundingClientRect();
            ctx.drawImage(maplibreCanvas,
              (mlRect.left - cRect.left) * scale, (mlRect.top - cRect.top) * scale,
              mlRect.width * scale, mlRect.height * scale);
          } catch (e) {
            _addLog("warn", "Nie udało się skopiować canvasu MapLibre: " + e.message);
          }
        }
      }

      // ── 4. Draw Leaflet overlay pane canvases (circleMarkers, polylines, polygons) ──
      const overlayPane = map.getPane("overlayPane");
      if (overlayPane) {
        const canvases = overlayPane.querySelectorAll("canvas");
        for (const c of canvases) {
          try {
            const cRect = c.getBoundingClientRect();
            const cx = (cRect.left - containerRect.left) * scale;
            const cy = (cRect.top - containerRect.top) * scale;
            ctx.drawImage(c, cx, cy, cRect.width * scale, cRect.height * scale);
          } catch (_) {}
        }
        // Also draw any SVG overlays (polylines in SVG mode, etc.)
        const svgs = overlayPane.querySelectorAll("svg");
        for (const svg of svgs) {
          try {
            const svgRect = svg.getBoundingClientRect();
            const svgData = new XMLSerializer().serializeToString(svg);
            const svgBlob = new Blob([svgData], { type: "image/svg+xml;charset=utf-8" });
            const svgUrl = URL.createObjectURL(svgBlob);
            const svgImg = new Image();
            await new Promise((resolve) => {
              svgImg.onload = resolve;
              svgImg.onerror = resolve;
              svgImg.src = svgUrl;
            });
            ctx.drawImage(svgImg,
              (svgRect.left - containerRect.left) * scale,
              (svgRect.top - containerRect.top) * scale,
              svgRect.width * scale, svgRect.height * scale);
            URL.revokeObjectURL(svgUrl);
          } catch (_) {}
        }
      }

      // ── 5. Draw shadow pane (marker shadows) ──
      _drawPaneMarkers(ctx, map, "shadowPane", scale);

      // ── 6. Draw marker pane (HTML markers / icons) ──
      _drawPaneMarkers(ctx, map, "markerPane", scale);

      // ── 6b. Draw pinned BTS cards + tether lines ──
      // Tether SVG lines
      const tetherSvg = container.querySelector(".gsm-pinned-tether-svg");
      if (tetherSvg) {
        const lines = tetherSvg.querySelectorAll("line");
        for (const ln of lines) {
          const x1 = parseFloat(ln.getAttribute("x1")) * scale;
          const y1 = parseFloat(ln.getAttribute("y1")) * scale;
          const x2 = parseFloat(ln.getAttribute("x2")) * scale;
          const y2 = parseFloat(ln.getAttribute("y2")) * scale;
          ctx.save();
          ctx.strokeStyle = ln.getAttribute("stroke") || "#64748b";
          ctx.lineWidth = parseFloat(ln.getAttribute("stroke-width") || 1.5) * scale;
          ctx.setLineDash([5 * scale, 4 * scale]);
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
          ctx.restore();
        }
      }
      // Pinned cards and Leaflet popups (rendered via html2canvas)
      const pinnedCardEls = container.querySelectorAll(".gsm-pinned-card");
      const popupPane = map.getPane("popupPane");
      const openPopups = popupPane ? popupPane.querySelectorAll(".leaflet-popup") : [];
      if (pinnedCardEls.length > 0 || openPopups.length > 0) {
        await _ensureHtml2Canvas();
        for (const card of pinnedCardEls) {
          try {
            const cardCanvas = await window.html2canvas(card, {
              scale: scale,
              backgroundColor: null,
              logging: false,
              useCORS: true,
            });
            const cardLeft = parseFloat(card.style.left || 0) * scale;
            const cardTop = parseFloat(card.style.top || 0) * scale;
            ctx.drawImage(cardCanvas, cardLeft, cardTop);
          } catch (e) {
            _addLog("warn", "Nie udało się narysować karty BTS: " + e.message);
          }
        }
        for (const popup of openPopups) {
          try {
            const popupCanvas = await window.html2canvas(popup, {
              scale: scale,
              backgroundColor: null,
              logging: false,
              useCORS: true,
            });
            const pRect = popup.getBoundingClientRect();
            const px = (pRect.left - containerRect.left) * scale;
            const py = (pRect.top - containerRect.top) * scale;
            ctx.drawImage(popupCanvas, px, py);
          } catch (_) {}
        }
      }

      // ── 7. Draw watermark ──
      const activeRadio = QS('input[name="gsm_map_layer"]:checked');
      const activeItem = activeRadio ? activeRadio.closest(".gsm-lp-item") : null;
      const layerLabel = activeItem ? activeItem.textContent.trim() : "";
      const extraParts = [];
      if (layerLabel) extraParts.push(layerLabel);
      extraParts.push("© OpenStreetMap contributors");

      const final = _drawWatermark(out, extraParts);

      // ── 8. Download ──
      const now = new Date();
      final.toBlob((blob) => {
        if (!blob) {
          _addLog("warn", "Nie udało się utworzyć zdjęcia mapy");
          return;
        }
        const activeR = QS('input[name="gsm_map_layer"]:checked');
        const layerName = activeR ? activeR.value : "mapa";
        const ts = now.toISOString().slice(0, 19).replace(/[T:]/g, "-");
        const filename = `BTS_${layerName}_${ts}.png`;

        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        _addLog("info", `Zapisano zdjęcie mapy: ${filename}`);
      }, "image/png");
    } catch (e) {
      _addLog("error", `Błąd zdjęcia mapy: ${e.message}`);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /**
   * Fetch an image URL via fetch() and return an ImageBitmap (CORS-safe).
   * Falls back to loading via <img crossOrigin="anonymous"> if fetch fails.
   */
  async function _fetchImageBitmap(url) {
    // Try fetch first (best for CORS)
    try {
      const resp = await fetch(url, { mode: "cors" });
      if (resp.ok) {
        const blob = await resp.blob();
        return createImageBitmap(blob);
      }
    } catch (_) { /* fall through to img approach */ }

    // Fallback: load via <img crossOrigin> — works for same-origin and CORS-enabled servers
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        createImageBitmap(img).then(resolve).catch(reject);
      };
      img.onerror = () => reject(new Error("img load failed"));
      img.src = url;
    });
  }

  /** Wait for all visible tile images to finish loading (with timeout) */
  function _waitForTilesToLoad(map, timeoutMs) {
    return new Promise((resolve) => {
      const tilePane = map.getPane("tilePane");
      if (!tilePane) { resolve(); return; }

      const check = () => {
        const imgs = tilePane.querySelectorAll("img.leaflet-tile");
        for (const img of imgs) {
          if (img.src && !img.complete) return false;
        }
        return true;
      };

      if (check()) { resolve(); return; }

      const deadline = Date.now() + timeoutMs;
      const interval = setInterval(() => {
        if (check() || Date.now() > deadline) {
          clearInterval(interval);
          resolve();
        }
      }, 100);
    });
  }

  /** Parse Leaflet's CSS transform (translate3d / translate) to {x, y} pixels */
  function _getLeafletPaneOffset(el) {
    const t = el.style.transform || window.getComputedStyle(el).transform;
    if (!t || t === "none") return { x: 0, y: 0 };
    // translate3d(Xpx, Ypx, 0px) or matrix(...)
    const m3d = t.match(/translate3d\(\s*(-?[\d.]+)px\s*,\s*(-?[\d.]+)px/);
    if (m3d) return { x: parseFloat(m3d[1]), y: parseFloat(m3d[2]) };
    const mat = t.match(/matrix\(\s*[\d.e+-]+\s*,\s*[\d.e+-]+\s*,\s*[\d.e+-]+\s*,\s*[\d.e+-]+\s*,\s*(-?[\d.e+-]+)\s*,\s*(-?[\d.e+-]+)/);
    if (mat) return { x: parseFloat(mat[1]), y: parseFloat(mat[2]) };
    return { x: 0, y: 0 };
  }

  /**
   * Draw marker images AND divIcon HTML markers from a Leaflet pane onto a canvas.
   * L.divIcon markers render as <div> elements (often with emoji text content),
   * while standard L.icon markers render as <img> elements.
   */
  function _drawPaneMarkers(ctx, map, paneName, scale) {
    const pane = map.getPane(paneName);
    if (!pane) return;
    const containerRect = map.getContainer().getBoundingClientRect();

    // 1) Draw <img> based markers (standard L.icon)
    const imgs = pane.querySelectorAll("img");
    for (const img of imgs) {
      if (!img.complete || !img.naturalWidth) continue;
      try {
        const rect = img.getBoundingClientRect();
        const x = (rect.left - containerRect.left) * scale;
        const y = (rect.top - containerRect.top) * scale;
        const iw = rect.width * scale;
        const ih = rect.height * scale;
        ctx.drawImage(img, x, y, iw, ih);
      } catch (_) {}
    }

    // 2) Draw L.divIcon markers (overlays, KML layers — rendered as <div> with emoji/text)
    const divIcons = pane.querySelectorAll(".leaflet-marker-icon");
    for (const div of divIcons) {
      // Skip if it's an <img> element (already handled above)
      if (div.tagName === "IMG") continue;
      try {
        const rect = div.getBoundingClientRect();
        // Skip markers outside the visible map area
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.right < containerRect.left || rect.left > containerRect.right) continue;
        if (rect.bottom < containerRect.top || rect.top > containerRect.bottom) continue;

        const x = (rect.left - containerRect.left) * scale;
        const y = (rect.top - containerRect.top) * scale;

        // Extract text content (emoji) from the divIcon
        const span = div.querySelector("span");
        const text = span ? span.textContent.trim() : div.textContent.trim();
        if (!text) continue;

        // Draw the emoji/text at the marker position
        const fontSize = Math.round((span ? parseFloat(getComputedStyle(span).fontSize) : 16) * scale);
        ctx.font = `${fontSize}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const cx = x + (rect.width * scale) / 2;
        const cy = y + (rect.height * scale) / 2;
        ctx.fillText(text, cx, cy);
      } catch (_) {}
    }
  }

  /* ── Generic card screenshot ───────────────────────────── */

  // Elements to hide in card screenshots (filters, selects, resize handles, screenshot buttons)
  const _SCREENSHOT_HIDE_SELECTORS = [
    ".gsm-period-select", "select", ".gsm-hm-filter-bar", ".gsm-filter-chips",
    ".gsm-col-filter-btn", ".gsm-card-screenshot-btn", ".gsm-map-screenshot-btn",
    ".gsm-graph-resize", ".gsm-records-resize",
  ].join(",");

  async function _takeCardScreenshot(btn) {
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
        backgroundColor: getComputedStyle(card).backgroundColor || "#fff",
        scale: 2,
        logging: false,
        onclone: (doc, clonedCard) => {
          // Hide filter/select/resize elements in the clone
          clonedCard.querySelectorAll(_SCREENSHOT_HIDE_SELECTORS).forEach(el => {
            el.style.display = "none";
          });
        },
      });

      const out = _drawWatermark(cardCanvas);

      out.toBlob((blob) => {
        if (!blob) return;
        const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
        const filename = `GSM_${name}_${ts}.png`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        _addLog("info", `Zapisano zrzut: ${filename}`);
      }, "image/png");
    } catch (e) {
      _addLog("error", `Błąd zrzutu: ${e.message}`);
    } finally {
      btn.disabled = false;
    }
  }

  // Bind all card screenshot buttons (called after render)
  function _bindCardScreenshotButtons(root) {
    (root || document).querySelectorAll(".gsm-card-screenshot-btn").forEach(btn => {
      if (btn._screenshotBound) return;
      btn._screenshotBound = true;
      btn.onclick = (e) => {
        e.stopPropagation();
        _takeCardScreenshot(btn);
      };
    });
  }

  async function _initMap(geo) {
    const container = QS("#gsm_map_container");
    if (!container || !window.L) return;

    // Destroy existing map
    if (St.map) {
      try { St.map.remove(); } catch(e) { /* ignore */ }
      St.map = null;
      St._maplibreLayer = null;
    }

    const map = L.map(container, {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,  // render vectors to <canvas> (better screenshot capture)
    });
    St.map = map;

    // Load tiles first, then add markers
    await _addTileLayer(map);

    // Add markers
    _addAllPoints(map, geo);
  }

  async function _addTileLayer(map) {
    // Fetch user preference
    let mapSource = "auto";
    try {
      const sResp = await fetch("/api/settings");
      const sData = await sResp.json();
      mapSource = sData.map_source || "auto";
    } catch (e) { /* default auto */ }

    // Force online mode
    if (mapSource === "online") {
      _addOnlineTileLayer(map);
      return;
    }

    // Check offline tiles availability
    let info = null;
    try {
      const resp = await fetch("/api/gsm/tiles/info");
      info = await resp.json();
    } catch (e) { /* ignore */ }

    const offlineAvailable = info && info.available;
    const fmt = offlineAvailable ? (info.format || "pbf") : "";

    // If forced offline but no tiles — show warning, add empty layer
    if (mapSource === "offline" && !offlineAvailable) {
      _addLog("warn", "Mapa offline wymuszona, ale brak pliku MBTiles — mapa będzie pusta");
      _setMapBadge(map, "OFFLINE — brak MBTiles", "#f97316");
      return;
    }

    // Use offline if available (auto or forced offline)
    if (offlineAvailable) {
      const isRaster = (fmt === "png" || fmt === "jpg" || fmt === "jpeg" || fmt === "webp");
      if (isRaster) {
        L.tileLayer("/api/gsm/tiles/{z}/{x}/{y}", {
          maxZoom: parseInt(info.maxzoom) || 18,
          minZoom: parseInt(info.minzoom) || 0,
          crossOrigin: true,
          attribution: "Offline map | OpenStreetMap",
        }).addTo(map);
        _addLog("info", "Używam mapy offline — raster (" + fmt.toUpperCase() + ")");
        _setMapBadge(map, "OFFLINE — " + fmt.toUpperCase(), "#22c55e");
        return;
      }
      if (fmt === "pbf") {
        // Vector PBF tiles via maplibre-gl rendered to a Leaflet layer
        await _addPbfVectorLayer(map, info);
        return;
      }
    }

    // Fallback: online
    _addOnlineTileLayer(map);
  }

  function _addOnlineTileLayer(map) {
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      crossOrigin: true,
      attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    _addLog("info", "Używam mapy online (OpenStreetMap)");
    _setMapBadge(map, "ONLINE", "#3b82f6");
  }

  /* ── MapLibre GL JS loader (for PBF vector tiles) ────── */

  function _loadMapLibre() {
    return new Promise((resolve) => {
      if (window.maplibregl) { resolve(true); return; }
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css";
      document.head.appendChild(css);
      // Also add Leaflet-MapLibre plugin
      const js1 = document.createElement("script");
      js1.src = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js";
      js1.onload = () => {
        const js2 = document.createElement("script");
        js2.src = "https://unpkg.com/@maplibre/maplibre-gl-leaflet@0.0.22/leaflet-maplibre-gl.js";
        js2.onload = () => resolve(true);
        js2.onerror = () => { console.warn("Leaflet-MapLibre plugin unavailable"); resolve(false); };
        document.head.appendChild(js2);
      };
      js1.onerror = () => { console.warn("MapLibre GL JS CDN unavailable"); resolve(false); };
      document.head.appendChild(js1);
    });
  }

  async function _addPbfVectorLayer(map, info) {
    const loaded = await _loadMapLibre();
    if (!loaded || !window.maplibregl || !L.maplibreGL) {
      _addLog("warn", "MapLibre GL JS niedostępne — fallback na mapę online");
      _addOnlineTileLayer(map);
      return;
    }

    const maxZoom = parseInt(info.maxzoom) || 14;
    const minZoom = parseInt(info.minzoom) || 0;

    // OSM Bright-like style for offline PBF tiles served from local API
    const style = {
      version: 8,
      name: "Offline PBF",
      sources: {
        openmaptiles: {
          type: "vector",
          tiles: [window.location.origin + "/api/gsm/tiles/{z}/{x}/{y}"],
          minzoom: minZoom,
          maxzoom: maxZoom,
        },
      },
      glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
      layers: [
        // Background
        { id: "background", type: "background", paint: { "background-color": "#f8f4f0" } },
        // Water
        { id: "water", type: "fill", source: "openmaptiles", "source-layer": "water",
          paint: { "fill-color": "#a0c8f0" } },
        // Landcover
        { id: "landcover-grass", type: "fill", source: "openmaptiles", "source-layer": "landcover",
          filter: ["==", "class", "grass"],
          paint: { "fill-color": "#d8e8c8", "fill-opacity": 0.6 } },
        { id: "landcover-wood", type: "fill", source: "openmaptiles", "source-layer": "landcover",
          filter: ["==", "class", "wood"],
          paint: { "fill-color": "#aed1a0", "fill-opacity": 0.6 } },
        // Landuse
        { id: "landuse-residential", type: "fill", source: "openmaptiles", "source-layer": "landuse",
          filter: ["==", "class", "residential"],
          paint: { "fill-color": "#e8e0d8", "fill-opacity": 0.5 } },
        { id: "landuse-commercial", type: "fill", source: "openmaptiles", "source-layer": "landuse",
          filter: ["in", "class", "commercial", "retail"],
          paint: { "fill-color": "#f2dad9", "fill-opacity": 0.4 } },
        { id: "landuse-industrial", type: "fill", source: "openmaptiles", "source-layer": "landuse",
          filter: ["==", "class", "industrial"],
          paint: { "fill-color": "#ebdbe8", "fill-opacity": 0.4 } },
        // Park
        { id: "park", type: "fill", source: "openmaptiles", "source-layer": "park",
          paint: { "fill-color": "#d8e8c8", "fill-opacity": 0.6 } },
        // Buildings
        { id: "building", type: "fill", source: "openmaptiles", "source-layer": "building",
          minzoom: 13,
          paint: { "fill-color": "#d9d0c9", "fill-outline-color": "#b9b0a9" } },
        // Roads
        { id: "road-motorway", type: "line", source: "openmaptiles", "source-layer": "transportation",
          filter: ["==", "class", "motorway"],
          paint: { "line-color": "#e892a2", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1, 14, 5] } },
        { id: "road-trunk", type: "line", source: "openmaptiles", "source-layer": "transportation",
          filter: ["==", "class", "trunk"],
          paint: { "line-color": "#f9b29c", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 14, 4] } },
        { id: "road-primary", type: "line", source: "openmaptiles", "source-layer": "transportation",
          filter: ["==", "class", "primary"],
          paint: { "line-color": "#fcd6a4", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 14, 3] } },
        { id: "road-secondary", type: "line", source: "openmaptiles", "source-layer": "transportation",
          filter: ["==", "class", "secondary"],
          paint: { "line-color": "#f7fabf", "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.3, 14, 2.5] } },
        { id: "road-minor", type: "line", source: "openmaptiles", "source-layer": "transportation",
          filter: ["in", "class", "tertiary", "minor", "service", "path"],
          minzoom: 10,
          paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.3, 14, 1.5] } },
        // Railway
        { id: "railway", type: "line", source: "openmaptiles", "source-layer": "transportation",
          filter: ["==", "class", "rail"],
          paint: { "line-color": "#bbb", "line-width": 1, "line-dasharray": [3, 3] } },
        // Boundaries
        { id: "boundary-country", type: "line", source: "openmaptiles", "source-layer": "boundary",
          filter: ["==", "admin_level", 2],
          paint: { "line-color": "#9e9cab", "line-width": 1.5 } },
        // Place labels
        { id: "place-city", type: "symbol", source: "openmaptiles", "source-layer": "place",
          filter: ["==", "class", "city"],
          layout: { "text-field": "{name:latin}", "text-size": 14, "text-font": ["Open Sans Bold"] },
          paint: { "text-color": "#333", "text-halo-color": "#fff", "text-halo-width": 1.5 } },
        { id: "place-town", type: "symbol", source: "openmaptiles", "source-layer": "place",
          filter: ["==", "class", "town"],
          layout: { "text-field": "{name:latin}", "text-size": 12, "text-font": ["Open Sans Regular"] },
          paint: { "text-color": "#555", "text-halo-color": "#fff", "text-halo-width": 1 } },
        { id: "place-village", type: "symbol", source: "openmaptiles", "source-layer": "place",
          filter: ["==", "class", "village"],
          minzoom: 10,
          layout: { "text-field": "{name:latin}", "text-size": 10, "text-font": ["Open Sans Regular"] },
          paint: { "text-color": "#666", "text-halo-color": "#fff", "text-halo-width": 1 } },
        // Road labels
        { id: "road-label", type: "symbol", source: "openmaptiles", "source-layer": "transportation_name",
          minzoom: 12,
          layout: {
            "text-field": "{name:latin}",
            "text-size": 10,
            "text-font": ["Open Sans Regular"],
            "symbol-placement": "line",
          },
          paint: { "text-color": "#666", "text-halo-color": "#fff", "text-halo-width": 1 } },
      ],
    };

    try {
      const glLayer = L.maplibreGL({
        style: style,
        attribution: "Offline map (PBF) | OpenStreetMap",
        // preserveDrawingBuffer must be inside maplibreOptions — the plugin
        // passes this object to the MapLibre GL Map constructor via Object.assign.
        maplibreOptions: {
          preserveDrawingBuffer: true,
        },
      }).addTo(map);
      // Store reference for screenshot use (triggerRepaint + getCanvas)
      St._maplibreLayer = glLayer;
      _addLog("info", "Używam mapy offline — wektor (PBF) via MapLibre GL");
      _setMapBadge(map, "OFFLINE — PBF", "#22c55e");
    } catch (e) {
      console.error("MapLibre GL layer error:", e);
      _addLog("warn", "Błąd MapLibre GL — fallback na mapę online");
      _addOnlineTileLayer(map);
    }
  }

  /* ── Map badge (source indicator) ────────────────────── */

  function _setMapBadge(map, text, color) {
    if (!map || !map.getContainer) return;
    const container = map.getContainer();
    // Remove old badge
    const old = container.querySelector(".gsm-map-badge");
    if (old) old.remove();
    // Create badge
    const badge = document.createElement("div");
    badge.className = "gsm-map-badge";
    badge.style.cssText = "position:absolute;top:10px;right:10px;z-index:1000;" +
      "padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;" +
      "color:#fff;pointer-events:none;opacity:0.85;" +
      "background:" + color + ";";
    badge.textContent = text;
    container.style.position = "relative";
    container.appendChild(badge);
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
          range_m: p.range_m || null,
          radio: p.radio || "",
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
    St.areaLocations = uniqueLocations;
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

      // Click → open pinned card (replaces popup)
      marker.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        _handleBtsClick(L.latLng(loc.lat, loc.lon), loc);
      });

      // Double-click → filter Records by this BTS location
      marker.on("dblclick", () => {
        const rowSet = new Set(loc.records.map(r => r.raw_row));
        const allRecs = St.lastResult ? St.lastResult.records : [];
        const filtered = allRecs.filter(r => rowSet.has(r.raw_row));
        const label = loc.city || "BTS";
        const filterText = `${label} — ${filtered.length} rek.`;
        _setRecordsFilter(filterText, () => {
          _clearRecordsFilter();
          if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
        });
        _renderRecords(filtered, false, filtered.length);
        const recCard = QS("#gsm_records_card");
        if (recCard) recCard.scrollIntoView({ behavior: "smooth", block: "start" });
      });

      allGroup.addLayer(marker);
    }
    St.mapLayers.all = allGroup;
    allGroup.addTo(map);

    // ── Path / route layer (simplified — only large movements >2km) ──
    const pathGroup = L.layerGroup();
    if (geo.path && geo.path.length) {
      // Filter only significant movements (> 2km) to avoid BTS noise
      const significant = geo.path.filter(s => s.distance_m > 2000);
      for (const seg of significant) {
        const dist_km = (seg.distance_m / 1000).toFixed(1);
        L.polyline(
          [[seg.from_point.lat, seg.from_point.lon],
           [seg.to_point.lat, seg.to_point.lon]],
          { color: "#3b82f6", weight: 2, opacity: 0.3, dashArray: "4 4" }
        ).bindPopup(`<b>Przemieszczenie</b><br>${dist_km} km<br>${seg.from_datetime} → ${seg.to_datetime}`)
         .addTo(pathGroup);
      }
      if (significant.length) _addLog("info", `Trasa: ${significant.length} istotnych przemieszczeń (z ${geo.path.length})`);
    }
    St.mapLayers.path = pathGroup;
    // Do NOT add path to map by default — it's a supplementary layer

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

    // ── Coverage layer (BTS sector / circle coverage areas) ──
    const coverageGroup = L.layerGroup();
    const _defaultRange = { "GSM": 5000, "UMTS": 3000, "LTE": 2000, "5G NR": 1000 };
    for (const loc of uniqueLocations) {
      const range = loc.range_m || _defaultRange[loc.radio] || 2000;
      const count = loc.records.length;
      // Color by radio technology
      const radioColors = { "GSM": "#ef4444", "UMTS": "#f97316", "LTE": "#3b82f6", "5G NR": "#8b5cf6" };
      const color = radioColors[loc.radio] || "#6b7280";
      const opacity = Math.min(0.55, 0.20 + Math.log2(count + 1) * 0.06);

      if (loc.azimuth != null) {
        // Omnidirectional circle (full range, visible behind sector)
        L.circle([loc.lat, loc.lon], {
          radius: range,
          fillColor: color,
          color: color,
          weight: 1,
          fillOpacity: opacity * 0.25,
          dashArray: "4 5",
        }).addTo(coverageGroup);

        // Draw sector (pie-slice) for directional antenna
        const beamWidth = loc.radio === "5G NR" ? 30 : loc.radio === "LTE" ? 45 : 60;
        const startAngle = loc.azimuth - beamWidth / 2;
        const endAngle = loc.azimuth + beamWidth / 2;
        const sectorCoords = _buildSectorCoords(loc.lat, loc.lon, range, startAngle, endAngle, 24);
        L.polygon(sectorCoords, {
          fillColor: color,
          color: color,
          weight: 1.5,
          fillOpacity: opacity,
        }).on("click", ((covLoc) => (e) => {
          L.DomEvent.stopPropagation(e);
          _handleBtsClick(L.latLng(covLoc.lat, covLoc.lon), covLoc);
        })(loc)).addTo(coverageGroup);
      } else {
        // Draw circle for omnidirectional / unknown azimuth
        L.circle([loc.lat, loc.lon], {
          radius: range,
          fillColor: color,
          color: color,
          weight: 1.5,
          fillOpacity: opacity * 0.8,
        }).on("click", ((covLoc) => (e) => {
          L.DomEvent.stopPropagation(e);
          _handleBtsClick(L.latLng(covLoc.lat, covLoc.lon), covLoc);
        })(loc)
        ).addTo(coverageGroup);
      }
    }
    St.mapLayers.coverage = coverageGroup;

    // ── Trips layer (OSRM-routed roads between clusters) ──
    const tripsGroup = L.layerGroup();
    if (geo.trips && geo.trips.length && geo.clusters && geo.clusters.length) {
      // Aggregate trips by from→to pair (bidirectional)
      const tripPairs = {};
      for (const t of geo.trips) {
        // Treat A→B and B→A as same route pair for routing
        const a = Math.min(t.from_cluster_idx, t.to_cluster_idx);
        const b = Math.max(t.from_cluster_idx, t.to_cluster_idx);
        const key = `${t.from_cluster_idx}_${t.to_cluster_idx}`;
        const routeKey = `${a}_${b}`;
        if (!tripPairs[key]) tripPairs[key] = { trips: [], from: t.from_cluster_idx, to: t.to_cluster_idx, routeKey };
        tripPairs[key].trips.push(t);
      }

      // Route cache: routeKey → coords (to reuse A→B route for B→A)
      const routeCache = {};

      // Process trip pairs sequentially (to respect OSRM rate limits)
      const pairList = Object.values(tripPairs);
      _addLog("info", `Podróże: ${geo.trips.length} między klastrami, wyznaczam ${pairList.length} tras drogowych…`);

      (async function() {
        for (const pair of pairList) {
          const fromC = geo.clusters.find(c => c.cluster_idx === pair.from);
          const toC = geo.clusters.find(c => c.cluster_idx === pair.to);
          if (!fromC || !toC) continue;

          const count = pair.trips.length;
          const avgDist = pair.trips.reduce((s, t) => s + t.distance_km, 0) / count;

          // Try OSRM routing (with cache)
          let routeCoords = routeCache[pair.routeKey] || null;
          if (!routeCoords) {
            routeCoords = await _fetchOSRMRoute(fromC.lat, fromC.lon, toC.lat, toC.lon);
            if (routeCoords) {
              routeCache[pair.routeKey] = routeCoords;
            }
          }

          // Use routed path if available, fallback to straight line
          const lineCoords = routeCoords || [[fromC.lat, fromC.lon], [toC.lat, toC.lon]];
          const isRouted = !!routeCoords;
          const line = L.polyline(lineCoords, {
            color: "#8b5cf6",
            weight: isRouted ? 4 : 3,
            opacity: 0.75,
            dashArray: isRouted ? null : "12 6",
          });

          // Build popup
          const modeCounts = {};
          pair.trips.forEach(t => { if (t.travel_mode) modeCounts[t.travel_mode] = (modeCounts[t.travel_mode]||0)+1; });
          const modeStr = Object.entries(modeCounts).map(([m,n]) => `${_travelModeIcon(m)} ${_travelModeLabel(m)}: ${n}`).join(", ");
          const sampleTrip = pair.trips[0];
          const estCarStr = sampleTrip.est_car_minutes ? `${_formatHours(sampleTrip.est_car_minutes / 60)}` : "";
          const estFlightStr = sampleTrip.est_flight_minutes ? `${_formatHours(sampleTrip.est_flight_minutes / 60)}` : "";

          let popupHtml = `<b>Podróż: ${fromC.city || "?"} → ${toC.city || "?"}</b><br>
            ${count} ${count === 1 ? "podróż" : "podróży"}, ~${avgDist.toFixed(0)} km${isRouted ? " (trasa drogowa)" : ""}<br>`;
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

          // Midpoint label
          const mid = routeCoords
            ? routeCoords[Math.floor(routeCoords.length / 2)]
            : [(fromC.lat + toC.lat) / 2, (fromC.lon + toC.lon) / 2];
          const arrowIcon = L.divIcon({
            className: "gsm-trip-arrow-icon",
            html: `<div style="background:#8b5cf6;color:#fff;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:bold;white-space:nowrap">${_travelModeIcon(sampleTrip.travel_mode)} ${count}×</div>`,
            iconSize: null,
          });
          L.marker(mid, { icon: arrowIcon }).addTo(tripsGroup);
        }
        _addLog("info", `Trasy drogowe: ${Object.keys(routeCache).length} wyznaczonych (OSRM)`);
      })();
    }
    St.mapLayers.trips = tripsGroup;

    // ── Border crossings layer ──
    const borderGroup = L.layerGroup();
    if (geo.border_crossings && geo.border_crossings.length) {
      for (const bc of geo.border_crossings) {
        // Departure point: use backend coords, fallback to cluster lookup
        let depLat = bc.last_domestic_lat || 0;
        let depLon = bc.last_domestic_lon || 0;
        if (!depLat && bc.last_domestic_city) {
          const cl = geo.clusters.find(c => c.city === bc.last_domestic_city);
          if (cl) { depLat = cl.lat; depLon = cl.lon; }
        }
        // Return point: same logic
        let retLat = bc.first_return_lat || 0;
        let retLon = bc.first_return_lon || 0;
        if (!retLat && bc.first_return_city) {
          const cl = geo.clusters.find(c => c.city === bc.first_return_city);
          if (cl) { retLat = cl.lat; retLon = cl.lon; }
        }

        const mode = bc.border_travel_mode || "unknown";
        const modeIcon = mode === "plane" ? "✈️" : mode === "car" ? "🚗" : mode === "walk" ? "🚶" : "❓";
        const modeLabel = mode === "plane" ? "Samolot" : mode === "car" ? "Samochód" : mode === "walk" ? "Pieszo" : "Nieznany";
        const countries = (bc.roaming_countries || []);
        const countryNames = countries.map(c => _countryName(c)).join(", ");
        const depDate = (bc.last_domestic_datetime || "").slice(0, 10);
        const retDate = (bc.first_return_datetime || "").slice(0, 10);
        const lineColor = mode === "plane" ? "#8b5cf6" : mode === "car" ? "#3b82f6" : "#f97316";

        // Last 24h domestic path before departure
        const path24h = bc.last_24h_path || [];
        if (path24h.length >= 2) {
          const pathCoords = path24h.map(p => [p.lat, p.lon]);
          L.polyline(pathCoords, {
            color: "#3b82f6", weight: 3, opacity: 0.7,
          }).bindPopup(
            `<b>Ostatnie 24h w Polsce</b><br>` +
            `${path24h.length} punktów BTS<br>` +
            `${path24h[0].datetime} → ${path24h[path24h.length - 1].datetime}`
          ).addTo(borderGroup);

          // Small dots along the path
          for (const p of path24h) {
            L.circleMarker([p.lat, p.lon], {
              radius: 4, fillColor: "#3b82f6", color: "#fff", weight: 1, fillOpacity: 0.8,
            }).bindPopup(
              `${p.datetime}<br>${p.city || ""}`
            ).addTo(borderGroup);
          }
        }

        // Departure marker (red) — last BTS before leaving
        if (depLat) {
          L.circleMarker([depLat, depLon], {
            radius: 10, fillColor: "#ef4444", color: "#fff", weight: 2.5, fillOpacity: 0.95,
          }).bindPopup(
            `<b>Ostatni punkt w Polsce</b><br>` +
            `${bc.last_domestic_datetime || "?"}<br>` +
            `${bc.last_domestic_city || ""}<br>` +
            `<b>${modeIcon} ${modeLabel}</b>`
          ).addTo(borderGroup);
        }

        // Return marker (green) — only if returned
        if (retLat && bc.first_return_datetime) {
          L.circleMarker([retLat, retLon], {
            radius: 9, fillColor: "#22c55e", color: "#fff", weight: 2, fillOpacity: 0.9,
          }).bindPopup(
            `<b>Powrót do Polski</b><br>` +
            `${bc.first_return_datetime}<br>` +
            `${bc.first_return_city || ""}`
          ).addTo(borderGroup);
        }

        // Lines to each country center
        for (const cc of countries) {
          const center = _COUNTRY_CENTERS[cc];
          if (!center) continue;
          const [cLat, cLon] = center;
          const cName = _countryName(cc);

          // Country center marker (flag-style label)
          L.marker([cLat, cLon], {
            icon: L.divIcon({
              className: "gsm-border-country-icon",
              html: `<div style="background:${lineColor};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;white-space:nowrap;text-align:center">${cName}</div>`,
              iconSize: null,
            }),
          }).bindPopup(
            `<b>${cName}</b><br>` +
            `Pobyt: ${depDate} → ${retDate || "?"}<br>` +
            `Nieobecność: ${_formatHours(bc.absence_hours)}<br>` +
            `${bc.roaming_records ? bc.roaming_records + " rekordów roamingu" : ""}`
          ).addTo(borderGroup);

          // Line from departure to country center
          if (depLat) {
            const lineStyle = mode === "plane"
              ? { color: lineColor, weight: 2.5, opacity: 0.7, dashArray: "8 6" }
              : { color: lineColor, weight: 2.5, opacity: 0.7 };

            // Build curved line for plane, straight for others
            let lineCoords;
            if (mode === "plane") {
              lineCoords = _buildArcCoords(depLat, depLon, cLat, cLon, 20);
            } else {
              lineCoords = [[depLat, depLon], [cLat, cLon]];
            }

            L.polyline(lineCoords, lineStyle)
              .bindPopup(
                `<b>${modeIcon} ${bc.last_domestic_city || "PL"} → ${cName}</b><br>` +
                `Wyjazd: ${depDate}<br>Powrót: ${retDate || "brak danych"}<br>` +
                `Nieobecność: ${_formatHours(bc.absence_hours)}`
              ).addTo(borderGroup);

            // Travel mode icon on the midpoint of the line
            const midIdx = Math.floor(lineCoords.length / 2);
            const midPt = lineCoords[midIdx];
            L.marker(midPt, {
              icon: L.divIcon({
                className: "gsm-border-mode-icon",
                html: `<div style="font-size:18px;text-align:center;line-height:1">${modeIcon}</div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
              }),
            }).addTo(borderGroup);

            // Date labels near departure and midpoint
            const dateLabelDep = L.marker([depLat, depLon], {
              icon: L.divIcon({
                className: "gsm-border-date",
                html: `<div style="background:rgba(239,68,68,0.9);color:#fff;padding:1px 5px;border-radius:6px;font-size:9px;white-space:nowrap;transform:translateY(-18px)">${depDate}</div>`,
                iconSize: null,
              }),
            }).addTo(borderGroup);

            if (retDate) {
              const retPt = retLat ? [retLat, retLon] : [cLat, cLon];
              L.marker(retPt, {
                icon: L.divIcon({
                  className: "gsm-border-date",
                  html: `<div style="background:rgba(34,197,94,0.9);color:#fff;padding:1px 5px;border-radius:6px;font-size:9px;white-space:nowrap;transform:translateY(-18px)">${retDate}</div>`,
                  iconSize: null,
                }),
              }).addTo(borderGroup);
            }
          }
        }

        // If no roaming countries but we have coords, draw a dashed line to indicate unknown destination
        if (!countries.length && depLat && retLat) {
          L.polyline([[depLat, depLon], [retLat, retLon]], {
            color: "#9ca3af", weight: 2, opacity: 0.5, dashArray: "6 4",
          }).bindPopup(
            `<b>Przerwa w aktywności</b><br>` +
            `${depDate} → ${retDate}<br>` +
            `Nieobecność: ${_formatHours(bc.absence_hours)}`
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
    _clearAreaSelection();
    _exitAreaSelectMode();

    // Remove all custom layers
    Object.values(St.mapLayers).forEach(lg => {
      if (map.hasLayer(lg)) map.removeLayer(lg);
    });

    if (layer === "all") {
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
      if (St.mapLayers.clusters) St.mapLayers.clusters.addTo(map);
    }
    if (layer === "path") {
      if (St.mapLayers.path) St.mapLayers.path.addTo(map);
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
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
    if (layer === "coverage") {
      const billingCb = QS("#gsm_cov_billing");
      if (St.mapLayers.coverage && (!billingCb || billingCb.checked)) {
        St.mapLayers.coverage.addTo(map);
      }
      if (St.mapLayers.coverageOther && _otherBtsEnabled) {
        St.mapLayers.coverageOther.addTo(map);
      }
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
    if (layer === "heatmap") {
      if (St.mapLayers.all) St.mapLayers.all.addTo(map);
    }
    if (layer === "timeline") {
      if (St.mapLayers.timeline) St.mapLayers.timeline.addTo(map);
      if (St.mapLayers.clusters) St.mapLayers.clusters.addTo(map);
    }
  }

  /* ── Dynamic "Other BTS" layer ── */

  /** Zoom-based radius and limit for nearby BTS queries */
  function _nearbyParams(zoom) {
    if (zoom >= 16) return { radius: 0.003, limit: 50 };
    if (zoom >= 15) return { radius: 0.005, limit: 60 };
    if (zoom >= 13) return { radius: 0.015, limit: 80 };
    if (zoom >= 11) return { radius: 0.04,  limit: 100 };
    return { radius: 0.1, limit: 80 };
  }

  /** Build exclude set from billing locations (LAC:CID pairs) for client-side filtering */
  function _buildExcludeSet(geo) {
    const seen = new Set();
    if (geo && geo.geo_records) {
      for (const r of geo.geo_records) {
        if (r.point && r.point.lac && r.point.cid) {
          seen.add(`${r.point.lac}:${r.point.cid}`);
        }
      }
    }
    return seen;
  }

  let _otherBtsDebounce = null;
  let _otherBtsEnabled = false;
  let _otherBtsExcludeSet = new Set();

  /** Fetch and render nearby BTS stations on the map */
  async function _loadOtherBts() {
    if (!St.map || !_otherBtsEnabled) return;
    const map = St.map;
    const center = map.getCenter();
    const zoom = map.getZoom();
    const params = _nearbyParams(zoom);

    const countEl = QS("#gsm_cov_other_count");

    try {
      const url = `/api/gsm/bts/nearby?lat=${center.lat.toFixed(6)}&lon=${center.lng.toFixed(6)}&radius_deg=${params.radius}&limit=${params.limit}`;
      const resp = await fetch(url);
      const data = await resp.json();
      if (data.status !== "ok" || !data.stations) {
        if (countEl) countEl.textContent = "";
        return;
      }
      // Filter out billing stations client-side
      if (_otherBtsExcludeSet.size > 0) {
        data.stations = data.stations.filter(s => !_otherBtsExcludeSet.has(`${s.lac}:${s.cid}`));
      }

      // Remove old layer
      if (St.mapLayers.coverageOther) {
        map.removeLayer(St.mapLayers.coverageOther);
      }

      const otherGroup = L.layerGroup();
      const defaultRange = { "GSM": 5000, "UMTS": 3000, "LTE": 2000, "5G NR": 1000 };
      const color = "#2563eb"; // blue for "other" BTS

      for (const s of data.stations) {
        const range = s.range_m || defaultRange[s.radio] || 2000;

        // Small blue marker
        L.circleMarker([s.lat, s.lon], {
          radius: 4,
          fillColor: color,
          color: "#fff",
          weight: 1.2,
          fillOpacity: 0.7,
        }).bindPopup(
          `<b>${s.city || "BTS"}${s.street ? ", " + s.street : ""}</b><br>` +
          `${s.radio ? "Technologia: " + s.radio + "<br>" : ""}` +
          `${s.azimuth != null ? "Azymut: " + s.azimuth + "°<br>" : ""}` +
          `Zasięg: ${(range / 1000).toFixed(1)} km<br>` +
          `<span class="small muted">LAC: ${s.lac}, CID: ${s.cid}</span><br>` +
          `<span class="small muted">Źródło: ${s.source || "?"}</span>`
        ).addTo(otherGroup);

        // Coverage visualization
        if (s.azimuth != null) {
          // Dashed circle behind sector
          L.circle([s.lat, s.lon], {
            radius: range,
            fillColor: color,
            color: color,
            weight: 0.8,
            fillOpacity: 0.04,
            dashArray: "4 6",
          }).addTo(otherGroup);

          // Sector
          const beamWidth = s.radio === "5G NR" ? 30 : s.radio === "LTE" ? 45 : 60;
          const startAngle = s.azimuth - beamWidth / 2;
          const endAngle = s.azimuth + beamWidth / 2;
          const sectorCoords = _buildSectorCoords(s.lat, s.lon, range, startAngle, endAngle, 24);
          L.polygon(sectorCoords, {
            fillColor: color,
            color: color,
            weight: 1,
            fillOpacity: 0.10,
            dashArray: "3 4",
          }).addTo(otherGroup);
        } else {
          // Omnidirectional circle
          L.circle([s.lat, s.lon], {
            radius: range,
            fillColor: color,
            color: color,
            weight: 1,
            fillOpacity: 0.08,
            dashArray: "3 4",
          }).addTo(otherGroup);
        }
      }

      St.mapLayers.coverageOther = otherGroup;
      otherGroup.addTo(map);
      if (countEl) countEl.textContent = data.stations.length ? `(${data.stations.length} stacji)` : "";
    } catch (e) {
      _addLog("warn", `Błąd ładowania innych BTS: ${e.message}`);
      if (countEl) countEl.textContent = "";
    }
  }

  /** Schedule a debounced reload of other BTS */
  function _scheduleOtherBtsReload() {
    if (_otherBtsDebounce) clearTimeout(_otherBtsDebounce);
    _otherBtsDebounce = setTimeout(_loadOtherBts, 400);
  }

  /** Remove the other BTS layer from the map */
  function _removeOtherBts() {
    if (St.map && St.mapLayers.coverageOther) {
      St.map.removeLayer(St.mapLayers.coverageOther);
      delete St.mapLayers.coverageOther;
    }
    const countEl = QS("#gsm_cov_other_count");
    if (countEl) countEl.textContent = "";
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

  /* ── Border crossings + Overnight stays (side by side) ── */
  function _renderBorderCrossings(geo) {
    _renderTravelSections(geo, null);
  }

  function _renderOvernightStays(analysis) {
    _renderTravelSections(null, analysis);
  }

  /**
   * Render border crossings (left) and overnight stays (right) in a
   * two-column grid, analogous to night/weekend activity charts.
   * Either argument may be null — the function merges with previously
   * rendered data stored on the DOM container.
   */
  function _renderTravelSections(geo, analysis) {
    // Use a hidden scratch element to cache data between calls
    let _cache = _renderTravelSections._cache || (_renderTravelSections._cache = {});
    if (geo) _cache.geo = geo;
    if (analysis) _cache.analysis = analysis;

    const crossings = (_cache.geo && _cache.geo.border_crossings) || [];
    const stays = (_cache.analysis && _cache.analysis.overnight_stays) || [];
    const home = (_cache.analysis && _cache.analysis.overnight_stays_home) || "";

    // ── Border crossings card ──
    const borderCard = QS("#gsm_border_card");
    const borderList = QS("#gsm_border_list");
    if (borderCard && borderList) {
      if (!crossings.length) {
        borderCard.style.display = "none";
      } else {
        borderCard.style.display = "";
        let bHtml = '<div style="display:flex;flex-direction:column;gap:8px">';
        for (let i = 0; i < crossings.length; i++) {
          const bc = crossings[i];
          const absence = _formatHours(bc.absence_hours);
          const countries = (bc.roaming_countries || []).map(c => _countryName(c)).join(", ");
          const confirmed = bc.roaming_confirmed
            ? `<span style="color:#22c55e" title="Potwierdzone danymi roamingu">✓ roaming</span>`
            : `<span style="color:#f97316" title="Wykryte na podstawie przerwy w aktywności">⚠ przerwa</span>`;
          bHtml += `<div data-bc-idx="${i}" class="gsm-travel-card" style="border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--bg-secondary);cursor:pointer" title="2×LPM → filtruj rekordy">
            <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
              <div><span style="color:#ef4444">●</span> <b>Wyjazd:</b> ${bc.last_domestic_datetime || "?"}${bc.last_domestic_city ? ` <span class="muted">(${bc.last_domestic_city})</span>` : ""}</div>
              <div><span style="color:#22c55e">●</span> <b>Powrót:</b> ${bc.first_return_datetime || "brak danych"}${bc.first_return_city ? ` <span class="muted">(${bc.first_return_city})</span>` : ""}</div>
            </div>
            <div class="small" style="margin-top:4px">
              Nieobecność: <b>${absence}</b>
              ${countries ? ` · Kraje: <b>${countries}</b>` : ""}
              ${bc.roaming_records ? ` · ${bc.roaming_records} rek. roamingu` : ""}
              · ${confirmed}
            </div>
          </div>`;
        }
        bHtml += '</div>';
        borderList.innerHTML = bHtml;
        borderList.querySelectorAll("[data-bc-idx]").forEach(el => {
          el.addEventListener("dblclick", () => {
            const bc = crossings[parseInt(el.dataset.bcIdx)];
            if (bc) _travelFilter("bc", bc);
          });
        });
      }
    }

    // ── Overnight stays card ──
    const overnightCard = QS("#gsm_overnight_card");
    const overnightHeader = QS("#gsm_overnight_header");
    const overnightList = QS("#gsm_overnight_list");
    if (overnightCard && overnightList) {
      if (!stays.length) {
        overnightCard.style.display = "none";
      } else {
        overnightCard.style.display = "";
        const totalNights = stays.reduce((s, v) => s + (v.nights || 0), 0);
        const stayWord = stays.length === 1 ? "pobyt" : (stays.length < 5 ? "pobyty" : "pobytów");
        const nightWord = totalNights === 1 ? "noc" : (totalNights < 5 ? "noce" : "nocy");
        if (overnightHeader) {
          overnightHeader.innerHTML = `Lokalizacja domowa: <b>${home}</b> — ${stays.length} ${stayWord} (${totalNights} ${nightWord})`;
        }
        let sHtml = '<div style="display:flex;flex-direction:column;gap:8px">';
        for (let j = 0; j < stays.length; j++) {
          const stay = stays[j];
          const period = stay.start_date === stay.end_date ? stay.start_date : `${stay.start_date} – ${stay.end_date}`;
          const locs = (stay.locations || []).join(", ");
          let detailsHtml = "";
          for (const d of (stay.details || [])) {
            detailsHtml += `<div>${d.date}: ${d.last_time || ""} <span class="muted">(${d.location_evening || ""})</span> → ${d.first_time || ""} <span class="muted">(${d.location_morning || ""})</span></div>`;
          }
          sHtml += `<div data-stay-idx="${j}" class="gsm-travel-card" style="border:1px solid var(--border);border-radius:8px;padding:10px 14px;background:var(--bg-secondary);cursor:pointer" title="2×LPM → filtruj rekordy">
            <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
              <div><b>${period}</b></div>
              <div>${stay.nights} ${stay.nights === 1 ? "noc" : (stay.nights < 5 ? "noce" : "nocy")}</div>
              <div class="muted">${locs}</div>
            </div>
            <div class="small" style="margin-top:4px">${detailsHtml}</div>
          </div>`;
        }
        sHtml += '</div>';
        overnightList.innerHTML = sHtml;
        overnightList.querySelectorAll("[data-stay-idx]").forEach(el => {
          el.addEventListener("dblclick", () => {
            const stay = stays[parseInt(el.dataset.stayIdx)];
            if (stay) _travelFilter("stay", stay);
          });
        });
      }
    }
  }

  /** Filter Records by border crossing or overnight stay date range. */
  function _travelFilter(type, data) {
    const records = St.lastResult ? St.lastResult.records : [];
    let filtered, filterText;

    if (type === "bc") {
      // Border crossing: filter by datetime range
      const from = _parseDt(data.last_domestic_datetime);
      const to = _parseDt(data.first_return_datetime);
      filtered = records.filter(r => {
        if (!r.datetime) return false;
        const t = _parseDt(r.datetime);
        return t >= from && t <= to;
      });
      const countries = (data.roaming_countries || []).map(c => _countryName(c)).join(", ");
      const fromDate = (data.last_domestic_datetime || "").slice(0, 10);
      const toDate = (data.first_return_datetime || "").slice(0, 10);
      const period = fromDate === toDate ? fromDate : `${fromDate} – ${toDate}`;
      filterText = `Wyjazd: ${period}${countries ? ` (${countries})` : ""} — ${filtered.length} rek.`;
    } else {
      // Overnight stay: filter by date range (start_date to end_date inclusive)
      filtered = records.filter(r => {
        if (!r.date) return false;
        return r.date >= data.start_date && r.date <= data.end_date;
      });
      const period = data.start_date === data.end_date
        ? data.start_date
        : `${data.start_date} – ${data.end_date}`;
      const locs = (data.locations || []).join(", ");
      filterText = `Nocleg: ${period}${locs ? ` (${locs})` : ""} — ${filtered.length} rek.`;
    }

    // Clear any active heatmap filter state
    St.hmActiveCell = null;
    const hmBar = QS("#gsm_hm_filter_bar");
    if (hmBar) hmBar.style.display = "none";

    // Show filter badge in Records header
    _setRecordsFilter(filterText, () => _clearTravelFilter());

    // Render filtered records
    _renderRecords(filtered, false, filtered.length);

    // Scroll to Records card
    const recCard = QS("#gsm_records_card");
    if (recCard) recCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /** Clear travel filter and restore original records. */
  function _clearTravelFilter() {
    _clearRecordsFilter();
    if (St.lastResult) {
      _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    }
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

  /**
   * Build a curved arc between two points (great-circle-like visual).
   * Used for plane routes — adds a visible bulge to the line.
   */
  function _buildArcCoords(lat1, lon1, lat2, lon2, segments) {
    const coords = [];
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const lat = lat1 + (lat2 - lat1) * t;
      const lon = lon1 + (lon2 - lon1) * t;
      // Add parabolic bulge perpendicular to the line
      const bulge = Math.sin(t * Math.PI) * 0.15 * Math.sqrt(
        Math.pow(lat2 - lat1, 2) + Math.pow(lon2 - lon1, 2)
      );
      // Perpendicular direction: rotate 90°
      const dx = lon2 - lon1;
      const dy = lat2 - lat1;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      coords.push([lat + (-dx / len) * bulge, lon + (dy / len) * bulge]);
    }
    return coords;
  }

  /**
   * Build polygon coords for a sector (pie-slice) on the map.
   * Returns array of [lat,lon] pairs forming a closed polygon.
   */
  function _buildSectorCoords(lat, lon, radiusM, startAngle, endAngle, segments) {
    const coords = [[lat, lon]]; // center point
    const step = (endAngle - startAngle) / segments;
    for (let i = 0; i <= segments; i++) {
      const angle = startAngle + step * i;
      const pt = _offsetByAzimuth(lat, lon, angle, radiusM);
      coords.push([pt.lat, pt.lon]);
    }
    coords.push([lat, lon]); // close polygon
    return coords;
  }

  /* ── Country code → full Polish name mapping ── */
  const _COUNTRY_NAMES = {
    // Europa
    PL:"Polska",DE:"Niemcy",CZ:"Czechy",SK:"S\u0142owacja",UA:"Ukraina",
    BY:"Bia\u0142oru\u015B",LT:"Litwa",RU:"Rosja",AT:"Austria",CH:"Szwajcaria",
    FR:"Francja",GB:"Wielka Brytania",IT:"W\u0142ochy",ES:"Hiszpania",
    NL:"Holandia",BE:"Belgia",DK:"Dania",SE:"Szwecja",NO:"Norwegia",
    FI:"Finlandia",PT:"Portugalia",IE:"Irlandia",HU:"W\u0119gry",RO:"Rumunia",
    BG:"Bu\u0142garia",HR:"Chorwacja",SI:"S\u0142owenia",RS:"Serbia",BA:"Bo\u015Bnia i Hercegowina",
    ME:"Czarnog\u00F3ra",MK:"Macedonia P\u00F3\u0142nocna",AL:"Albania",GR:"Grecja",TR:"Turcja",
    EE:"Estonia",LV:"\u0141otwa",LU:"Luksemburg",MT:"Malta",CY:"Cypr",
    IS:"Islandia",MD:"Mo\u0142dawia",XK:"Kosowo",MC:"Monako",AD:"Andora",
    VA:"Watykan",SM:"San Marino",LI:"Liechtenstein",GI:"Gibraltar",
    FO:"Wyspy Owcze",GL:"Grenlandia",GE:"Gruzja",AM:"Armenia",AZ:"Azerbejd\u017Can",
    // Ameryka P\u00F3\u0142nocna i \u015Arodkowa
    US:"USA",CA:"Kanada",MX:"Meksyk",PR:"Portoryko",JM:"Jamajka",
    CU:"Kuba",HT:"Haiti",DO:"Rep. Dominika\u0144ska",TT:"Trynidad i Tobago",
    BB:"Barbados",BS:"Bahamy",GT:"Gwatemala",SV:"Salwador",HN:"Honduras",
    NI:"Nikaragua",CR:"Kostaryka",PA:"Panama",BZ:"Belize",
    // Ameryka Po\u0142udniowa
    BR:"Brazylia",AR:"Argentyna",CL:"Chile",CO:"Kolumbia",PE:"Peru",
    VE:"Wenezuela",EC:"Ekwador",BO:"Boliwia",PY:"Paragwaj",UY:"Urugwaj",
    GY:"Gujana",SR:"Surinam",
    // Bliski Wsch\u00F3d
    AE:"Zjedn. Emiraty Arabskie",SA:"Arabia Saudyjska",IL:"Izrael",
    JO:"Jordania",LB:"Liban",SY:"Syria",IQ:"Irak",IR:"Iran",
    KW:"Kuwejt",BH:"Bahrajn",QA:"Katar",OM:"Oman",YE:"Jemen",
    // Azja
    IN:"Indie",PK:"Pakistan",BD:"Bangladesz",LK:"Sri Lanka",NP:"Nepal",
    AF:"Afganistan",MM:"Mjanma",KZ:"Kazachstan",UZ:"Uzbekistan",
    TJ:"Tad\u017Cykistan",KG:"Kirgistan",TM:"Turkmenistan",MN:"Mongolia",
    CN:"Chiny",JP:"Japonia",KR:"Korea Po\u0142udniowa",KP:"Korea P\u00F3\u0142nocna",
    TW:"Tajwan",HK:"Hongkong",MO:"Makau",
    VN:"Wietnam",TH:"Tajlandia",MY:"Malezja",SG:"Singapur",ID:"Indonezja",
    PH:"Filipiny",KH:"Kambod\u017Ca",LA:"Laos",BN:"Brunei",TL:"Timor Wschodni",
    BT:"Bhutan",MV:"Malediwy",
    // Oceania
    AU:"Australia",NZ:"Nowa Zelandia",FJ:"Fid\u017Ci",PG:"Papua-Nowa Gwinea",
    WS:"Samoa",TO:"Tonga",
    // Afryka
    EG:"Egipt",MA:"Maroko",DZ:"Algieria",TN:"Tunezja",LY:"Libia",
    ZA:"RPA",NG:"Nigeria",GH:"Ghana",KE:"Kenia",TZ:"Tanzania",
    ET:"Etiopia",UG:"Uganda",RW:"Rwanda",SD:"Sudan",SS:"Sudan Po\u0142udniowy",
    AO:"Angola",MZ:"Mozambik",ZW:"Zimbabwe",ZM:"Zambia",MW:"Malawi",
    NA:"Namibia",BW:"Botswana",MG:"Madagaskar",SN:"Senegal",CI:"Wybrze\u017Ce Ko\u015Bci S\u0142oniowej",
    CM:"Kamerun",CD:"Kongo (DR)",CG:"Kongo",GA:"Gabon",ML:"Mali",
    BF:"Burkina Faso",NE:"Niger",TD:"Czad",SO:"Somalia",DJ:"D\u017Cibuti",
    ER:"Erytrea",BI:"Burundi",LS:"Lesotho",SZ:"Eswatini",GM:"Gambia",
    GN:"Gwinea",SL:"Sierra Leone",LR:"Liberia",TG:"Togo",BJ:"Benin",
    MU:"Mauritius",MR:"Mauretania",SC:"Seszele",CV:"Republika Zielonego Przyl\u0105dka",
    CF:"Rep. \u015Arodkowoafryka\u0144ska",GQ:"Gwinea R\u00F3wnikowa",
  };

  /* ── Country center coordinates (approx geographic center) ── */
  const _COUNTRY_CENTERS = {
    PL:[52.07,19.48],DE:[51.16,10.45],CZ:[49.82,15.47],SK:[48.67,19.70],
    UA:[48.38,31.17],BY:[53.71,27.95],LT:[55.17,23.88],RU:[55.75,37.62],
    AT:[47.52,14.55],CH:[46.82,8.23],FR:[46.23,2.21],GB:[55.38,-3.44],
    IT:[41.87,12.57],ES:[40.46,-3.75],NL:[52.13,5.29],BE:[50.50,4.47],
    DK:[56.26,9.50],SE:[60.13,18.64],NO:[60.47,8.47],FI:[61.92,25.75],
    PT:[39.40,-8.22],IE:[53.14,-7.69],HU:[47.16,19.50],RO:[45.94,24.97],
    BG:[42.73,25.49],HR:[45.10,15.20],SI:[46.15,14.99],RS:[44.02,21.01],
    BA:[43.92,17.68],ME:[42.71,19.37],MK:[41.51,21.75],AL:[41.15,20.17],
    GR:[39.07,21.82],TR:[38.96,35.24],EE:[58.60,25.01],LV:[56.88,24.60],
    LU:[49.82,6.13],MT:[35.94,14.38],CY:[35.13,33.43],IS:[64.96,-19.02],
    MD:[47.41,28.37],XK:[42.60,20.90],US:[37.09,-95.71],CA:[56.13,-106.35],
    MC:[43.73,7.42],AD:[42.55,1.57],VA:[41.90,12.45],SM:[43.94,12.46],
    LI:[47.17,9.51],GI:[36.14,-5.35],FO:[62.01,-6.77],GL:[71.71,-42.60],
    GE:[42.32,43.36],AM:[40.07,44.53],AZ:[40.14,47.58],
    MX:[23.63,-102.55],JM:[18.11,-77.30],CU:[21.52,-77.78],
    BR:[-14.24,-51.93],AR:[-38.42,-63.62],CL:[-35.68,-71.54],
    CO:[4.57,-74.30],PE:[-9.19,-75.02],VE:[6.42,-66.59],
    AE:[23.42,53.85],SA:[23.89,45.08],IL:[31.05,34.85],
    JO:[30.59,36.24],LB:[33.85,35.86],IQ:[33.22,43.68],IR:[32.43,53.69],
    KW:[29.31,47.48],QA:[25.35,51.18],OM:[21.47,55.98],BH:[26.07,50.56],
    IN:[20.59,78.96],PK:[30.38,69.35],BD:[23.68,90.36],NP:[28.39,84.12],
    KZ:[48.02,66.92],UZ:[41.38,64.59],MN:[46.86,103.85],
    CN:[35.86,104.20],JP:[36.20,138.25],KR:[35.91,127.77],
    TW:[23.70,121.00],HK:[22.40,114.11],
    VN:[14.06,108.28],TH:[15.87,100.99],MY:[4.21,101.98],SG:[1.35,103.82],
    ID:[-0.79,113.92],PH:[12.88,121.77],
    AU:[-25.27,133.78],NZ:[-40.90,174.89],
    EG:[26.82,30.80],MA:[31.79,-7.09],ZA:[-30.56,22.94],
    NG:[9.08,8.68],KE:[-0.02,37.91],TZ:[-6.37,34.89],ET:[9.15,40.49],
  };
  function _countryName(code) {
    if (!code) return "";
    const up = code.toUpperCase().trim();
    return _COUNTRY_NAMES[up] || up;
  }

  /* ══════════════════════════════════════════════════════════
   *  Timeline Player v4 — smooth animation, mode icons,
   *  fading Marauder trail, year-spanning global slider
   * ══════════════════════════════════════════════════════════ */

  /** Haversine distance in meters. */
  function _haversineDist(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2
            + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
            * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  /**
   * Offset a lat/lon point along a compass bearing by `distMeters`.
   * Used to estimate user position from BTS tower + azimuth.
   */
  function _offsetByAzimuth(lat, lon, azimuthDeg, distMeters) {
    const R = 6371000;
    const bearing = azimuthDeg * Math.PI / 180;
    const latRad = lat * Math.PI / 180;
    const lonRad = lon * Math.PI / 180;
    const d = distMeters / R;
    const newLat = Math.asin(
      Math.sin(latRad) * Math.cos(d) + Math.cos(latRad) * Math.sin(d) * Math.cos(bearing)
    );
    const newLon = lonRad + Math.atan2(
      Math.sin(bearing) * Math.sin(d) * Math.cos(latRad),
      Math.cos(d) - Math.sin(latRad) * Math.sin(newLat)
    );
    return { lat: newLat * 180 / Math.PI, lon: newLon * 180 / Math.PI };
  }

  /** Parse datetime string to ms timestamp. */
  function _parseDt(s) {
    if (!s) return 0;
    const d = new Date(s.replace(" ", "T"));
    return isNaN(d.getTime()) ? 0 : d.getTime();
  }

  /** Travel mode emoji. */
  function _modeEmoji(mode) {
    if (mode === "walk") return "\uD83D\uDEB6";
    if (mode === "car") return "\uD83D\uDE97";
    if (mode === "plane") return "\u2708\uFE0F";
    return "\uD83D\uDCCD";
  }

  /** Calculate smooth animation duration (ms) based on distance between waypoints. */
  function _calcAnimDuration(distMeters) {
    if (distMeters < 500)   return 700;
    if (distMeters < 2000)  return 1000;
    if (distMeters < 10000) return 1400;
    if (distMeters < 50000) return 1800;
    return 2200;
  }

  /**
   * Build waypoints: deduplicate consecutive same-BTS records,
   * adjust position using azimuth (shift toward user),
   * then remove BTS oscillation (A→B→A within short time/distance).
   * Finally, calculate travel mode for each waypoint.
   */
  function _buildWaypoints(recs) {
    if (!recs.length) return [];

    // Step 1: merge consecutive records at same BTS
    const merged = [];
    let cur = {
      lat: recs[0].point.lat, lon: recs[0].point.lon,
      btsLat: recs[0].point.lat, btsLon: recs[0].point.lon,
      city: recs[0].point.city || "", street: recs[0].point.street || "",
      firstDt: recs[0].datetime, lastDt: recs[0].datetime,
      count: 1, records: [recs[0]],
      azimuths: recs[0].point.azimuth != null ? [recs[0].point.azimuth] : [],
    };
    for (let i = 1; i < recs.length; i++) {
      const r = recs[i];
      const same = Math.abs(r.point.lat - cur.btsLat) < 0.0005
                && Math.abs(r.point.lon - cur.btsLon) < 0.0005;
      if (same) {
        cur.count++;
        cur.lastDt = r.datetime;
        cur.records.push(r);
        if (r.point.city && !cur.city) cur.city = r.point.city;
        if (r.point.street && !cur.street) cur.street = r.point.street;
        if (r.point.azimuth != null) cur.azimuths.push(r.point.azimuth);
      } else {
        merged.push(cur);
        cur = {
          lat: r.point.lat, lon: r.point.lon,
          btsLat: r.point.lat, btsLon: r.point.lon,
          city: r.point.city || "", street: r.point.street || "",
          firstDt: r.datetime, lastDt: r.datetime,
          count: 1, records: [r],
          azimuths: r.point.azimuth != null ? [r.point.azimuth] : [],
        };
      }
    }
    merged.push(cur);

    // Step 1b: Adjust position using average azimuth
    for (const wp of merged) {
      if (wp.azimuths.length > 0) {
        let sinSum = 0, cosSum = 0;
        for (const az of wp.azimuths) {
          sinSum += Math.sin(az * Math.PI / 180);
          cosSum += Math.cos(az * Math.PI / 180);
        }
        const avgAz = (Math.atan2(sinSum, cosSum) * 180 / Math.PI + 360) % 360;
        const offset = _offsetByAzimuth(wp.btsLat, wp.btsLon, avgAz, 400);
        wp.lat = offset.lat;
        wp.lon = offset.lon;
      }
    }

    // Step 2: remove BTS oscillations (A→B→A where B is brief & close)
    if (merged.length < 3) return _addTravelModes(merged);
    const filtered = [merged[0]];
    for (let i = 1; i < merged.length - 1; i++) {
      const prev = filtered[filtered.length - 1];
      const curr = merged[i];
      const next = merged[i + 1];
      const prevNextDist = _haversineDist(prev.lat, prev.lon, next.lat, next.lon);
      const prevCurrDist = _haversineDist(prev.lat, prev.lon, curr.lat, curr.lon);
      if (prevNextDist < 500 && curr.count <= 2 && prevCurrDist < 3000) {
        prev.count += curr.count;
        prev.lastDt = curr.lastDt;
        prev.records = prev.records.concat(curr.records);
        continue;
      }
      filtered.push(curr);
    }
    filtered.push(merged[merged.length - 1]);
    return _addTravelModes(filtered);
  }

  /** Add travelMode to each waypoint based on speed to next waypoint. */
  function _addTravelModes(wps) {
    for (let i = 0; i < wps.length; i++) {
      if (i < wps.length - 1) {
        const curr = wps[i];
        const next = wps[i + 1];
        const dist = _haversineDist(curr.lat, curr.lon, next.lat, next.lon);
        const t1 = _parseDt(curr.lastDt);
        const t2 = _parseDt(next.firstDt);
        if (t1 && t2 && t2 > t1) {
          const hours = (t2 - t1) / 3600000;
          const speed = (dist / 1000) / hours;
          curr.travelMode = speed < 7 ? "walk" : speed < 250 ? "car" : "plane";
          curr.speedKmh = speed;
        } else {
          curr.travelMode = dist > 100000 ? "plane" : dist > 2000 ? "car" : "walk";
          curr.speedKmh = 0;
        }
        curr.distToNext = dist;
      } else {
        wps[i].travelMode = "stationary";
        wps[i].speedKmh = 0;
        wps[i].distToNext = 0;
      }
    }
    return wps;
  }

  // ── Fading trail constants ──
  const FADE_COUNT = 18;
  const FADE_DECAY = 0.80;

  function _initTimeline(geo) {
    const wrap = QS("#gsm_timeline_wrap");
    if (!wrap || !St.map) return;

    // Filter and sort records with valid coordinates + datetime
    const recs = (geo.geo_records || []).filter(r =>
      r.point && r.point.lat && r.point.lon && r.datetime
    );
    recs.sort((a, b) => (a.datetime < b.datetime ? -1 : a.datetime > b.datetime ? 1 : 0));
    if (recs.length < 2) { wrap.style.display = "none"; return; }

    St.tlAllRecords = recs;

    // Extract unique days
    const daySet = new Set();
    for (const r of recs) {
      const d = (r.datetime || "").substring(0, 10);
      if (d.length === 10) daySet.add(d);
    }
    St.tlDays = Array.from(daySet).sort();

    // Build global waypoints: per-day build, then concatenate
    St.tlAllWaypoints = [];
    St.tlDayBoundaries = [];
    for (const day of St.tlDays) {
      const dayRecs = recs.filter(r => (r.datetime || "").startsWith(day));
      const startIdx = St.tlAllWaypoints.length;
      const dayWps = _buildWaypoints(dayRecs);
      for (const wp of dayWps) wp.day = day;
      St.tlAllWaypoints = St.tlAllWaypoints.concat(dayWps);
      St.tlDayBoundaries.push({
        day: day,
        startIdx: startIdx,
        endIdx: St.tlAllWaypoints.length - 1,
      });
    }

    if (St.tlAllWaypoints.length < 2) { wrap.style.display = "none"; return; }

    St.tlIdx = 0;
    St.tlPlaying = false;
    St.tlSpeed = 1;
    St.tlSavedZoom = null;
    _tlClearTimer();

    // Create timeline layer group
    const tlGroup = L.layerGroup();
    St.mapLayers.timeline = tlGroup;

    // Full route polyline (entire range, very thin gray dashed)
    const allCoords = St.tlAllWaypoints.map(w => [w.lat, w.lon]);
    St.tlFullRoute = L.polyline(allCoords, {
      color: "#94a3b8", weight: 1.5, opacity: 0.2, dashArray: "4 6",
    });
    St.tlFullRoute.addTo(tlGroup);

    // Visited trail — faint line showing the full visited path so far
    St.tlTrailCoords = [[St.tlAllWaypoints[0].lat, St.tlAllWaypoints[0].lon]];
    St.tlVisitedTrail = L.polyline(St.tlTrailCoords, {
      color: "#2563eb", weight: 2, opacity: 0.12,
    });
    St.tlVisitedTrail.addTo(tlGroup);

    // Fading trail segments (Marauder's Map effect)
    St.tlFadeSegments = [];

    // Waypoint dots along the route (subtle)
    St.tlRouteDots = L.layerGroup();
    for (let i = 0; i < St.tlAllWaypoints.length; i++) {
      const w = St.tlAllWaypoints[i];
      const dotColor = w.count > 10 ? "#3b82f6" : w.count > 3 ? "#60a5fa" : "#cbd5e1";
      const dotR = Math.min(5, Math.max(1.5, 0.5 + Math.log2(w.count)));
      L.circleMarker([w.lat, w.lon], {
        radius: dotR, color: dotColor, fillColor: dotColor,
        fillOpacity: 0.3, weight: 0.5,
      }).bindTooltip(
        `${(w.firstDt || "").substring(11, 16)} \u00B7 ${w.count} rek.` +
        (w.city ? `<br>${w.city}` : ""),
        { direction: "top", opacity: 0.9 }
      ).addTo(St.tlRouteDots);
    }
    tlGroup.addLayer(St.tlRouteDots);

    // Marker — L.marker with divIcon showing mode emoji
    const firstWp = St.tlAllWaypoints[0];
    St.tlMarker = L.marker([firstWp.lat, firstWp.lon], {
      icon: L.divIcon({
        className: "gsm-tl-marker-icon",
        html: '<div class="gsm-tl-marker">' + _modeEmoji("stationary") + '</div>',
        iconSize: [36, 36],
        iconAnchor: [18, 18],
      }),
      zIndexOffset: 1000,
    });
    St.tlMarker.addTo(tlGroup);
    St.tlMarker.bindPopup("");

    wrap.style.display = "";

    // Slider setup (global — covers all waypoints across all days)
    const slider = QS("#gsm_tl_slider");
    if (slider) {
      slider.min = 0;
      slider.max = St.tlAllWaypoints.length - 1;
      slider.value = 0;
    }

    // Build month strip for quick navigation
    _buildMonthStrip();

    // Draw global density bar
    _drawDensityBar(recs);

    // Initial labels
    _timelineUpdateLabels();

    // ── Wire up controls ──
    const playBtn = QS("#gsm_tl_play");
    if (playBtn) {
      playBtn.onclick = function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (St.tlPlaying) _timelinePause(); else _timelinePlay();
      };
    }

    const speedBtn = QS("#gsm_tl_speed");
    if (speedBtn) {
      speedBtn.onclick = function (e) {
        e.preventDefault();
        e.stopPropagation();
        const speeds = [1, 2, 5, 10];
        const idx = speeds.indexOf(St.tlSpeed);
        St.tlSpeed = speeds[(idx + 1) % speeds.length];
        speedBtn.textContent = St.tlSpeed + "\u00D7";
      };
    }

    if (slider) {
      slider.onmousedown = slider.ontouchstart = function () {
        if (St.tlPlaying) _timelinePause();
      };
      slider.oninput = function () {
        _timelineSeek(parseInt(this.value));
      };
    }

    const canvas = QS("#gsm_tl_density");
    if (canvas) {
      canvas.onclick = function (e) {
        if (St.tlPlaying) _timelinePause();
        const rect = canvas.getBoundingClientRect();
        const ratio = (e.clientX - rect.left) / rect.width;
        const idx = Math.round(ratio * Math.max(0, St.tlAllWaypoints.length - 1));
        _timelineSeek(Math.max(0, Math.min(idx, St.tlAllWaypoints.length - 1)));
      };
    }

    const prevDay = QS("#gsm_tl_prev_day");
    const nextDay = QS("#gsm_tl_next_day");
    if (prevDay) prevDay.onclick = function () { _timelineJumpDay(-1); };
    if (nextDay) nextDay.onclick = function () { _timelineJumpDay(1); };

    console.log("[GSM Timeline v4]", recs.length, "records,",
      St.tlAllWaypoints.length, "waypoints,", St.tlDays.length, "days");
  }

  /** Build month navigation strip. */
  function _buildMonthStrip() {
    const el = QS("#gsm_tl_months");
    if (!el || !St.tlAllWaypoints.length) return;

    const monthMap = new Map();
    for (let i = 0; i < St.tlAllWaypoints.length; i++) {
      const m = (St.tlAllWaypoints[i].firstDt || "").substring(0, 7);
      if (m.length === 7 && !monthMap.has(m)) monthMap.set(m, i);
    }
    if (monthMap.size <= 1) { el.style.display = "none"; return; }

    const mNames = ["Sty","Lut","Mar","Kwi","Maj","Cze","Lip","Sie","Wrz","Pa\u017A","Lis","Gru"];
    var html = "";
    for (const [key, firstIdx] of monthMap) {
      const parts = key.split("-");
      html += '<button class="gsm-tl-month-chip" data-idx="' + firstIdx + '">' +
              mNames[parseInt(parts[1]) - 1] + "'" + parts[0].slice(2) + '</button>';
    }
    el.innerHTML = html;

    QSA(".gsm-tl-month-chip", el).forEach(function (btn) {
      btn.onclick = function () {
        if (St.tlPlaying) _timelinePause();
        _timelineSeek(parseInt(btn.dataset.idx));
      };
    });
  }

  /** Highlight current month in strip. */
  function _updateMonthHighlight() {
    var el = QS("#gsm_tl_months");
    if (!el || !St.tlAllWaypoints.length) return;
    var wp = St.tlAllWaypoints[St.tlIdx];
    if (!wp) return;
    var curMonth = (wp.firstDt || "").substring(0, 7);
    QSA(".gsm-tl-month-chip", el).forEach(function (btn) {
      var idx = parseInt(btn.dataset.idx);
      var btnMonth = (St.tlAllWaypoints[idx] && St.tlAllWaypoints[idx].firstDt || "").substring(0, 7);
      if (btnMonth === curMonth) btn.classList.add("active");
      else btn.classList.remove("active");
    });
  }

  function _tlClearTimer() {
    if (St.tlTimer) { clearInterval(St.tlTimer); St.tlTimer = null; }
    if (St.tlAnimFrame) { cancelAnimationFrame(St.tlAnimFrame); St.tlAnimFrame = null; }
  }

  /** Jump to next/prev day from current position. */
  function _timelineJumpDay(dir) {
    if (!St.tlAllWaypoints.length) return;
    if (St.tlPlaying) _timelinePause();

    var curDay = St.tlAllWaypoints[St.tlIdx].day;
    var curDayIdx = St.tlDays.indexOf(curDay);
    var newDayIdx = curDayIdx + dir;
    if (newDayIdx < 0 || newDayIdx >= St.tlDays.length) return;

    var boundary = St.tlDayBoundaries[newDayIdx];
    if (!boundary) return;
    _timelineSeek(boundary.startIdx);

    // Fit map to the new day's bounds
    var dayWps = St.tlAllWaypoints.slice(boundary.startIdx, boundary.endIdx + 1);
    if (dayWps.length && St.map) {
      var bounds = dayWps.map(function (w) { return [w.lat, w.lon]; });
      St.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }
  }

  function _timelinePlay() {
    if (!St.tlAllWaypoints.length) return;
    if (St.tlIdx >= St.tlAllWaypoints.length - 1) _timelineSeek(0);

    St.tlPlaying = true;
    var playBtn = QS("#gsm_tl_play");
    if (playBtn) playBtn.textContent = "\u23F8";

    // Ensure timeline layer visible
    if (St.map && St.mapLayers.timeline && !St.map.hasLayer(St.mapLayers.timeline)) {
      St.mapLayers.timeline.addTo(St.map);
    }

    _tlClearTimer();
    // Start smooth animation loop
    St._tlAnimating = false;
    St.tlAnimFrame = requestAnimationFrame(_timelineAnimLoop);
  }

  function _timelinePause() {
    St.tlPlaying = false;
    _tlClearTimer();
    var playBtn = QS("#gsm_tl_play");
    if (playBtn) playBtn.textContent = "\u25B6";

    // Snap marker to current waypoint position
    if (St.tlMarker && St.tlAllWaypoints[St.tlIdx]) {
      var wp = St.tlAllWaypoints[St.tlIdx];
      St.tlMarker.setLatLng([wp.lat, wp.lon]);
    }
  }

  /** Smooth animation loop using requestAnimationFrame.
   *  Interpolates marker position between consecutive waypoints. */
  function _timelineAnimLoop(now) {
    if (!St.tlPlaying) return;

    if (St.tlIdx >= St.tlAllWaypoints.length - 1) {
      _timelinePause();
      return;
    }

    // Start new animation segment if not currently animating
    if (!St._tlAnimating) {
      St._tlAnimating = true;
      St._tlAnimStart = now;
      var curr = St.tlAllWaypoints[St.tlIdx];
      var next = St.tlAllWaypoints[St.tlIdx + 1];
      St._tlAnimFrom = [curr.lat, curr.lon];
      St._tlAnimTo = [next.lat, next.lon];
      var dist = _haversineDist(curr.lat, curr.lon, next.lat, next.lon);
      St._tlAnimDuration = Math.max(80, _calcAnimDuration(dist) / St.tlSpeed);
    }

    var elapsed = now - St._tlAnimStart;
    var t = Math.min(1, elapsed / St._tlAnimDuration);

    // Ease-in-out for smooth movement
    var ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;

    var lat = St._tlAnimFrom[0] + (St._tlAnimTo[0] - St._tlAnimFrom[0]) * ease;
    var lon = St._tlAnimFrom[1] + (St._tlAnimTo[1] - St._tlAnimFrom[1]) * ease;

    if (St.tlMarker) St.tlMarker.setLatLng([lat, lon]);

    // Intermediate trail: draw partial line during animation
    if (t >= 1) {
      // Arrived at next waypoint
      St._tlAnimating = false;
      St.tlIdx++;
      _onWaypointArrived(St.tlIdx);
    }

    St.tlAnimFrame = requestAnimationFrame(_timelineAnimLoop);
  }

  /** Called when animation reaches a new waypoint. */
  function _onWaypointArrived(idx) {
    var wp = St.tlAllWaypoints[idx];
    if (!wp) return;

    // Add fading trail segment
    if (idx > 0) {
      var prev = St.tlAllWaypoints[idx - 1];
      _addFadeSegment([prev.lat, prev.lon], [wp.lat, wp.lon]);
    }

    // Update visited trail (faint full path)
    St.tlTrailCoords.push([wp.lat, wp.lon]);
    if (St.tlVisitedTrail) St.tlVisitedTrail.setLatLngs(St.tlTrailCoords);

    // Update marker icon based on travel mode
    _updateMarkerMode(wp);

    // Update slider
    var slider = QS("#gsm_tl_slider");
    if (slider) slider.value = idx;

    // Update labels
    _timelineUpdateLabels();
    _timelineUpdatePopup(wp);
    _updateMonthHighlight();

    // Follow map
    _timelineFollowMap([wp.lat, wp.lon]);
  }

  /** Update marker emoji to match travel mode. */
  function _updateMarkerMode(wp) {
    if (!St.tlMarker) return;
    var emoji = _modeEmoji(wp.travelMode || "stationary");
    var iconEl = St.tlMarker.getElement();
    if (iconEl) {
      var inner = iconEl.querySelector(".gsm-tl-marker");
      if (inner) inner.textContent = emoji;
    }
    // Also update mode label in controls
    var modeEl = QS("#gsm_tl_mode_icon");
    if (modeEl) {
      modeEl.textContent = emoji;
      var labels = { walk: "pieszo", car: "samoch\u00F3d", plane: "samolot", stationary: "" };
      modeEl.title = labels[wp.travelMode] || "";
    }
  }

  /** Add a fading trail segment (Marauder's Map effect). */
  function _addFadeSegment(from, to) {
    if (!St.mapLayers.timeline) return;
    var seg = L.polyline([from, to], {
      color: "#2563eb", weight: 4, opacity: 0.9, lineCap: "round",
    });
    seg.addTo(St.mapLayers.timeline);
    St.tlFadeSegments.push(seg);
    _updateFadeOpacities();
    // Remove oldest segments beyond limit
    while (St.tlFadeSegments.length > FADE_COUNT) {
      var old = St.tlFadeSegments.shift();
      St.mapLayers.timeline.removeLayer(old);
    }
  }

  /** Update opacity of all fade segments (newest=bright, oldest=faint). */
  function _updateFadeOpacities() {
    var n = St.tlFadeSegments.length;
    for (var i = 0; i < n; i++) {
      var age = n - 1 - i; // 0 = newest
      var opacity = 0.9 * Math.pow(FADE_DECAY, age);
      St.tlFadeSegments[i].setStyle({ opacity: Math.max(0.04, opacity) });
    }
  }

  /** Clear all fading trail segments. */
  function _clearFadeSegments() {
    if (!St.mapLayers.timeline) return;
    for (var i = 0; i < St.tlFadeSegments.length; i++) {
      St.mapLayers.timeline.removeLayer(St.tlFadeSegments[i]);
    }
    St.tlFadeSegments = [];
  }

  /** Rebuild fading segments around a given index (for seek). */
  function _rebuildFadeSegments(upToIdx) {
    _clearFadeSegments();
    var start = Math.max(1, upToIdx - FADE_COUNT + 1);
    for (var i = start; i <= upToIdx; i++) {
      var prev = St.tlAllWaypoints[i - 1];
      var curr = St.tlAllWaypoints[i];
      var seg = L.polyline(
        [[prev.lat, prev.lon], [curr.lat, curr.lon]],
        { color: "#2563eb", weight: 4, opacity: 0.9, lineCap: "round" }
      );
      seg.addTo(St.mapLayers.timeline);
      St.tlFadeSegments.push(seg);
    }
    _updateFadeOpacities();
  }

  /** Seek to a specific global waypoint index (slider-driven). */
  function _timelineSeek(idx) {
    idx = Math.max(0, Math.min(idx, St.tlAllWaypoints.length - 1));
    St.tlIdx = idx;
    St._tlAnimating = false; // reset animation state

    if (!St.tlAllWaypoints.length) return;
    var wp = St.tlAllWaypoints[idx];
    var latlng = [wp.lat, wp.lon];

    if (St.tlMarker) St.tlMarker.setLatLng(latlng);

    // Rebuild visited trail up to idx
    var coords = [];
    for (var i = 0; i <= idx; i++) {
      coords.push([St.tlAllWaypoints[i].lat, St.tlAllWaypoints[i].lon]);
    }
    St.tlTrailCoords = coords;
    if (St.tlVisitedTrail) St.tlVisitedTrail.setLatLngs(coords);

    // Rebuild fading segments
    _rebuildFadeSegments(idx);

    // Update marker mode
    _updateMarkerMode(wp);

    var slider = QS("#gsm_tl_slider");
    if (slider && parseInt(slider.value) !== idx) slider.value = idx;

    _timelineUpdateLabels();
    _timelineUpdatePopup(wp);
    _updateMonthHighlight();

    // Pan map to marker position
    if (St.map) {
      var bounds = St.map.getBounds();
      if (!bounds.contains(latlng)) {
        St.map.panTo(latlng, { animate: true, duration: 0.3 });
      }
    }

    // Ensure timeline layer visible
    if (St.map && St.mapLayers.timeline && !St.map.hasLayer(St.mapLayers.timeline)) {
      St.mapLayers.timeline.addTo(St.map);
    }
  }

  /** Pan map to keep marker visible (with inner padding). */
  function _timelineFollowMap(latlng) {
    if (!St.map) return;
    var bounds = St.map.getBounds();
    var padLat = (bounds.getNorth() - bounds.getSouth()) * 0.25;
    var padLng = (bounds.getEast() - bounds.getWest()) * 0.25;
    var inner = L.latLngBounds(
      [bounds.getSouth() + padLat, bounds.getWest() + padLng],
      [bounds.getNorth() - padLat, bounds.getEast() - padLng]
    );
    if (!inner.contains(latlng)) {
      St.map.panTo(latlng, { animate: true, duration: 0.4 });
    }
  }

  function _timelineUpdateLabels() {
    var dtLabel = QS("#gsm_tl_datetime");
    var counter = QS("#gsm_tl_counter");
    var dayLabel = QS("#gsm_tl_day_label");
    var dayInfo = QS("#gsm_tl_day_info");

    if (!St.tlAllWaypoints.length) return;
    var wp = St.tlAllWaypoints[St.tlIdx];

    if (dtLabel) {
      var date = (wp.firstDt || "").substring(0, 10);
      var t1 = (wp.firstDt || "").substring(11, 16);
      if (wp.count > 1 && wp.firstDt !== wp.lastDt) {
        var t2 = (wp.lastDt || "").substring(11, 16);
        dtLabel.textContent = date + " " + t1 + "\u2014" + t2;
      } else {
        dtLabel.textContent = date + " " + t1;
      }
    }

    if (counter) counter.textContent = (St.tlIdx + 1) + " / " + St.tlAllWaypoints.length;

    if (dayLabel) {
      var day = wp.day || (wp.firstDt || "").substring(0, 10);
      var parts = day.split("-");
      var dayNames = ["Nd","Pn","Wt","\u015Ar","Cz","Pt","Sb"];
      try {
        var dt = new Date(day + "T00:00:00");
        dayLabel.textContent = dayNames[dt.getDay()] + " " + parts[2] + "." + parts[1] + "." + parts[0];
      } catch(e) { dayLabel.textContent = day; }
    }

    if (dayInfo) {
      var curDay = wp.day;
      var boundary = null;
      for (var b = 0; b < St.tlDayBoundaries.length; b++) {
        if (St.tlDayBoundaries[b].day === curDay) { boundary = St.tlDayBoundaries[b]; break; }
      }
      var dayCount = boundary ? (boundary.endIdx - boundary.startIdx + 1) : 0;
      var dayIdx = St.tlDays.indexOf(curDay);
      dayInfo.textContent = dayCount + " pkt \u00B7 dzie\u0144 " + (dayIdx + 1) + "/" + St.tlDays.length;
    }
  }

  function _timelineUpdatePopup(wp) {
    if (!St.tlMarker) return;
    var loc = [wp.city, wp.street].filter(Boolean).join(", ")
              || wp.lat.toFixed(4) + ", " + wp.lon.toFixed(4);
    var t1 = (wp.firstDt || "").substring(11, 16);
    var timeRange = (wp.count > 1 && wp.firstDt !== wp.lastDt)
      ? t1 + " \u2014 " + (wp.lastDt || "").substring(11, 16)
      : t1;
    var types = {};
    for (var ri = 0; ri < wp.records.length; ri++) {
      var rt = wp.records[ri].record_type;
      if (rt) types[rt] = (types[rt] || 0) + 1;
    }
    var typeStr = Object.entries(types).map(function (e) { return _typeLabel(e[0]) + ": " + e[1]; }).join(", ");
    var modeStr = wp.travelMode ? " " + _modeEmoji(wp.travelMode) : "";
    var speedStr = wp.speedKmh > 0 ? " ~" + Math.round(wp.speedKmh) + " km/h" : "";
    St.tlMarker.setPopupContent(
      "<b>" + loc + "</b><br>" + timeRange + " \u00B7 " + wp.count + " rek." + modeStr + speedStr + (typeStr ? "<br>" + typeStr : "")
    );
  }

  function _drawDensityBar(recs) {
    var canvas = QS("#gsm_tl_density");
    if (!canvas || !recs.length) return;

    var rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(rect.width, 300);
    canvas.height = 24;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    var numBuckets = Math.min(canvas.width, 500);
    var buckets = [];
    for (var bi = 0; bi < numBuckets; bi++) buckets.push({ count: 0, hours: [] });

    for (var i = 0; i < recs.length; i++) {
      var bIdx = Math.min(Math.floor((i / recs.length) * numBuckets), numBuckets - 1);
      buckets[bIdx].count++;
      var dt = recs[i].datetime || "";
      var m = dt.match(/(\d{2}):\d{2}/);
      if (m) buckets[bIdx].hours.push(parseInt(m[1]));
    }

    var maxCount = 1;
    for (var j = 0; j < numBuckets; j++) { if (buckets[j].count > maxCount) maxCount = buckets[j].count; }
    var colW = canvas.width / numBuckets;

    for (var b = 0; b < numBuckets; b++) {
      if (buckets[b].count === 0) continue;
      var h = Math.max(2, (buckets[b].count / maxCount) * canvas.height);
      var avgH = buckets[b].hours.length
        ? Math.round(buckets[b].hours.reduce(function (s, v) { return s + v; }, 0) / buckets[b].hours.length) : 12;
      ctx.fillStyle = (avgH >= 22 || avgH < 6) ? "#1e3a5f"
                    : avgH < 10 ? "#f97316" : avgH < 18 ? "#22c55e" : "#8b5cf6";
      ctx.globalAlpha = 0.7;
      ctx.fillRect(b * colW, canvas.height - h, colW, h);
    }
    ctx.globalAlpha = 1.0;
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

  /* ── heatmap: hour × day-of-week grid ─────────────────── */

  const _DOW_LABELS = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"];
  const _DOW_SHORT  = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"];
  const _MONTH_NAMES = ["Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
                         "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"];

  /** Map JS getDay() (0=Sun..6=Sat) → our index (0=Mon..6=Sun). */
  function _jsDowToIdx(jsDay) {
    return jsDay === 0 ? 6 : jsDay - 1;
  }

  /** Classify record_type to category. */
  function _hmCategory(rt) {
    if (!rt) return null;
    if (rt.startsWith("CALL")) return "calls";
    if (rt === "SMS_OUT" || rt === "SMS_IN" || rt === "MMS_OUT" || rt === "MMS_IN") return "sms";
    if (rt === "DATA") return "data";
    return null;
  }

  /** Build heatmap grid from records. */
  function _buildHeatmapData(records) {
    if (!records || !records.length) { St.hmData = null; return; }

    // Init 24×7 grid
    const grid = [];
    for (let h = 0; h < 24; h++) {
      grid[h] = [];
      for (let d = 0; d < 7; d++) {
        grid[h][d] = { calls: 0, sms: 0, data: 0, total: 0 };
      }
    }

    const monthsSet = new Set();
    const monthFilter = St.hmMonth !== "all" ? St.hmMonth : null;

    for (const r of records) {
      if (!r.datetime) continue;
      // Parse "YYYY-MM-DD HH:MM:SS" or similar
      const dt = new Date(r.datetime.replace(" ", "T"));
      if (isNaN(dt.getTime())) continue;

      const ym = r.datetime.slice(0, 7); // "YYYY-MM"
      monthsSet.add(ym);

      if (monthFilter && ym !== monthFilter) continue;

      const hour = dt.getHours();
      const dow = _jsDowToIdx(dt.getDay());
      const cat = _hmCategory(r.record_type);
      if (!cat) continue;

      grid[hour][dow][cat]++;
      grid[hour][dow].total++;
    }

    // Find max for heatmap scaling
    let maxTotal = 0;
    for (let h = 0; h < 24; h++)
      for (let d = 0; d < 7; d++)
        if (grid[h][d].total > maxTotal) maxTotal = grid[h][d].total;

    const months = Array.from(monthsSet).sort();

    St.hmData = { grid, months, maxTotal };
  }

  /** Render the heatmap table HTML. */
  function _renderHeatmap() {
    const card = QS("#gsm_heatmap_card");
    const body = QS("#gsm_heatmap_body");
    if (!body) return;

    if (!St.hmData || !St.hmData.maxTotal) {
      if (card) card.style.display = "none";
      return;
    }
    if (card) card.style.display = "";

    const { grid } = St.hmData;
    const ac = St.hmActiveCell;  // legacy single cell (or null)
    const activeCells = St.hmActiveCells || [];  // multi-select set
    const typeKey = St.hmType || "all";  // all, calls, sms, data

    // Compute max for the selected type (for heatmap color scaling)
    let typeMax = 0;
    for (let h = 0; h < 24; h++)
      for (let d = 0; d < 7; d++) {
        const v = typeKey === "all" ? grid[h][d].total : (grid[h][d][typeKey] || 0);
        if (v > typeMax) typeMax = v;
      }

    // Heatmap color per type
    const colorMap = { all: "37,99,235", calls: "22,163,74", sms: "234,88,12", data: "124,58,237" };
    const rgb = colorMap[typeKey] || colorMap.all;

    // table-layout:fixed — narrow hour col + 7 equal day cols
    let html = '<table class="gsm-heatmap" style="width:100%"><thead><tr><th class="gsm-hm-hour"></th>';
    for (const d of _DOW_LABELS) html += `<th>${d}</th>`;
    html += "</tr></thead><tbody>";

    for (let h = 0; h < 24; h++) {
      const hShort = String(h).padStart(2, "0") + "–" + String(h + 1 === 24 ? 0 : h + 1).padStart(2, "0");
      const hLabel = String(h).padStart(2, "0") + ":00–" + String(h + 1 === 24 ? 0 : h + 1).padStart(2, "0") + ":00";
      html += `<tr><td class="gsm-hm-hour" title="${hLabel}">${hShort}</td>`;

      for (let d = 0; d < 7; d++) {
        const c = grid[h][d];
        const val = typeKey === "all" ? c.total : (c[typeKey] || 0);
        const opacity = val > 0 && typeMax > 0 ? (val / typeMax) * 0.65 + 0.08 : 0;
        const bg = val > 0 ? `background-color:rgba(${rgb},${opacity.toFixed(3)})` : "";
        const isActive = activeCells.some(c => c.hour === h && c.dow === d)
          || (ac && ac.hour === h && ac.dow === d);
        const cls = isActive ? " gsm-hm-active" : "";

        // Tooltip — always show full breakdown
        const parts = [];
        if (c.calls) parts.push(`${c.calls} rozm.`);
        if (c.sms) parts.push(`${c.sms} SMS`);
        if (c.data) parts.push(`${c.data} dane`);
        const tip = `${_DOW_LABELS[d]} ${hLabel}: ${parts.join(", ") || "brak"}`;

        html += `<td data-hour="${h}" data-dow="${d}" class="${cls}" style="${bg}" title="${tip}">${val || ""}</td>`;
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    body.innerHTML = html;

    // Event delegation — click on cell (supports Ctrl+click multi-select)
    const table = body.querySelector("table");
    if (table) {
      table.onclick = (e) => {
        const td = e.target.closest("td[data-hour]");
        if (!td) return;
        const hour = parseInt(td.dataset.hour, 10);
        const dow = parseInt(td.dataset.dow, 10);

        if (e.ctrlKey || e.metaKey) {
          // Ctrl+click: toggle this cell in multi-select (don't scroll yet)
          _heatmapMultiToggle(hour, dow);
        } else {
          // Normal click: single-cell filter (original behavior)
          St.hmActiveCells = [];
          _heatmapFilter(hour, dow);
        }
      };

      // When Ctrl is released, apply the accumulated multi-select filter
      const _onKeyUp = (e) => {
        if ((e.key === "Control" || e.key === "Meta") && St.hmActiveCells && St.hmActiveCells.length) {
          _heatmapApplyMultiFilter();
        }
      };
      // Store handler ref for cleanup; use capture on document
      if (St._hmKeyUpHandler) document.removeEventListener("keyup", St._hmKeyUpHandler);
      St._hmKeyUpHandler = _onKeyUp;
      document.addEventListener("keyup", _onKeyUp);
    }

    // Month selector
    _initHeatmapMonthSelector();
  }

  /** Populate the month <select> and wire the type <select>. */
  function _initHeatmapMonthSelector() {
    const sel = QS("#gsm_hm_month");
    if (sel && St.hmData) {
      // Rebuild options
      sel.innerHTML = '<option value="all">Cały okres</option>';
      for (const ym of St.hmData.months) {
        const [y, m] = ym.split("-");
        const label = `${_MONTH_NAMES[parseInt(m, 10) - 1]} ${y}`;
        sel.innerHTML += `<option value="${ym}">${label}</option>`;
      }

      // Restore selection
      sel.value = St.hmMonth;
      if (sel.value !== St.hmMonth) sel.value = "all";

      sel.onchange = () => {
        St.hmMonth = sel.value;
        St.hmActiveCell = null;
        _clearHeatmapFilter();
        _buildHeatmapData(St.lastResult ? St.lastResult.records : []);
        _renderHeatmap();
      };
    }

    // Type selector
    const typeSel = QS("#gsm_hm_type");
    if (typeSel) {
      typeSel.value = St.hmType || "all";
      typeSel.onchange = () => {
        St.hmType = typeSel.value;
        // Re-render heatmap with different type key
        _renderHeatmap();
        // Re-apply active cell filter if any (type changes what records match)
        if (St.hmActiveCell) {
          _heatmapFilter(St.hmActiveCell.hour, St.hmActiveCell.dow, true);
        }
      };
    }
  }

  /* ── Map overlays (military / airports / diplomacy) ─────────────── */

  const _OVERLAY_TYPE_ICONS = {
    // Military type → emoji
    brygada: "⚔️", dywizja: "⚔️", pulk: "🎯", batalion: "🎯",
    lotnisko_wojskowe: "✈️", baza_morska: "⚓", centrum: "🏛️",
    poligon: "💥", jednostka: "🪖", baza: "🏗️", dywizjon: "🎯",
  };
  const _OVERLAY_TYPE_COLORS = {
    brygada: "#b91c1c", dywizja: "#991b1b", pulk: "#dc2626",
    batalion: "#ef4444", lotnisko_wojskowe: "#7c3aed",
    baza_morska: "#0369a1", centrum: "#b45309", poligon: "#65a30d",
    jednostka: "#e11d48", baza: "#be123c", dywizjon: "#f97316",
  };
  const _DIPLOMACY_TYPE_ICONS = {
    ambasada_rp: "🇵🇱", konsulat_rp: "🇵🇱", konsulat_honorowy_rp: "🇵🇱",
    stale_przedstawicielstwo_rp: "🇵🇱", instytut_polski: "🇵🇱", biuro_ataszatu_rp: "🇵🇱",
    ambasada_obca: "🏛️", konsulat_obcy: "🏛️",
  };
  const _DIPLOMACY_TYPE_COLORS = {
    ambasada_rp: "#dc2626", konsulat_rp: "#ea580c", konsulat_honorowy_rp: "#d97706",
    stale_przedstawicielstwo_rp: "#7c3aed", instytut_polski: "#0891b2", biuro_ataszatu_rp: "#be123c",
    ambasada_obca: "#059669", konsulat_obcy: "#0d9488",
  };

  async function _toggleOverlay(which, show) {
    if (!St.map) return;
    const keyMap = { military: "overlayMilitary", airports: "overlayAirports", diplomacy: "overlayDiplomacy" };
    const dataMap = { military: "overlayMilitaryData", airports: "overlayAirportsData", diplomacy: "overlayDiplomacyData" };
    const urlMap = {
      military: "/static/data/poland_military.json",
      airports: "/static/data/poland_airports.json",
      diplomacy: "/static/data/poland_diplomacy.json",
    };
    const cbMap = { military: "#gsm_overlay_military", airports: "#gsm_overlay_airports", diplomacy: "#gsm_overlay_diplomacy" };
    const layerKey = keyMap[which];
    const dataKey = dataMap[which];
    const url = urlMap[which];

    if (!show) {
      if (St[layerKey]) { St.map.removeLayer(St[layerKey]); }
      return;
    }

    // Load data if not cached
    if (!St[dataKey]) {
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        St[dataKey] = await resp.json();
      } catch (err) {
        _addLog("error", `Nie udało się załadować danych: ${err.message}`);
        const cb = QS(cbMap[which]);
        if (cb) cb.checked = false;
        return;
      }
    }

    // Build layer group if needed
    if (!St[layerKey]) {
      const group = L.layerGroup();
      const data = St[dataKey];

      if (which === "military") {
        for (const item of data) {
          const icon = _OVERLAY_TYPE_ICONS[item.type] || "🪖";
          const color = _OVERLAY_TYPE_COLORS[item.type] || "#b91c1c";
          const divIcon = L.divIcon({
            className: "gsm-overlay-marker",
            html: `<span style="font-size:18px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">${icon}</span>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
          });
          const m = L.marker([item.lat, item.lon], { icon: divIcon, interactive: true });
          m.bindTooltip(`<b style="color:${color}">${item.name}</b><br><span class="small">${item.desc || ""}</span>`, {
            direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip"
          });
          m.on("click", () => _handleOverlayClick(
            { lat: item.lat, lon: item.lon },
            { name: item.name, desc: item.desc || "", type: item.type || "", color }
          ));
          m.addTo(group);
        }
      } else if (which === "diplomacy") {
        for (const item of data) {
          const icon = _DIPLOMACY_TYPE_ICONS[item.type] || "🏛️";
          const color = _DIPLOMACY_TYPE_COLORS[item.type] || "#059669";
          const divIcon = L.divIcon({
            className: "gsm-overlay-marker",
            html: `<span style="font-size:16px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">${icon}</span>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11],
          });
          const m = L.marker([item.lat, item.lon], { icon: divIcon, interactive: true });
          const countryTag = item.country ? ` <span class="small" style="color:#6b7280">(${item.country})</span>` : "";
          m.bindTooltip(`<b style="color:${color}">${item.name}</b>${countryTag}<br><span class="small">${item.desc || ""}</span>`, {
            direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip"
          });
          m.on("click", () => _handleOverlayClick(
            { lat: item.lat, lon: item.lon },
            { name: item.name, desc: item.desc || "", type: item.type || "", color, extra: countryTag ? `<span class="small muted">Kraj: ${item.country}</span>` : "" }
          ));
          m.addTo(group);
        }
      } else {
        // Airports
        for (const item of data) {
          const label = item.iata ? `${item.iata}` : "";
          const divIcon = L.divIcon({
            className: "gsm-overlay-marker",
            html: `<span style="font-size:18px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">✈️</span>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
          });
          const m = L.marker([item.lat, item.lon], { icon: divIcon, interactive: true });
          const tooltipHtml = `<b style="color:#2563eb">${item.name}</b>`
            + (label ? `<br><span class="small" style="color:#6b7280">${label} — ${item.city}</span>` : `<br><span class="small">${item.city}</span>`);
          m.bindTooltip(tooltipHtml, {
            direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip"
          });
          m.on("click", () => _handleOverlayClick(
            { lat: item.lat, lon: item.lon },
            { name: item.name, desc: item.city || "", type: label ? `✈️ ${label}` : "Lotnisko", color: "#2563eb" }
          ));
          m.addTo(group);
        }
      }
      St[layerKey] = group;
    }

    St[layerKey].addTo(St.map);
  }

  /* ── KML user overlays ─────────────────────────────────── */

  // Store: { overlayId: L.layerGroup }
  if (!St._kmlLayers) St._kmlLayers = {};
  if (!St._kmlData) St._kmlData = {};

  async function _loadKmlOverlayCheckboxes() {
    const container = QS("#gsm_kml_overlays");
    if (!container) return;

    try {
      const resp = await fetch("/api/gsm/overlays");
      if (!resp.ok) return;
      const data = await resp.json();
      const items = (data && data.overlays) ? data.overlays : [];

      if (!items.length) {
        container.innerHTML = "";
        return;
      }

      container.innerHTML = items.map(ov => {
        const checked = St._kmlLayers[ov.id] && St.map && St.map.hasLayer(St._kmlLayers[ov.id]) ? " checked" : "";
        const safeName = String(ov.name || ov.id).replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return `<label class="gsm-lp-item">
          <input type="checkbox" data-kml-id="${ov.id}"${checked}> <span style="color:#8b5cf6">&#9679;</span> ${safeName}
        </label>`;
      }).join("");

      // Bind events
      container.querySelectorAll("input[data-kml-id]").forEach(cb => {
        cb.onchange = () => _toggleKmlOverlay(cb.dataset.kmlId, cb.checked);
      });
    } catch (e) {
      // silent
    }
  }

  async function _toggleKmlOverlay(overlayId, show) {
    if (!St.map) return;

    if (!show) {
      if (St._kmlLayers[overlayId]) {
        St.map.removeLayer(St._kmlLayers[overlayId]);
      }
      return;
    }

    // Load data if not cached
    if (!St._kmlData[overlayId]) {
      try {
        const resp = await fetch(`/api/gsm/overlays/${overlayId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        St._kmlData[overlayId] = await resp.json();
      } catch (err) {
        _addLog("error", `Nie udało się załadować warstwy KML: ${err.message}`);
        const cb = QS(`input[data-kml-id="${overlayId}"]`);
        if (cb) cb.checked = false;
        return;
      }
    }

    // Build layer group if needed
    if (!St._kmlLayers[overlayId]) {
      const group = L.layerGroup();
      const data = St._kmlData[overlayId];
      const points = data.points || [];
      const layerName = data.name || overlayId;

      for (const pt of points) {
        if (pt.lat == null || pt.lon == null) continue;
        const divIcon = L.divIcon({
          className: "gsm-overlay-marker",
          html: '<span style="font-size:16px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">📍</span>',
          iconSize: [22, 22],
          iconAnchor: [11, 22],
        });
        const m = L.marker([pt.lat, pt.lon], { icon: divIcon, interactive: true });
        const safeName = String(pt.name || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const safeDesc = String(pt.desc || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        m.bindTooltip(
          `<b style="color:#8b5cf6">${safeName}</b>` +
          (safeDesc ? `<br><span class="small">${safeDesc}</span>` : "") +
          `<br><span class="small muted">${layerName}</span>`,
          { direction: "top", offset: [0, -14], className: "gsm-overlay-tooltip" }
        );
        m.on("click", () => _handleOverlayClick(
          { lat: pt.lat, lon: pt.lon },
          { name: pt.name || "", desc: pt.desc || "", color: "#8b5cf6", layer: layerName }
        ));
        m.addTo(group);
      }
      St._kmlLayers[overlayId] = group;
    }

    St._kmlLayers[overlayId].addTo(St.map);
  }

  /* ── Area selection (circle / rectangle) ─────────────── */

  function _enterAreaSelectMode(mode) {
    if (!St.map) return;
    // If same mode active, cancel it
    if (St.areaSelectMode === mode) {
      _exitAreaSelectMode();
      return;
    }
    // Cancel any previous mode
    _exitAreaSelectMode();
    St.areaSelectMode = mode;

    // Toggle button active state
    const circleBtn = QS("#gsm_select_circle_btn");
    const rectBtn = QS("#gsm_select_rect_btn");
    if (circleBtn) circleBtn.classList.toggle("btn-active", mode === "circle");
    if (rectBtn) rectBtn.classList.toggle("btn-active", mode === "rect");

    // Disable map drag so drawing doesn't pan
    St.map.dragging.disable();
    // Change cursor
    const mapEl = St.map.getContainer();
    mapEl.style.cursor = "crosshair";

    // Disable ALL vector layer interactivity during area select
    // (coverage polygons, path lines, overlay markers, etc. can steal mouse events)
    _setOverlayInteractive(false);
    _setAllLayersInteractive(false);

    // Bind events
    St.map.on("mousedown", _areaMouseDown);
    document.addEventListener("keydown", _areaEscHandler);
  }

  function _exitAreaSelectMode() {
    if (!St.map) return;
    St.areaSelectMode = null;
    St.areaSelectOrigin = null;

    // Remove temp drawing layer
    if (St.areaSelectLayer) {
      St.map.removeLayer(St.areaSelectLayer);
      St.areaSelectLayer = null;
    }

    // Reset buttons only if no active area filter (keep pressed while filter active)
    if (!St.areaShape) {
      const circleBtn = QS("#gsm_select_circle_btn");
      const rectBtn = QS("#gsm_select_rect_btn");
      if (circleBtn) circleBtn.classList.remove("btn-active");
      if (rectBtn) rectBtn.classList.remove("btn-active");
    }

    // Re-enable map drag
    St.map.dragging.enable();
    const mapEl = St.map.getContainer();
    mapEl.style.cursor = "";

    // Re-enable all layer interactivity
    _setOverlayInteractive(true);
    _setAllLayersInteractive(true);

    // Unbind events
    St.map.off("mousedown", _areaMouseDown);
    St.map.off("mousemove", _areaMouseMove);
    St.map.off("mouseup", _areaMouseUp);
    document.removeEventListener("keydown", _areaEscHandler);
  }

  /** Enable/disable overlay markers during area select so they don't steal mouse events */
  function _setOverlayInteractive(enabled) {
    for (const key of ["overlayMilitary", "overlayAirports", "overlayDiplomacy"]) {
      const group = St[key];
      if (!group) continue;
      group.eachLayer(marker => {
        const el = marker.getElement && marker.getElement();
        if (el) el.style.pointerEvents = enabled ? "" : "none";
      });
    }
  }

  /** Enable/disable interactivity on ALL map vector layers (coverage, path, clusters, etc.)
   *  so they don't steal mouse events during area selection drawing.
   *  Works with both canvas and SVG renderer by disabling pointer-events on the
   *  overlay pane and toggling Leaflet's internal interactive flag on each layer. */
  function _setAllLayersInteractive(enabled) {
    if (!St.map) return;
    // Disable pointer-events on the overlay pane (canvas or SVG) to prevent hit detection
    const pane = St.map.getPane("overlayPane");
    if (pane) pane.style.pointerEvents = enabled ? "" : "none";
  }

  function _areaEscHandler(e) {
    if (e.key === "Escape") _exitAreaSelectMode();
  }

  function _areaMouseDown(e) {
    if (!St.areaSelectMode) return;
    if (e.originalEvent) {
      L.DomEvent.stopPropagation(e.originalEvent);
      L.DomEvent.preventDefault(e.originalEvent);
    }
    St.areaSelectOrigin = e.latlng;

    St.map.on("mousemove", _areaMouseMove);
    St.map.on("mouseup", _areaMouseUp);
  }

  function _areaMouseMove(e) {
    if (!St.areaSelectMode || !St.areaSelectOrigin) return;

    // Remove previous temp shape
    if (St.areaSelectLayer) {
      St.map.removeLayer(St.areaSelectLayer);
      St.areaSelectLayer = null;
    }

    const style = { color: "#a855f7", weight: 2, dashArray: "6 4", fillColor: "#a855f7", fillOpacity: 0.08 };

    if (St.areaSelectMode === "circle") {
      const radius = St.areaSelectOrigin.distanceTo(e.latlng);
      St.areaSelectLayer = L.circle(St.areaSelectOrigin, { ...style, radius }).addTo(St.map);
    } else {
      const bounds = L.latLngBounds(St.areaSelectOrigin, e.latlng);
      St.areaSelectLayer = L.rectangle(bounds, style).addTo(St.map);
    }
  }

  function _areaMouseUp(e) {
    if (!St.areaSelectMode || !St.areaSelectOrigin) return;
    if (e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent);

    const endLatLng = e.latlng;
    const mode = St.areaSelectMode;
    const origin = St.areaSelectOrigin;

    // Min drag threshold: 10px to avoid accidental clicks
    const p1 = St.map.latLngToContainerPoint(origin);
    const p2 = St.map.latLngToContainerPoint(endLatLng);
    const dist = p1.distanceTo(p2);
    if (dist < 10) {
      // Too small — ignore, keep mode active for another try
      if (St.areaSelectLayer) { St.map.removeLayer(St.areaSelectLayer); St.areaSelectLayer = null; }
      St.areaSelectOrigin = null;
      St.map.off("mousemove", _areaMouseMove);
      St.map.off("mouseup", _areaMouseUp);
      return;
    }

    // Find BTS locations inside the drawn shape
    let insideLocations;
    if (mode === "circle") {
      const radius = origin.distanceTo(endLatLng);
      insideLocations = St.areaLocations.filter(loc =>
        origin.distanceTo(L.latLng(loc.lat, loc.lon)) <= radius
      );
    } else {
      const bounds = L.latLngBounds(origin, endLatLng);
      insideLocations = St.areaLocations.filter(loc =>
        bounds.contains(L.latLng(loc.lat, loc.lon))
      );
    }

    // Remove temp drawing layer (will be replaced by persistent shape)
    if (St.areaSelectLayer) { St.map.removeLayer(St.areaSelectLayer); St.areaSelectLayer = null; }
    _exitAreaSelectMode();

    if (!insideLocations.length) {
      _addLog("info", `Zaznaczenie ${mode === "circle" ? "koła" : "prostokąta"}: brak punktów BTS w obszarze`);
      return;
    }

    // Clear any previous selection
    _clearAreaSelection();

    // Create persistent shape on map (stays until user clicks it or clears filter)
    const persistStyle = { color: "#a855f7", weight: 2, dashArray: "6 4", fillColor: "#a855f7", fillOpacity: 0.06, interactive: true };
    if (mode === "circle") {
      const radius = origin.distanceTo(endLatLng);
      St.areaShape = L.circle(origin, { ...persistStyle, radius }).addTo(St.map);
    } else {
      const bounds = L.latLngBounds(origin, endLatLng);
      St.areaShape = L.rectangle(bounds, persistStyle).addTo(St.map);
    }
    // Mark the used button as active (persistent indicator that filter is on)
    const circleBtn = QS("#gsm_select_circle_btn");
    const rectBtn = QS("#gsm_select_rect_btn");
    if (circleBtn) circleBtn.classList.toggle("btn-active", mode === "circle");
    if (rectBtn) rectBtn.classList.toggle("btn-active", mode === "rect");

    // Click on the shape = remove selection & clear filters
    St.areaShape.on("click", (e) => {
      if (e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent);
      _clearAreaSelection();
      _clearRecordsFilter();
      if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    });
    // Cursor hint on hover
    St.areaShape.on("mouseover", () => { St.map.getContainer().style.cursor = "pointer"; });
    St.areaShape.on("mouseout", () => { St.map.getContainer().style.cursor = ""; });

    // Highlight selected BTS markers
    _highlightBtsLocations(insideLocations);

    // Collect all records from selected locations and filter table (match by raw_row for uniqueness)
    const rowSet = new Set();
    for (const loc of insideLocations) {
      for (const r of loc.records) rowSet.add(r.raw_row);
    }
    const allRecs = St.lastResult ? St.lastResult.records : [];
    const filtered = allRecs.filter(r => rowSet.has(r.raw_row));
    console.log("[GSM Area] insideLocations:", insideLocations.length,
      "geoRecords in area:", rowSet.size, "allRecs:", allRecs.length, "filtered:", filtered.length,
      "sample rowSet:", [...rowSet].slice(0, 5), "sample allRecs raw_row:", allRecs.slice(0, 5).map(r => r.raw_row));

    const label = mode === "circle" ? "Koło" : "Prostokąt";
    const filterText = `${label}: ${insideLocations.length} BTS — ${filtered.length} rek.`;
    _setRecordsFilter(filterText, () => {
      _clearAreaSelection();
      _clearRecordsFilter();
      if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    });
    _renderRecords(filtered, false, filtered.length);
    const recCard = QS("#gsm_records_card");
    if (recCard) recCard.scrollIntoView({ behavior: "smooth", block: "start" });

    _addLog("info", `Zaznaczenie ${label.toLowerCase()}: ${insideLocations.length} lokalizacji BTS, ${filtered.length} rekordów`);
  }

  /** Add highlight rings around selected BTS markers */
  function _highlightBtsLocations(locations) {
    _clearAreaHighlights();
    const group = L.layerGroup();
    for (const loc of locations) {
      L.circleMarker([loc.lat, loc.lon], {
        radius: 18,
        color: "#f59e0b",
        weight: 2.5,
        fillColor: "#f59e0b",
        fillOpacity: 0.12,
        dashArray: "4 3",
      }).addTo(group);
    }
    St.areaHighlights = group;
    if (St.map) group.addTo(St.map);
  }

  /** Remove area selection highlights */
  function _clearAreaHighlights() {
    if (St.areaHighlights && St.map) {
      St.map.removeLayer(St.areaHighlights);
      St.areaHighlights = null;
    }
  }

  /** Remove persistent shape + highlights (full area selection cleanup) */
  function _clearAreaSelection() {
    _clearAreaHighlights();
    if (St.areaShape && St.map) {
      St.map.removeLayer(St.areaShape);
      St.areaShape = null;
    }
    // Reset button active state (filter cleared)
    const circleBtn = QS("#gsm_select_circle_btn");
    const rectBtn = QS("#gsm_select_rect_btn");
    if (circleBtn) circleBtn.classList.remove("btn-active");
    if (rectBtn) rectBtn.classList.remove("btn-active");
  }

  /* ── Records filter badge helpers ────────────────────── */

  /** Show an active filter in the Records header. */
  function _setRecordsFilter(text, onClear) {
    const badgeText = QS("#gsm_records_filter_text");
    const clearBtn = QS("#gsm_records_filter_clear");
    if (badgeText) {
      badgeText.textContent = text;
      badgeText.classList.remove("muted");
      badgeText.style.color = "var(--brand-blue,#2563eb)";
    }
    if (clearBtn) {
      clearBtn.style.display = "";
      clearBtn.onclick = onClear;
    }
  }

  /** Reset the filter badge to "brak". */
  function _clearRecordsFilter() {
    St._anomalyHighlight = null;  // clear +5 row coloring
    const badgeText = QS("#gsm_records_filter_text");
    const clearBtn = QS("#gsm_records_filter_clear");
    if (badgeText) {
      badgeText.textContent = "brak";
      badgeText.classList.add("muted");
      badgeText.style.color = "";
    }
    if (clearBtn) clearBtn.style.display = "none";
  }

  /** Filter records by clicked heatmap cell. skipToggle=true to re-apply without toggling off. */
  function _heatmapFilter(hour, dow, skipToggle) {
    // Toggle off if clicking same cell (unless re-applying from selector change)
    if (!skipToggle && St.hmActiveCell && St.hmActiveCell.hour === hour && St.hmActiveCell.dow === dow) {
      _clearHeatmapFilter();
      return;
    }

    St.hmActiveCell = { hour, dow };

    // Filter records
    const records = St.lastResult ? St.lastResult.records : [];
    const monthFilter = St.hmMonth !== "all" ? St.hmMonth : null;
    const typeFilter = St.hmType !== "all" ? St.hmType : null;

    const filtered = records.filter(r => {
      if (!r.datetime) return false;
      const dt = new Date(r.datetime.replace(" ", "T"));
      if (isNaN(dt.getTime())) return false;
      if (monthFilter && r.datetime.slice(0, 7) !== monthFilter) return false;
      if (typeFilter && _hmCategory(r.record_type) !== typeFilter) return false;
      return dt.getHours() === hour && _jsDowToIdx(dt.getDay()) === dow;
    });

    // Update heatmap visuals
    _renderHeatmap();

    // Build filter label
    const hLabel = String(hour).padStart(2, "0") + ":00–" + String(hour + 1 === 24 ? 0 : hour + 1).padStart(2, "0") + ":00";
    const typeLabels = { all: "", calls: " · Połączenia", sms: " · SMS/MMS", data: " · Dane" };
    const filterText = `${_DOW_LABELS[dow]} ${hLabel}${typeLabels[St.hmType] || ""} — ${filtered.length} rek.`;

    // Show filter bar under heatmap
    const bar = QS("#gsm_hm_filter_bar");
    const label = QS("#gsm_hm_filter_label");
    if (bar) bar.style.display = "flex";
    if (label) label.textContent = `Filtr: ${filterText}`;

    // Show filter badge in Records header
    _setRecordsFilter(filterText, () => _clearHeatmapFilter());

    // Wire heatmap bar clear button
    const clearBtn = QS("#gsm_hm_filter_clear");
    if (clearBtn) clearBtn.onclick = () => _clearHeatmapFilter();

    // Render filtered records and unique numbers panel
    _renderRecords(filtered, false, filtered.length);
    _renderUniqueNumbers(filtered);

    // Scroll to Records card
    const recCard = QS("#gsm_records_card");
    if (recCard) recCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /** Toggle a cell in multi-select mode (Ctrl+click). Does not scroll or filter records yet. */
  function _heatmapMultiToggle(hour, dow) {
    if (!St.hmActiveCells) St.hmActiveCells = [];

    // Clear single-cell mode
    St.hmActiveCell = null;

    const idx = St.hmActiveCells.findIndex(c => c.hour === hour && c.dow === dow);
    if (idx >= 0) {
      // Deselect
      St.hmActiveCells.splice(idx, 1);
    } else {
      // Add to selection
      St.hmActiveCells.push({ hour, dow });
    }

    // Re-render heatmap to show updated highlights (no record filtering yet)
    _renderHeatmap();

    // Update filter bar to show how many cells are selected
    const bar = QS("#gsm_hm_filter_bar");
    const label = QS("#gsm_hm_filter_label");
    if (St.hmActiveCells.length) {
      if (bar) bar.style.display = "flex";
      if (label) label.textContent = `Zaznaczono ${St.hmActiveCells.length} pól (puść Ctrl aby filtrować)`;
    } else {
      _clearHeatmapFilter();
    }
  }

  /** Apply the accumulated multi-cell filter when Ctrl is released. */
  function _heatmapApplyMultiFilter() {
    const cells = St.hmActiveCells || [];
    if (!cells.length) return;

    // Filter records matching ANY of the selected cells
    const records = St.lastResult ? St.lastResult.records : [];
    const monthFilter = St.hmMonth !== "all" ? St.hmMonth : null;
    const typeFilter = St.hmType !== "all" ? St.hmType : null;

    const filtered = records.filter(r => {
      if (!r.datetime) return false;
      const dt = new Date(r.datetime.replace(" ", "T"));
      if (isNaN(dt.getTime())) return false;
      if (monthFilter && r.datetime.slice(0, 7) !== monthFilter) return false;
      if (typeFilter && _hmCategory(r.record_type) !== typeFilter) return false;
      const rHour = dt.getHours();
      const rDow = _jsDowToIdx(dt.getDay());
      return cells.some(c => c.hour === rHour && c.dow === rDow);
    });

    // Build filter label
    const typeLabels = { all: "", calls: " · Połączenia", sms: " · SMS/MMS", data: " · Dane" };
    const cellLabels = cells.map(c => {
      const hLabel = String(c.hour).padStart(2, "0") + ":00";
      return `${_DOW_LABELS[c.dow]} ${hLabel}`;
    });
    const filterText = `${cells.length} pól (${cellLabels.slice(0, 3).join(", ")}${cells.length > 3 ? "…" : ""})${typeLabels[St.hmType] || ""} — ${filtered.length} rek.`;

    // Show filter bar
    const bar = QS("#gsm_hm_filter_bar");
    const label = QS("#gsm_hm_filter_label");
    if (bar) bar.style.display = "flex";
    if (label) label.textContent = `Filtr: ${filterText}`;

    // Show filter badge in Records header
    _setRecordsFilter(filterText, () => _clearHeatmapFilter());

    // Wire clear button
    const clearBtn = QS("#gsm_hm_filter_clear");
    if (clearBtn) clearBtn.onclick = () => _clearHeatmapFilter();

    // Render filtered records and unique numbers panel
    _renderRecords(filtered, false, filtered.length);
    _renderUniqueNumbers(filtered);

    // Scroll to Records card
    const recCard = QS("#gsm_records_card");
    if (recCard) recCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /**
   * Show panel with all numbers from filtered records, grouped by occurrence count.
   * Numbers appearing only 1× are highlighted (potential one-off contacts).
   * Records without a callee (DATA sessions, VOICEMAIL etc.) are counted separately.
   */
  function _renderUniqueNumbers(filteredRecords) {
    const container = QS("#gsm_hm_unique_numbers");
    if (!container) return;

    if (!filteredRecords || !filteredRecords.length) {
      container.style.display = "none";
      return;
    }

    // Count occurrences of each number (callee) in filtered records
    const numberCounts = {};
    const numberTypes = {};  // number → { record_type: count }
    let noCallee = 0;  // records without a number (DATA, VOICEMAIL etc.)

    for (const r of filteredRecords) {
      const num = r.callee;
      if (!num || num === "—" || num === "") {
        noCallee++;
        continue;
      }
      numberCounts[num] = (numberCounts[num] || 0) + 1;
      if (!numberTypes[num]) numberTypes[num] = {};
      numberTypes[num][r.record_type] = (numberTypes[num][r.record_type] || 0) + 1;
    }

    const allNums = Object.entries(numberCounts);
    if (!allNums.length) {
      // All records are DATA/VOICEMAIL without callee
      if (noCallee > 0) {
        container.style.display = "";
        container.innerHTML = `<div class="small muted">Brak numerów w ${noCallee} ${noCallee === 1 ? "rekordzie" : "rekordach"} (sesje danych / poczta głosowa)</div>`;
      } else {
        container.style.display = "none";
      }
      return;
    }

    // Sort: single-occurrence first, then by count ascending
    allNums.sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]));

    const singleCount = allNums.filter(([, c]) => c === 1).length;
    const totalNums = allNums.length;

    container.style.display = "";

    let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:4px">`;
    html += `<span class="h3" style="margin:0;font-size:13px">Unikatowe numery</span>`;
    html += `<span class="small muted">${totalNums} ${totalNums === 1 ? "numer" : (totalNums < 5 ? "numery" : "numerów")}`;
    if (singleCount > 0) html += ` · <b>${singleCount}</b> pojedynczych (1×)`;
    if (noCallee > 0) html += ` · ${noCallee} bez numeru`;
    html += `</span></div>`;

    html += '<div style="display:flex;flex-wrap:wrap;gap:4px">';

    const colorMap = {
      CALL_OUT: "#3b82f6", CALL_IN: "#22c55e",
      SMS_OUT: "#a855f7", SMS_IN: "#ec4899",
      MMS_OUT: "#a855f7", MMS_IN: "#ec4899",
      DATA: "#f97316", VOICEMAIL: "#6b7280",
    };

    for (const [num, count] of allNums) {
      const types = numberTypes[num] || {};
      const typeEntries = Object.entries(types);
      const typeTag = typeEntries.map(([t, n]) => `${_typeLabel(t)}: ${n}`).join(", ");
      const domType = typeEntries.sort((a, b) => b[1] - a[1])[0]?.[0] || "";
      const tagColor = colorMap[domType] || "#6b7280";
      const isSingle = count === 1;

      // Single-occurrence numbers get a highlighted border
      const borderStyle = isSingle
        ? `border:1.5px solid ${tagColor}`
        : `border:1px solid var(--border)`;

      html += `<div class="gsm-unique-num" data-num="${num}" style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;${borderStyle};border-radius:8px;font-size:12px;cursor:pointer;background:var(--card-bg,#fff)" title="${typeTag} · klik → filtruj rekordy">`;
      html += `<span style="color:${tagColor};font-size:10px">●</span>`;
      html += `<code style="font-size:11px">${num}</code>`;
      if (count > 1) {
        html += ` <span class="small muted" style="font-size:10px">${count}×</span>`;
      }
      // Identification label
      const idInfo = _idLookup(num);
      if (idInfo) {
        html += ` <span class="small ${idInfo.css}" style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${idInfo.type}">${idInfo.label}</span>`;
      }
      html += `</div>`;
    }
    html += '</div>';

    container.innerHTML = html;

    // Click on number → filter Records table to that number (all records, not just filtered)
    container.querySelectorAll(".gsm-unique-num").forEach(el => {
      el.addEventListener("click", () => {
        const num = el.dataset.num;
        const allRecs = St.lastResult ? St.lastResult.records : [];
        const numFiltered = allRecs.filter(r => r.callee === num);
        const filterText = `Nr: ${num} — ${numFiltered.length} rek.`;
        _setRecordsFilter(filterText, () => {
          _clearRecordsFilter();
          if (St.lastResult) _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
        });
        _renderRecords(numFiltered, false, numFiltered.length);
        const recCard = QS("#gsm_records_card");
        if (recCard) recCard.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  /** Clear heatmap filter and restore original records. */
  function _clearHeatmapFilter() {
    St.hmActiveCell = null;
    St.hmActiveCells = [];

    // Hide heatmap filter bar and unique numbers panel
    const bar = QS("#gsm_hm_filter_bar");
    const uniqPanel = QS("#gsm_hm_unique_numbers");
    if (uniqPanel) uniqPanel.style.display = "none";
    if (bar) bar.style.display = "none";

    // Reset Records filter badge
    _clearRecordsFilter();

    // Re-render heatmap (remove active highlight)
    _renderHeatmap();

    // Restore original records
    if (St.lastResult) {
      _renderRecords(St.lastResult.records, St.lastResult.records_truncated, St.lastResult.record_count);
    }
  }

  /* ── project persistence ──────────────────────────────── */

  /**
   * Get current project ID from AISTATE global.
   */
  function _getProjectId() {
    return (typeof AISTATE !== "undefined" && AISTATE && AISTATE.projectId)
      ? String(AISTATE.projectId) : "";
  }

  /**
   * Save GSM state (billing + identification) to the current project.
   * Called automatically after a successful smart import.
   * Ensures a project is selected (prompts if not).
   */
  async function _saveToProject() {
    let pid = _getProjectId();

    // If no project is selected, ask the user to pick/create one
    if (!pid && typeof requireProjectId === "function") {
      try {
        pid = await requireProjectId("gsm");
      } catch (e) {
        _addLog("warn", "Nie wybrano projektu — dane GSM nie zostały zapisane");
        return;
      }
    }
    if (!pid) {
      _addLog("warn", "Brak projektu — dane GSM nie zostały zapisane");
      return;
    }

    const payload = {};

    // Include billing data
    if (St.lastResult) {
      payload.billing = St.lastResult;
    }

    // Include identification map
    if (Object.keys(St.idMap).length > 0) {
      payload.identification = { lookup: St.idMap };
    }

    if (!payload.billing && !payload.identification) return;

    try {
      const resp = await fetch(`/api/gsm/${encodeURIComponent(pid)}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (resp.ok) {
        _addLog("info", "💾 Dane GSM zapisane w projekcie");
      } else {
        const data = await resp.json().catch(() => ({}));
        _addLog("error", `Błąd zapisu GSM: ${data.detail || resp.status}`);
      }
    } catch (e) {
      _addLog("error", `Błąd zapisu GSM: ${e.message || e}`);
    }
  }

  /* ── loading progress on empty state ─────────────────── */

  function _showLoadingOverlay(text) {
    const progress = QS("#gsm_progress");
    const status = QS("#gsm_status");
    const bar = QS("#gsm_bar");
    const progressDiv = progress ? progress.querySelector(".progress") : null;

    if (status) status.textContent = text || "Ładowanie…";
    if (progressDiv) progressDiv.classList.add("indeterminate");
    if (bar) bar.style.width = "30%";
    if (progress) progress.style.display = "";
  }

  function _hideLoadingOverlay() {
    const progress = QS("#gsm_progress");
    const bar = QS("#gsm_bar");
    const progressDiv = progress ? progress.querySelector(".progress") : null;

    if (progressDiv) progressDiv.classList.remove("indeterminate");
    if (bar) bar.style.width = "0%";
    if (progress) progress.style.display = "none";
  }

  /**
   * Load GSM state from the current project.
   * Called on GsmManager.init() to auto-restore data.
   * Shows a progress indicator over the empty state while loading.
   */
  async function _loadFromProject() {
    const pid = _getProjectId();
    if (!pid) {
      console.log("[GSM] No project ID — skip auto-load");
      return false;
    }

    _showLoadingOverlay("Ładowanie danych GSM z projektu…");

    try {
      const resp = await fetch(`/api/gsm/${encodeURIComponent(pid)}/load`);
      if (!resp.ok) {
        console.warn("[GSM] Load failed:", resp.status);
        _hideLoadingOverlay();
        return false;
      }

      const data = await resp.json();
      if (!data.has_data) {
        _hideLoadingOverlay();
        return false;
      }

      // Restore identification map
      if (data.identification && data.identification.lookup) {
        St.idMap = data.identification.lookup;
      }

      // Restore billing data and render
      if (data.billing) {
        St.lastResult = data.billing;
        St.filename = data.billing.filename || "";
        _showLoadingOverlay("Renderowanie wyników…");
        await _renderResults(data.billing);
        _hideLoadingOverlay();
        const idCount = Object.keys(St.idMap).length;
        _addLog("info",
          `Przywrócono dane GSM z projektu: ${data.billing.record_count || 0} rekordów`
          + (idCount ? `, ${idCount} identyfikacji` : "")
          + ` (${data.billing.operator || "?"})`);
        return true;
      }

      _hideLoadingOverlay();
      return false;
    } catch (e) {
      console.warn("[GSM] Load error:", e);
      _hideLoadingOverlay();
      _addLog("warn", `Nie udało się wczytać danych GSM: ${e.message || e}`);
      return false;
    }
  }

  /* ── Standalone map (no billing data) ─────────────────── */

  let _smapInstance = null;      // Leaflet map
  let _smapBtsLayer = null;      // BTS layer group
  let _smapBtsEnabled = false;
  let _smapOverlays = {};        // { military: L.layerGroup, ... }
  let _smapOverlayData = {};     // cached data
  let _smapKmlLayers = {};
  let _smapKmlData = {};
  let _smapDebounce = null;

  async function _openStandaloneMap() {
    const overlay = QS("#gsm_standalone_map_overlay");
    if (!overlay) return;
    overlay.style.display = "";

    await _loadLeaflet();
    if (!window.L) { _addLog("error", "Nie udało się załadować Leaflet"); return; }

    const container = QS("#gsm_smap_container");
    if (!container) return;

    // Destroy previous instance
    if (_smapInstance) {
      try { _smapInstance.remove(); } catch(e) {}
      _smapInstance = null;
      _smapBtsLayer = null;
      _smapBtsEnabled = false;
      _smapOverlays = {};
      _smapKmlLayers = {};
    }

    const map = L.map(container, {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
    }).setView([52.0, 19.5], 7);  // Poland center

    _smapInstance = map;

    // Add tiles (reuse logic)
    await _addTileLayer(map);

    // Layer panel toggle
    const lpHeader = QS("#gsm_smap_lp_header_toggle");
    if (lpHeader) {
      lpHeader.onclick = () => {
        const panel = QS("#gsm_smap_layer_panel");
        if (panel) panel.classList.toggle("collapsed");
      };
    }

    // Layer radio buttons
    const layerRadios = document.querySelectorAll('input[name="gsm_smap_layer"]');
    layerRadios.forEach(r => {
      r.onchange = () => {
        // Update active class
        document.querySelectorAll('#gsm_smap_layer_panel label[data-layer]').forEach(l => l.classList.remove("active"));
        const parentLabel = r.closest("label");
        if (parentLabel) parentLabel.classList.add("active");

        if (r.value === "general") {
          _smapBtsEnabled = false;
          if (_smapBtsLayer) { map.removeLayer(_smapBtsLayer); _smapBtsLayer = null; }
        } else if (r.value === "bts_coverage") {
          _smapBtsEnabled = true;
          _loadSmapBts();
        }
      };
    });

    // BTS loading on move/zoom
    map.on("moveend", () => {
      if (!_smapBtsEnabled) return;
      clearTimeout(_smapDebounce);
      _smapDebounce = setTimeout(() => _loadSmapBts(), 300);
    });

    // Overlay checkboxes
    const ovMil = QS("#gsm_smap_overlay_military");
    const ovAir = QS("#gsm_smap_overlay_airports");
    const ovDip = QS("#gsm_smap_overlay_diplomacy");
    if (ovMil) { ovMil.checked = false; ovMil.onchange = () => _toggleSmapOverlay("military", ovMil.checked); }
    if (ovAir) { ovAir.checked = false; ovAir.onchange = () => _toggleSmapOverlay("airports", ovAir.checked); }
    if (ovDip) { ovDip.checked = false; ovDip.onchange = () => _toggleSmapOverlay("diplomacy", ovDip.checked); }

    // Load KML overlay checkboxes
    _loadSmapKmlCheckboxes();

    // Screenshot button
    const ssBtn = QS("#gsm_smap_screenshot_btn");
    if (ssBtn) {
      ssBtn.onclick = () => _takeSmapScreenshot();
    }

    // Edit mode button
    const editBtn = QS("#gsm_smap_edit_btn");
    if (editBtn) {
      editBtn.onclick = () => _toggleSmapEditMode();
    }

    // Add layer button
    const addLayerBtn = QS("#gsm_smap_add_layer_btn");
    if (addLayerBtn) {
      addLayerBtn.onclick = () => _smapCreateLayer();
    }

    // Close button
    const closeBtn = QS("#gsm_smap_close_btn");
    if (closeBtn) {
      closeBtn.onclick = () => _closeStandaloneMap();
    }

    // ESC key
    overlay._escHandler = (e) => {
      if (e.key === "Escape") {
        // Close location dialog first if open
        const locDialog = QS("#gsm_location_dialog");
        if (locDialog && locDialog.open) { locDialog.close(); return; }
        const lyDialog = QS("#gsm_layer_dialog");
        if (lyDialog && lyDialog.open) { lyDialog.close(); return; }
        _closeStandaloneMap();
      }
    };
    document.addEventListener("keydown", overlay._escHandler);

    // Load user layers
    _smapLoadUserLayers();

    // Force map to recalculate size after overlay is visible
    setTimeout(() => map.invalidateSize(), 100);
  }

  function _closeStandaloneMap() {
    const overlay = QS("#gsm_standalone_map_overlay");
    if (overlay) {
      overlay.style.display = "none";
      if (overlay._escHandler) {
        document.removeEventListener("keydown", overlay._escHandler);
        overlay._escHandler = null;
      }
    }
    // Reset edit mode
    _smapEditMode = false;
    const indicator = QS("#gsm_smap_edit_indicator");
    if (indicator) indicator.style.display = "none";
    const editBtn = QS("#gsm_smap_edit_btn");
    if (editBtn) editBtn.style.background = "";
    const container = QS("#gsm_smap_container");
    if (container) container.style.cursor = "";

    if (_smapInstance) {
      try { _smapInstance.remove(); } catch(e) {}
      _smapInstance = null;
      _smapBtsLayer = null;
      _smapBtsEnabled = false;
      _smapOverlays = {};
      _smapKmlLayers = {};
    }
    _smapUserLayers = {};
    _smapActiveLayerId = null;
    _smapEditingPoint = null;
  }

  /** Load nearby BTS for standalone map */
  async function _loadSmapBts() {
    if (!_smapInstance || !_smapBtsEnabled) return;
    const map = _smapInstance;
    const center = map.getCenter();
    const zoom = map.getZoom();
    const params = _nearbyParams(zoom);

    try {
      const url = `/api/gsm/bts/nearby?lat=${center.lat.toFixed(6)}&lon=${center.lng.toFixed(6)}&radius_deg=${params.radius}&limit=${params.limit}`;
      const resp = await fetch(url);
      const data = await resp.json();
      if (data.status !== "ok" || !data.stations) return;

      // Remove old layer
      if (_smapBtsLayer) { map.removeLayer(_smapBtsLayer); }

      const group = L.layerGroup();
      const defaultRange = { "GSM": 5000, "UMTS": 3000, "LTE": 2000, "5G NR": 1000 };
      const color = "#2563eb";

      for (const s of data.stations) {
        const range = s.range_m || defaultRange[s.radio] || 2000;
        L.circleMarker([s.lat, s.lon], {
          radius: 4,
          fillColor: color,
          color: "#fff",
          weight: 1.2,
          fillOpacity: 0.7,
        }).bindPopup(
          `<b>${s.city || "BTS"}${s.street ? ", " + s.street : ""}</b><br>` +
          `${s.radio ? "Technologia: " + s.radio + "<br>" : ""}` +
          `LAC: ${s.lac || "?"} / CID: ${s.cid || "?"}<br>` +
          `Zasięg: ~${(range/1000).toFixed(1)} km`
        ).addTo(group);
      }
      group.addTo(map);
      _smapBtsLayer = group;
    } catch (e) {
      console.warn("[GSM] Standalone BTS load error:", e);
    }
  }

  /** Toggle overlay on standalone map */
  async function _toggleSmapOverlay(which, show) {
    if (!_smapInstance) return;
    const urlMap = {
      military: "/static/data/poland_military.json",
      airports: "/static/data/poland_airports.json",
      diplomacy: "/static/data/poland_diplomacy.json",
    };

    if (!show) {
      if (_smapOverlays[which]) { _smapInstance.removeLayer(_smapOverlays[which]); }
      return;
    }

    // Load data if not cached
    if (!_smapOverlayData[which]) {
      try {
        const resp = await fetch(urlMap[which]);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        _smapOverlayData[which] = await resp.json();
      } catch (err) {
        _addLog("error", `Nie udało się załadować nakładki: ${err.message}`);
        return;
      }
    }

    // Build layer
    if (!_smapOverlays[which]) {
      const group = L.layerGroup();
      const data = _smapOverlayData[which];

      if (which === "military") {
        for (const item of data) {
          const icon = _OVERLAY_TYPE_ICONS[item.type] || "🪖";
          const color = _OVERLAY_TYPE_COLORS[item.type] || "#b91c1c";
          const divIcon = L.divIcon({
            className: "gsm-overlay-marker",
            html: `<span style="font-size:18px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">${icon}</span>`,
            iconSize: [24, 24], iconAnchor: [12, 12],
          });
          const m = L.marker([item.lat, item.lon], { icon: divIcon, interactive: true });
          m.bindTooltip(
            `<b style="color:${color}">${item.name}</b><br><span class="small">${item.desc || ""}</span>`,
            { direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip" }
          );
          m.on("click", () => _handleOverlayClick(
            { lat: item.lat, lon: item.lon },
            { name: item.name, desc: item.desc || "", type: item.type || "", color },
            _smapInstance
          ));
          m.addTo(group);
        }
      } else if (which === "diplomacy") {
        for (const item of data) {
          const icon = _DIPLOMACY_TYPE_ICONS[item.type] || "🏛️";
          const color = _DIPLOMACY_TYPE_COLORS[item.type] || "#059669";
          const divIcon = L.divIcon({
            className: "gsm-overlay-marker",
            html: `<span style="font-size:16px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">${icon}</span>`,
            iconSize: [22, 22], iconAnchor: [11, 11],
          });
          const m = L.marker([item.lat, item.lon], { icon: divIcon, interactive: true });
          m.bindTooltip(
            `<b style="color:${color}">${item.name}</b><br><span class="small">${item.desc || ""}</span>`,
            { direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip" }
          );
          const countryTag = item.country ? `<span class="small muted">Kraj: ${item.country}</span>` : "";
          m.on("click", () => _handleOverlayClick(
            { lat: item.lat, lon: item.lon },
            { name: item.name, desc: item.desc || "", type: item.type || "", color, extra: countryTag },
            _smapInstance
          ));
          m.addTo(group);
        }
      } else {
        // Airports
        for (const item of data) {
          const divIcon = L.divIcon({
            className: "gsm-overlay-marker",
            html: `<span style="font-size:18px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">✈️</span>`,
            iconSize: [24, 24], iconAnchor: [12, 12],
          });
          const label = item.iata ? `${item.iata}` : "";
          const m = L.marker([item.lat, item.lon], { icon: divIcon, interactive: true });
          m.bindTooltip(
            `<b style="color:#2563eb">${item.name}</b>` +
            (label ? `<br><span class="small" style="color:#6b7280">${label} — ${item.city}</span>` : `<br><span class="small">${item.city}</span>`),
            { direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip" }
          );
          m.on("click", () => _handleOverlayClick(
            { lat: item.lat, lon: item.lon },
            { name: item.name, desc: item.city || "", type: label ? `✈️ ${label}` : "Lotnisko", color: "#2563eb" },
            _smapInstance
          ));
          m.addTo(group);
        }
      }
      _smapOverlays[which] = group;
    }

    _smapOverlays[which].addTo(_smapInstance);
  }

  /** Load KML overlay checkboxes for standalone map */
  async function _loadSmapKmlCheckboxes() {
    const container = QS("#gsm_smap_kml_overlays");
    if (!container) return;

    try {
      const resp = await fetch("/api/gsm/overlays");
      if (!resp.ok) return;
      const data = await resp.json();
      const items = (data && data.overlays) ? data.overlays : [];
      if (!items.length) { container.innerHTML = ""; return; }

      container.innerHTML = items.map(ov => {
        const safeName = String(ov.name || ov.id).replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return `<label class="gsm-lp-item">
          <input type="checkbox" data-smap-kml-id="${ov.id}"> <span style="color:#8b5cf6">&#9679;</span> ${safeName}
        </label>`;
      }).join("");

      container.querySelectorAll("input[data-smap-kml-id]").forEach(cb => {
        cb.onchange = () => _toggleSmapKml(cb.dataset.smapKmlId, cb.checked);
      });
    } catch (e) { /* silent */ }
  }

  /** Toggle KML overlay on standalone map */
  async function _toggleSmapKml(overlayId, show) {
    if (!_smapInstance) return;

    if (!show) {
      if (_smapKmlLayers[overlayId]) { _smapInstance.removeLayer(_smapKmlLayers[overlayId]); }
      return;
    }

    if (!_smapKmlData[overlayId]) {
      try {
        const resp = await fetch(`/api/gsm/overlays/${overlayId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        _smapKmlData[overlayId] = await resp.json();
      } catch (err) {
        _addLog("error", `Nie udało się załadować KML: ${err.message}`);
        return;
      }
    }

    if (!_smapKmlLayers[overlayId]) {
      const group = L.layerGroup();
      const data = _smapKmlData[overlayId];
      const points = data.points || [];
      const lines = data.lines || [];
      const polygons = data.polygons || [];
      const defaultColor = "#8b5cf6";

      for (const pt of points) {
        if (!pt.lat || !pt.lon) continue;
        const c = pt.color || defaultColor;
        L.circleMarker([pt.lat, pt.lon], {
          radius: 5, fillColor: c, color: "#fff", weight: 1, fillOpacity: 0.8,
        }).bindPopup(pt.name ? `<b>${pt.name}</b>${pt.desc ? "<br>" + pt.desc : ""}` : "").addTo(group);
      }
      for (const ln of lines) {
        if (!ln.coords || !ln.coords.length) continue;
        L.polyline(ln.coords.map(c => [c[1], c[0]]), {
          color: ln.color || defaultColor, weight: 2, opacity: 0.8,
        }).addTo(group);
      }
      for (const pg of polygons) {
        if (!pg.coords || !pg.coords.length) continue;
        L.polygon(pg.coords.map(c => [c[1], c[0]]), {
          color: pg.color || defaultColor, fillColor: pg.color || defaultColor, weight: 1, fillOpacity: 0.2,
        }).addTo(group);
      }
      _smapKmlLayers[overlayId] = group;
    }

    _smapKmlLayers[overlayId].addTo(_smapInstance);
  }

  /** Screenshot for standalone map (reuses existing helpers) */
  async function _takeSmapScreenshot() {
    if (!_smapInstance) return;
    const btn = QS("#gsm_smap_screenshot_btn");
    if (btn) btn.disabled = true;

    try {
      const map = _smapInstance;
      const scale = 2;
      const size = map.getSize();
      const w = size.x * scale;
      const h = size.y * scale;

      await _waitForTilesToLoad(map, 3000);

      const out = document.createElement("canvas");
      out.width = w;
      out.height = h;
      const ctx = out.getContext("2d");

      ctx.fillStyle = "#e8e8e8";
      ctx.fillRect(0, 0, w, h);

      // Draw tile images (use getBoundingClientRect for correct positioning)
      const containerRect = map.getContainer().getBoundingClientRect();
      const tilePane = map.getPane("tilePane");
      if (tilePane) {
        const tileImgs = tilePane.querySelectorAll("img.leaflet-tile");
        const tilePromises = [];
        for (const img of tileImgs) {
          if (!img.src) continue;
          const rect = img.getBoundingClientRect();
          const x = (rect.left - containerRect.left) * scale;
          const y = (rect.top - containerRect.top) * scale;
          const tw = rect.width * scale;
          const th = rect.height * scale;
          tilePromises.push(
            _fetchImageBitmap(img.src)
              .then(bmp => ({ bmp, x, y, tw, th }))
              .catch(() => null)
          );
        }
        const tiles = await Promise.all(tilePromises);
        for (const tile of tiles) {
          if (!tile) continue;
          ctx.drawImage(tile.bmp, tile.x, tile.y, tile.tw, tile.th);
          tile.bmp.close();
        }
      }

      // Draw MapLibre GL canvas (for PBF vector tiles)
      const smapContainer = QS("#gsm_smap_container");
      const maplibreCanvas = smapContainer ? smapContainer.querySelector(".maplibregl-canvas, .mapboxgl-canvas") : null;
      if (maplibreCanvas) {
        try {
          const mlRect = maplibreCanvas.getBoundingClientRect();
          ctx.drawImage(maplibreCanvas,
            (mlRect.left - containerRect.left) * scale,
            (mlRect.top - containerRect.top) * scale,
            mlRect.width * scale, mlRect.height * scale);
        } catch (e) {
          console.warn("[GSM] Standalone MapLibre canvas capture failed:", e);
        }
      }

      // Draw overlay pane canvases (circleMarkers, polylines)
      const overlayPane = map.getPane("overlayPane");
      if (overlayPane) {
        const canvases = overlayPane.querySelectorAll("canvas");
        for (const c of canvases) {
          try {
            const cRect = c.getBoundingClientRect();
            ctx.drawImage(c,
              (cRect.left - containerRect.left) * scale,
              (cRect.top - containerRect.top) * scale,
              cRect.width * scale, cRect.height * scale);
          } catch (_) {}
        }
      }

      // Draw marker panes
      _drawPaneMarkers(ctx, map, "shadowPane", scale);
      _drawPaneMarkers(ctx, map, "markerPane", scale);

      // Watermark
      const activeRadio = QS('input[name="gsm_smap_layer"]:checked');
      const activeItem = activeRadio ? activeRadio.closest(".gsm-lp-item") : null;
      const layerLabel = activeItem ? activeItem.textContent.trim() : "Mapa";
      const extraParts = [layerLabel, "© OpenStreetMap contributors"];
      const final = _drawWatermark(out, extraParts);

      // Download
      const now = new Date();
      final.toBlob((blob) => {
        if (!blob) return;
        const ts = now.toISOString().slice(0, 19).replace(/[T:]/g, "-");
        const filename = `mapa_${ts}.png`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        _addLog("info", `Zapisano zrzut mapy: ${filename}`);
      }, "image/png");
    } catch (err) {
      console.error("[GSM] Standalone map screenshot error:", err);
      _addLog("error", "Nie udało się zrobić zrzutu mapy: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ── Map edit mode ─────────────────────────────────────── */

  let _smapEditMode = false;
  let _smapUserLayers = {};       // { overlayId: { data, leafletGroup, markers[] } }
  let _smapActiveLayerId = null;  // currently selected user layer for editing
  let _smapEditingPoint = null;   // { layerId, pointIndex } — point being edited

  /* ── Polygon drawing state ────────────────────────────── */
  let _smapDrawingPolygon = false;
  let _smapPolygonPoints = [];       // [{lat, lng}]
  let _smapPolygonMarkers = [];      // L.circleMarker for each vertex
  let _smapPolygonPolyline = null;   // L.polyline showing edges
  let _smapPolygonGuideLine = null;  // L.polyline from last point to cursor
  let _smapContextMenu = null;       // DOM element for context menu

  function _toggleSmapEditMode() {
    _smapEditMode = !_smapEditMode;
    const btn = QS("#gsm_smap_edit_btn");
    const indicator = QS("#gsm_smap_edit_indicator");
    const container = QS("#gsm_smap_container");

    if (btn) btn.style.background = _smapEditMode ? "var(--accent,#4a6cf7)" : "";
    if (btn) btn.style.borderRadius = _smapEditMode ? "8px" : "";
    if (indicator) indicator.style.display = _smapEditMode ? "" : "none";
    if (container) container.style.cursor = _smapEditMode ? "crosshair" : "";

    if (_smapEditMode && _smapInstance) {
      _smapInstance.on("click", _smapOnMapClick);
    } else if (_smapInstance) {
      _smapInstance.off("click", _smapOnMapClick);
      _smapHideContextMenu();
      if (_smapDrawingPolygon) _smapCancelPolygonDraw();
    }
  }

  function _smapOnMapClick(e) {
    if (!_smapEditMode || !_smapInstance) return;
    if (!_smapActiveLayerId) {
      // Auto-select the only user layer, or auto-create one
      const userLayerIds = Object.keys(_smapUserLayers);
      if (userLayerIds.length === 1) {
        _smapActiveLayerId = userLayerIds[0];
        _smapRefreshUserLayersList();
      } else if (userLayerIds.length === 0) {
        _smapAutoCreateLayerThenClick(e);
        return;
      } else {
        _smapShowToast("Wybierz warstwę w panelu po lewej przed dodaniem elementów");
        return;
      }
    }

    // If currently drawing a polygon, add vertex
    if (_smapDrawingPolygon) {
      _smapPolygonAddVertex(e.latlng);
      return;
    }

    // Show context menu with options
    _smapShowContextMenu(e);
  }

  /* ── Context menu for edit mode (Leaflet popup) ──────────── */

  function _smapShowContextMenu(e) {
    _smapHideContextMenu();
    const latlng = e.latlng;

    const html = `<div style="min-width:140px;margin:-4px -8px;font-size:13px">
      <div class="gsm-ctx-item" data-action="point" style="padding:7px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;border-radius:6px 6px 0 0">
        <span style="font-size:15px">\ud83d\udccd</span><span>Dodaj punkt</span>
      </div>
      <div class="gsm-ctx-item" data-action="polygon" style="padding:7px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;border-radius:0 0 6px 6px">
        <span style="font-size:15px">\u2b21</span><span>Zr\u00f3b obrys</span>
      </div>
    </div>`;

    const popup = L.popup({ closeButton: false, className: "gsm-edit-ctx-popup", offset: [0, 0], autoPan: false })
      .setLatLng(latlng)
      .setContent(html)
      .openOn(_smapInstance);

    _smapContextMenu = popup;

    // Bind actions after popup opens
    setTimeout(() => {
      const popupEl = popup.getElement();
      if (!popupEl) return;
      popupEl.querySelectorAll(".gsm-ctx-item").forEach(el => {
        el.onmouseenter = () => { el.style.background = "rgba(74,108,247,.1)"; };
        el.onmouseleave = () => { el.style.background = ""; };
        el.onclick = (ev) => {
          ev.stopPropagation();
          L.DomEvent.stopPropagation(ev);
          const action = el.getAttribute("data-action");
          _smapHideContextMenu();
          if (action === "point") {
            _openLocationDialog({ type: "point", isNew: true, layerId: _smapActiveLayerId, lat: latlng.lat, lon: latlng.lng, name: "", desc: "", color: "#e63946", icon: "" });
          } else if (action === "polygon") {
            _smapStartPolygonDraw(latlng);
          }
        };
      });
    }, 50);
  }

  function _smapHideContextMenu() {
    if (_smapContextMenu) {
      try { _smapInstance.closePopup(_smapContextMenu); } catch (_) {}
      _smapContextMenu = null;
    }
  }

  /** Auto-create a default layer then re-fire the click */
  async function _smapAutoCreateLayerThenClick(originalEvent) {
    try {
      const resp = await fetch("/api/gsm/overlays/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Moja warstwa" }),
      });
      const data = await resp.json();
      if (data.status === "ok") {
        _smapUserLayers[data.id] = {
          data: { name: data.name, points: [], polygons: [], user_layer: true },
          leafletGroup: null, markers: [],
        };
        _smapActiveLayerId = data.id;
        _smapRefreshUserLayersList();
        _smapShowToast("Utworzono warstwę: " + data.name);
        // Re-process the original click now that a layer is active
        _smapOnMapClick(originalEvent);
      }
    } catch (err) {
      _smapShowToast("Nie udało się utworzyć warstwy");
    }
  }

  /** Show a brief toast message on the map */
  function _smapShowToast(msg) {
    const container = QS("#gsm_smap_container");
    if (!container) return;
    // Remove existing toast
    const old = container.querySelector(".gsm-smap-toast");
    if (old) old.remove();
    const toast = document.createElement("div");
    toast.className = "gsm-smap-toast";
    toast.textContent = msg;
    toast.style.cssText = "position:absolute;top:12px;left:50%;transform:translateX(-50%);z-index:9200;background:var(--card-bg,#fff);color:var(--text,#222);border:1px solid var(--border,#ddd);border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.15);padding:8px 18px;font-size:13px;font-weight:500;pointer-events:none;opacity:1;transition:opacity .4s";
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; }, 2500);
    setTimeout(() => { toast.remove(); }, 3000);
  }

  /* ── Polygon drawing ─────────────────────────────────────── */

  function _smapStartPolygonDraw(startLatLng) {
    _smapDrawingPolygon = true;
    _smapPolygonPoints = [];
    _smapPolygonMarkers = [];
    _smapPolygonPolyline = null;
    _smapPolygonGuideLine = null;
    const indicator = QS("#gsm_smap_edit_indicator");
    if (indicator) indicator.textContent = "Rysowanie obrysu \u2014 kliknij aby doda\u0107 wierzcho\u0142ki, kliknij pierwszy punkt aby zamkn\u0105\u0107";
    const container = QS("#gsm_smap_container");
    if (container) container.style.cursor = "crosshair";
    _smapPolygonGuideLine = L.polyline([], { color: "#4a6cf7", weight: 2, dashArray: "6,4", opacity: 0.7 }).addTo(_smapInstance);
    _smapInstance.on("mousemove", _smapPolygonMouseMove);
    document.addEventListener("keydown", _smapPolygonEscHandler);
    _smapPolygonAddVertex(startLatLng);
  }

  function _smapPolygonMouseMove(e) {
    if (!_smapDrawingPolygon || !_smapPolygonGuideLine || !_smapPolygonPoints.length) return;
    const lastPt = _smapPolygonPoints[_smapPolygonPoints.length - 1];
    _smapPolygonGuideLine.setLatLngs([[lastPt.lat, lastPt.lng], [e.latlng.lat, e.latlng.lng]]);
  }

  function _smapPolygonEscHandler(e) { if (e.key === "Escape") _smapCancelPolygonDraw(); }

  function _smapPolygonAddVertex(latlng) {
    if (_smapPolygonPoints.length >= 3) {
      const firstPt = _smapPolygonPoints[0];
      const firstPixel = _smapInstance.latLngToContainerPoint(L.latLng(firstPt.lat, firstPt.lng));
      const clickPixel = _smapInstance.latLngToContainerPoint(latlng);
      const dist = Math.sqrt(Math.pow(firstPixel.x - clickPixel.x, 2) + Math.pow(firstPixel.y - clickPixel.y, 2));
      if (dist < 15) { _smapFinishPolygonDraw(); return; }
    }
    _smapPolygonPoints.push({ lat: latlng.lat, lng: latlng.lng });
    const isFirst = _smapPolygonPoints.length === 1;
    const marker = L.circleMarker([latlng.lat, latlng.lng], {
      radius: isFirst ? 8 : 5, fillColor: isFirst ? "#22c55e" : "#4a6cf7",
      color: "#fff", weight: 2, fillOpacity: 0.9, interactive: true,
    }).addTo(_smapInstance);
    if (isFirst) {
      marker.bindTooltip("Kliknij tutaj aby zamkn\u0105\u0107 obrys", { direction: "top", offset: [0, -10], className: "gsm-overlay-tooltip" });
      marker.on("click", (e) => { L.DomEvent.stopPropagation(e); if (_smapPolygonPoints.length >= 3) _smapFinishPolygonDraw(); });
    }
    _smapPolygonMarkers.push(marker);
    const latLngs = _smapPolygonPoints.map(p => [p.lat, p.lng]);
    if (_smapPolygonPolyline) { _smapPolygonPolyline.setLatLngs(latLngs); }
    else { _smapPolygonPolyline = L.polyline(latLngs, { color: "#4a6cf7", weight: 2, opacity: 0.8 }).addTo(_smapInstance); }
  }

  function _smapFinishPolygonDraw() {
    _smapInstance.off("mousemove", _smapPolygonMouseMove);
    document.removeEventListener("keydown", _smapPolygonEscHandler);
    if (_smapPolygonGuideLine) { _smapInstance.removeLayer(_smapPolygonGuideLine); _smapPolygonGuideLine = null; }
    if (_smapPolygonPolyline) { _smapInstance.removeLayer(_smapPolygonPolyline); _smapPolygonPolyline = null; }
    for (const m of _smapPolygonMarkers) _smapInstance.removeLayer(m);
    _smapPolygonMarkers = [];
    const indicator = QS("#gsm_smap_edit_indicator");
    if (indicator) indicator.textContent = "Tryb edycji";
    const coords = _smapPolygonPoints.map(p => [p.lat, p.lng]);
    _smapDrawingPolygon = false;
    _openLocationDialog({ type: "polygon", isNew: true, layerId: _smapActiveLayerId, coords, name: "", desc: "", fillColor: "#4a6cf7", icon: "" });
  }

  function _smapCancelPolygonDraw() {
    _smapInstance.off("mousemove", _smapPolygonMouseMove);
    document.removeEventListener("keydown", _smapPolygonEscHandler);
    if (_smapPolygonGuideLine) { _smapInstance.removeLayer(_smapPolygonGuideLine); _smapPolygonGuideLine = null; }
    if (_smapPolygonPolyline) { _smapInstance.removeLayer(_smapPolygonPolyline); _smapPolygonPolyline = null; }
    for (const m of _smapPolygonMarkers) _smapInstance.removeLayer(m);
    _smapPolygonMarkers = []; _smapPolygonPoints = []; _smapDrawingPolygon = false;
    const indicator = QS("#gsm_smap_edit_indicator");
    if (indicator) indicator.textContent = "Tryb edycji";
    _addLog("info", "Anulowano rysowanie obrysu");
  }

  /* ── Polygon CRUD ────────────────────────────────────────── */

  function _smapAddPolygon(layerId, polygon) {
    const layer = _smapUserLayers[layerId];
    if (!layer) return;
    if (!layer.data.polygons) layer.data.polygons = [];
    layer.data.polygons.push(polygon);
    _smapRebuildLayerMarkers(layerId); _smapSaveLayer(layerId);
  }

  function _smapUpdatePolygon(layerId, idx, polygon, targetLayerId) {
    const layer = _smapUserLayers[layerId];
    if (!layer || !layer.data.polygons) return;
    if (targetLayerId && targetLayerId !== layerId) {
      layer.data.polygons.splice(idx, 1);
      _smapRebuildLayerMarkers(layerId); _smapSaveLayer(layerId);
      _smapAddPolygon(targetLayerId, polygon);
    } else {
      layer.data.polygons[idx] = polygon;
      _smapRebuildLayerMarkers(layerId); _smapSaveLayer(layerId);
    }
  }

  function _smapDeletePolygon(layerId, idx) {
    const layer = _smapUserLayers[layerId];
    if (!layer || !layer.data.polygons) return;
    layer.data.polygons.splice(idx, 1);
    _smapRebuildLayerMarkers(layerId); _smapSaveLayer(layerId);
  }

  // --- Icon preview helper: handles both path-based and raw SVG icons ---
  function _smapUpdateIconPreview(iconValue) {
    const preview = QS("#gsm_loc_icon_preview");
    if (!preview) return;
    if (!iconValue) {
      preview.innerHTML = '<span class="muted small">—</span>';
      return;
    }
    if (iconValue.startsWith("/static/")) {
      preview.innerHTML = `<img src="${iconValue}" style="width:32px;height:32px;object-fit:contain">`;
    } else {
      preview.innerHTML = iconValue;
      const svg = preview.querySelector("svg");
      if (svg) { svg.style.width = "28px"; svg.style.height = "28px"; }
    }
  }

  // --- Category label translations ---
  const _iconCategoryLabels = {
    embassy: "Ambasada",
    fire: "Straż pożarna",
    intelligence: "Wywiad",
    justice: "Wymiar sprawiedliwości",
    medical: "Medyczny",
    military: "Wojskowy",
    national_security: "Bezpieczeństwo",
    police: "Policja",
  };

  // --- Icon picker: fetch categories from API and render grid ---
  let _mapIconsCache = null;
  async function _smapLoadIconPicker() {
    const body = QS("#gsm_loc_icon_picker_body");
    if (!body) return;
    if (_mapIconsCache) {
      _smapRenderIconPicker(_mapIconsCache);
      return;
    }
    body.innerHTML = '<span class="muted small">Ładowanie ikon…</span>';
    try {
      const resp = await fetch("/api/gsm/map-icons");
      const data = await resp.json();
      if (data.status === "ok" && data.categories) {
        _mapIconsCache = data.categories;
        _smapRenderIconPicker(data.categories);
      } else {
        body.innerHTML = '<span class="muted small">Brak ikon</span>';
      }
    } catch (e) {
      body.innerHTML = '<span class="muted small">Błąd ładowania ikon</span>';
    }
  }

  function _smapRenderIconPicker(categories) {
    const body = QS("#gsm_loc_icon_picker_body");
    if (!body) return;
    body.innerHTML = "";
    for (const cat of categories) {
      const label = _iconCategoryLabels[cat.category] || cat.category;
      const header = document.createElement("div");
      header.style.cssText = "font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:6px 0 3px;color:var(--text-secondary,#666)";
      header.textContent = label;
      body.appendChild(header);

      const grid = document.createElement("div");
      grid.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px";
      for (const ic of cat.icons) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.title = ic.name.replace(/_/g, " ");
        btn.style.cssText = "width:38px;height:38px;border:1px solid var(--border,#ddd);border-radius:6px;background:var(--bg-card,#fff);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:3px;transition:border-color .15s";
        btn.innerHTML = `<img src="${ic.path}" style="width:28px;height:28px;object-fit:contain">`;
        btn.onmouseenter = () => { btn.style.borderColor = "var(--primary,#4361ee)"; };
        btn.onmouseleave = () => { btn.style.borderColor = "var(--border,#ddd)"; };
        btn.onclick = () => {
          const iconData = QS("#gsm_loc_icon_data");
          const iconClearBtn = QS("#gsm_loc_icon_clear_btn");
          const picker = QS("#gsm_loc_icon_picker");
          if (iconData) iconData.value = ic.path;
          _smapUpdateIconPreview(ic.path);
          if (iconClearBtn) iconClearBtn.style.display = "";
          if (picker) picker.style.display = "none";
        };
        grid.appendChild(btn);
      }
      body.appendChild(grid);
    }
  }

  /* ── Unified location dialog (point & polygon) ──────────── */
  function _openLocationDialog(opts) {
    const dialog = QS("#gsm_location_dialog");
    if (!dialog) return;

    const isPoint = opts.type === "point";

    // --- Element refs ---
    const title = QS("#gsm_loc_title");
    const typeLabel = QS("#gsm_loc_type_label");
    const nameEl = QS("#gsm_loc_name");
    const descEl = QS("#gsm_loc_desc");
    const latEl = QS("#gsm_loc_lat");
    const lonEl = QS("#gsm_loc_lon");
    const pointSection = QS("#gsm_loc_point_section");
    const polygonSection = QS("#gsm_loc_polygon_section");
    const vertexInfo = QS("#gsm_loc_vertex_count");
    const colorEl = QS("#gsm_loc_color");
    const colorLabel = QS("#gsm_loc_color_label");
    const layerSel = QS("#gsm_loc_layer_select");
    const delBtn = QS("#gsm_loc_delete_btn");
    const iconData = QS("#gsm_loc_icon_data");
    const iconFile = QS("#gsm_loc_icon_file");
    const iconUploadBtn = QS("#gsm_loc_icon_upload_btn");
    const iconClearBtn = QS("#gsm_loc_icon_clear_btn");
    const iconPickBtn = QS("#gsm_loc_icon_pick_btn");
    const iconPicker = QS("#gsm_loc_icon_picker");

    // --- Title & type badge ---
    if (title) title.textContent = opts.isNew ? "Nowa Lokalizacja" : "Edycja Lokalizacji";
    if (typeLabel) {
      typeLabel.textContent = isPoint ? "Punkt" : "Obrys";
      typeLabel.style.background = isPoint ? "var(--accent,#4a6cf7)" : "#059669";
    }

    // --- Show/hide type-specific sections ---
    if (pointSection) pointSection.style.display = isPoint ? "" : "none";
    if (polygonSection) polygonSection.style.display = isPoint ? "none" : "";
    if (colorLabel) colorLabel.textContent = isPoint ? "Kolor" : "Kolor wypełnienia";

    // --- Populate common fields ---
    if (nameEl) nameEl.value = opts.name || "";
    if (descEl) descEl.value = opts.desc || "";
    const currentColor = opts.fillColor || opts.color || (isPoint ? "#e63946" : "#4a6cf7");
    if (colorEl) colorEl.value = currentColor;

    if (isPoint) {
      if (latEl) latEl.value = (opts.lat != null) ? opts.lat.toFixed(6) : "";
      if (lonEl) lonEl.value = (opts.lon != null) ? opts.lon.toFixed(6) : "";
    }
    if (!isPoint && vertexInfo) {
      vertexInfo.textContent = `${(opts.coords || []).length} wierzchołków`;
    }

    if (delBtn) {
      delBtn.style.display = opts.isNew ? "none" : "";
      delBtn.textContent = isPoint ? "Usuń punkt" : "Usuń obrys";
    }

    // --- Icon state ---
    const iconVal = opts.icon || "";
    if (iconData) iconData.value = iconVal;
    _smapUpdateIconPreview(iconVal);
    if (iconClearBtn) iconClearBtn.style.display = iconVal ? "" : "none";
    if (iconPicker) iconPicker.style.display = "none";

    if (iconPickBtn) {
      iconPickBtn.onclick = async () => {
        if (!iconPicker) return;
        const wasOpen = iconPicker.style.display !== "none";
        iconPicker.style.display = wasOpen ? "none" : "";
        if (!wasOpen) await _smapLoadIconPicker();
      };
    }

    if (iconUploadBtn && iconFile) {
      iconUploadBtn.onclick = () => iconFile.click();
      iconFile.value = "";
      iconFile.onchange = () => {
        const file = iconFile.files && iconFile.files[0];
        if (!file) return;
        if (!file.name.toLowerCase().endsWith(".svg") && file.type !== "image/svg+xml") {
          _addLog("warn", "Tylko pliki SVG są obsługiwane"); return;
        }
        if (file.size > 50000) {
          _addLog("warn", "Plik SVG zbyt duży (max 50 KB)"); return;
        }
        const reader = new FileReader();
        reader.onload = (ev) => {
          let svgText = ev.target.result;
          svgText = svgText.replace(/<script[\s\S]*?<\/script>/gi, "");
          if (iconData) iconData.value = svgText;
          _smapUpdateIconPreview(svgText);
          if (iconClearBtn) iconClearBtn.style.display = "";
          if (iconPicker) iconPicker.style.display = "none";
        };
        reader.readAsText(file);
      };
    }
    if (iconClearBtn) {
      iconClearBtn.onclick = () => {
        if (iconData) iconData.value = "";
        _smapUpdateIconPreview("");
        iconClearBtn.style.display = "none";
        if (iconPicker) iconPicker.style.display = "none";
      };
    }

    // --- Layer dropdown ---
    if (layerSel) {
      layerSel.innerHTML = "";
      for (const [id, layer] of Object.entries(_smapUserLayers)) {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = layer.data.name;
        if (id === opts.layerId) opt.selected = true;
        layerSel.appendChild(opt);
      }
    }

    if (isPoint) {
      _smapEditingPoint = opts.isNew ? null : { layerId: opts.layerId, pointIndex: opts.pointIndex };
    }

    // --- Submit ---
    const form = dialog.querySelector("form");
    const submitHandler = (e) => {
      e.preventDefault();
      form.removeEventListener("submit", submitHandler);
      const iconValue = iconData ? iconData.value.trim() : "";
      const targetLayer = layerSel ? layerSel.value : opts.layerId;

      if (isPoint) {
        const point = {
          name: nameEl ? nameEl.value.trim() : "",
          desc: descEl ? descEl.value.trim() : "",
          lat: parseFloat(latEl ? latEl.value : opts.lat),
          lon: parseFloat(lonEl ? lonEl.value : opts.lon),
          color: colorEl ? colorEl.value : "#e63946",
          icon: iconValue,
        };
        if (opts.isNew) _smapAddPoint(targetLayer, point);
        else _smapUpdatePoint(opts.layerId, opts.pointIndex, point, targetLayer);
      } else {
        const polygon = {
          name: nameEl ? nameEl.value.trim() : "",
          desc: descEl ? descEl.value.trim() : "",
          coords: opts.coords,
          fillColor: colorEl ? colorEl.value : "#4a6cf7",
          icon: iconValue,
        };
        if (opts.isNew) _smapAddPolygon(targetLayer, polygon);
        else _smapUpdatePolygon(opts.layerId, opts.polygonIndex, polygon, targetLayer);
      }
      dialog.close();
    };
    form.addEventListener("submit", submitHandler);

    const cancelBtn = QS("#gsm_loc_cancel_btn");
    const cancelHandler = () => {
      cancelBtn.removeEventListener("click", cancelHandler);
      form.removeEventListener("submit", submitHandler);
      dialog.close();
    };
    if (cancelBtn) cancelBtn.addEventListener("click", cancelHandler);

    if (delBtn && !opts.isNew) {
      const delHandler = () => {
        delBtn.removeEventListener("click", delHandler);
        form.removeEventListener("submit", submitHandler);
        if (isPoint) _smapDeletePoint(opts.layerId, opts.pointIndex);
        else _smapDeletePolygon(opts.layerId, opts.polygonIndex);
        dialog.close();
      };
      delBtn.addEventListener("click", delHandler);
    }

    dialog.showModal();
  }

  function _smapAddPoint(layerId, point) {
    const layer = _smapUserLayers[layerId];
    if (!layer) return;
    layer.data.points.push(point);
    _smapRebuildLayerMarkers(layerId);
    _smapSaveLayer(layerId);
  }

  function _smapUpdatePoint(layerId, idx, point, targetLayerId) {
    const layer = _smapUserLayers[layerId];
    if (!layer) return;

    if (targetLayerId !== layerId) {
      // Move to different layer
      layer.data.points.splice(idx, 1);
      _smapRebuildLayerMarkers(layerId);
      _smapSaveLayer(layerId);
      _smapAddPoint(targetLayerId, point);
    } else {
      layer.data.points[idx] = point;
      _smapRebuildLayerMarkers(layerId);
      _smapSaveLayer(layerId);
    }
  }

  function _smapDeletePoint(layerId, idx) {
    const layer = _smapUserLayers[layerId];
    if (!layer) return;
    layer.data.points.splice(idx, 1);
    _smapRebuildLayerMarkers(layerId);
    _smapSaveLayer(layerId);
  }

  function _smapRebuildLayerMarkers(layerId) {
    const layer = _smapUserLayers[layerId];
    if (!layer || !_smapInstance) return;

    // Remove old group
    if (layer.leafletGroup) {
      _smapInstance.removeLayer(layer.leafletGroup);
    }

    const group = L.layerGroup();
    layer.markers = [];

    layer.data.points.forEach((pt, idx) => {
      const color = pt.color || "#e63946";
      let marker;

      if (pt.icon) {
        // Icon marker — either a static path or raw SVG, shown on white circle with border
        let innerHtml;
        if (pt.icon.startsWith("/static/")) {
          innerHtml = `<img src="${pt.icon}" style="width:22px;height:22px;object-fit:contain">`;
        } else {
          innerHtml = pt.icon.replace(/<svg/,
            '<svg style="width:22px;height:22px"');
        }
        const iconHtml = `<div style="width:32px;height:32px;background:#fff;border:2px solid ${pt.color || '#555'};border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 4px rgba(0,0,0,.3)">${innerHtml}</div>`;
        const divIcon = L.divIcon({
          className: "gsm-user-point-icon",
          html: iconHtml,
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });
        marker = L.marker([pt.lat, pt.lon], { icon: divIcon, interactive: true });
      } else {
        // Default circle marker
        marker = L.circleMarker([pt.lat, pt.lon], {
          radius: 7,
          fillColor: color,
          color: "#fff",
          weight: 2,
          fillOpacity: 0.9,
        });
      }

      marker.bindTooltip(
        `<b style="color:${color}">${pt.name || "Punkt"}</b>${pt.desc ? "<br><span class='small'>" + pt.desc + "</span>" : ""}`,
        { direction: "top", offset: [0, pt.icon ? -16 : -8], className: "gsm-overlay-tooltip" }
      );

      marker.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        if (_smapEditMode) {
          _openLocationDialog({
            type: "point", isNew: false,
            layerId: layerId, pointIndex: idx,
            lat: pt.lat, lon: pt.lon,
            name: pt.name, desc: pt.desc,
            color: pt.color || "#e63946",
            icon: pt.icon || "",
          });
        } else {
          _handleOverlayClick(
            { lat: pt.lat, lon: pt.lon },
            { name: pt.name || "Punkt", desc: pt.desc || "", color, layer: layer.data.name || layerId },
            _smapInstance
          );
        }
      });

      marker.addTo(group);
      layer.markers.push(marker);
    });

    // Render polygons
    const polygons = layer.data.polygons || [];
    polygons.forEach((pg, idx) => {
      const fillColor = pg.fillColor || "#4a6cf7";
      const poly = L.polygon(pg.coords, { color: fillColor, fillColor, weight: 2, fillOpacity: 0.3, interactive: true });
      poly.bindTooltip(
        `<b style="color:${fillColor}">${pg.name || "Obrys"}</b>${pg.desc ? "<br><span class='small'>" + pg.desc + "</span>" : ""}`,
        { direction: "center", className: "gsm-overlay-tooltip" }
      );
      poly.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        if (_smapEditMode) {
          _openLocationDialog({ type: "polygon", isNew: false, layerId, polygonIndex: idx, coords: pg.coords, name: pg.name || "", desc: pg.desc || "", fillColor, icon: pg.icon || "" });
        } else {
          const center = poly.getBounds().getCenter();
          _handleOverlayClick(
            { lat: center.lat, lon: center.lng },
            { name: pg.name || "Obrys", desc: pg.desc || "", color: fillColor, layer: layer.data.name || layerId, extra: `<span class="small muted">Wierzchołki: ${pg.coords.length}</span>` },
            _smapInstance
          );
        }
      });
      poly.addTo(group);
    });

    group.addTo(_smapInstance);
    layer.leafletGroup = group;

    // Update layer panel count
    _smapRefreshUserLayersList();
  }

  async function _smapSaveLayer(layerId) {
    const layer = _smapUserLayers[layerId];
    if (!layer) return;
    try {
      await fetch(`/api/gsm/overlays/${layerId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: layer.data.name,
          points: layer.data.points,
          polygons: layer.data.polygons || [],
        }),
      });
    } catch (e) {
      _addLog("error", "Nie udało się zapisać warstwy: " + e.message);
    }
  }

  /** Load user layers list and render checkboxes */
  async function _smapLoadUserLayers() {
    try {
      const resp = await fetch("/api/gsm/overlays");
      if (!resp.ok) return;
      const data = await resp.json();
      const items = (data && data.overlays) ? data.overlays : [];

      // Load full data for user layers (or all KML layers that can be shown)
      for (const ov of items) {
        if (_smapUserLayers[ov.id]) continue; // already loaded
        try {
          const r = await fetch(`/api/gsm/overlays/${ov.id}`);
          const d = await r.json();
          if (d.status === "ok") {
            _smapUserLayers[ov.id] = {
              data: { name: d.name, points: d.points || [], polygons: d.polygons || [], user_layer: d.user_layer || false },
              leafletGroup: null,
              markers: [],
            };
          }
        } catch (_) {}
      }
      _smapRefreshUserLayersList();
    } catch (e) {
      console.warn("[GSM] Failed to load user layers:", e);
    }
  }

  function _smapRefreshUserLayersList() {
    const container = QS("#gsm_smap_user_layers");
    if (!container) return;

    const entries = Object.entries(_smapUserLayers);
    if (!entries.length) {
      container.innerHTML = '<span class="small muted" style="padding:4px 0;display:block">Brak warstw. Kliknij "+ Nowa".</span>';
      return;
    }

    container.innerHTML = entries.map(([id, layer]) => {
      const isActive = _smapActiveLayerId === id;
      const ptCount = layer.data.points.length;
      const pgCount = (layer.data.polygons || []).length;
      const count = pgCount > 0 ? `${ptCount}p, ${pgCount}o` : ptCount;
      const isVisible = layer.leafletGroup && _smapInstance && _smapInstance.hasLayer(layer.leafletGroup);
      const safeName = String(layer.data.name).replace(/</g, "&lt;");
      return `<div class="gsm-lp-item" style="display:flex;align-items:center;gap:4px;padding:2px 0${isActive ? ";background:rgba(74,108,247,.08);border-radius:6px" : ""}">
        <input type="checkbox" data-user-layer-id="${id}"${isVisible ? " checked" : ""} style="margin:0">
        <span class="small" style="flex:1;cursor:pointer;font-weight:${isActive ? 600 : 400}" data-select-layer="${id}">${safeName} <span class="muted">(${count})</span></span>
        <button class="btn mini" data-export-layer="${id}" title="Eksport KML" style="font-size:10px;padding:0 4px">KML</button>
        <button class="btn mini danger" data-delete-layer="${id}" title="Usuń warstwę" style="font-size:10px;padding:0 4px">&times;</button>
      </div>`;
    }).join("");

    // Bind events
    container.querySelectorAll("input[data-user-layer-id]").forEach(cb => {
      cb.onchange = () => {
        const id = cb.dataset.userLayerId;
        if (cb.checked) {
          _smapRebuildLayerMarkers(id);
        } else {
          const layer = _smapUserLayers[id];
          if (layer && layer.leafletGroup && _smapInstance) {
            _smapInstance.removeLayer(layer.leafletGroup);
          }
        }
      };
    });

    container.querySelectorAll("[data-select-layer]").forEach(el => {
      el.onclick = () => {
        _smapActiveLayerId = el.dataset.selectLayer;
        _smapRefreshUserLayersList();
      };
    });

    container.querySelectorAll("[data-export-layer]").forEach(el => {
      el.onclick = () => {
        const id = el.dataset.exportLayer;
        window.open(`/api/gsm/overlays/${id}/export/kml`, "_blank");
      };
    });

    container.querySelectorAll("[data-delete-layer]").forEach(el => {
      el.onclick = async () => {
        const id = el.dataset.deleteLayer;
        if (!confirm("Usunąć warstwę?")) return;
        const layer = _smapUserLayers[id];
        if (layer && layer.leafletGroup && _smapInstance) {
          _smapInstance.removeLayer(layer.leafletGroup);
        }
        delete _smapUserLayers[id];
        if (_smapActiveLayerId === id) _smapActiveLayerId = null;
        try { await fetch(`/api/gsm/overlays/${id}`, { method: "DELETE" }); } catch (_) {}
        _smapRefreshUserLayersList();
      };
    });
  }

  async function _smapCreateLayer() {
    const dialog = QS("#gsm_layer_dialog");
    if (!dialog) return;

    const nameInput = QS("#gsm_layer_name");
    if (nameInput) nameInput.value = "";

    const form = dialog.querySelector("form");
    const submitHandler = async (e) => {
      e.preventDefault();
      form.removeEventListener("submit", submitHandler);
      const name = nameInput ? nameInput.value.trim() : "";
      if (!name) { dialog.close(); return; }

      try {
        const resp = await fetch("/api/gsm/overlays/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        const data = await resp.json();
        if (data.status === "ok") {
          _smapUserLayers[data.id] = {
            data: { name: data.name, points: [], polygons: [], user_layer: true },
            leafletGroup: null,
            markers: [],
          };
          _smapActiveLayerId = data.id;
          _smapRefreshUserLayersList();
          _addLog("info", `Utworzono warstwę: ${data.name}`);
        }
      } catch (err) {
        _addLog("error", "Nie udało się utworzyć warstwy: " + err.message);
      }
      dialog.close();
    };
    form.addEventListener("submit", submitHandler);

    const cancelBtn = QS("#gsm_layer_cancel_btn");
    const cancelHandler = () => {
      cancelBtn.removeEventListener("click", cancelHandler);
      form.removeEventListener("submit", submitHandler);
      dialog.close();
    };
    if (cancelBtn) cancelBtn.addEventListener("click", cancelHandler);

    dialog.showModal();
  }

  /* ── bindings ───────────────────────────────────────────── */
  function _bind() {
    const fileInput = QS("#gsm_file_input");
    const uploadBtn = QS("#gsm_add_file_toolbar_btn");

    if (uploadBtn) {
      uploadBtn.onclick = () => { if (fileInput) fileInput.click(); };
    }

    // Standalone map button
    const smapBtn = QS("#gsm_standalone_map_btn");
    if (smapBtn) {
      smapBtn.onclick = () => _openStandaloneMap();
    }
    if (fileInput) {
      fileInput.onchange = () => {
        if (fileInput.files && fileInput.files.length > 0) {
          _smartImport(fileInput.files);
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

    // (empty state has no button — upload via toolbar icon only)

    // Columns manager button
    const colsBtn = QS("#gsm_columns_btn");
    if (colsBtn) {
      colsBtn.onclick = () => _openColumnsPanel(colsBtn);
    }

    // Records panel resize handle
    const resizeHandle = QS("#gsm_records_resize");
    if (resizeHandle) {
      let startY = 0, startH = 0, wrap = null;
      resizeHandle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        wrap = resizeHandle.parentElement;
        startY = e.clientY;
        startH = wrap.offsetHeight;
        const onMove = (ev) => {
          const newH = Math.max(100, startH + (ev.clientY - startY));
          wrap.style.height = newH + "px";
        };
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    }

    // Graph card 2D resize handle (bottom-right corner)
    const graphResize = QS("#gsm_graph_resize");
    if (graphResize) {
      graphResize.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const card = QS("#gsm_graph_card");
        if (!card) return;
        const startX = e.clientX, startY = e.clientY;
        const startW = card.offsetWidth, startH = card.offsetHeight;
        const onMove = (ev) => {
          const newW = Math.max(320, startW + (ev.clientX - startX));
          const newH = Math.max(200, startH + (ev.clientY - startY));
          card.style.width = newW + "px";
          card.style.maxWidth = newW + "px";
          card.style.height = newH + "px";
          card.dataset.userResized = "1";
        };
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    }

    // Map card 2D resize handle (bottom-right corner)
    const mapResize = QS("#gsm_map_resize");
    if (mapResize) {
      mapResize.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const card = QS("#gsm_map_card");
        const mapCont = QS("#gsm_map_container");
        if (!card || !mapCont) return;
        const startX = e.clientX, startY = e.clientY;
        const startW = card.offsetWidth, startH = card.offsetHeight;
        const startMapH = mapCont.offsetHeight;
        const onMove = (ev) => {
          const dx = ev.clientX - startX, dy = ev.clientY - startY;
          const newW = Math.max(400, startW + dx);
          const newH = Math.max(300, startH + dy);
          const newMapH = Math.max(200, startMapH + dy);
          card.style.width = newW + "px";
          card.style.maxWidth = newW + "px";
          card.style.height = newH + "px";
          mapCont.style.height = newMapH + "px";
          if (St.map) St.map.invalidateSize();
        };
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          if (St.map) St.map.invalidateSize();
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    }

    // New analysis button
    const newBtn = QS("#gsm_new_analysis");
    if (newBtn) {
      newBtn.onclick = () => {
        St.lastResult = null;
        St.idMap = {};
        St.hmData = null;
        St.hmActiveCell = null;
        St.hmMonth = "all";
        St.hmType = "all";
        if (St.map) { St.map.remove(); St.map = null; St._maplibreLayer = null; }
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

      // Auto-load saved GSM data from the current project
      try {
        await _loadFromProject();
      } catch (e) {
        console.warn("[GSM] Auto-load failed:", e);
      }
    },
  };
})();
