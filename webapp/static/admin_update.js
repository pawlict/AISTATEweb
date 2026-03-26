/* admin_update.js — Software Update panel */
(function () {
  "use strict";

  // --- DOM refs ---
  const dropzone = document.getElementById("upd_dropzone");
  const fileInput = document.getElementById("upd_file");
  const uploadingDiv = document.getElementById("upd_uploading");
  const progressBar = document.getElementById("upd_progress_bar");
  const infoDiv = document.getElementById("upd_info");
  const errorDiv = document.getElementById("upd_error");
  const versionSpan = document.getElementById("upd_version");
  const releaseDateDiv = document.getElementById("upd_release_date");
  const changelogDiv = document.getElementById("upd_changelog");
  const changelogBox = document.getElementById("upd_changelog_box");
  const migrationsDiv = document.getElementById("upd_migrations");
  const depsDiv = document.getElementById("upd_deps");
  const installBtn = document.getElementById("upd_install_btn");
  const cancelUploadBtn = document.getElementById("upd_cancel_upload_btn");
  const installMsg = document.getElementById("upd_install_msg");
  const restartPanel = document.getElementById("upd_restart_panel");
  const countdownSpan = document.getElementById("upd_countdown");
  const restartNowBtn = document.getElementById("upd_restart_now_btn");
  const cancelRestartBtn = document.getElementById("upd_cancel_restart_btn");
  const manualRestartDiv = document.getElementById("upd_manual_restart");
  const manualRestartBtn = document.getElementById("upd_manual_restart_btn");
  const autoRestartCb = document.getElementById("upd_auto_restart");
  const delayInput = document.getElementById("upd_delay");
  const historyBody = document.getElementById("upd_history_body");

  let _pollTimer = null;
  let _countdownTimer = null;

  // --- Helpers ---
  function showError(msg) {
    errorDiv.textContent = msg;
    errorDiv.style.display = "block";
    setTimeout(() => { errorDiv.style.display = "none"; }, 8000);
  }

  function hideAll() {
    uploadingDiv.style.display = "none";
    infoDiv.style.display = "none";
    errorDiv.style.display = "none";
    restartPanel.style.display = "none";
    manualRestartDiv.style.display = "none";
    installMsg.textContent = "";
  }

  // --- Drag & drop / file pick ---
  if (dropzone) {
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.style.borderColor = "var(--accent,#4a6cf7)";
    });
    dropzone.addEventListener("dragleave", () => {
      dropzone.style.borderColor = "rgba(255,255,255,0.12)";
    });
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.style.borderColor = "rgba(255,255,255,0.12)";
      const files = e.dataTransfer.files;
      if (files.length > 0) uploadFile(files[0]);
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files.length > 0) uploadFile(fileInput.files[0]);
    });
  }

  // --- Upload ---
  async function uploadFile(file) {
    if (!file.name.endsWith(".zip")) {
      showError("Wymagany plik .zip");
      return;
    }

    hideAll();
    uploadingDiv.style.display = "block";
    progressBar.style.width = "30%";

    const form = new FormData();
    form.append("file", file);

    try {
      progressBar.style.width = "60%";
      const resp = await fetch("/api/admin/update/upload", {
        method: "POST",
        body: form,
      });
      progressBar.style.width = "100%";

      const data = await resp.json();
      uploadingDiv.style.display = "none";

      if (data.status !== "ok") {
        showError(data.message || "Błąd przesyłania");
        return;
      }

      showPackageInfo(data.info);
    } catch (e) {
      uploadingDiv.style.display = "none";
      showError("Błąd połączenia: " + e.message);
    }
  }

  // --- Show package info ---
  function showPackageInfo(info) {
    infoDiv.style.display = "block";
    versionSpan.textContent = info.version || "?";

    if (info.release_date) {
      releaseDateDiv.textContent = "Data wydania: " + info.release_date;
      releaseDateDiv.style.display = "block";
    } else {
      releaseDateDiv.style.display = "none";
    }

    if (info.changelog) {
      changelogDiv.textContent = info.changelog;
      changelogBox.style.display = "block";
    } else {
      changelogBox.style.display = "none";
    }

    if (info.migrations && info.migrations.length > 0) {
      migrationsDiv.textContent = "Migracje danych: " + info.migrations.length + " (zostaną wykonane automatycznie)";
      migrationsDiv.style.display = "block";
    } else {
      migrationsDiv.style.display = "none";
    }

    if (info.new_dependencies && info.new_dependencies.length > 0) {
      depsDiv.textContent = "Nowe zależności: " + info.new_dependencies.join(", ");
      depsDiv.style.display = "block";
    } else {
      depsDiv.style.display = "none";
    }
  }

  // --- Install ---
  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      installBtn.disabled = true;
      installMsg.textContent = "Instalowanie...";

      try {
        // Send auto-restart preference before install
        await fetch("/api/admin/update/auto-restart", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: autoRestartCb.checked,
            delay_seconds: (parseInt(delayInput.value) || 5) * 60,
          }),
        });

        const resp = await fetch("/api/admin/update/install", { method: "POST" });
        const data = await resp.json();

        if (data.status !== "ok") {
          installMsg.textContent = "";
          showError(data.message || "Błąd instalacji");
          installBtn.disabled = false;
          return;
        }

        installMsg.textContent = data.message || "Zainstalowano!";
        infoDiv.style.display = "none";
        dropzone.style.display = "none";

        if (data.restart && data.restart.scheduled) {
          showRestartCountdown(data.restart);
        } else if (data.restart && data.restart.pending) {
          manualRestartDiv.style.display = "block";
        }

        loadHistory();
      } catch (e) {
        installMsg.textContent = "";
        showError("Błąd: " + e.message);
        installBtn.disabled = false;
      }
    });
  }

  // --- Cancel upload ---
  if (cancelUploadBtn) {
    cancelUploadBtn.addEventListener("click", () => {
      hideAll();
      dropzone.style.display = "block";
      fileInput.value = "";
    });
  }

  // --- Restart countdown ---
  function showRestartCountdown(restartInfo) {
    restartPanel.style.display = "block";
    manualRestartDiv.style.display = "none";
    updateCountdown(restartInfo.seconds_remaining || 300);
    startCountdownPoll();
  }

  function updateCountdown(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    countdownSpan.textContent = m + ":" + (s < 10 ? "0" : "") + s;
  }

  function startCountdownPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/admin/update/status");
        const data = await resp.json();
        if (data.status !== "ok") return;

        const r = data.restart || {};
        if (r.scheduled) {
          updateCountdown(r.seconds_remaining || 0);
          restartPanel.style.display = "block";
          manualRestartDiv.style.display = "none";
        } else if (r.pending) {
          restartPanel.style.display = "none";
          manualRestartDiv.style.display = "block";
          clearInterval(_pollTimer);
        } else {
          restartPanel.style.display = "none";
          manualRestartDiv.style.display = "none";
          clearInterval(_pollTimer);
        }
      } catch (e) {
        // Server may be restarting — stop polling
        clearInterval(_pollTimer);
      }
    }, 5000);
  }

  // --- Restart now ---
  if (restartNowBtn) {
    restartNowBtn.addEventListener("click", async () => {
      if (!confirm("Czy na pewno chcesz zrestartować teraz?")) return;
      try {
        await fetch("/api/admin/update/restart-now", { method: "POST" });
      } catch (e) { /* server restarting */ }
    });
  }
  if (manualRestartBtn) {
    manualRestartBtn.addEventListener("click", async () => {
      if (!confirm("Czy na pewno chcesz zrestartować teraz?")) return;
      try {
        await fetch("/api/admin/update/restart-now", { method: "POST" });
      } catch (e) { /* server restarting */ }
    });
  }

  // --- Cancel restart ---
  if (cancelRestartBtn) {
    cancelRestartBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/admin/update/cancel-restart", { method: "POST" });
        restartPanel.style.display = "none";
        manualRestartDiv.style.display = "block";
        if (_pollTimer) clearInterval(_pollTimer);
      } catch (e) {
        showError("Błąd: " + e.message);
      }
    });
  }

  // --- Auto-restart toggle ---
  if (autoRestartCb) {
    autoRestartCb.addEventListener("change", async () => {
      try {
        await fetch("/api/admin/update/auto-restart", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: autoRestartCb.checked,
            delay_seconds: (parseInt(delayInput.value) || 5) * 60,
          }),
        });
      } catch (e) { /* ignore */ }
    });
  }

  // --- History & Rollback ---
  async function loadHistory() {
    try {
      const resp = await fetch("/api/admin/update/history");
      const data = await resp.json();
      if (data.status !== "ok") return;

      renderHistory(data.history || [], data.backups || [], data.current_version || "");
    } catch (e) {
      historyBody.innerHTML = '<tr><td colspan="5" class="small muted" style="text-align:center;">Błąd ładowania historii</td></tr>';
    }
  }

  function renderHistory(history, backups, currentVersion) {
    if (history.length === 0 && backups.length === 0) {
      historyBody.innerHTML = '<tr><td colspan="5" class="small muted" style="text-align:center;">Brak historii aktualizacji</td></tr>';
      return;
    }

    let html = "";

    // Current version row
    html += '<tr style="background:rgba(255,255,255,0.03);">';
    html += '<td style="font-weight:700;">' + esc(currentVersion) + '</td>';
    html += '<td class="small muted">—</td>';
    html += '<td><span style="color:var(--accent,#4a6cf7);">bieżąca</span></td>';
    html += '<td>—</td>';
    html += '<td>—</td>';
    html += '</tr>';

    // History entries
    for (const entry of history) {
      const dt = entry.installed_at ? entry.installed_at.replace("T", " ").substring(0, 19) : "";
      const isRollback = entry.status === "rollback";
      const typeLabel = isRollback ? "rollback" : "aktualizacja";
      const typeColor = isRollback ? "#f59e0b" : "var(--accent,#4a6cf7)";

      // Check if there's a matching backup for rollback
      const backup = backups.find(b => b.version === entry.version || b.path === entry.backup_path);

      html += "<tr>";
      html += '<td style="font-weight:600;">' + esc(entry.version) + "</td>";
      html += '<td class="small muted">' + esc(dt) + "</td>";
      html += '<td><span style="color:' + typeColor + ';">' + typeLabel + "</span></td>";
      html += '<td class="small muted">' + esc(entry.previous_version || "—") + "</td>";
      html += "<td>";
      // Only show rollback for non-current versions that have a backup
      if (entry.backup_path) {
        html += '<button class="btn" style="font-size:.72rem;padding:.2rem .5rem;" onclick="window._updRollback(\'' + esc(entry.backup_path) + '\')">Przywr\u00f3\u0107</button>';
      }
      html += "</td>";
      html += "</tr>";
    }

    historyBody.innerHTML = html;
  }

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // --- Rollback ---
  window._updRollback = async function (backupPath) {
    if (!confirm("Czy na pewno chcesz przywrócić tę wersję? Obecny kod zostanie zastąpiony.")) return;

    try {
      const resp = await fetch("/api/admin/update/rollback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backup_path: backupPath }),
      });
      const data = await resp.json();

      if (data.status !== "ok") {
        showError(data.message || "Błąd rollbacku");
        return;
      }

      if (data.restart && data.restart.scheduled) {
        showRestartCountdown(data.restart);
      }

      loadHistory();
    } catch (e) {
      showError("Błąd: " + e.message);
    }
  };

  // --- Init: check status & load history ---
  async function init() {
    try {
      const resp = await fetch("/api/admin/update/status");
      const data = await resp.json();
      if (data.status !== "ok") return;

      // If there's a pending restart, show countdown
      const r = data.restart || {};
      if (r.scheduled) {
        showRestartCountdown(r);
        dropzone.style.display = "none";
      } else if (r.pending) {
        manualRestartDiv.style.display = "block";
        dropzone.style.display = "none";
      }

      // If an update was uploaded but not installed, show its info
      if (data.update_status === "uploaded" && data.info) {
        showPackageInfo(data.info);
      }

      autoRestartCb.checked = r.auto_restart !== false;
      if (r.delay_seconds) {
        delayInput.value = Math.round(r.delay_seconds / 60);
      }
    } catch (e) { /* ignore */ }

    loadHistory();
  }

  init();
})();
