/* users.js — User management panel (Strażnik Dostępu / Super Admin) */
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

  /* ---- Role-access matrix table ---- */

  function buildRoleMatrix() {
    var thead = document.getElementById('roleMatrixHead');
    var tbody = document.getElementById('roleMatrixBody');
    if (!thead || !tbody) return;

    /* Header row: Rola | Module1 | Module2 | ... */
    thead.innerHTML = '<th>Rola <br><span class="en">Role</span></th>';
    MODULE_ORDER.forEach(function(mk) {
      var lab = MODULE_LABELS[mk] || { pl: mk, en: mk };
      thead.innerHTML += '<th>' + esc(lab.pl) + '<br><span class="en">' + esc(lab.en) + '</span></th>';
    });

    /* Body: one row per user role */
    tbody.innerHTML = '';
    userRoles.forEach(function(role) {
      var mods = roleModules[role] || [];
      var tr = document.createElement('tr');
      tr.innerHTML = '<td>' + esc(role) + '</td>';
      MODULE_ORDER.forEach(function(mk) {
        if (mods.indexOf(mk) !== -1) {
          tr.innerHTML += '<td class="check">&#10003;</td>';
        } else {
          tr.innerHTML += '<td class="dash">—</td>';
        }
      });
      tbody.appendChild(tr);
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
      headerTr.innerHTML = '<td colspan="6" style="background:#fef3c7;color:#92400e;font-weight:600;padding:.6rem .75rem;border-bottom:2px solid #fcd34d;">' +
        'Oczekujące na zatwierdzenie <span class="en">Pending approval</span> (' + pendingUsers.length + ')' +
        '</td>';
      tbody.appendChild(headerTr);

      pendingUsers.forEach(function(u) {
        var tr = document.createElement('tr');
        tr.style.background = '#fffbeb';
        tr.innerHTML =
          '<td><b>' + esc(u.username) + '</b></td>' +
          '<td>' + esc(u.display_name || '') + '</td>' +
          '<td><span style="color:#d97706;font-style:italic;">Oczekuje <span class="en">Pending</span></span></td>' +
          '<td><span style="color:#d97706;">—</span></td>' +
          '<td style="font-size:.8rem;">' + esc(u.created_at ? u.created_at.replace('T',' ').slice(0,19) : '—') + '</td>' +
          '<td class="actions-cell"></td>';

        var acts = tr.querySelector('.actions-cell');
        acts.appendChild(btn('Zatwierdź', function() { openApproveModal(u); }, '#27ae60'));
        acts.appendChild(btn('Odrzuć', function() { openRejectModal(u); }, '#e74c3c'));

        tbody.appendChild(tr);
      });

      if (activeUsers.length > 0) {
        var sepTr = document.createElement('tr');
        sepTr.innerHTML = '<td colspan="6" style="padding:.3rem;"></td>';
        tbody.appendChild(sepTr);
      }
    }

    activeUsers.forEach(function(u) {
      var tr = document.createElement('tr');
      var statusBadge = u.banned
        ? '<span style="color:#e74c3c;font-weight:600;">Zbanowany <span class="en">Banned</span></span>'
        : '<span style="color:#27ae60;">Aktywny <span class="en">Active</span></span>';

      var roleText = u.role || '';
      if (u.is_superadmin) roleText = 'Super Admin';
      else if (u.is_admin) roleText = (u.admin_roles || []).join(', ');

      tr.innerHTML =
        '<td><b>' + esc(u.username) + '</b></td>' +
        '<td>' + esc(u.display_name || '') + '</td>' +
        '<td>' + esc(roleText) + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td style="font-size:.8rem;">' + esc(u.last_login ? u.last_login.replace('T',' ').slice(0,19) : '—') + '</td>' +
        '<td class="actions-cell"></td>';

      var acts = tr.querySelector('.actions-cell');

      if (!u.is_superadmin) {
        acts.appendChild(btn('Edytuj', function() { openEditModal(u); }));
        if (u.banned) {
          acts.appendChild(btn('Odbanuj', function() { unbanUser(u.user_id); }));
        } else {
          acts.appendChild(btn('Ban', function() { openBanModal(u.user_id); }, '#e67e22'));
        }
        acts.appendChild(btn('Reset hasła', function() { resetPassword(u.user_id); }));
        acts.appendChild(btn('Usuń', function() { openDeleteModal(u); }, '#e74c3c'));
      } else {
        acts.textContent = '—';
      }

      tbody.appendChild(tr);
    });
  }

  function btn(text, onClick, bg) {
    var b = document.createElement('button');
    b.textContent = text;
    b.className = 'btn-sm';
    b.style.cssText = 'padding:.25rem .5rem;font-size:.75rem;border:none;border-radius:4px;cursor:pointer;margin-right:.3rem;background:' + (bg || 'var(--accent,#4a6cf7)') + ';color:#fff;';
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

  var banningUserId = null;

  function openBanModal(uid) {
    banningUserId = uid;
    document.getElementById('banReason').value = '';
    document.getElementById('banUntil').value = '';
    document.getElementById('banModal').style.display = 'flex';
  }

  document.getElementById('banCancel').addEventListener('click', function() {
    document.getElementById('banModal').style.display = 'none';
  });

  document.getElementById('banConfirm').addEventListener('click', async function() {
    if (!banningUserId) return;
    var reason = document.getElementById('banReason').value.trim();
    var until = document.getElementById('banUntil').value || null;
    try {
      await fetch('/api/users/' + banningUserId + '/ban', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ reason: reason, until: until }),
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

  async function resetPassword(uid) {
    var pw = prompt('Nowe hasło (min. 6 znaków) / New password (min. 6 chars):');
    if (!pw || pw.length < 6) { alert('Hasło musi mieć min. 6 znaków / Password must be at least 6 characters'); return; }
    try {
      var res = await fetch('/api/users/' + uid + '/reset-password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ new_password: pw }),
      });
      var data = await res.json();
      if (res.ok) alert('Hasło zmienione / Password changed');
      else alert(data.message || 'Error');
    } catch (e) { alert('Connection error'); }
  }

  /* ---- Init ---- */
  loadRoles().then(function() { loadUsers(); });
})();
