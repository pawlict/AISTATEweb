/* users.js — User management panel (Strażnik Dostępu / Główny Opiekun) */
(function(){
  'use strict';

  var allUsers = [];
  var userRoles = [];
  var adminRoles = [];
  var roleModules = {};     // role name → [module keys]
  var adminRoleModules = {}; // admin role → [module keys]
  var editingUserId = null;

  /* Module key → PL/EN labels */
  var MODULE_LABELS = {
    projects:       { pl: 'Projekty',       en: 'Projects' },
    transcription:  { pl: 'Transkrypcja',   en: 'Transcription' },
    diarization:    { pl: 'Diaryzacja',     en: 'Diarization' },
    translation:    { pl: 'Tłumaczenia',    en: 'Translation' },
    analysis:       { pl: 'Analiza',        en: 'Analysis' },
    chat:           { pl: 'Czat / LLM',     en: 'Chat / LLM' },
    admin_settings: { pl: 'Panel admina',   en: 'Admin panel' },
    user_mgmt:      { pl: 'Użytkownicy',   en: 'Users' },
  };

  /* Role name → English translation */
  var ROLE_EN = {
    'Transkryptor':  'Transcriber',
    'Lingwista':     'Linguist',
    'Analityk':      'Analyst',
    'Dialogista':    'Dialogue Spec.',
    'Strateg':       'Strategist',
    'Mistrz Sesji':  'Session Master',
    'G\u0142\u00f3wny Opiekun': 'Main Guardian',
    'Architekt Funkcji': 'Function Architect',
    'Stra\u017cnik Dost\u0119pu':  'Access Guardian',
  };

  /* All module keys in display order */
  var MODULE_ORDER = ['projects','transcription','diarization','translation','analysis','chat','admin_settings','user_mgmt'];

  /* ---- Data loading ---- */

  async function loadRoles() {
    try {
      var res = await fetch('/api/users/roles');
      var data = await res.json();
      if (data.status === 'ok') {
        userRoles = data.user_roles || [];
        adminRoles = data.admin_roles || [];
        roleModules = data.role_modules || {};
        adminRoleModules = data.admin_role_modules || {};
        buildRoleMatrix();
      }
    } catch (e) { /* ignore */ }
  }

  async function loadUsers() {
    try {
      var res = await fetch('/api/users');
      var data = await res.json();
      if (data.status === 'ok') {
        allUsers = data.users || [];
        renderTable();
      }
    } catch (e) { /* ignore */ }
  }

  /* ---- Role-access matrix (CSS Grid) ---- */

  function buildRoleMatrix() {
    var grid = document.getElementById('roleMatrixGrid');
    if (!grid) return;

    var cols = MODULE_ORDER.length + 1; // role name + modules
    grid.style.gridTemplateColumns = 'minmax(120px, auto) ' + MODULE_ORDER.map(function() { return 'minmax(60px, 1fr)'; }).join(' ');
    grid.innerHTML = '';

    /* Helper: add a cell */
    function addCell(html, cls) {
      var cell = document.createElement('div');
      cell.className = 'rm-cell ' + (cls || '');
      cell.innerHTML = html;
      grid.appendChild(cell);
      return cell;
    }

    /* Header row */
    addCell('Rola <span class="en">Role</span>', 'rm-header rm-role-name');
    MODULE_ORDER.forEach(function(mk) {
      var lab = MODULE_LABELS[mk] || { pl: mk, en: mk };
      addCell(esc(lab.pl) + ' <span class="en">' + esc(lab.en) + '</span>', 'rm-header');
    });

    /* Section: User roles */
    var sec1 = addCell('Role użytkowników <span class="en">User roles</span>', 'rm-section');
    sec1.style.gridColumn = '1 / ' + (cols + 1);

    userRoles.forEach(function(role) {
      var mods = roleModules[role] || [];
      var enName = ROLE_EN[role] ? ' <span class="en">' + esc(ROLE_EN[role]) + '</span>' : '';
      addCell(esc(role) + enName, 'rm-role-name');
      MODULE_ORDER.forEach(function(mk) {
        if (mods.indexOf(mk) !== -1) {
          addCell('\u2713', 'rm-check');
        } else {
          addCell('\u2212', 'rm-no');
        }
      });
    });

    /* Section: Admin roles */
    var sec2 = addCell('Role administracyjne <span class="en">Admin roles</span>', 'rm-section');
    sec2.style.gridColumn = '1 / ' + (cols + 1);

    /* Główny Opiekun — all modules */
    addCell('G\u0142\u00f3wny Opiekun <span class="en">Main Guardian</span>', 'rm-role-name');
    MODULE_ORDER.forEach(function() {
      addCell('\u2713', 'rm-check');
    });

    /* Individual admin roles */
    adminRoles.forEach(function(role) {
      var mods = adminRoleModules[role] || [];
      var enName = ROLE_EN[role] ? ' <span class="en">' + esc(ROLE_EN[role]) + '</span>' : '';
      addCell(esc(role) + enName, 'rm-role-name');
      MODULE_ORDER.forEach(function(mk) {
        if (mods.indexOf(mk) !== -1) {
          addCell('\u2713', 'rm-check');
        } else {
          addCell('\u2212', 'rm-no');
        }
      });
    });
  }

  /* ---- Module hints for role selects ---- */

  function showModuleHint(selectId, hintId) {
    var sel = document.getElementById(selectId);
    var hint = document.getElementById(hintId);
    if (!sel || !hint) return;

    function update() {
      var role = sel.value;
      var mods = roleModules[role] || [];
      if (mods.length === 0) { hint.innerHTML = ''; return; }
      var labels = mods.map(function(mk) {
        var lab = MODULE_LABELS[mk];
        return lab ? (lab.pl + ' <span class="en">' + lab.en + '</span>') : mk;
      });
      hint.innerHTML = 'Dostęp do: <span class="en">Access to:</span> ' + labels.join(', ');
    }

    sel.addEventListener('change', update);
    update();
  }

  /* ---- Users table ---- */

  function renderTable() {
    var tbody = document.getElementById('usersBody');
    tbody.innerHTML = '';

    var pendingUsers = allUsers.filter(function(u) { return u.pending; });
    var activeUsers = allUsers.filter(function(u) { return !u.pending; });

    if (pendingUsers.length > 0) {
      var headerTr = document.createElement('tr');
      headerTr.innerHTML = '<td colspan="7" style="background:#fef3c7;color:#92400e;font-weight:600;padding:.6rem .75rem;border-bottom:2px solid #fcd34d;">' +
        'Oczekujące na zatwierdzenie <span class="en">Pending approval</span> (' + pendingUsers.length + ')' +
        '</td>';
      tbody.appendChild(headerTr);

      pendingUsers.forEach(function(u) {
        var tr = document.createElement('tr');
        tr.style.background = '#fffbeb';
        tr.dataset.uid = u.user_id;
        tr.innerHTML =
          '<td style="font-size:.68rem;font-family:monospace;color:var(--muted,#888);white-space:nowrap;" title="' + esc(u.user_id || '') + '">' + esc(_shortUid(u.user_id)) + '</td>' +
          '<td><b>' + esc(u.username) + '</b></td>' +
          '<td>' + esc(u.display_name || '') + '</td>' +
          '<td><span style="color:#d97706;font-style:italic;">Oczekuje <span class="en">Pending</span></span></td>' +
          '<td><span style="color:#d97706;">—</span></td>' +
          '<td style="font-size:.8rem;">' + esc(u.created_at ? u.created_at.replace('T',' ').slice(0,19) : '—') + '</td>' +
          '<td class="actions-cell"></td>';

        var acts = tr.querySelector('.actions-cell');
        acts.appendChild(btn('Zatwierdź', function() { openApproveModal(u); }, '#27ae60'));
        acts.appendChild(btn('Odrzuć', function() { openRejectModal(u); }, '#e74c3c'));

        _attachUserRowDblClick(tr, u);
        tbody.appendChild(tr);
      });

      if (activeUsers.length > 0) {
        var sepTr = document.createElement('tr');
        sepTr.innerHTML = '<td colspan="7" style="padding:.3rem;"></td>';
        tbody.appendChild(sepTr);
      }
    }

    activeUsers.forEach(function(u) {
      var tr = document.createElement('tr');
      tr.dataset.uid = u.user_id;
      var statusBadge = u.banned
        ? '<span style="color:#e74c3c;font-weight:600;">Zbanowany <span class="en">Banned</span></span>'
        : '<span style="color:#27ae60;">Aktywny <span class="en">Active</span></span>';
      if (u.locked_until) {
        var lockDt = new Date(u.locked_until);
        if (lockDt > new Date()) {
          statusBadge += '<br><span style="color:#e67e22;font-weight:600;font-size:.75rem;">\uD83D\uDD12 zablokowane <span class="en">locked</span></span>';
        }
      }
      if (u.password_reset_requested) {
        statusBadge += '<br><span style="color:#e67e22;font-weight:600;font-size:.75rem;">\u26A0 wymagany reset <span class="en">reset required</span></span>';
      }

      var roleText = u.role || '';
      if (u.is_superadmin) roleText = 'G\u0142\u00f3wny Opiekun';
      else if (u.is_admin) roleText = (u.admin_roles || []).join(', ');

      tr.innerHTML =
        '<td style="font-size:.68rem;font-family:monospace;color:var(--muted,#888);white-space:nowrap;" title="' + esc(u.user_id || '') + '">' + esc(_shortUid(u.user_id)) + '</td>' +
        '<td><b>' + esc(u.username) + '</b></td>' +
        '<td>' + esc(u.display_name || '') + '</td>' +
        '<td>' + esc(roleText) + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td style="font-size:.8rem;">' + esc(u.last_login ? u.last_login.replace('T',' ').slice(0,19) : '—') + '</td>' +
        '<td class="actions-cell"></td>';

      var acts = tr.querySelector('.actions-cell');

      if (!u.is_superadmin) {
        acts.appendChild(btn('Zmień rolę', function() { openChangeRoleModal(u); }));
        if (u.banned) {
          acts.appendChild(btn('Odbanuj', function() { unbanUser(u.user_id); }, '#27ae60'));
        } else {
          acts.appendChild(btn('Banuj', function() { openBanModal(u); }, '#e67e22'));
        }
        /* Unlock button for locked accounts */
        if (u.locked_until && new Date(u.locked_until) > new Date()) {
          acts.appendChild(btn('Odblokuj', function() { unlockUser(u.user_id); }, '#3498db'));
        }
        if (u.password_reset_requested) {
          acts.appendChild(btn('\u26A0 Wymagany reset', function() { openResetPwModal(u); }, '#e74c3c'));
        } else {
          acts.appendChild(btn('Reset has\u0142a', function() { openResetPwModal(u); }, '#8e44ad'));
        }
        acts.appendChild(btn('Usuń', function() { openDeleteModal(u); }, '#e74c3c'));
      } else {
        acts.textContent = '—';
      }

      _attachUserRowDblClick(tr, u);
      tbody.appendChild(tr);
    });
  }

  /* Double-click on user row → navigate to Security tab with that user filtered */
  function _attachUserRowDblClick(tr, u) {
    tr.addEventListener('dblclick', function(e) {
      /* Don't trigger on button clicks */
      if (e.target.closest('.actions-cell') || e.target.closest('button')) return;
      _navigateToAuditForUser(u);
    });
  }

  /* Switch to Security tab and apply filter for the given user */
  function _navigateToAuditForUser(u) {
    /* Click the Security tab */
    var secTab = document.querySelector('.users-tab[data-panel="securityPanel"]');
    if (secTab) secTab.click();
    /* Wait for tab to render, then apply the user filter */
    setTimeout(function() {
      _selectUser(u);
    }, 100);
  }

  /* Switch to Users tab and flash/highlight a specific user row */
  function _navigateToUsersForUser(uid) {
    var usersTab = document.querySelector('.users-tab[data-panel="usersPanel"]');
    if (usersTab) usersTab.click();
    setTimeout(function() {
      var row = document.querySelector('#usersBody tr[data-uid="' + uid + '"]');
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.style.background = 'rgba(74,108,247,.18)';
        row.style.transition = 'background 1.5s';
        setTimeout(function() { row.style.background = ''; }, 2000);
      }
    }, 100);
  }

  function btn(text, onClick, bg) {
    var b = document.createElement('button');
    b.textContent = text;
    b.className = 'btn-sm';
    b.style.cssText = 'padding:.25rem .5rem;font-size:.75rem;border:none;border-radius:4px;cursor:pointer;margin-right:.3rem;margin-bottom:.2rem;background:' + (bg || 'var(--accent,#4a6cf7)') + ';color:#fff;';
    b.addEventListener('click', onClick);
    return b;
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  /* ---- Add/Edit Modal ---- */

  function populateRoleSelect(targetId) {
    var sel = document.getElementById(targetId || 'uRole');
    sel.innerHTML = '';
    userRoles.forEach(function(r) {
      var opt = document.createElement('option');
      opt.value = r; opt.textContent = r;
      sel.appendChild(opt);
    });
  }

  function populateAdminChecks(targetId) {
    var checks = document.getElementById(targetId || 'adminRolesChecks');
    checks.innerHTML = '';
    adminRoles.forEach(function(r) {
      var label = document.createElement('label');
      label.style.cssText = 'display:block;cursor:pointer;margin:.2rem 0;';
      var desc = adminRoleModules[r] || [];
      var descLabels = desc.map(function(mk) {
        var lab = MODULE_LABELS[mk];
        return lab ? lab.pl : mk;
      }).join(', ');
      label.innerHTML = '<input type="checkbox" value="' + esc(r) + '"/> ' + esc(r) +
        (descLabels ? ' <span style="font-size:.76rem;color:var(--muted,#999);">(' + esc(descLabels) + ')</span>' : '');
      checks.appendChild(label);
    });
  }

  document.getElementById('uIsAdmin').addEventListener('change', function() {
    document.getElementById('roleSection').style.display = this.checked ? 'none' : '';
    document.getElementById('adminRoleSection').style.display = this.checked ? '' : 'none';
  });

  document.getElementById('btnAddUser').addEventListener('click', function() {
    editingUserId = null;
    document.getElementById('userModalTitle').innerHTML = 'Dodaj użytkownika <span class="en">Add user</span>';
    document.getElementById('uUsername').value = '';
    document.getElementById('uDisplayName').value = '';
    document.getElementById('uPassword').value = '';
    document.getElementById('uIsAdmin').checked = false;
    document.getElementById('uIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect('uRole');
    populateAdminChecks('adminRolesChecks');
    showModuleHint('uRole', 'uRoleModules');
    document.getElementById('userModalError').textContent = '';
    document.getElementById('userModal').style.display = 'flex';
  });

  function openEditModal(u) {
    editingUserId = u.user_id;
    document.getElementById('userModalTitle').innerHTML = 'Edytuj: ' + esc(u.username) + ' <span class="en">Edit</span>';
    document.getElementById('uUsername').value = u.username;
    document.getElementById('uDisplayName').value = u.display_name || '';
    document.getElementById('uPassword').value = '';
    document.getElementById('uIsAdmin').checked = u.is_admin;
    document.getElementById('uIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect('uRole');
    populateAdminChecks('adminRolesChecks');
    if (u.role) document.getElementById('uRole').value = u.role;
    if (u.admin_roles) {
      document.querySelectorAll('#adminRolesChecks input').forEach(function(cb) {
        cb.checked = u.admin_roles.includes(cb.value);
      });
    }
    showModuleHint('uRole', 'uRoleModules');
    document.getElementById('userModalError').textContent = '';
    document.getElementById('userModal').style.display = 'flex';
  }

  document.getElementById('userModalCancel').addEventListener('click', function() {
    document.getElementById('userModal').style.display = 'none';
  });

  document.getElementById('userModalSave').addEventListener('click', async function() {
    var errEl = document.getElementById('userModalError');
    errEl.textContent = '';

    var isAdmin = document.getElementById('uIsAdmin').checked;
    var payload = {
      username: document.getElementById('uUsername').value.trim(),
      display_name: document.getElementById('uDisplayName').value.trim(),
      is_admin: isAdmin,
    };

    var pw = document.getElementById('uPassword').value;
    if (editingUserId) {
      if (pw) payload.password = pw;
    } else {
      payload.password = pw;
    }

    if (isAdmin) {
      payload.admin_roles = [];
      document.querySelectorAll('#adminRolesChecks input:checked').forEach(function(cb) {
        payload.admin_roles.push(cb.value);
      });
    } else {
      payload.role = document.getElementById('uRole').value;
    }

    try {
      var res;
      if (editingUserId) {
        res = await fetch('/api/users/' + editingUserId, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch('/api/users', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
      }
      var data = await res.json();
      if (!res.ok) { errEl.textContent = data.message || 'Error'; return; }
      document.getElementById('userModal').style.display = 'none';
      loadUsers();
    } catch (e) {
      errEl.textContent = 'Connection error';
    }
  });

  /* ---- Change Role Modal ---- */

  var changingRoleUser = null;

  function openChangeRoleModal(u) {
    changingRoleUser = u;
    document.getElementById('crUsername').textContent = u.username;
    document.getElementById('crIsAdmin').checked = u.is_admin;
    document.getElementById('crIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect('crRole');
    populateAdminChecks('crAdminRolesChecks');
    if (u.role) document.getElementById('crRole').value = u.role;
    if (u.admin_roles) {
      document.querySelectorAll('#crAdminRolesChecks input').forEach(function(cb) {
        cb.checked = u.admin_roles.includes(cb.value);
      });
    }
    showModuleHint('crRole', 'crRoleModules');
    document.getElementById('crError').textContent = '';
    document.getElementById('changeRoleModal').style.display = 'flex';
  }

  document.getElementById('crIsAdmin').addEventListener('change', function() {
    document.getElementById('crRoleSection').style.display = this.checked ? 'none' : '';
    document.getElementById('crAdminRoleSection').style.display = this.checked ? '' : 'none';
  });

  document.getElementById('crCancel').addEventListener('click', function() {
    document.getElementById('changeRoleModal').style.display = 'none';
  });

  document.getElementById('crSave').addEventListener('click', async function() {
    if (!changingRoleUser) return;
    var errEl = document.getElementById('crError');
    errEl.textContent = '';

    var isAdmin = document.getElementById('crIsAdmin').checked;
    var payload = { is_admin: isAdmin };

    if (isAdmin) {
      payload.admin_roles = [];
      document.querySelectorAll('#crAdminRolesChecks input:checked').forEach(function(cb) {
        payload.admin_roles.push(cb.value);
      });
      payload.role = null;
    } else {
      payload.role = document.getElementById('crRole').value;
      payload.admin_roles = [];
    }

    try {
      var res = await fetch('/api/users/' + changingRoleUser.user_id, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      var data = await res.json();
      if (!res.ok) { errEl.textContent = data.message || 'Error'; return; }
      document.getElementById('changeRoleModal').style.display = 'none';
      loadUsers();
    } catch (e) {
      errEl.textContent = 'Connection error';
    }
  });

  /* ---- Approve Modal ---- */

  var approvingUser = null;

  function openApproveModal(u) {
    approvingUser = u;
    document.getElementById('approveUsername').textContent = u.username;
    document.getElementById('approveIsAdmin').checked = false;
    document.getElementById('approveIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect('approveRole');
    populateAdminChecks('approveAdminRolesChecks');
    showModuleHint('approveRole', 'approveRoleModules');
    document.getElementById('approveError').textContent = '';
    document.getElementById('approveModal').style.display = 'flex';
  }

  document.getElementById('approveIsAdmin').addEventListener('change', function() {
    document.getElementById('approveRoleSection').style.display = this.checked ? 'none' : '';
    document.getElementById('approveAdminRoleSection').style.display = this.checked ? '' : 'none';
  });

  document.getElementById('approveCancel').addEventListener('click', function() {
    document.getElementById('approveModal').style.display = 'none';
  });

  document.getElementById('approveConfirm').addEventListener('click', async function() {
    if (!approvingUser) return;
    var errEl = document.getElementById('approveError');
    errEl.textContent = '';

    var isAdmin = document.getElementById('approveIsAdmin').checked;
    var payload = { is_admin: isAdmin };

    if (isAdmin) {
      payload.admin_roles = [];
      document.querySelectorAll('#approveAdminRolesChecks input:checked').forEach(function(cb) {
        payload.admin_roles.push(cb.value);
      });
    } else {
      payload.role = document.getElementById('approveRole').value;
    }

    try {
      var res = await fetch('/api/users/' + approvingUser.user_id + '/approve', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      var data = await res.json();
      if (!res.ok) { errEl.textContent = data.message || 'Error'; return; }
      document.getElementById('approveModal').style.display = 'none';
      loadUsers();
    } catch (e) {
      errEl.textContent = 'Connection error';
    }
  });

  /* ---- Reject Modal ---- */

  var rejectingUser = null;

  function openRejectModal(u) {
    rejectingUser = u;
    document.getElementById('rejectMsg').innerHTML = 'Odrzucić rejestrację użytkownika "<b>' + esc(u.username) + '</b>"? Konto zostanie usunięte.<br><span class="en">Reject registration for "' + esc(u.username) + '"? Account will be deleted.</span>';
    document.getElementById('rejectModal').style.display = 'flex';
  }

  document.getElementById('rejectCancel').addEventListener('click', function() {
    document.getElementById('rejectModal').style.display = 'none';
  });

  document.getElementById('rejectConfirm').addEventListener('click', async function() {
    if (!rejectingUser) return;
    try {
      await fetch('/api/users/' + rejectingUser.user_id + '/reject', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
      });
    } catch (e) { /* ignore */ }
    document.getElementById('rejectModal').style.display = 'none';
    loadUsers();
  });

  /* ---- Delete Modal ---- */

  var deletingUserId = null;

  function openDeleteModal(u) {
    deletingUserId = u.user_id;
    document.getElementById('deleteMsg').innerHTML = 'Czy na pewno chcesz usunąć użytkownika "<b>' + esc(u.username) + '</b>"?<br><span class="en">Are you sure you want to delete user "' + esc(u.username) + '"?</span>';
    document.getElementById('deleteModal').style.display = 'flex';
  }

  document.getElementById('deleteCancel').addEventListener('click', function() {
    document.getElementById('deleteModal').style.display = 'none';
  });

  document.getElementById('deleteConfirm').addEventListener('click', async function() {
    if (!deletingUserId) return;
    try {
      await fetch('/api/users/' + deletingUserId, { method: 'DELETE' });
    } catch (e) { /* ignore */ }
    document.getElementById('deleteModal').style.display = 'none';
    loadUsers();
  });

  /* ---- Ban Modal ---- */

  var banningUser = null;

  function openBanModal(u) {
    banningUser = u;
    document.getElementById('banUsername').textContent = u.username;
    document.getElementById('banDuration').value = 'perm';
    document.getElementById('banReason').value = '';
    document.getElementById('banShowExpiry').checked = true;
    document.getElementById('banModal').style.display = 'flex';
  }

  document.getElementById('banCancel').addEventListener('click', function() {
    document.getElementById('banModal').style.display = 'none';
  });

  document.getElementById('banConfirm').addEventListener('click', async function() {
    if (!banningUser) return;
    var reason = document.getElementById('banReason').value.trim();
    var duration = document.getElementById('banDuration').value;
    var until = null;

    if (duration !== 'perm') {
      var now = new Date();
      var ms = 0;
      if (duration === '1h')  ms = 1 * 60 * 60 * 1000;
      if (duration === '6h')  ms = 6 * 60 * 60 * 1000;
      if (duration === '24h') ms = 24 * 60 * 60 * 1000;
      if (duration === '3d')  ms = 3 * 24 * 60 * 60 * 1000;
      if (duration === '7d')  ms = 7 * 24 * 60 * 60 * 1000;
      if (duration === '30d') ms = 30 * 24 * 60 * 60 * 1000;
      until = new Date(now.getTime() + ms).toISOString();
    }

    var showExpiry = document.getElementById('banShowExpiry').checked;

    try {
      await fetch('/api/users/' + banningUser.user_id + '/ban', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ reason: reason, until: until, show_ban_expiry: showExpiry }),
      });
    } catch (e) { /* ignore */ }
    document.getElementById('banModal').style.display = 'none';
    loadUsers();
  });

  async function unbanUser(uid) {
    try {
      await fetch('/api/users/' + uid + '/unban', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
    } catch (e) { /* ignore */ }
    loadUsers();
  }

  /* ---- Reset Password Modal ---- */

  var resetPwUser = null;

  function openResetPwModal(u) {
    resetPwUser = u;
    document.getElementById('rpUsername').textContent = u.username;
    document.getElementById('rpPassword').value = '';
    document.getElementById('rpError').textContent = '';
    document.getElementById('resetPwModal').style.display = 'flex';
  }

  document.getElementById('rpCancel').addEventListener('click', function() {
    document.getElementById('resetPwModal').style.display = 'none';
  });

  document.getElementById('rpConfirm').addEventListener('click', async function() {
    if (!resetPwUser) return;
    var errEl = document.getElementById('rpError');
    errEl.textContent = '';

    var pw = document.getElementById('rpPassword').value;
    if (!pw || pw.length < 6) {
      errEl.textContent = 'Hasło musi mieć min. 6 znaków / Password must be at least 6 characters';
      return;
    }

    try {
      var res = await fetch('/api/users/' + resetPwUser.user_id + '/reset-password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ new_password: pw }),
      });
      var data = await res.json();
      if (!res.ok) { errEl.textContent = data.message || 'Error'; return; }
      document.getElementById('resetPwModal').style.display = 'none';
      loadUsers();
    } catch (e) {
      errEl.textContent = 'Connection error';
    }
  });

  /* ---- Unlock User ---- */

  async function unlockUser(uid) {
    try {
      await fetch('/api/users/' + uid + '/unlock', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
    } catch (e) { /* ignore */ }
    loadUsers();
  }

  /* ---- Audit Log Tab ---- */

  var EVENT_LABELS = {
    'login':             { pl: 'Logowanie', en: 'Login' },
    'login_failed':      { pl: 'Nieudane logowanie', en: 'Failed login' },
    'logout':            { pl: 'Wylogowanie', en: 'Logout' },
    'password_changed':  { pl: 'Zmiana hasła', en: 'Password changed' },
    'password_reset':    { pl: 'Reset hasła', en: 'Password reset' },
    'account_locked':    { pl: 'Konto zablokowane', en: 'Account locked' },
    'account_unlocked':  { pl: 'Konto odblokowane', en: 'Account unlocked' },
    'user_created':      { pl: 'Utworzenie konta', en: 'User created' },
    'user_deleted':      { pl: 'Usunięcie konta', en: 'User deleted' },
    'user_banned':       { pl: 'Ban', en: 'Banned' },
    'user_unbanned':     { pl: 'Odbanowanie', en: 'Unbanned' },
    'user_approved':     { pl: 'Zatwierdzenie', en: 'Approved' },
    'user_rejected':     { pl: 'Odrzucenie', en: 'Rejected' },
    'password_expired_redirect': { pl: 'Hasło wygasło', en: 'Password expired' },
  };

  var EVENT_COLORS = {
    'login': '#27ae60',
    'login_failed': '#e74c3c',
    'logout': '#8e44ad',
    'account_locked': '#e67e22',
    'account_unlocked': '#3498db',
    'user_banned': '#e74c3c',
    'user_deleted': '#e74c3c',
    'password_expired_redirect': '#e67e22',
  };

  function _lang() {
    return (typeof getUiLang === 'function') ? getUiLang() : (localStorage.getItem('aistate_ui_lang') || 'pl');
  }

  var auditData = [];
  var auditFilterUser = '';
  var auditFilterEvent = '';
  var auditOffset = 0;
  var auditTotal = 0;

  async function loadAuditLog() {
    var params = new URLSearchParams();
    if (auditFilterUser) params.set('user_id', auditFilterUser);
    if (auditFilterEvent) params.set('event', auditFilterEvent);
    params.set('limit', '100');
    params.set('offset', String(auditOffset));
    try {
      var res = await fetch('/api/auth/audit?' + params.toString());
      var data = await res.json();
      if (data.status === 'ok') {
        auditData = data.events || [];
        auditTotal = data.total || 0;
        renderAuditLog();
      }
    } catch (e) { /* ignore */ }
  }

  function _formatFingerprint(fp) {
    if (!fp || typeof fp !== 'object') return '';
    var parts = [];
    if (fp.browser) parts.push(fp.browser);
    if (fp.os) parts.push(fp.os);
    if (fp.screen) parts.push(fp.screen);
    if (fp.timezone) parts.push(fp.timezone);
    if (fp.language) parts.push(fp.language);
    return parts.join(' \u00b7 ');
  }

  function _shortUid(uid) {
    if (!uid) return '—';
    /* Show first 8 chars of UUID */
    return uid.length > 8 ? uid.slice(0, 8) + '…' : uid;
  }

  function renderAuditLog() {
    var tbody = document.getElementById('auditBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    var lang = _lang();

    auditData.forEach(function(ev) {
      var tr = document.createElement('tr');
      if (ev.user_id) tr.dataset.uid = ev.user_id;
      var lab = EVENT_LABELS[ev.event] || { pl: ev.event, en: ev.event };
      var color = EVENT_COLORS[ev.event] || 'var(--text, #333)';
      var dt = ev.timestamp ? ev.timestamp.replace('T', ' ').slice(0, 19) : '—';
      var actorInfo = ev.actor_name ? (' <span style="color:var(--muted,#999);font-size:.75rem;">(' + esc(ev.actor_name) + ')</span>') : '';
      var fpText = _formatFingerprint(ev.fingerprint);
      tr.innerHTML =
        '<td style="font-size:.82rem;white-space:nowrap;">' + esc(dt) + '</td>' +
        '<td style="font-size:.72rem;font-family:monospace;color:var(--muted,#888);white-space:nowrap;" title="' + esc(ev.user_id || '') + '">' + esc(_shortUid(ev.user_id)) + '</td>' +
        '<td><b>' + esc(ev.username || '—') + '</b></td>' +
        '<td><span style="color:' + color + ';font-weight:600;">' + esc(lab[lang] || lab.pl) + '</span>' + actorInfo + '</td>' +
        '<td style="font-size:.82rem;">' + esc(ev.ip || '—') + '</td>' +
        '<td style="font-size:.8rem;color:var(--muted,#888);">' + esc(ev.detail || '') + '</td>' +
        '<td style="font-size:.72rem;color:var(--muted,#888);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(fpText) + '">' + esc(fpText || '—') + '</td>';

      /* Click on audit row → show context menu */
      if (ev.user_id && ev.username) {
        tr.addEventListener('click', function(e) {
          _showCtxMenu(e, { user_id: ev.user_id, username: ev.username, display_name: '' });
        });
      }

      tbody.appendChild(tr);
    });

    var info = document.getElementById('auditInfo');
    if (info) {
      var showing = Math.min(auditOffset + 100, auditTotal);
      info.textContent = (auditOffset + 1) + '–' + showing + ' / ' + auditTotal;
    }
  }

  /* Audit tab init (deferred to first click) */
  var auditTabLoaded = false;

  var _auditSelectedUser = null; /* { user_id, username, display_name } or null */

  function _buildAuditLabels() {
    var lang = _lang();

    /* Section heading */
    var heading = document.getElementById('auditHeading');
    if (heading) heading.textContent = lang === 'en' ? 'Login history' : 'Historia logowań';

    /* Labels */
    var ul = document.getElementById('auditUserLabel');
    if (ul) ul.textContent = lang === 'en' ? 'Users' : 'Użytkownicy';
    var el = document.getElementById('auditEventLabel');
    if (el) el.textContent = lang === 'en' ? 'Events' : 'Zdarzenia';

    /* Search placeholder */
    var si = document.getElementById('auditUserSearch');
    if (si) si.placeholder = lang === 'en' ? 'Search by name or UID...' : 'Szukaj po nazwie lub UID...';

    /* Description text */
    var descEl = document.getElementById('auditDescription');
    if (descEl) {
      descEl.innerHTML = lang === 'en'
        ? 'Search by username or paste a UID (e.g. <code style="font-size:.72rem;">3fa85f64-5717...</code>). Select an event type to filter the list. Click a user in results to see their history.'
        : 'Wyszukuj po nazwie użytkownika lub wklej UID (np. <code style="font-size:.72rem;">3fa85f64-5717...</code>). Wybierz typ zdarzenia, aby przefiltrować listę. Kliknij użytkownika w wynikach, aby zobaczyć jego historię.';
    }

    /* Audit table headers */
    var auditThead = document.querySelector('#auditBody')?.closest('table')?.querySelector('thead');
    if (auditThead) {
      var ths = auditThead.querySelectorAll('th');
      var headers = lang === 'en'
        ? ['Date / time', 'UID', 'User', 'Event', 'IP', 'Details', 'Device']
        : ['Data / czas', 'UID', 'Użytkownik', 'Zdarzenie', 'IP', 'Szczegóły', 'Urządzenie'];
      ths.forEach(function(th, i) { if (headers[i]) th.textContent = headers[i]; });
    }

    /* Event filter dropdown */
    var evtSel = document.getElementById('auditEventFilter');
    if (evtSel) {
      var curEvt = evtSel.value;
      evtSel.innerHTML = '';
      var evtAll = document.createElement('option');
      evtAll.value = '';
      evtAll.textContent = lang === 'en' ? 'All events' : 'Wszystkie zdarzenia';
      evtSel.appendChild(evtAll);
      Object.keys(EVENT_LABELS).forEach(function(key) {
        var opt = document.createElement('option');
        opt.value = key;
        opt.textContent = EVENT_LABELS[key][lang] || EVENT_LABELS[key].pl;
        evtSel.appendChild(opt);
      });
      evtSel.value = curEvt || '';
    }
  }

  /* Highlight matching substring in text */
  function _highlight(text, query) {
    if (!query) return esc(text);
    var idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx < 0) return esc(text);
    return esc(text.slice(0, idx)) + '<span class="au-match">' + esc(text.slice(idx, idx + query.length)) + '</span>' + esc(text.slice(idx + query.length));
  }

  function _showUserResults(query) {
    var results = document.getElementById('auditUserResults');
    if (!results) return;
    if (!query) { results.style.display = 'none'; results.innerHTML = ''; return; }

    var q = query.toLowerCase();
    var matches = allUsers.filter(function(u) {
      return u.username.toLowerCase().indexOf(q) >= 0 ||
             (u.display_name && u.display_name.toLowerCase().indexOf(q) >= 0) ||
             (u.user_id && u.user_id.toLowerCase().indexOf(q) >= 0);
    });

    if (matches.length === 0) {
      var lang = _lang();
      results.innerHTML = '<div style="padding:.5rem .6rem;font-size:.8rem;color:var(--muted,#999);">' + (lang === 'en' ? 'No matching users' : 'Brak pasujących użytkowników') + '</div>';
      results.style.display = '';
      return;
    }

    results.innerHTML = '';
    matches.forEach(function(u) {
      var item = document.createElement('div');
      item.className = 'audit-user-item';
      item.dataset.userId = u.user_id;
      item.dataset.username = u.username;
      item.dataset.displayName = u.display_name || '';
      var html = '<span class="au-username">' + _highlight(u.username, query) + '</span>';
      if (u.display_name) {
        html += '<span class="au-display">' + _highlight(u.display_name, query) + '</span>';
      }
      /* Show UID match hint when searching by UID */
      var uidMatch = u.user_id && u.user_id.toLowerCase().indexOf(q) >= 0 &&
                     u.username.toLowerCase().indexOf(q) < 0 &&
                     !(u.display_name && u.display_name.toLowerCase().indexOf(q) >= 0);
      if (uidMatch) {
        html += '<span class="au-display" style="font-family:monospace;font-size:.68rem;">' + _highlight(u.user_id, query) + '</span>';
      }
      item.innerHTML = html;
      item.addEventListener('click', function() {
        _selectUser(u);
      });
      results.appendChild(item);
    });
    results.style.display = '';
  }

  function _selectUser(u) {
    _auditSelectedUser = u;
    auditFilterUser = u.user_id;
    auditOffset = 0;

    /* Show badge */
    var badge = document.getElementById('auditUserActiveFilter');
    var badgeText = document.getElementById('auditUserBadgeText');
    if (badge && badgeText) {
      badgeText.textContent = u.username + (u.display_name ? ' (' + u.display_name + ')' : '');
      badge.style.display = '';
    }

    /* Clear & hide search */
    var si = document.getElementById('auditUserSearch');
    if (si) si.value = '';
    var results = document.getElementById('auditUserResults');
    if (results) { results.style.display = 'none'; results.innerHTML = ''; }

    loadAuditLog();
  }

  function _clearUserFilter() {
    _auditSelectedUser = null;
    auditFilterUser = '';
    auditOffset = 0;

    var badge = document.getElementById('auditUserActiveFilter');
    if (badge) badge.style.display = 'none';
    var si = document.getElementById('auditUserSearch');
    if (si) si.value = '';

    loadAuditLog();
  }

  function initAuditTab() {
    if (auditTabLoaded) {
      _buildAuditLabels();
      return;
    }
    auditTabLoaded = true;

    _buildAuditLabels();

    /* User search — autocomplete */
    var searchInput = document.getElementById('auditUserSearch');
    if (searchInput) {
      searchInput.addEventListener('input', function() {
        _showUserResults(searchInput.value.trim());
      });
      searchInput.addEventListener('focus', function() {
        if (searchInput.value.trim()) _showUserResults(searchInput.value.trim());
      });
      /* Hide results on click outside */
      document.addEventListener('click', function(e) {
        var group = document.querySelector('.audit-filter-group');
        if (group && !group.contains(e.target)) {
          var results = document.getElementById('auditUserResults');
          if (results) { results.style.display = 'none'; }
        }
      });
    }

    /* Clear user filter button */
    var clearBtn = document.getElementById('auditUserClear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function(e) {
        e.preventDefault();
        _clearUserFilter();
      });
    }

    /* Event filter change */
    var evtSel = document.getElementById('auditEventFilter');
    if (evtSel) {
      evtSel.addEventListener('change', function() { auditFilterEvent = evtSel.value; auditOffset = 0; loadAuditLog(); });
    }

    /* Pagination */
    var prevBtn = document.getElementById('auditPrev');
    var nextBtn = document.getElementById('auditNext');
    if (prevBtn) prevBtn.addEventListener('click', function() { auditOffset = Math.max(0, auditOffset - 100); loadAuditLog(); });
    if (nextBtn) nextBtn.addEventListener('click', function() { if (auditOffset + 100 < auditTotal) { auditOffset += 100; loadAuditLog(); } });

    loadAuditLog();
  }

  /* ---- Security Settings Tab ---- */

  async function loadSecuritySettings() {
    try {
      var res = await fetch('/api/settings/security');
      var data = await res.json();
      if (data.status === 'ok') {
        var el;
        el = document.getElementById('secLockoutThreshold');
        if (el) el.value = data.account_lockout_threshold;
        el = document.getElementById('secLockoutDuration');
        if (el) el.value = data.account_lockout_duration;
        el = document.getElementById('secPasswordPolicy');
        if (el) el.value = data.password_policy;
        el = document.getElementById('secPasswordExpiry');
        if (el) el.value = data.password_expiry_days;
        el = document.getElementById('secSessionTimeout');
        if (el) el.value = data.session_timeout_hours;
      }
    } catch (e) { /* ignore */ }
  }

  window.saveSecuritySetting = saveSecuritySetting;
  async function saveSecuritySetting(key, value) {
    var payload = {};
    payload[key] = value;
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      var msg = document.getElementById('secSaveMsg');
      if (msg) { msg.textContent = 'Zapisano / Saved'; setTimeout(function(){ msg.textContent = ''; }, 2000); }
    } catch (e) { /* ignore */ }
  }

  /* ---- Password Blacklist ---- */

  var _blData = null; // { builtin: [], custom: [] }

  window.toggleBlacklist = function() {
    var panel = document.getElementById('blPanel');
    var arrow = document.getElementById('blArrow');
    if (!panel) return;
    var visible = panel.style.display !== 'none';
    panel.style.display = visible ? 'none' : '';
    if (arrow) arrow.classList.toggle('open', !visible);
    if (!visible) loadBlacklist();
  };

  async function loadBlacklist() {
    try {
      var res = await fetch('/api/auth/password-blacklist');
      var data = await res.json();
      if (data.status === 'ok') {
        _blData = { builtin: data.builtin || [], custom: data.custom || [] };
        renderBlacklist();
        updateBlCount();
        // Show builtin file path
        var fp = document.getElementById('blFilePath');
        if (fp && data.builtin_file) {
          fp.textContent = data.builtin_file;
        }
      }
    } catch (e) { /* ignore */ }
  }

  window.reloadBuiltinPasswords = async function() {
    try {
      var res = await fetch('/api/auth/password-blacklist/reload', { method: 'POST' });
      var data = await res.json();
      if (data.status === 'ok') {
        _blMsg('Przeładowano ' + data.builtin_count + ' haseł wbudowanych / Reloaded ' + data.builtin_count + ' built-in passwords', false);
        _blData = null;
        loadBlacklist();
      } else {
        _blMsg(data.message || 'Błąd / Error', true);
      }
    } catch (e) {
      _blMsg('Błąd połączenia / Connection error', true);
    }
  };

  function updateBlCount() {
    var el = document.getElementById('blCount');
    if (el && _blData) {
      el.textContent = (_blData.builtin.length + _blData.custom.length);
    }
  }

  function renderBlacklist() {
    var list = document.getElementById('blList');
    if (!list || !_blData) return;
    var all = [];
    _blData.builtin.forEach(function(p) { all.push({ pw: p, builtin: true }); });
    _blData.custom.forEach(function(p) { all.push({ pw: p, builtin: false }); });
    all.sort(function(a, b) { return a.pw.localeCompare(b.pw); });

    if (all.length === 0) {
      list.innerHTML = '<div class="bl-empty">Brak haseł na liście <span class="en">No passwords on the list</span></div>';
      return;
    }

    var html = '';
    all.forEach(function(item) {
      html += '<div class="bl-item"><span>' + _escBl(item.pw);
      if (item.builtin) {
        html += ' <span class="bl-badge">wbudowane</span>';
      }
      html += '</span>';
      if (!item.builtin) {
        html += '<button class="bl-del" data-pw="' + _escAttr(item.pw) + '" title="Usuń / Remove">&times;</button>';
      }
      html += '</div>';
    });
    list.innerHTML = html;

    list.querySelectorAll('.bl-del').forEach(function(btn) {
      btn.addEventListener('click', function() { removeFromBlacklist(btn.dataset.pw); });
    });
  }

  function _blMsg(text, isError) {
    var el = document.getElementById('blFeedback');
    if (!el) return;
    el.textContent = text;
    el.style.color = isError ? '#e74c3c' : '#27ae60';
    clearTimeout(el._timer);
    el._timer = setTimeout(function() { el.textContent = ''; }, 3500);
  }

  window.addToBlacklist = async function() {
    var inp = document.getElementById('blNewPassword');
    if (!inp) return;
    var pw = inp.value.trim();
    if (!pw) return;

    // Client-side duplicate check
    if (_blData) {
      var lower = pw.toLowerCase();
      var isDupBuiltin = _blData.builtin.indexOf(lower) !== -1;
      var isDupCustom = _blData.custom.indexOf(lower) !== -1;
      if (isDupBuiltin) {
        _blMsg('To hasło jest już na liście wbudowanej / Already on built-in list', true);
        return;
      }
      if (isDupCustom) {
        _blMsg('To hasło jest już na liście / Already on the list', true);
        return;
      }
    }

    try {
      var res = await fetch('/api/auth/password-blacklist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      });
      var data = await res.json();
      if (data.status === 'ok') {
        inp.value = '';
        _blMsg('Dodano hasło / Password added', false);
        _blData = null;
        loadBlacklist();
      } else if (res.status === 409) {
        if (data.message === 'duplicate_builtin') {
          _blMsg('To hasło jest już na liście wbudowanej / Already on built-in list', true);
        } else {
          _blMsg('To hasło jest już na liście / Already on the list', true);
        }
      } else {
        _blMsg(data.message || 'Błąd / Error', true);
      }
    } catch (e) {
      _blMsg('Błąd połączenia / Connection error', true);
    }
  };

  var blInp = document.getElementById('blNewPassword');
  if (blInp) {
    blInp.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); addToBlacklist(); }
    });
  }

  async function removeFromBlacklist(pw) {
    try {
      var res = await fetch('/api/auth/password-blacklist', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      });
      var data = await res.json();
      if (data.status === 'ok') {
        _blData = null;
        loadBlacklist();
      }
    } catch (e) { /* ignore */ }
  }

  function _escBl(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function _escAttr(s) {
    return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;');
  }

  /* ---- Messages Inbox ---- */

  var _inboxLoaded = false;

  window.toggleInbox = function() {
    var panel = document.getElementById('inboxPanel');
    var arrow = document.getElementById('inboxArrow');
    if (!panel) return;
    var visible = panel.style.display !== 'none';
    panel.style.display = visible ? 'none' : '';
    if (arrow) arrow.classList.toggle('open', !visible);
    if (!visible) loadInbox();
  };

  async function loadInbox() {
    var list = document.getElementById('inboxList');
    if (!list) return;
    try {
      var res = await fetch('/api/messages');
      if (!res.ok) {
        /* Non-superadmin: try unread endpoint */
        res = await fetch('/api/messages/unread');
      }
      var data = await res.json();
      if (data.status !== 'ok') return;
      var msgs = data.messages || [];
      _inboxLoaded = true;
      _renderInbox(msgs);
    } catch (e) { /* ignore */ }
  }

  async function loadInboxBadge() {
    var badge = document.getElementById('inboxBadge');
    if (!badge) return;
    try {
      var res = await fetch('/api/messages');
      if (!res.ok) res = await fetch('/api/messages/unread');
      var data = await res.json();
      if (data.status !== 'ok') return;
      var msgs = data.messages || [];
      if (msgs.length > 0) {
        badge.textContent = msgs.length;
        badge.style.display = '';
      } else {
        badge.style.display = 'none';
      }
    } catch (e) { /* ignore */ }
  }

  function _renderInbox(msgs) {
    var list = document.getElementById('inboxList');
    if (!list) return;
    var badge = document.getElementById('inboxBadge');

    if (msgs.length === 0) {
      list.innerHTML = '<div style="color:var(--muted,#999);font-size:.76rem;padding:.3rem;">Brak wiadomości <span class="en">No messages</span></div>';
      if (badge) badge.style.display = 'none';
      return;
    }

    if (badge) {
      badge.textContent = msgs.length;
      badge.style.display = '';
    }

    list.innerHTML = '';
    msgs.forEach(function(m) {
      var item = document.createElement('div');
      item.className = 'inbox-msg unread';
      item.dataset.mid = m.message_id;
      var dt = m.created_at ? m.created_at.replace('T', ' ').slice(0, 16) : '';
      var groups = (m.target_groups || []).join(', ');
      var readCount = (m.read_by || []).length;
      item.innerHTML =
        '<div class="inbox-msg-head">' +
          '<span class="inbox-msg-subj">' + esc(m.subject) + '</span>' +
          '<span class="inbox-msg-meta">' + esc(dt) + '</span>' +
        '</div>' +
        '<div class="inbox-msg-body">' + (m.content || '') + '</div>' +
        '<div class="inbox-msg-meta" style="margin-top:.15rem;">' +
          '&#8594; ' + esc(groups) +
          ' &middot; ' + readCount + ' przeczytało <span class="en">read</span>' +
        '</div>' +
        '<div class="inbox-msg-actions">' +
          '<button class="inbox-msg-btn inbox-mark-read" data-mid="' + m.message_id + '">Oznacz przeczytane <span class="en">Mark read</span></button>' +
          '<button class="inbox-msg-btn inbox-delete" data-mid="' + m.message_id + '" style="color:#e74c3c;">Usuń <span class="en">Delete</span></button>' +
        '</div>';
      list.appendChild(item);
    });

    /* Event handlers */
    list.querySelectorAll('.inbox-mark-read').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        var mid = btn.dataset.mid;
        try {
          await fetch('/api/messages/' + mid + '/read', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
          var card = btn.closest('.inbox-msg');
          if (card) { card.style.opacity = '0'; setTimeout(function() { card.remove(); _updateInboxBadge(); }, 300); }
        } catch (e) { /* ignore */ }
      });
    });

    list.querySelectorAll('.inbox-delete').forEach(function(btn) {
      btn.addEventListener('click', async function() {
        var mid = btn.dataset.mid;
        try {
          await fetch('/api/messages/' + mid, { method: 'DELETE' });
          var card = btn.closest('.inbox-msg');
          if (card) { card.style.opacity = '0'; setTimeout(function() { card.remove(); _updateInboxBadge(); }, 300); }
        } catch (e) { /* ignore */ }
      });
    });

    if (typeof applyBilingualMode === 'function') applyBilingualMode();
  }

  function _updateInboxBadge() {
    var badge = document.getElementById('inboxBadge');
    var list = document.getElementById('inboxList');
    if (!badge || !list) return;
    var remaining = list.querySelectorAll('.inbox-msg').length;
    if (remaining > 0) {
      badge.textContent = remaining;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  }

  /* Load badge count on page load */
  loadInboxBadge();

  /* ---- Context Menu (for audit log rows) ---- */

  var _ctxUser = null;

  function _showCtxMenu(e, user) {
    e.stopPropagation();
    _ctxUser = user;
    var menu = document.getElementById('userContextMenu');
    if (!menu) return;

    /* Header */
    var hdr = document.getElementById('ctxMenuHeader');
    if (hdr) {
      var displayName = user.display_name || '';
      /* Try to find display_name from allUsers if not provided */
      if (!displayName) {
        var found = allUsers.find(function(u) { return u.user_id === user.user_id; });
        if (found) displayName = found.display_name || '';
      }
      hdr.textContent = user.username + (displayName ? ' (' + displayName + ')' : '');
    }

    /* Position the menu near the click */
    menu.style.display = '';
    var mx = e.clientX;
    var my = e.clientY;
    /* Adjust if menu goes off-screen */
    var mw = menu.offsetWidth || 240;
    var mh = menu.offsetHeight || 120;
    if (mx + mw > window.innerWidth) mx = window.innerWidth - mw - 8;
    if (my + mh > window.innerHeight) my = window.innerHeight - mh - 8;
    menu.style.left = mx + 'px';
    menu.style.top = my + 'px';
  }

  function _hideCtxMenu() {
    var menu = document.getElementById('userContextMenu');
    if (menu) menu.style.display = 'none';
    _ctxUser = null;
  }

  /* Close on any click outside */
  document.addEventListener('click', function(e) {
    var menu = document.getElementById('userContextMenu');
    if (menu && menu.style.display !== 'none' && !menu.contains(e.target)) {
      _hideCtxMenu();
    }
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') _hideCtxMenu();
  });

  /* Context menu actions */
  var ctxFilter = document.getElementById('ctxFilterAudit');
  if (ctxFilter) {
    ctxFilter.addEventListener('click', function() {
      if (!_ctxUser) return;
      /* Already on security tab — just apply filter */
      var u = allUsers.find(function(x) { return x.user_id === _ctxUser.user_id; });
      _selectUser(u || _ctxUser);
      _hideCtxMenu();
    });
  }

  var ctxGoUsers = document.getElementById('ctxGoToUsers');
  if (ctxGoUsers) {
    ctxGoUsers.addEventListener('click', function() {
      if (!_ctxUser) return;
      var uid = _ctxUser.user_id;
      _hideCtxMenu();
      _navigateToUsersForUser(uid);
    });
  }

  /* ---- Tabs ---- */

  function initTabs() {
    var tabs = document.querySelectorAll('.users-tab');
    var panels = document.querySelectorAll('.users-panel');

    tabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        tabs.forEach(function(t) { t.classList.remove('active'); });
        panels.forEach(function(p) { p.style.display = 'none'; });
        tab.classList.add('active');
        var target = tab.dataset.panel;
        var panel = document.getElementById(target);
        if (panel) panel.style.display = '';
        if (target === 'securityPanel') { loadSecuritySettings(); initAuditTab(); loadBlacklist(); }
        if (target === 'projectsPanel') { loadAdminProjects(); }
      });
    });
  }

  /* ---- Admin Projects Tab ---- */

  var _adminProjectsLoaded = false;

  function formatSize(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function escHtml(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  var AP_TYPE_ICONS = {
    transcription: '\uD83C\uDFA4', diarization: '\uD83D\uDC65', analysis: '\uD83D\uDCCA',
    chat: '\uD83D\uDCAC', translation: '\uD83C\uDF10', finance: '\uD83C\uDFE6'
  };

  async function loadAdminProjects() {
    if (_adminProjectsLoaded) return;
    var loadingEl = document.getElementById('adminProjectsLoading');
    var listEl = document.getElementById('adminProjectsList');
    var orphanSection = document.getElementById('orphanProjectsSection');
    var orphanList = document.getElementById('orphanProjectsList');
    if (!listEl) return;

    try {
      var res = await fetch('/api/admin/user-projects');
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.message || 'Error');

      if (loadingEl) loadingEl.style.display = 'none';
      listEl.innerHTML = '';

      var users = data.users || [];
      if (!users.length) {
        listEl.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--muted,#888);font-size:.85rem;">Brak projektów</div>';
        _adminProjectsLoaded = true;
        return;
      }

      users.forEach(function(entry) {
        var u = entry.user;
        var card = document.createElement('div');
        card.className = 'ap-user-card';

        // Header
        var header = document.createElement('div');
        header.className = 'ap-user-header';
        header.innerHTML =
          '<div>' +
            '<div class="ap-user-name">' + escHtml(u.display_name || u.username) + ' <span style="font-weight:400;color:var(--muted,#888);font-size:.78rem;">(' + escHtml(u.username) + ')</span></div>' +
            '<div class="ap-user-meta">' +
              '<span>Rola: <b>' + escHtml(u.role || (u.is_superadmin ? 'Główny Opiekun' : 'admin')) + '</b></span>' +
              '<span>' + entry.workspace_count + ' workspace' + (entry.workspace_count !== 1 ? 'ów' : '') + '</span>' +
              '<span>' + entry.project_count + ' projekt' + (entry.project_count !== 1 ? 'ów' : '') + ' (plikowych)</span>' +
            '</div>' +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:.6rem;">' +
            '<span class="ap-size-badge">' + formatSize(entry.total_size) + '</span>' +
            '<span style="font-size:1rem;transition:transform .2s;" class="ap-arrow">&#9654;</span>' +
          '</div>';

        header.addEventListener('click', function() {
          var detail = card.querySelector('.ap-user-detail');
          var arrow = header.querySelector('.ap-arrow');
          if (detail.classList.contains('open')) {
            detail.classList.remove('open');
            arrow.style.transform = '';
          } else {
            detail.classList.add('open');
            arrow.style.transform = 'rotate(90deg)';
          }
        });

        // Detail
        var detail = document.createElement('div');
        detail.className = 'ap-user-detail';

        // Workspaces
        if (entry.workspaces && entry.workspaces.length) {
          detail.innerHTML += '<div class="ap-section-title">Workspace\'y <span class="en">Workspaces</span></div>';
          entry.workspaces.forEach(function(ws) {
            var wsDiv = document.createElement('div');
            wsDiv.className = 'ap-ws-card';
            wsDiv.style.borderLeftColor = ws.color || '#4a6cf7';

            var membersHtml = '';
            if (ws.members && ws.members.length) {
              membersHtml = '<div class="ap-members">Zespół: ' +
                ws.members.map(function(m) {
                  return '<span class="ap-member-chip">' + escHtml(m.username || m.display_name || '?') + ' (' + escHtml(m.role) + ')</span>';
                }).join('') +
                '</div>';
            }

            var subsHtml = '';
            if (ws.subprojects && ws.subprojects.length) {
              subsHtml = '<div style="margin-top:.4rem;">';
              ws.subprojects.forEach(function(sp) {
                var icon = AP_TYPE_ICONS[sp.subproject_type] || '\uD83D\uDCC4';
                subsHtml +=
                  '<div class="ap-sp-item">' +
                    '<span class="ap-sp-icon">' + icon + '</span>' +
                    '<div style="flex:1;">' +
                      '<div class="ap-sp-name">' + escHtml(sp.name) + ' <span style="font-weight:400;color:var(--muted,#888);font-size:.7rem;">(' + escHtml(sp.subproject_type) + ' · ' + escHtml(sp.status || '') + ')</span></div>' +
                      '<div class="ap-sp-path">' + escHtml(sp.dir_path) + '</div>' +
                    '</div>' +
                    '<span class="ap-size-badge">' + formatSize(sp.dir_size) + '</span>' +
                  '</div>';
              });
              subsHtml += '</div>';
            }

            wsDiv.innerHTML =
              '<div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap;">' +
                '<div class="ap-ws-name">' + escHtml(ws.name) + '</div>' +
                '<span style="font-size:.7rem;padding:.15rem .5rem;border-radius:4px;background:' + (ws.status === 'active' ? '#27ae60' : '#888') + ';color:#fff;">' + escHtml(ws.status) + '</span>' +
              '</div>' +
              '<div class="ap-ws-meta">' +
                'ID: <code style="font-size:.68rem;">' + escHtml(ws.id) + '</code>' +
                ' &middot; Utworzony: ' + escHtml((ws.created_at || '').replace('T', ' ').slice(0, 16)) +
                ' &middot; Zaktualizowany: ' + escHtml((ws.updated_at || '').replace('T', ' ').slice(0, 16)) +
                (ws.description ? ' &middot; ' + escHtml(ws.description) : '') +
              '</div>' +
              membersHtml +
              subsHtml;
            detail.appendChild(wsDiv);
          });
        }

        // File-based projects
        if (entry.file_projects && entry.file_projects.length) {
          var fpTitle = document.createElement('div');
          fpTitle.className = 'ap-section-title';
          fpTitle.innerHTML = 'Projekty plikowe <span class="en">File-based projects</span>';
          detail.appendChild(fpTitle);

          entry.file_projects.forEach(function(fp) {
            var fpDiv = document.createElement('div');
            fpDiv.className = 'ap-fp-item';

            var sharesHtml = '';
            if (fp.shares && fp.shares.length) {
              sharesHtml = '<div class="ap-shares">Udostępniony: ' +
                fp.shares.map(function(s) {
                  return '<span class="ap-member-chip">' + escHtml(s.username || s.user_id) + ' (' + escHtml(s.permission || 'read') + ')</span>';
                }).join('') +
                '</div>';
            }

            fpDiv.innerHTML =
              '<div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;">' +
                '<div class="ap-fp-name">' + escHtml(fp.name || fp.project_id) + '</div>' +
                '<span class="ap-size-badge">' + formatSize(fp.dir_size) + '</span>' +
              '</div>' +
              '<div class="ap-fp-meta">' +
                'ID: <code style="font-size:.68rem;">' + escHtml(fp.project_id) + '</code>' +
                ' &middot; Audio: ' + (fp.audio_file ? escHtml(fp.audio_file) + ' (' + formatSize(fp.audio_size) + ')' : '<span style="opacity:.5;">brak</span>') +
                ' &middot; Transkrypcja: ' + (fp.has_transcript ? '<span style="color:#27ae60;">&#10003;</span>' : '<span style="color:#e74c3c;">&#10007;</span>') +
                ' &middot; Diaryzacja: ' + (fp.has_diarized ? '<span style="color:#27ae60;">&#10003;</span>' : '<span style="color:#e74c3c;">&#10007;</span>') +
                ' &middot; Utworzony: ' + escHtml((fp.created_at || '').replace('T', ' ').slice(0, 16)) +
              '</div>' +
              '<div class="ap-fp-path">' + escHtml(fp.dir_path) + '</div>' +
              sharesHtml;
            detail.appendChild(fpDiv);
          });
        }

        card.appendChild(header);
        card.appendChild(detail);
        listEl.appendChild(card);
      });

      // Orphan projects
      var orphans = data.orphan_projects || [];
      if (orphans.length && orphanSection && orphanList) {
        orphanSection.style.display = '';
        orphanList.innerHTML = '';
        orphans.forEach(function(fp) {
          var fpDiv = document.createElement('div');
          fpDiv.className = 'ap-fp-item';
          fpDiv.innerHTML =
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;">' +
              '<div class="ap-fp-name">' + escHtml(fp.name || fp.project_id) + '</div>' +
              '<span class="ap-size-badge">' + formatSize(fp.dir_size) + '</span>' +
            '</div>' +
            '<div class="ap-fp-meta">' +
              'ID: <code style="font-size:.68rem;">' + escHtml(fp.project_id) + '</code>' +
              ' &middot; Audio: ' + (fp.audio_file ? escHtml(fp.audio_file) : '<span style="opacity:.5;">brak</span>') +
            '</div>' +
            '<div class="ap-fp-path">' + escHtml(fp.dir_path) + '</div>';
          orphanList.appendChild(fpDiv);
        });
      }

      _adminProjectsLoaded = true;
    } catch(e) {
      console.error(e);
      if (loadingEl) loadingEl.textContent = 'Błąd ładowania: ' + (e.message || 'Error');
    }
  }

  /* ---- Init ---- */
  initTabs();
  loadRoles().then(function() {
    loadUsers().then(function() {
      if (typeof applyBilingualMode === 'function') applyBilingualMode();
    });
  });

  /* ---- Inline form validation ---- */
  if (typeof attachValidation === 'function') {
    attachValidation('uUsername', { required: true, minLength: 2, maxLength: 64, pattern: /^[a-zA-Z0-9_.\-]+$/, patternMsg: 'Tylko litery, cyfry, _ . -' });
    attachValidation('uPassword', { minLength: 6 });
    attachValidation('rpPassword', { required: true, minLength: 6 });
  }
  if (typeof attachPasswordMeter === 'function') {
    attachPasswordMeter('uPassword', 'basic');
    attachPasswordMeter('rpPassword', 'basic');
  }
})();
