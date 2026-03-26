/* admin_license.js — License panel */
(function () {
  "use strict";

  // Feature display names (Polish + English)
  var FEATURE_NAMES = {
    transcription:     "Transkrypcja / Transcription",
    diarization:       "Diaryzacja / Diarization",
    translation:       "T\u0142umaczenie / Translation",
    analysis:          "Analiza / Analysis",
    chat:              "Chat LLM",
    tts:               "TTS (podstawowy / basic)",
    tts_kokoro:        "TTS Kokoro (zaawansowany / advanced)",
    sound_detection:   "Detekcja d\u017awi\u0119k\u00f3w / Sound detection",
    batch_processing:  "Przetwarzanie wsadowe / Batch processing",
    advanced_reports:  "Zaawansowane raporty / Advanced reports",
    update_panel:      "Panel aktualizacji / Update panel"
  };

  // --- DOM refs ---
  var planName      = document.getElementById("lic_plan_name");
  var statusIcon    = document.getElementById("lic_status_icon");
  var statusText    = document.getElementById("lic_status_text");
  var licId         = document.getElementById("lic_id");
  var licName       = document.getElementById("lic_name");
  var licEmail      = document.getElementById("lic_email");
  var licExpires    = document.getElementById("lic_expires");
  var licUpdates    = document.getElementById("lic_updates_until");
  var licIssued     = document.getElementById("lic_issued");
  var featuresList  = document.getElementById("lic_features_list");
  var keyInput      = document.getElementById("lic_key_input");
  var activateBtn   = document.getElementById("lic_activate_btn");
  var removeBtn     = document.getElementById("lic_remove_btn");
  var actionMsg     = document.getElementById("lic_action_msg");

  if (!planName) return; // panel not rendered (not superadmin)

  // --- Load license status ---
  function loadStatus() {
    fetch("/api/admin/license/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status !== "ok") return;
        renderLicense(data.license, data.all_features, data.licensing_enabled);
      })
      .catch(function () {});
  }

  function renderLicense(lic, allFeatures, licensingEnabled) {
    // Plan name
    var pName = (lic.plan || "community").charAt(0).toUpperCase() + (lic.plan || "community").slice(1);
    planName.textContent = pName;

    // Status
    if (lic.is_expired) {
      statusIcon.innerHTML = "&#10060;"; // red X
      statusText.textContent = "Wygas\u0142a / Expired";
      statusText.style.color = "#e74c3c";
    } else {
      statusIcon.innerHTML = "&#9989;"; // green check
      statusText.textContent = "Aktywna / Active";
      statusText.style.color = "#27ae60";
    }

    // Details
    licId.textContent = lic.license_id || "\u2014";
    if (licName) licName.textContent = lic.name || "\u2014";
    licEmail.textContent = lic.email || "\u2014";

    if (lic.is_perpetual || lic.expires === null) {
      licExpires.innerHTML = "Bezterminowa <span class='en'>Perpetual</span>";
    } else {
      var expStr = lic.expires;
      if (lic.days_remaining !== null && lic.days_remaining !== undefined) {
        expStr += " (" + lic.days_remaining + " dni / days)";
      }
      licExpires.textContent = expStr;
      if (lic.days_remaining !== null && lic.days_remaining <= 30) {
        licExpires.style.color = "#e67e22";
      }
      if (lic.is_expired) {
        licExpires.style.color = "#e74c3c";
      }
    }

    if (lic.updates_until === null) {
      licUpdates.innerHTML = "Bezterminowe <span class='en'>Perpetual</span>";
    } else {
      var updStr = lic.updates_until;
      if (lic.updates_days_remaining !== null && lic.updates_days_remaining !== undefined) {
        updStr += " (" + lic.updates_days_remaining + " dni / days)";
      }
      licUpdates.textContent = updStr;
      if (lic.updates_expired) {
        licUpdates.style.color = "#e67e22";
      }
    }

    licIssued.textContent = lic.issued || "\u2014";

    // Features list
    var features = lic.features || [];
    var html = "";
    (allFeatures || []).forEach(function (f) {
      var has = features.indexOf(f) >= 0 || features.indexOf("all") >= 0;
      var icon = has ? "&#9989;" : "&#128274;";
      var name = FEATURE_NAMES[f] || f;
      var style = has ? "" : "opacity:.5;";
      html += '<div style="display:flex;align-items:center;gap:.4rem;padding:.2rem 0;font-size:.78rem;' + style + '">';
      html += '<span>' + icon + '</span>';
      html += '<span>' + name + '</span>';
      html += '</div>';
    });
    featuresList.innerHTML = html;

    // Info label when licensing not enforced
    if (!licensingEnabled) {
      var badge = document.createElement("div");
      badge.style.cssText = "margin-top:.6rem;padding:.4rem .6rem;background:rgba(39,174,96,.08);border:1px solid rgba(39,174,96,.2);border-radius:6px;font-size:.74rem;color:#27ae60;";
      badge.innerHTML = "Licencjonowanie nieaktywne \u2014 wszystkie funkcje odblokowane. " +
                         "<span class='en'>Licensing not enforced \u2014 all features unlocked.</span>";
      featuresList.appendChild(badge);
    }
  }

  // --- Activate ---
  function showMsg(text, color) {
    actionMsg.textContent = text;
    actionMsg.style.color = color || "var(--text,#333)";
    setTimeout(function () { actionMsg.textContent = ""; }, 6000);
  }

  activateBtn.addEventListener("click", function () {
    var key = keyInput.value.trim();
    if (!key) {
      showMsg("Wpisz klucz licencyjny / Enter a license key", "#e74c3c");
      return;
    }
    activateBtn.disabled = true;
    fetch("/api/admin/license/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        activateBtn.disabled = false;
        if (data.status === "ok") {
          showMsg("Licencja aktywowana! / License activated!", "#27ae60");
          keyInput.value = "";
          loadStatus();
        } else {
          showMsg(data.message || "B\u0142\u0105d aktywacji", "#e74c3c");
        }
      })
      .catch(function () {
        activateBtn.disabled = false;
        showMsg("B\u0142\u0105d po\u0142\u0105czenia / Connection error", "#e74c3c");
      });
  });

  // --- Remove ---
  removeBtn.addEventListener("click", function () {
    if (!confirm("Czy na pewno chcesz usun\u0105\u0107 licencj\u0119?\nAre you sure you want to remove the license?")) {
      return;
    }
    fetch("/api/admin/license/remove", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status === "ok") {
          showMsg("Licencja usuni\u0119ta / License removed", "#27ae60");
          loadStatus();
        } else {
          showMsg(data.message || "B\u0142\u0105d", "#e74c3c");
        }
      })
      .catch(function () {
        showMsg("B\u0142\u0105d po\u0142\u0105czenia / Connection error", "#e74c3c");
      });
  });

  // --- Init ---
  loadStatus();
})();
