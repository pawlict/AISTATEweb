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
    allUsers.forEach(u => {
      const tr = document.createElement('tr');
      const statusBadge = u.banned
        ? '<span style="color:#e74c3c;font-weight:600;">Zbanowany</span>'
        : '<span style="color:#27ae60;">Aktywny</span>';

      let roleText = u.role || '';
      if (u.is_superadmin) roleText = 'Super Admin';
      else if (u.is_admin) roleText = (u.admin_roles || []).join(', ');

      tr.innerHTML =
        '<td><b>' + esc(u.username) + '</b></td>' +
        '<td>' + esc(u.display_name || '') + '</td>' +
        '<td>' + esc(roleText) + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td style="font-size:.8rem;">' + esc(u.last_login ? u.last_login.replace('T',' ').slice(0,19) : '—') + '</td>' +
        '<td class="actions-cell"></td>';

      const acts = tr.querySelector('.actions-cell');

      if (!u.is_superadmin) {
        const editBtn = btn('Edytuj', () => openEditModal(u));
        acts.appendChild(editBtn);

        if (u.banned) {
          acts.appendChild(btn('Odbanuj', () => unbanUser(u.user_id)));
        } else {
          acts.appendChild(btn('Ban', () => openBanModal(u.user_id), '#e67e22'));
        }

        acts.appendChild(btn('Reset hasła', () => resetPassword(u.user_id)));
        acts.appendChild(btn('Usuń', () => openDeleteModal(u), '#e74c3c'));
      } else {
        acts.textContent = '—';
      }

      tbody.appendChild(tr);
    });
  }

  function btn(text, onClick, bg) {
    const b = document.createElement('button');
    b.textContent = text;
    b.className = 'btn-sm';
    b.style.cssText = 'padding:.25rem .5rem;font-size:.75rem;border:none;border-radius:4px;cursor:pointer;margin-right:.3rem;background:' + (bg || 'var(--accent,#4a6cf7)') + ';color:#fff;';
    b.addEventListener('click', onClick);
    return b;
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // --- Add/Edit Modal ---

  function populateRoleSelect() {
    const sel = document.getElementById('uRole');
    sel.innerHTML = '';
    userRoles.forEach(r => {
      const opt = document.createElement('option');
      opt.value = r; opt.textContent = r;
      sel.appendChild(opt);
    });
    const checks = document.getElementById('adminRolesChecks');
    checks.innerHTML = '';
    adminRoles.forEach(r => {
      const label = document.createElement('label');
      label.style.cssText = 'display:block;cursor:pointer;margin:.2rem 0;';
      label.innerHTML = '<input type="checkbox" value="' + esc(r) + '"/> ' + esc(r);
      checks.appendChild(label);
    });
  }

  document.getElementById('uIsAdmin').addEventListener('change', function() {
    document.getElementById('roleSection').style.display = this.checked ? 'none' : '';
    document.getElementById('adminRoleSection').style.display = this.checked ? '' : 'none';
  });

  document.getElementById('btnAddUser').addEventListener('click', () => {
    editingUserId = null;
    document.getElementById('userModalTitle').textContent = 'Dodaj użytkownika';
    document.getElementById('uUsername').value = '';
    document.getElementById('uDisplayName').value = '';
    document.getElementById('uPassword').value = '';
    document.getElementById('uIsAdmin').checked = false;
    document.getElementById('uIsAdmin').dispatchEvent(new Event('change'));
    populateRoleSelect();
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
    populateRoleSelect();
    if (u.role) document.getElementById('uRole').value = u.role;
    if (u.admin_roles) {
      document.querySelectorAll('#adminRolesChecks input').forEach(cb => {
        cb.checked = u.admin_roles.includes(cb.value);
      });
    }
    document.getElementById('userModalError').textContent = '';
    document.getElementById('userModal').style.display = 'flex';
  }

  document.getElementById('userModalCancel').addEventListener('click', () => {
    document.getElementById('userModal').style.display = 'none';
  });

  document.getElementById('userModalSave').addEventListener('click', async () => {
    const errEl = document.getElementById('userModalError');
    errEl.textContent = '';

    const isAdmin = document.getElementById('uIsAdmin').checked;
    const payload = {
      username: document.getElementById('uUsername').value.trim(),
      display_name: document.getElementById('uDisplayName').value.trim(),
      is_admin: isAdmin,
    };

    const pw = document.getElementById('uPassword').value;
    if (editingUserId) {
      if (pw) payload.password = pw;
    } else {
      payload.password = pw;
    }

    if (isAdmin) {
      payload.admin_roles = [];
      document.querySelectorAll('#adminRolesChecks input:checked').forEach(cb => {
        payload.admin_roles.push(cb.value);
      });
    } else {
      payload.role = document.getElementById('uRole').value;
    }

    try {
      let res;
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
      const data = await res.json();
      if (!res.ok) { errEl.textContent = data.message || 'Error'; return; }
      document.getElementById('userModal').style.display = 'none';
      loadUsers();
    } catch (e) {
      errEl.textContent = 'Connection error';
    }
  });

  // --- Delete Modal ---

  let deletingUserId = null;

  function openDeleteModal(u) {
    deletingUserId = u.user_id;
    document.getElementById('deleteMsg').textContent = 'Czy na pewno chcesz usunąć użytkownika "' + u.username + '"?';
    document.getElementById('deleteModal').style.display = 'flex';
  }

  document.getElementById('deleteCancel').addEventListener('click', () => {
    document.getElementById('deleteModal').style.display = 'none';
  });

  document.getElementById('deleteConfirm').addEventListener('click', async () => {
    if (!deletingUserId) return;
    try {
      await fetch('/api/users/' + deletingUserId, { method: 'DELETE' });
    } catch (e) { /* ignore */ }
    document.getElementById('deleteModal').style.display = 'none';
    loadUsers();
  });

  // --- Ban Modal ---

  let banningUserId = null;

  function openBanModal(uid) {
    banningUserId = uid;
    document.getElementById('banReason').value = '';
    document.getElementById('banUntil').value = '';
    document.getElementById('banModal').style.display = 'flex';
  }

  document.getElementById('banCancel').addEventListener('click', () => {
    document.getElementById('banModal').style.display = 'none';
  });

  document.getElementById('banConfirm').addEventListener('click', async () => {
    if (!banningUserId) return;
    const reason = document.getElementById('banReason').value.trim();
    const until = document.getElementById('banUntil').value || null;
    try {
      await fetch('/api/users/' + banningUserId + '/ban', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ reason, until }),
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
    const pw = prompt('Nowe hasło (min. 6 znaków):');
    if (!pw || pw.length < 6) { alert('Hasło musi mieć min. 6 znaków'); return; }
    try {
      const res = await fetch('/api/users/' + uid + '/reset-password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ new_password: pw }),
      });
      const data = await res.json();
      if (res.ok) alert('Hasło zmienione');
      else alert(data.message || 'Error');
    } catch (e) { alert('Connection error'); }
  }

  // --- Init ---
  loadRoles().then(() => loadUsers());
})();
