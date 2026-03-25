/* admin_modules.js — Addon Modules management panel */
(function () {
  "use strict";

  // --- DOM refs ---
  const listDiv = document.getElementById("mod_list");
  const dropzone = document.getElementById("mod_dropzone");
  const fileInput = document.getElementById("mod_file");
  const uploadingDiv = document.getElementById("mod_uploading");
  const progressBar = document.getElementById("mod_progress_bar");
  const successDiv = document.getElementById("mod_success");
  const errorDiv = document.getElementById("mod_error");

  if (!listDiv) return; // not on modules panel page

  // --- Helpers ---
  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function showError(msg) {
    successDiv.style.display = "none";
    errorDiv.textContent = msg;
    errorDiv.style.display = "block";
    setTimeout(() => { errorDiv.style.display = "none"; }, 10000);
  }

  function showSuccess(msg) {
    errorDiv.style.display = "none";
    successDiv.textContent = msg;
    successDiv.style.display = "block";
  }

  function hideMessages() {
    successDiv.style.display = "none";
    errorDiv.style.display = "none";
    uploadingDiv.style.display = "none";
  }

  // Detect UI language
  function isEn() {
    try { return (document.documentElement.lang || "").startsWith("en"); } catch(e) { return false; }
  }

  // --- Load modules list ---
  async function loadModules() {
    try {
      const resp = await fetch("/api/admin/modules");
      const data = await resp.json();
      if (data.status !== "ok") {
        listDiv.innerHTML = '<div style="color:#e74c3c;font-size:.82rem;">B\u0142\u0105d \u0142adowania modu\u0142\u00f3w</div>';
        return;
      }
      renderModules(data.modules || []);
    } catch (e) {
      listDiv.innerHTML = '<div style="color:#e74c3c;font-size:.82rem;">B\u0142\u0105d po\u0142\u0105czenia</div>';
    }
  }

  function renderModules(modules) {
    if (modules.length === 0) {
      listDiv.innerHTML = '<div style="font-size:.82rem;color:var(--muted,#888);text-align:center;padding:1.5rem;">Brak dost\u0119pnych modu\u0142\u00f3w <span class="en">No modules available</span></div>';
      return;
    }

    let html = "";
    for (const m of modules) {
      const installed = m.installed;
      const licensed = m.license && m.license.allowed;
      const plan = (m.license && m.license.plan) || "community";
      const requiredPlan = m.required_plan || "pro";

      // Status badge
      let statusBadge = "";
      if (installed) {
        statusBadge = '<span style="display:inline-flex;align-items:center;gap:.25rem;font-size:.74rem;padding:.15rem .5rem;border-radius:10px;background:rgba(39,174,96,.12);color:#27ae60;font-weight:600;">'
          + '\u2713 Zainstalowany <span class="en">Installed</span>'
          + (m.installed_version ? " v" + esc(m.installed_version) : "")
          + "</span>";
      } else {
        statusBadge = '<span style="display:inline-flex;align-items:center;gap:.25rem;font-size:.74rem;padding:.15rem .5rem;border-radius:10px;background:rgba(136,136,136,.12);color:var(--muted,#888);font-weight:600;">'
          + 'Nie zainstalowany <span class="en">Not installed</span></span>';
      }

      // License badge
      let licenseBadge = "";
      if (!licensed) {
        const reason = (m.license && m.license.reason) || "feature_locked";
        if (reason === "license_expired") {
          licenseBadge = '<span style="font-size:.74rem;padding:.15rem .5rem;border-radius:10px;background:rgba(231,76,60,.12);color:#e74c3c;font-weight:600;">Licencja wygas\u0142a <span class="en">License expired</span></span>';
        } else {
          licenseBadge = '<span style="font-size:.74rem;padding:.15rem .5rem;border-radius:10px;background:rgba(245,158,11,.12);color:#f59e0b;font-weight:600;">Wymaga planu ' + esc(requiredPlan.charAt(0).toUpperCase() + requiredPlan.slice(1)) + ' <span class="en">Requires ' + esc(requiredPlan) + ' plan</span></span>';
        }
      }

      // Action button
      let actionBtn = "";
      if (installed) {
        actionBtn = '<button class="btn mod-uninstall-btn" data-id="' + esc(m.id) + '" style="font-size:.76rem;padding:.25rem .6rem;background:transparent;border:1px solid var(--border,#ccc);color:var(--muted,#888);">'
          + 'Odinstaluj <span class="en">Uninstall</span></button>';
      } else if (licensed) {
        actionBtn = '<span style="font-size:.76rem;color:var(--muted,#888);">Prze\u015blij plik .whl poni\u017cej <span class="en">Upload .whl file below</span></span>';
      } else {
        actionBtn = '<span style="font-size:.76rem;color:var(--muted,#888);">Aktywuj licencj\u0119 ' + esc(requiredPlan) + ' <span class="en">Activate ' + esc(requiredPlan) + ' license</span></span>';
      }

      html += '<div style="padding:.7rem 1rem;background:var(--panel2,#f8f9fa);border:1px solid var(--border,#e0e3e8);border-radius:8px;">'
        + '<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.4rem;">'
        + '<span style="font-size:1.3rem;">' + (m.icon || "\u{1F4E6}") + '</span>'
        + '<div style="flex:1;">'
        + '<div style="font-weight:700;font-size:.88rem;">' + esc(m.name) + '</div>'
        + '<div style="font-size:.76rem;color:var(--muted,#888);">' + esc(m.description) + '</div>'
        + '</div>'
        + '<div style="display:flex;flex-direction:column;gap:.3rem;align-items:flex-end;">'
        + statusBadge
        + licenseBadge
        + '</div>'
        + '</div>'
        + '<div style="display:flex;align-items:center;gap:.6rem;margin-top:.4rem;">'
        + actionBtn
        + (m.version_available ? '<span style="font-size:.72rem;color:var(--muted,#888);">Najnowsza: v' + esc(m.version_available) + '</span>' : '')
        + '</div>'
        + '</div>';
    }

    listDiv.innerHTML = html;

    // Attach uninstall handlers
    listDiv.querySelectorAll(".mod-uninstall-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var mid = btn.getAttribute("data-id");
        uninstallModule(mid);
      });
    });
  }

  // --- Uninstall ---
  async function uninstallModule(moduleId) {
    var confirmMsg = "Czy na pewno chcesz odinstalowa\u0107 ten modu\u0142? Wymagany restart serwera.";
    if (!confirm(confirmMsg)) return;

    hideMessages();
    try {
      const resp = await fetch("/api/admin/modules/uninstall/" + encodeURIComponent(moduleId), {
        method: "POST",
      });
      const data = await resp.json();
      if (data.status !== "ok") {
        showError(data.detail || data.message || "B\u0142\u0105d odinstalowania");
        return;
      }
      showSuccess(data.message || "Modu\u0142 odinstalowany. Wymagany restart serwera.");
      loadModules();
    } catch (e) {
      showError("B\u0142\u0105d po\u0142\u0105czenia: " + e.message);
    }
  }

  // --- Drag & drop / file pick ---
  if (dropzone) {
    dropzone.addEventListener("click", function () { fileInput.click(); });
    dropzone.addEventListener("dragover", function (e) {
      e.preventDefault();
      dropzone.style.borderColor = "var(--accent,#4a6cf7)";
    });
    dropzone.addEventListener("dragleave", function () {
      dropzone.style.borderColor = "rgba(255,255,255,0.12)";
    });
    dropzone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropzone.style.borderColor = "rgba(255,255,255,0.12)";
      if (e.dataTransfer.files.length > 0) uploadWhl(e.dataTransfer.files[0]);
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      if (fileInput.files.length > 0) uploadWhl(fileInput.files[0]);
    });
  }

  // --- Upload .whl ---
  async function uploadWhl(file) {
    if (!file.name.endsWith(".whl")) {
      showError("Wymagany plik .whl (Python wheel)");
      return;
    }

    hideMessages();
    uploadingDiv.style.display = "block";
    progressBar.style.width = "30%";

    const form = new FormData();
    form.append("file", file);

    try {
      progressBar.style.width = "60%";
      const resp = await fetch("/api/admin/modules/install", {
        method: "POST",
        body: form,
      });
      progressBar.style.width = "100%";

      const data = await resp.json();
      uploadingDiv.style.display = "none";

      if (data.status !== "ok") {
        showError(data.detail || data.message || "B\u0142\u0105d instalacji modu\u0142u");
        return;
      }

      showSuccess(data.message || "Modu\u0142 zainstalowany! Zrestartuj serwer aby aktywowa\u0107.");
      fileInput.value = "";
      loadModules();
    } catch (e) {
      uploadingDiv.style.display = "none";
      showError("B\u0142\u0105d po\u0142\u0105czenia: " + e.message);
    }
  }

  // --- Init ---
  loadModules();
})();
