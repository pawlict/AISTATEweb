/* admin_license.js — License panel with Community vs Pro comparison */
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
        renderLicense(data.license, data.all_features, data.licensing_enabled, data.pro_only_features || [], data.app_edition || "Community");
      })
      .catch(function () {});
  }

  function renderLicense(lic, allFeatures, licensingEnabled, proOnlyFeatures, appEdition) {
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

    // --- Features comparison table ---
    var features = lic.features || [];
    var isCommunity = appEdition === "Community";
    var hasProFeatures = proOnlyFeatures && proOnlyFeatures.length > 0;

    var html = "";

    // Table header
    html += '<div style="display:grid;grid-template-columns:1fr auto auto;gap:0;border-bottom:2px solid var(--border,#e0e3e8);padding-bottom:.4rem;margin-bottom:.3rem;">';
    html += '<div style="font-size:.72rem;font-weight:700;color:var(--muted,#888);">Funkcja <span class=\'en\'>Feature</span></div>';
    html += '<div style="font-size:.72rem;font-weight:700;color:#27ae60;text-align:center;min-width:80px;">Community</div>';
    html += '<div style="font-size:.72rem;font-weight:700;color:#d4a017;text-align:center;min-width:80px;">Pro</div>';
    html += '</div>';

    // Community features (available in both)
    (allFeatures || []).forEach(function (f) {
      var has = features.indexOf(f) >= 0 || features.indexOf("all") >= 0;
      var icon = has ? "&#9989;" : "&#128274;";
      var name = FEATURE_NAMES[f] || f;
      var style = has ? "" : "opacity:.5;";
      html += '<div style="display:grid;grid-template-columns:1fr auto auto;gap:0;padding:.25rem 0;border-bottom:1px solid var(--border,#f0f0f0);font-size:.76rem;' + style + '">';
      html += '<span>' + name + '</span>';
      html += '<span style="text-align:center;min-width:80px;">' + icon + '</span>';
      html += '<span style="text-align:center;min-width:80px;">' + icon + '</span>';
      html += '</div>';
    });

    // Pro-only features (shown only in Community edition)
    if (isCommunity && hasProFeatures) {
      proOnlyFeatures.forEach(function (pf) {
        var namePl = pf.name_pl || pf.key;
        var nameEn = pf.name_en || "";
        var descPl = pf.desc_pl || "";
        var descEn = pf.desc_en || "";
        var displayName = namePl + (nameEn ? ' <span class="en">/ ' + nameEn + '</span>' : '');
        var tooltip = descPl + (descEn ? ' / ' + descEn : '');

        html += '<div style="display:grid;grid-template-columns:1fr auto auto;gap:0;padding:.25rem 0;border-bottom:1px solid var(--border,#f0f0f0);font-size:.76rem;" title="' + tooltip + '">';
        html += '<span style="color:#d4a017;font-weight:500;">' + displayName + ' <span style="font-size:.65rem;background:linear-gradient(135deg,#d4a017,#f0c040);color:#fff;padding:1px 5px;border-radius:3px;font-weight:700;vertical-align:middle;">PRO</span></span>';
        html += '<span style="text-align:center;min-width:80px;opacity:.4;">&#8212;</span>';
        html += '<span style="text-align:center;min-width:80px;">&#9989;</span>';
        html += '</div>';
      });
    }

    featuresList.innerHTML = html;

    // Info label when licensing not enforced
    if (!licensingEnabled) {
      var badge = document.createElement("div");
      badge.style.cssText = "margin-top:.6rem;padding:.4rem .6rem;background:rgba(39,174,96,.08);border:1px solid rgba(39,174,96,.2);border-radius:6px;font-size:.74rem;color:#27ae60;";
      badge.innerHTML = "Licencjonowanie nieaktywne \u2014 wszystkie funkcje odblokowane. " +
                         "<span class='en'>Licensing not enforced \u2014 all features unlocked.</span>";
      featuresList.appendChild(badge);
    }

    // Pro upgrade info (only in Community)
    if (isCommunity && hasProFeatures) {
      var proBadge = document.createElement("div");
      proBadge.style.cssText = "margin-top:.5rem;padding:.5rem .7rem;background:linear-gradient(135deg,rgba(212,160,23,.06),rgba(240,192,64,.1));border:1px solid rgba(212,160,23,.25);border-radius:6px;font-size:.74rem;color:#b8860b;";
      proBadge.innerHTML = '<b>AISTATEweb Pro</b> \u2014 Zaawansowane funkcje dost\u0119pne wy\u0142\u0105cznie w wersji Pro. ' +
                           '<span class="en">Advanced features available exclusively in the Pro version.</span>';
      featuresList.appendChild(proBadge);
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
