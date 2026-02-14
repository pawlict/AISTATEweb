/* users.js — User management panel (Strażnik Dostępu / Super Admin) */
(function(){
  'use strict';

  let allUsers = [];
  let userRoles = [];
  let adminRoles = [];
  let editingUserId = null;

  async function loadRoles() {
    try {
      const res = await fetch('/api/users/roles');
      const data = await res.json();
      if (data.status === 'ok') {
        userRoles = data.user_roles || [];
        adminRoles = data.admin_roles || [];
      }
    } catch (e) { /* ignore */ }
  }

  async function loadUsers() {
    try {
      const res = await fetch('/api/users');
      const data = await res.json();
      if (data.status === 'ok') {
        allUsers = data.users || [];
        renderTable();
      }
    } catch (e) { /* ignore */ }
  }

  function renderTable() {
    const tbody = document.getElementById('usersBody');
    tbody.innerHTML = '';

    // Separate pending and active users
    var pendingUsers = allUsers.filter(function(u) { return u.pending; });
    var activeUsers = allUsers.filter(function(u) { return !u.pending; });

    // Render pending section if any
    if (pendingUsers.length > 0) {
      var headerTr = document.createElement('tr');
      headerTr.innerHTML = '<td colspan="6" style="background:#fef3c7;color:#92400e;font-weight:600;padding:.6rem .75rem;border-bottom:2px solid #fcd34d;">' +
        'Oczekujące na zatwierdzenie (' + pendingUsers.length + ')' +
        '</td>';
      tbody.appendChild(headerTr);

      pendingUsers.forEach(function(u) {
        var tr = document.createElement('tr');
        tr.style.background = '#fffbeb';
        tr.innerHTML =
          '<td><b>' + esc(u.username) + '</b></td>' +
          '<td>' + esc(u.display_name || '') + '</td>' +
          '<td><span style="color:#d97706;font-style:italic;">Oczekuje</span></td>' +
          '<td><span style="color:#d97706;">Pending</span></td>' +
          '<td style="font-size:.8rem;">' + esc(u.created_at ? u.created_at.replace('T',' ').slice(0,19) : '—') + '</td>' +
          '<td class="actions-cell"></td>';

        var acts = tr.querySelector('.actions-cell');
        acts.appendChild(btn('Zatwierdź', function() { openApproveModal(u); }, '#27ae60'));
        acts.appendChild(btn('Odrzuć', function() { openRejectModal(u); }, '#e74c3c'));

        tbody.appendChild(tr);
      });

      // Separator
      if (activeUsers.length > 0) {
        var sepTr = document.createElement('tr');
        sepTr.innerHTML = '<td colspan="6" style="padding:.3rem;"></td>';
        tbody.appendChild(sepTr);
      }
    }

    // Render active users
    activeUsers.forEach(function(u) {
      var tr = document.createElement('tr');
      var statusBadge = u.banned
        ? '<span style="color:#e74c3c;font-weight:600;">Zbanowany</span>'
        : '<span style="color:#27ae60;">Aktywny</span>';

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
        var editBtn = btn('Edytuj', function() { openEditModal(u); });
        acts.appendChild(editBtn);

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

  // --- Add/Edit Modal ---

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
      label.innerHTML = '<input type="checkbox" value="' + esc(r) + '"/> ' + esc(r);
      checks.appendChild(label);
    });
  }

  document.getElementById('uIsAdmin').addEventListener('change', function() {
    document.getElementById('roleSection').style.display = this.checked ? 'none' : '';
    document.getElementById('adminRoleSection').style.display = this.checked ? '' : 'none';
  });

  document.getElementById('btnAddUser').addEventListener('click', function() {
    editingUserId = null;
    document.getElementById('userModalTitle').textContent = 'Dodaj użytkownika';
    document.getElementById('uUsername').value = '';
    document.getElementById('uDisplayName').value = '';
    document.getElementById('uPassword').value = '';
    document.getElementById('uIsAdmin').checked = false;
    document.getElementById('uIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect('uRole');
    populateAdminChecks('adminRolesChecks');
    document.getElementById('userModalError').textContent = '';
    document.getElementById('userModal').style.display = 'flex';
  });

  function openEditModal(u) {
    editingUserId = u.user_id;
    document.getElementById('userModalTitle').textContent = 'Edytuj: ' + u.username;
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

  // --- Approve Modal ---

  var approvingUser = null;

  function openApproveModal(u) {
    approvingUser = u;
    document.getElementById('approveUsername').textContent = u.username;
    document.getElementById('approveIsAdmin').checked = false;
    document.getElementById('approveIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect('approveRole');
    populateAdminChecks('approveAdminRolesChecks');
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

  // --- Reject Modal ---

  var rejectingUser = null;

  function openRejectModal(u) {
    rejectingUser = u;
    document.getElementById('rejectMsg').textContent = 'Odrzucić rejestrację użytkownika "' + u.username + '"? Konto zostanie usunięte.';
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

  // --- Delete Modal ---

  var deletingUserId = null;

  function openDeleteModal(u) {
    deletingUserId = u.user_id;
    document.getElementById('deleteMsg').textContent = 'Czy na pewno chcesz usunąć użytkownika "' + u.username + '"?';
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

  // --- Ban Modal ---

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
    var pw = prompt('Nowe hasło (min. 6 znaków):');
    if (!pw || pw.length < 6) { alert('Hasło musi mieć min. 6 znaków'); return; }
    try {
      var res = await fetch('/api/users/' + uid + '/reset-password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ new_password: pw }),
      });
      var data = await res.json();
      if (res.ok) alert('Hasło zmienione');
      else alert(data.message || 'Error');
    } catch (e) { alert('Connection error'); }
  }

  // --- Init ---
  loadRoles().then(function() { loadUsers(); });
})();
