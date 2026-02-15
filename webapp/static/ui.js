/* ui.js — Shared UI components: Toast, ConfirmModal, FormValidation, Breadcrumbs */
(function(){
  'use strict';

  // ===================== TOAST / SNACKBAR =====================

  var _toastContainer = null;
  var _toastQueue = [];

  var _ai = typeof aiIcon === 'function' ? aiIcon : null;
  var TOAST_TYPES = {
    success: { icon: _ai ? _ai('success', 16) : '\u2713', color: '#15803d', bg: 'rgba(21,128,61,.10)', border: 'rgba(21,128,61,.25)', html: true },
    error:   { icon: _ai ? _ai('error', 16) : '\u2715', color: '#b91c1c', bg: 'rgba(185,28,28,.10)', border: 'rgba(185,28,28,.25)', html: true },
    warning: { icon: _ai ? _ai('warning', 16) : '\u26A0', color: '#d97706', bg: 'rgba(217,119,6,.10)', border: 'rgba(217,119,6,.25)', html: true },
    info:    { icon: _ai ? _ai('info_circle', 16) : '\u2139', color: '#1f5aa6', bg: 'rgba(31,90,166,.10)', border: 'rgba(31,90,166,.25)', html: true },
  };

  function _ensureToastContainer() {
    if (_toastContainer) return _toastContainer;
    _toastContainer = document.createElement('div');
    _toastContainer.id = 'aistate-toast-container';
    _toastContainer.setAttribute('aria-live', 'polite');
    _toastContainer.setAttribute('aria-atomic', 'true');
    document.body.appendChild(_toastContainer);
    return _toastContainer;
  }

  /**
   * Show a toast notification.
   * @param {string} message - Text to display
   * @param {string} [type='info'] - 'success' | 'error' | 'warning' | 'info'
   * @param {number} [duration=3500] - Auto-dismiss in ms (0 = manual close only)
   */
  function showToast(message, type, duration) {
    type = type || 'info';
    duration = (duration !== undefined) ? duration : 3500;
    var cfg = TOAST_TYPES[type] || TOAST_TYPES.info;

    var container = _ensureToastContainer();
    var toast = document.createElement('div');
    toast.className = 'aistate-toast aistate-toast-' + type;
    toast.setAttribute('role', 'alert');

    var icon = document.createElement('span');
    icon.className = 'aistate-toast-icon';
    if (cfg.html) { icon.innerHTML = cfg.icon; } else { icon.textContent = cfg.icon; }
    icon.style.color = cfg.color;

    var text = document.createElement('span');
    text.className = 'aistate-toast-text';
    text.textContent = message;

    var close = document.createElement('button');
    close.className = 'aistate-toast-close';
    close.textContent = '\u00D7';
    close.setAttribute('aria-label', 'Close');
    close.addEventListener('click', function() { _removeToast(toast); });

    toast.appendChild(icon);
    toast.appendChild(text);
    toast.appendChild(close);
    container.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(function() {
      toast.classList.add('aistate-toast-show');
    });

    if (duration > 0) {
      toast._timer = setTimeout(function() { _removeToast(toast); }, duration);
    }

    return toast;
  }

  function _removeToast(toast) {
    if (toast._removed) return;
    toast._removed = true;
    clearTimeout(toast._timer);
    toast.classList.remove('aistate-toast-show');
    toast.classList.add('aistate-toast-hide');
    setTimeout(function() {
      try { toast.parentNode.removeChild(toast); } catch(e) {}
    }, 300);
  }

  // ===================== CONFIRM MODAL =====================

  /**
   * Show a styled confirmation modal. Returns a Promise<boolean>.
   * @param {Object} opts
   * @param {string} opts.title - Modal title
   * @param {string} opts.message - Description text
   * @param {string} [opts.detail] - Entity name or extra detail (shown bold)
   * @param {string} [opts.confirmText='OK'] - Confirm button label
   * @param {string} [opts.cancelText='Anuluj'] - Cancel button label
   * @param {string} [opts.type='danger'] - 'danger' | 'warning' | 'info'
   * @returns {Promise<boolean>}
   */
  function showConfirm(opts) {
    opts = opts || {};
    return new Promise(function(resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'aistate-confirm-overlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');

      var _cai = typeof aiIcon === 'function' ? aiIcon : null;
      var typeColors = {
        danger:  { accent: '#b91c1c', bg: 'rgba(185,28,28,.08)', iconBg: 'rgba(185,28,28,.12)', icon: _cai ? _cai('warning', 28) : '\u26A0' },
        warning: { accent: '#d97706', bg: 'rgba(217,119,6,.08)', iconBg: 'rgba(217,119,6,.12)', icon: _cai ? _cai('warning', 28) : '\u26A0' },
        info:    { accent: '#1f5aa6', bg: 'rgba(31,90,166,.08)',  iconBg: 'rgba(31,90,166,.12)', icon: _cai ? _cai('info_circle', 28) : '\u2139' },
      };
      var tc = typeColors[opts.type || 'danger'] || typeColors.danger;

      var html = '';
      html += '<div class="aistate-confirm-panel">';
      html += '<div class="aistate-confirm-icon" style="background:' + tc.iconBg + ';color:' + tc.accent + ';">' + tc.icon + '</div>';
      html += '<h3 class="aistate-confirm-title">' + _esc(opts.title || 'Potwierdzenie') + '</h3>';
      html += '<p class="aistate-confirm-msg">' + _esc(opts.message || '') + '</p>';
      if (opts.detail) {
        html += '<p class="aistate-confirm-detail">"' + _esc(opts.detail) + '"</p>';
      }
      if (opts.warning) {
        html += '<p class="aistate-confirm-warning">' + _esc(opts.warning) + '</p>';
      }
      html += '<div class="aistate-confirm-actions">';
      html += '<button class="aistate-confirm-btn aistate-confirm-cancel" type="button">' + _esc(opts.cancelText || 'Anuluj') + '</button>';
      html += '<button class="aistate-confirm-btn aistate-confirm-ok" type="button" style="background:' + tc.accent + ';border-color:' + tc.accent + ';color:#fff;">' + _esc(opts.confirmText || 'OK') + '</button>';
      html += '</div>';
      html += '</div>';

      overlay.innerHTML = html;
      document.body.appendChild(overlay);

      // Animate in
      requestAnimationFrame(function() {
        overlay.classList.add('aistate-confirm-show');
      });

      var cancelBtn = overlay.querySelector('.aistate-confirm-cancel');
      var okBtn = overlay.querySelector('.aistate-confirm-ok');

      function close(result) {
        overlay.classList.remove('aistate-confirm-show');
        overlay.classList.add('aistate-confirm-hide');
        setTimeout(function() {
          try { document.body.removeChild(overlay); } catch(e) {}
        }, 200);
        resolve(result);
      }

      cancelBtn.addEventListener('click', function() { close(false); });
      okBtn.addEventListener('click', function() { close(true); });
      overlay.addEventListener('click', function(e) { if (e.target === overlay) close(false); });

      // Keyboard
      function onKey(e) {
        if (e.key === 'Escape') { close(false); cleanup(); }
        if (e.key === 'Enter') { close(true); cleanup(); }
      }
      function cleanup() { document.removeEventListener('keydown', onKey); }
      document.addEventListener('keydown', onKey);

      // Focus the cancel button (safer default)
      setTimeout(function() { cancelBtn.focus(); }, 50);
    });
  }

  // ===================== FORM VALIDATION =====================

  var _validationRules = {};

  /**
   * Attach inline validation to a form field.
   * @param {string|HTMLElement} field - ID or element
   * @param {Object} rules
   * @param {boolean} [rules.required]
   * @param {number} [rules.minLength]
   * @param {number} [rules.maxLength]
   * @param {RegExp} [rules.pattern]
   * @param {string} [rules.patternMsg]
   * @param {Function} [rules.custom] - (value) => string|null (error msg or null)
   */
  function attachValidation(field, rules) {
    var el = (typeof field === 'string') ? document.getElementById(field) : field;
    if (!el) return;

    // Create hint element
    var hint = document.createElement('div');
    hint.className = 'aistate-field-hint';
    el.parentNode.insertBefore(hint, el.nextSibling);

    function validate() {
      var val = el.value || '';
      var err = null;

      if (rules.required && !val.trim()) {
        err = typeof rules.required === 'string' ? rules.required : 'To pole jest wymagane';
      }
      if (!err && rules.minLength && val.length < rules.minLength) {
        err = 'Min. ' + rules.minLength + ' znaków';
      }
      if (!err && rules.maxLength && val.length > rules.maxLength) {
        err = 'Max. ' + rules.maxLength + ' znaków';
      }
      if (!err && rules.pattern && val && !rules.pattern.test(val)) {
        err = rules.patternMsg || 'Nieprawidłowy format';
      }
      if (!err && rules.custom) {
        err = rules.custom(val);
      }

      if (err) {
        el.classList.add('aistate-field-invalid');
        el.classList.remove('aistate-field-valid');
        hint.textContent = err;
        hint.className = 'aistate-field-hint aistate-field-hint-error';
      } else if (val.trim()) {
        el.classList.remove('aistate-field-invalid');
        el.classList.add('aistate-field-valid');
        hint.textContent = '';
        hint.className = 'aistate-field-hint';
      } else {
        el.classList.remove('aistate-field-invalid', 'aistate-field-valid');
        hint.textContent = '';
        hint.className = 'aistate-field-hint';
      }

      return !err;
    }

    el.addEventListener('input', validate);
    el.addEventListener('blur', validate);
    el._aistateValidate = validate;

    return { validate: validate, hint: hint, element: el };
  }

  /**
   * Create a password strength meter below a password field.
   * @param {string|HTMLElement} field - ID or element
   * @param {string} [policy='basic'] - 'none' | 'basic' | 'medium' | 'strong'
   */
  function attachPasswordMeter(field, policy) {
    var el = (typeof field === 'string') ? document.getElementById(field) : field;
    if (!el) return;
    policy = policy || 'basic';

    var meter = document.createElement('div');
    meter.className = 'aistate-pw-meter';
    meter.innerHTML = '<div class="aistate-pw-bar"><div class="aistate-pw-fill"></div></div><div class="aistate-pw-label"></div><div class="aistate-pw-checks"></div>';
    el.parentNode.insertBefore(meter, el.nextSibling);

    var fill = meter.querySelector('.aistate-pw-fill');
    var label = meter.querySelector('.aistate-pw-label');
    var checks = meter.querySelector('.aistate-pw-checks');

    function update() {
      var pw = el.value || '';
      if (!pw) {
        meter.style.display = 'none';
        return;
      }
      meter.style.display = '';

      var score = 0;
      var reqs = [];

      // Basic: min 8
      var hasLen8 = pw.length >= 8;
      var hasLen12 = pw.length >= 12;
      var hasLower = /[a-z]/.test(pw);
      var hasUpper = /[A-Z]/.test(pw);
      var hasDigit = /\d/.test(pw);
      var hasSpecial = /[^a-zA-Z0-9]/.test(pw);

      if (policy === 'basic' || policy === 'medium' || policy === 'strong') {
        reqs.push({ met: hasLen8, text: 'Min. 8 znaków' });
      }
      if (policy === 'medium' || policy === 'strong') {
        reqs.push({ met: hasLower, text: 'Mała litera (a-z)' });
        reqs.push({ met: hasUpper, text: 'Duża litera (A-Z)' });
        reqs.push({ met: hasDigit, text: 'Cyfra (0-9)' });
      }
      if (policy === 'strong') {
        reqs.push({ met: hasLen12, text: 'Min. 12 znaków' });
        reqs.push({ met: hasSpecial, text: 'Znak specjalny (!@#...)' });
      }

      // Calculate score
      if (hasLen8) score++;
      if (hasLower) score++;
      if (hasUpper) score++;
      if (hasDigit) score++;
      if (hasSpecial) score++;
      if (hasLen12) score++;

      var pct = Math.min(100, Math.round(score / 6 * 100));
      var strength = pct < 33 ? 'weak' : (pct < 66 ? 'medium' : 'strong');

      fill.style.width = pct + '%';
      fill.className = 'aistate-pw-fill aistate-pw-' + strength;

      var labels = { weak: 'Słabe', medium: 'Średnie', strong: 'Silne' };
      label.textContent = labels[strength] || '';
      label.className = 'aistate-pw-label aistate-pw-label-' + strength;

      // Render checks
      checks.innerHTML = '';
      reqs.forEach(function(r) {
        var line = document.createElement('div');
        line.className = 'aistate-pw-check ' + (r.met ? 'aistate-pw-check-ok' : 'aistate-pw-check-fail');
        var _pwAi = typeof aiIcon === 'function' ? aiIcon : null;
        if (_pwAi) {
          line.innerHTML = (r.met ? _pwAi('success', 12) : _pwAi('error', 12)) + ' ' + r.text;
        } else {
          line.textContent = (r.met ? '\u2713 ' : '\u2715 ') + r.text;
        }
        checks.appendChild(line);
      });
    }

    el.addEventListener('input', update);
    el.addEventListener('focus', update);
    update();

    return { update: update, meter: meter };
  }

  /**
   * Validate all fields with _aistateValidate in a container.
   * @param {string|HTMLElement} container - ID or element
   * @returns {boolean} true if all valid
   */
  function validateForm(container) {
    var el = (typeof container === 'string') ? document.getElementById(container) : container;
    if (!el) return true;
    var valid = true;
    el.querySelectorAll('input, textarea, select').forEach(function(field) {
      if (field._aistateValidate) {
        if (!field._aistateValidate()) valid = false;
      }
    });
    return valid;
  }

  // ===================== BREADCRUMBS =====================

  /**
   * Initialize breadcrumbs from a configuration.
   * Reads data-breadcrumbs attribute from <main> or uses page-specific setup.
   */
  function initBreadcrumbs() {
    var bc = document.getElementById('aistate-breadcrumbs');
    if (!bc) return;

    var items = [];
    try {
      var raw = bc.getAttribute('data-items');
      if (raw) items = JSON.parse(raw);
    } catch(e) {}

    if (items.length === 0) return;

    bc.innerHTML = '';
    items.forEach(function(item, idx) {
      if (idx > 0) {
        var sep = document.createElement('span');
        sep.className = 'aistate-bc-sep';
        sep.textContent = '\u203A';
        bc.appendChild(sep);
      }
      if (item.href && idx < items.length - 1) {
        var a = document.createElement('a');
        a.href = item.href;
        a.className = 'aistate-bc-link';
        a.textContent = item.label;
        bc.appendChild(a);
      } else {
        var span = document.createElement('span');
        span.className = 'aistate-bc-current';
        span.textContent = item.label;
        bc.appendChild(span);
      }
    });
  }

  // ===================== BUTTON LOADING STATE =====================

  /**
   * Set a button to loading state and restore after promise resolves.
   * @param {HTMLElement} btn
   * @param {Promise} promise
   * @param {string} [loadingText]
   */
  function withButtonLoading(btn, promise, loadingText) {
    if (!btn || !promise) return promise;
    var original = btn.innerHTML;
    var wasDisabled = btn.disabled;
    btn.disabled = true;
    btn.innerHTML = '<span class="aistate-btn-spinner"></span> ' + (loadingText || original);
    btn.classList.add('aistate-btn-loading');

    return promise.then(function(result) {
      btn.disabled = wasDisabled;
      btn.innerHTML = original;
      btn.classList.remove('aistate-btn-loading');
      return result;
    }).catch(function(err) {
      btn.disabled = wasDisabled;
      btn.innerHTML = original;
      btn.classList.remove('aistate-btn-loading');
      throw err;
    });
  }

  // ===================== HELPERS =====================

  function _esc(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  // ===================== INIT =====================

  document.addEventListener('DOMContentLoaded', function() {
    initBreadcrumbs();
  });

  // ===================== EXPORTS =====================

  window.showToast = showToast;
  window.showConfirm = showConfirm;
  window.attachValidation = attachValidation;
  window.attachPasswordMeter = attachPasswordMeter;
  window.validateForm = validateForm;
  window.withButtonLoading = withButtonLoading;
  window.initBreadcrumbs = initBreadcrumbs;

})();
