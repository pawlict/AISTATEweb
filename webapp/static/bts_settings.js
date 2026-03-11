/**
 * BTS Settings page — manages BTS station databases and offline maps.
 */
(function () {
  "use strict";

  const QS = (sel, root = document) => root.querySelector(sel);

  function _fmt(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString("pl-PL");
  }

  /* ── Progress helpers ─────────────────────────────────── */

  function _showProgress(msg, pct) {
    const wrap = QS("#bts_progress");
    const status = QS("#bts_progress_status");
    const bar = QS("#bts_progress_bar");
    if (wrap) wrap.style.display = "";
    if (status) status.textContent = msg;
    if (bar) bar.style.width = (pct || 0) + "%";
  }

  function _hideProgress(delay) {
    setTimeout(() => {
      const wrap = QS("#bts_progress");
      if (wrap) wrap.style.display = "none";
    }, delay || 0);
  }

  /* ── Stats ────────────────────────────────────────────── */

  function _fmtDate(ts) {
    if (!ts) return "";
    const d = new Date(parseInt(ts, 10) * 1000);
    return d.toLocaleDateString("pl-PL") + " " + d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  }

  function _updateSourceStatus(prefix, count, importedTs) {
    const wrap = QS(`#bts_${prefix}_source_status`);
    const info = QS(`#bts_${prefix}_source_info`);
    if (!wrap || !info) return;

    if (count > 0) {
      wrap.className = "bts-source-status active ok";
      let text = `Załadowano ${_fmt(count)} stacji`;
      if (importedTs) text += ` (import: ${_fmtDate(importedTs)})`;
      info.textContent = text;
    } else {
      wrap.className = "bts-source-status active empty";
      info.textContent = "Baza nie jest pobrana";
    }
  }

  async function refreshStats() {
    try {
      const resp = await fetch("/api/gsm/bts/stats");
      const data = await resp.json();
      const t = QS("#bts_total");
      const s = QS("#bts_size");
      const c = QS("#bts_cities");
      const src = QS("#bts_sources");
      if (t) t.textContent = _fmt(data.total_stations || 0);
      if (s) s.textContent = (data.db_size_mb || 0).toFixed(1);
      if (c) c.textContent = _fmt(data.unique_cities || 0);
      if (src) {
        const bySrc = data.by_source || {};
        const parts = Object.entries(bySrc).map(([k, v]) => `${k}: ${_fmt(v)}`);
        src.textContent = parts.length ? parts.join(", ") : "—";
      }

      // Per-source status banners
      const bySrc = data.by_source || {};
      const meta = data.meta || {};
      _updateSourceStatus("ocid", bySrc.opencellid || 0, meta.opencellid_imported);
      _updateSourceStatus("uke", bySrc.uke || 0, meta.uke_imported);

    } catch (e) {
      console.warn("BTS stats error:", e);
    }
  }

  /* ── Tiles status ─────────────────────────────────────── */

  async function refreshTilesStatus() {
    try {
      const resp = await fetch("/api/gsm/tiles/info");
      const info = await resp.json();
      const el = QS("#bts_tiles_status");
      const removeBtn = QS("#bts_mbtiles_remove_btn");

      if (el) {
        if (info.available) {
          el.innerHTML = `<span style="color:#22c55e;font-weight:600">&#10003; Dostępna</span> — ${info.name || "map.mbtiles"}, ` +
            `${info.size_mb} MB, ${_fmt(info.tile_count)} kafelków, format: ${info.format}, ` +
            `zoom: ${info.minzoom}–${info.maxzoom}`;
          if (removeBtn) removeBtn.style.display = "";
        } else {
          el.innerHTML = `<span style="color:#f97316;font-weight:600">Niedostępna</span> — brak pliku MBTiles`;
          if (removeBtn) removeBtn.style.display = "none";
        }
      }
    } catch (e) {
      console.warn("Tiles info error:", e);
    }
  }

  /* ── Import CSV (manual upload) ───────────────────────── */

  async function importCSV(source, file, statusEl) {
    _showProgress(`Importowanie ${file.name}…`, 30);
    if (statusEl) statusEl.textContent = "Importowanie…";

    const fd = new FormData();
    fd.append("file", file);
    fd.append("source", source);

    try {
      _showProgress(`Importowanie ${file.name}…`, 60);
      const resp = await fetch("/api/gsm/bts/import", { method: "POST", body: fd });
      const data = await resp.json();
      _showProgress("Gotowe", 100);

      if (data.status === "ok") {
        if (statusEl) statusEl.innerHTML = `<span style="color:#22c55e">Zaimportowano ${_fmt(data.imported)} stacji</span>`;
        await refreshStats();
      } else {
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${data.detail || "?"}</span>`;
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${e.message}</span>`;
    }
    _hideProgress(2000);
  }

  /* ── Map source selector ─────────────────────────────── */

  async function loadMapSource() {
    try {
      const resp = await fetch("/api/settings");
      const data = await resp.json();
      const sel = QS("#bts_map_source");
      if (sel && data.map_source) {
        sel.value = data.map_source;
      }
      _updateMapSourceStatus(data.map_source || "auto");
      return data;
    } catch (e) {
      console.warn("Failed to load map source:", e);
      return {};
    }
  }

  async function saveMapSource(value) {
    try {
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ map_source: value }),
      });
      _updateMapSourceStatus(value);
    } catch (e) {
      console.warn("Failed to save map source:", e);
    }
  }

  async function _updateMapSourceStatus(mode) {
    const statusEl = QS("#bts_map_source_status");
    if (!statusEl) return;

    // Check offline availability
    let offlineAvailable = false;
    let offlineFormat = "";
    try {
      const resp = await fetch("/api/gsm/tiles/info");
      const info = await resp.json();
      offlineAvailable = info.available;
      offlineFormat = info.format || "";
    } catch (e) { /* ignore */ }

    let html = "";
    if (mode === "auto") {
      if (offlineAvailable) {
        html = '<span style="color:#22c55e">&#9679;</span> <span class="small">Aktywna: mapa offline (' + offlineFormat.toUpperCase() + ')</span>';
      } else {
        html = '<span style="color:#3b82f6">&#9679;</span> <span class="small">Aktywna: OpenStreetMap online</span>';
      }
    } else if (mode === "offline") {
      if (offlineAvailable) {
        html = '<span style="color:#22c55e">&#9679;</span> <span class="small">Aktywna: mapa offline (' + offlineFormat.toUpperCase() + ')</span>';
      } else {
        html = '<span style="color:#f97316">&#9679;</span> <span class="small">Uwaga: brak pliku MBTiles — mapa nie będzie dostępna</span>';
      }
    } else {
      html = '<span style="color:#3b82f6">&#9679;</span> <span class="small">Aktywna: OpenStreetMap online</span>';
    }
    statusEl.innerHTML = html;
  }

  /* ── OpenCelliD token persistence ─────────────────────── */

  let _ocidTokenSaveTimer = null;

  async function loadOcidToken() {
    try {
      const resp = await fetch("/api/settings");
      const data = await resp.json();
      const tokenInput = QS("#bts_ocid_token");
      if (tokenInput && data.opencellid_token) {
        tokenInput.value = data.opencellid_token;
      }
    } catch (e) {
      console.warn("Failed to load OpenCelliD token:", e);
    }
  }

  function saveOcidToken(token) {
    // Debounce: save 500ms after the user stops typing
    if (_ocidTokenSaveTimer) clearTimeout(_ocidTokenSaveTimer);
    _ocidTokenSaveTimer = setTimeout(async () => {
      try {
        await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ opencellid_token: token }),
        });
      } catch (e) {
        console.warn("Failed to save OpenCelliD token:", e);
      }
    }, 500);
  }

  /* ── Download OpenCelliD ──────────────────────────────── */

  async function downloadOpenCelliD() {
    const tokenInput = QS("#bts_ocid_token");
    const statusEl = QS("#bts_ocid_status");
    const token = (tokenInput ? tokenInput.value : "").trim();

    if (!token) {
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--danger)">Podaj token API z opencellid.org</span>';
      if (tokenInput) tokenInput.focus();
      return;
    }

    // Save token before downloading
    saveOcidToken(token);

    if (statusEl) statusEl.textContent = "Pobieranie bazy PL…";
    _showProgress("Pobieranie bazy OpenCelliD (Polska)…", 20);

    try {
      const resp = await fetch("/api/gsm/bts/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "opencellid", token: token }),
      });
      const data = await resp.json();

      if (data.status === "ok") {
        _showProgress("Import do bazy…", 80);
        // Poll task if async
        if (data.task_id) {
          await _pollTask(data.task_id, statusEl);
        } else {
          _showProgress("Gotowe", 100);
          if (statusEl) statusEl.innerHTML = `<span style="color:#22c55e">Pobrano i zaimportowano ${_fmt(data.imported)} stacji</span>`;
          await refreshStats();
        }
      } else {
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${data.detail || "?"}</span>`;
        _showProgress("Błąd", 0);
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${e.message}</span>`;
    }
    _hideProgress(3000);
  }

  /* ── Download UKE ─────────────────────────────────────── */

  async function downloadUKE() {
    const statusEl = QS("#bts_uke_status");
    if (statusEl) statusEl.textContent = "Pobieranie z BIP UKE…";
    _showProgress("Pobieranie bazy UKE…", 20);

    try {
      const resp = await fetch("/api/gsm/bts/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "uke" }),
      });
      const data = await resp.json();

      if (data.status === "ok") {
        _showProgress("Import do bazy…", 80);
        if (data.task_id) {
          await _pollTask(data.task_id, statusEl);
        } else {
          _showProgress("Gotowe", 100);
          if (statusEl) statusEl.innerHTML = `<span style="color:#22c55e">Pobrano i zaimportowano ${_fmt(data.imported)} stacji</span>`;
          await refreshStats();
        }
      } else {
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${data.detail || "?"}</span>`;
        _showProgress("Błąd", 0);
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${e.message}</span>`;
    }
    _hideProgress(3000);
  }

  /* ── Poll task ────────────────────────────────────────── */

  async function _pollTask(taskId, statusEl) {
    for (let i = 0; i < 300; i++) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const resp = await fetch(`/api/tasks/${taskId}`);
        const t = await resp.json();
        const pct = t.progress || 0;
        _showProgress(t.status_text || "Przetwarzanie…", pct);

        if (t.state === "done" || t.state === "completed") {
          _showProgress("Gotowe", 100);
          if (statusEl) statusEl.innerHTML = `<span style="color:#22c55e">${t.status_text || "Gotowe"}</span>`;
          await refreshStats();
          return;
        }
        if (t.state === "error" || t.state === "failed") {
          if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${t.error || t.status_text || "?"}</span>`;
          return;
        }
      } catch (e) {
        // continue polling
      }
    }
  }

  /* ── Upload MBTiles ───────────────────────────────────── */

  async function uploadMBTiles(file) {
    const statusEl = QS("#bts_mbtiles_upload_status");
    const pctEl = QS("#bts_mbtiles_pct");
    const barEl = QS("#bts_mbtiles_bar");
    const progressWrap = QS("#bts_mbtiles_progress");

    if (progressWrap) progressWrap.style.display = "";
    if (statusEl) statusEl.textContent = "Wgrywanie…";

    const fd = new FormData();
    fd.append("file", file);

    try {
      const xhr = new XMLHttpRequest();
      await new Promise((resolve, reject) => {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            if (pctEl) pctEl.textContent = pct + "%";
            if (barEl) barEl.style.width = pct + "%";
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(xhr.responseText);
          } else {
            reject(new Error(`HTTP ${xhr.status}: ${xhr.responseText.slice(0, 200)}`));
          }
        };
        xhr.onerror = () => reject(new Error("Błąd sieci"));
        xhr.open("POST", "/api/gsm/tiles/upload");
        xhr.send(fd);
      });

      if (statusEl) statusEl.innerHTML = '<span style="color:#22c55e">Wgrano pomyślnie</span>';
      await refreshTilesStatus();
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">Błąd: ${e.message}</span>`;
    }

    setTimeout(() => {
      if (progressWrap) progressWrap.style.display = "none";
    }, 3000);
  }

  /* ── Remove MBTiles ───────────────────────────────────── */

  async function removeMBTiles() {
    if (!confirm("Usunąć mapę offline?")) return;
    try {
      const resp = await fetch("/api/gsm/tiles/remove", { method: "POST" });
      const data = await resp.json();
      if (data.status === "ok") {
        await refreshTilesStatus();
      }
    } catch (e) {
      console.warn("Tile remove error:", e);
    }
  }

  /* ── Clear database ───────────────────────────────────── */

  async function clearDB() {
    const sourceSelect = QS("#bts_clear_source_select");
    const source = sourceSelect ? sourceSelect.value : "";
    const label = source ? source : "całą bazę";

    if (!confirm(`Wyczyścić ${label} stacji BTS?`)) return;

    try {
      const fd = new FormData();
      fd.append("source", source);
      const resp = await fetch("/api/gsm/bts/clear", { method: "POST", body: fd });
      const data = await resp.json();
      if (data.status === "ok") {
        await refreshStats();
      }
    } catch (e) {
      console.warn("BTS clear error:", e);
    }
  }

  /* ── Bindings ─────────────────────────────────────────── */

  function bind() {
    // Refresh
    const refreshBtn = QS("#bts_refresh_btn");
    if (refreshBtn) refreshBtn.onclick = () => { refreshStats(); refreshTilesStatus(); };

    // Clear
    const clearBtn = QS("#bts_clear_btn");
    if (clearBtn) clearBtn.onclick = clearDB;

    // OpenCelliD token auto-save on edit
    const ocidTokenInput = QS("#bts_ocid_token");
    if (ocidTokenInput) {
      ocidTokenInput.addEventListener("input", () => saveOcidToken(ocidTokenInput.value.trim()));
      ocidTokenInput.addEventListener("change", () => saveOcidToken(ocidTokenInput.value.trim()));
    }

    // OpenCelliD download
    const ocidDlBtn = QS("#bts_ocid_download_btn");
    if (ocidDlBtn) ocidDlBtn.onclick = downloadOpenCelliD;

    // OpenCelliD manual upload
    const ocidUpBtn = QS("#bts_ocid_upload_btn");
    const ocidFile = QS("#bts_ocid_file");
    if (ocidUpBtn && ocidFile) {
      ocidUpBtn.onclick = () => ocidFile.click();
      ocidFile.onchange = () => {
        if (ocidFile.files && ocidFile.files.length) {
          importCSV("opencellid", ocidFile.files[0], QS("#bts_ocid_upload_status"));
          ocidFile.value = "";
        }
      };
    }

    // UKE download
    const ukeDlBtn = QS("#bts_uke_download_btn");
    if (ukeDlBtn) ukeDlBtn.onclick = downloadUKE;

    // UKE manual upload
    const ukeUpBtn = QS("#bts_uke_upload_btn");
    const ukeFile = QS("#bts_uke_file");
    if (ukeUpBtn && ukeFile) {
      ukeUpBtn.onclick = () => ukeFile.click();
      ukeFile.onchange = () => {
        if (ukeFile.files && ukeFile.files.length) {
          importCSV("uke", ukeFile.files[0], QS("#bts_uke_upload_status"));
          ukeFile.value = "";
        }
      };
    }

    // MBTiles upload
    const mbUpBtn = QS("#bts_mbtiles_upload_btn");
    const mbFile = QS("#bts_mbtiles_file");
    if (mbUpBtn && mbFile) {
      mbUpBtn.onclick = () => mbFile.click();
      mbFile.onchange = () => {
        if (mbFile.files && mbFile.files.length) {
          uploadMBTiles(mbFile.files[0]);
          mbFile.value = "";
        }
      };
    }

    // MBTiles remove
    const mbRemove = QS("#bts_mbtiles_remove_btn");
    if (mbRemove) mbRemove.onclick = removeMBTiles;

    // Map source selector
    const mapSrcSel = QS("#bts_map_source");
    if (mapSrcSel) mapSrcSel.onchange = () => saveMapSource(mapSrcSel.value);
  }

  /* ── Init ─────────────────────────────────────────────── */

  bind();
  loadMapSource();
  loadOcidToken();
  refreshStats();
  refreshTilesStatus();
})();
