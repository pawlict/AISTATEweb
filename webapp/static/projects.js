/* projects.js — Flat project dashboard (no workspace layer) */
(function(){
"use strict";

const API = '/api/workspaces';
let _ws = null;  // the single default workspace (used internally)

function _updateStatusLine(text){
  const el = document.getElementById('projects_status_line');
  if(el) el.textContent = text;
}

// --- Helpers ---
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function shortDate(iso){ return iso ? iso.replace('T',' ').slice(0,16) : '—'; }

async function apiFetch(url, opts){
  const r = await fetch(url, {headers:{'Content-Type':'application/json'}, cache:'no-store', ...opts});
  let j;
  try { j = await r.json(); } catch(_){ throw new Error(`HTTP ${r.status} — nieprawidłowa odpowiedź serwera`); }
  if(!r.ok || j.status === 'error') throw new Error(j.message || j.detail || `HTTP ${r.status}`);
  return j;
}

const TYPE_ICONS = {
  transcription: '<img src="/static/icons/sidebar/transcription.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
  diarization:   '<img src="/static/icons/sidebar/diarization.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
  analysis:      '<img src="/static/icons/sidebar/analysis.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
  chat:          '<img src="/static/icons/sidebar/chat.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
  translation:   '<img src="/static/icons/sidebar/translation.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
  finance:       '<img src="/static/icons/sidebar/finance.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
  general:       '<img src="/static/icons/sidebar/projects.svg" alt="" draggable="false" style="width:18px;height:18px;vertical-align:middle">',
};
const TYPE_LABELS = {
  transcription: 'Transkrypcja', diarization: 'Diaryzacja', analysis: 'Analiza',
  chat: 'Chat', translation: 'Tłumaczenie', finance: 'Finanse', general: 'Ogólny'
};
const TYPE_ROUTES = {
  transcription: '/transcription', diarization: '/diarization', analysis: '/analysis',
  chat: '/chat', translation: '/translation', finance: '/analysis', general: '/projects'
};
const ROLE_LABELS = {
  owner: 'Owner', manager: 'Manager', editor: 'Editor', viewer: 'Viewer'
};

// --- Modal helpers ---
function showModal(id){ document.getElementById(id).style.display = 'flex'; }
function hideModal(id){ document.getElementById(id).style.display = 'none'; }
document.querySelectorAll('.modal-overlay').forEach(m => {
  m.addEventListener('click', e => { if(e.target === m) m.style.display = 'none'; });
});
document.querySelectorAll('.modal-close-x').forEach(b => {
  b.addEventListener('click', () => { b.closest('.modal-overlay').style.display = 'none'; });
});

// --- Type buttons ---
document.querySelectorAll('.sp-type-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sp-type-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

// =====================================================================
// LOAD & RENDER PROJECTS
// =====================================================================

async function loadProjects(){
  try {
    // 1. Load user's OWN workspace (always owner → full permissions)
    const data = await apiFetch(API + '/default');
    _ws = data.workspace;

    // 2. Load ALL workspaces (own + shared) to find shared ones
    let sharedWorkspaces = [];
    try {
      const allData = await apiFetch(API + '?include=subprojects&scope=mine');
      const all = allData.workspaces || [];
      sharedWorkspaces = all.filter(w => w.id !== _ws.id && w.my_role && w.my_role !== 'owner');
    } catch(_){}

    renderProjects(_ws, sharedWorkspaces);
  } catch(e){
    console.error('Load projects error:', e);
    _updateStatusLine('Błąd ładowania');
  }
}

function _renderProjectCard(sp, ws, canEdit){
  const icon = TYPE_ICONS[sp.subproject_type] || aiIcon('document', 18);
  const typeLabel = TYPE_LABELS[sp.subproject_type] || sp.subproject_type;

  // Build team section — owner first, then workspace members + shared members
  const members = ws.members || [];
  const sharedMembers = sp.shared_members || [];
  const owner = members.find(m => m.role === 'owner');
  // Merge workspace members + shared members (deduplicate by user_id)
  const seen = new Set();
  const others = [];
  members.filter(m => m.role !== 'owner').forEach(m => { if(!seen.has(m.user_id)){ seen.add(m.user_id); others.push(m); }});
  sharedMembers.forEach(m => { if(!seen.has(m.user_id)){ seen.add(m.user_id); others.push(m); }});
  let teamHtml = '';
  if(owner){
    const ownerName = owner.display_name || owner.username || owner.name || '?';
    teamHtml += `<div style="font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"><img src="/static/icons/uzytkownicy/user_role.svg" alt="" draggable="false" style="width:12px;height:12px;vertical-align:middle;opacity:.7;margin-right:1px"><b>${esc(ownerName)}</b></div>`;
  }
  if(others.length){
    const shown = others.slice(0, 2);
    const extra = others.length - shown.length;
    const names = shown.map(m => esc(m.display_name || m.username || m.name || '?')).join(', ');
    teamHtml += `<div style="font-size:.65rem;opacity:.55;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${others.map(m=>esc(m.display_name||m.username||'?')+' ('+esc(ROLE_LABELS[m.role]||m.role)+')').join(', ')}">${names}${extra ? ' +' + extra : ''}</div>`;
  }
  if(!members.length && !others.length){
    teamHtml = '<div style="font-size:.7rem;opacity:.35">—</div>';
  }

  const solo = others.length === 0;
  const card = document.createElement('div');
  card.className = 'subcard sp-card' + (solo ? ' sp-solo' : '');
  card.innerHTML = `
    <div class="sp-card-row">
      <div class="sp-card-info">
        <div>${icon} ${esc(sp.name)}</div>
        <div class="small" style="font-size:.7rem;white-space:nowrap">${esc(typeLabel)} · ${shortDate(sp.created_at)}</div>
      </div>
      <div class="sp-card-sep"></div>
      <div class="sp-card-team">
        ${teamHtml}
      </div>
      <div class="sp-card-sep"></div>
      <div class="sp-card-actions">
        <button class="btn pill-icon sp-open" title="Otwórz"><img src="/static/icons/projekty/project_open.svg" alt="Otwórz" draggable="false"></button>
        ${canEdit ? '<button class="btn pill-icon sp-invite" title="Zaproś użytkownika"><img src="/static/icons/uzytkownicy/user_invite.svg" alt="Zaproś" draggable="false"></button>' : ''}
        ${canEdit && others.length ? '<button class="btn pill-icon sp-members" title="Zarządzaj członkami"><img src="/static/icons/uzytkownicy/user_role.svg" alt="Członkowie" draggable="false"></button>' : ''}
        ${canEdit ? '<button class="btn pill-icon sp-del" title="Usuń"><img src="/static/icons/akcje/remove.svg" alt="Usuń" draggable="false"></button>' : ''}
      </div>
    </div>`;

  // Open project
  card.querySelector('.sp-open').addEventListener('click', (e) => {
    e.stopPropagation();
    const dir = sp.data_dir || '';
    const projectId = dir.replace('projects/', '');
    if(projectId) {
      AISTATE.projectId = projectId;
      AISTATE.audioFile = sp.audio_file || '';
      localStorage.setItem('aistate_workspace_id', ws.id);
      localStorage.setItem('aistate_workspace_name', ws.name);
      localStorage.setItem('aistate_subproject_name', sp.name);
      localStorage.setItem('aistate_subproject_type', sp.subproject_type || '');
    }
    const route = TYPE_ROUTES[sp.subproject_type] || '/analysis';
    window.location.href = route;
  });

  // Inline invite
  const invBtn = card.querySelector('.sp-invite');
  if(invBtn) invBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    _openInviteModal(sp.id);
  });

  // Inline manage members (per-project)
  const membersBtn = card.querySelector('.sp-members');
  if(membersBtn) membersBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    _openMembersForProject(sp, others);
  });

  // Inline delete
  const delBtn = card.querySelector('.sp-del');
  if(delBtn) delBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    _openDeleteModalForProject(ws, sp.id);
  });

  // Click card → also open
  card.addEventListener('click', () => { card.querySelector('.sp-open').click(); });

  return card;
}

function renderProjects(ws, sharedWorkspaces){
  sharedWorkspaces = sharedWorkspaces || [];
  const projects = ws.subprojects || [];
  const pList = document.getElementById('projectList');
  const pEmpty = document.getElementById('projectEmpty');
  pList.innerHTML = '';

  // Count all projects (own + shared)
  let sharedCount = 0;
  sharedWorkspaces.forEach(sw => { sharedCount += (sw.subproject_count || 0); });
  const totalCount = projects.length + sharedCount;

  _updateStatusLine(totalCount + ' projekt' + (totalCount === 1 ? '' : (totalCount < 5 ? 'y' : 'ów')));

  if(!projects.length && !sharedWorkspaces.length){ pEmpty.style.display = 'block'; }
  else { pEmpty.style.display = 'none'; }

  // Render own projects
  projects.forEach(sp => {
    pList.appendChild(_renderProjectCard(sp, ws, true));
  });

  // Render shared workspace projects (from workspaces user was invited to)
  sharedWorkspaces.forEach(sw => {
    const subs = sw.subprojects || [];
    if(!subs.length) return;

    const canEdit = sw.my_role === 'owner' || sw.my_role === 'manager' || sw.my_role === 'editor';
    const ownerMember = (sw.members || []).find(m => m.role === 'owner');
    const ownerName = ownerMember ? (ownerMember.display_name || ownerMember.username || '?') : '?';

    // Section header for shared workspace
    const header = document.createElement('div');
    header.style.cssText = 'grid-column:1/-1;margin-top:12px;padding:6px 0;font-size:.78rem;font-weight:600;color:var(--muted,#64748b);display:flex;align-items:center;gap:6px';
    header.innerHTML = '<img src="/static/icons/uzytkownicy/user_invite.svg" alt="" draggable="false" style="width:14px;height:14px;opacity:.6">'
      + esc(ownerName) + ' — ' + esc(sw.name || 'Projekty')
      + ' <span style="font-weight:400;opacity:.7">(' + esc(ROLE_LABELS[sw.my_role] || sw.my_role) + ')</span>';
    pList.appendChild(header);

    subs.forEach(sp => {
      pList.appendChild(_renderProjectCard(sp, sw, canEdit));
    });
  });

  // Populate link-to dropdown in new project modal
  const linkSelect = document.getElementById('npLinkTo');
  if(linkSelect){
    linkSelect.innerHTML = '<option value="">— brak —</option>';
    projects.forEach(sp => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.textContent = sp.name;
      linkSelect.appendChild(opt);
    });
  }

  // Toolbar buttons: always visible for own workspace (user is always owner)
  const btnInvite = document.getElementById('btnInviteUser');
  const btnNew = document.getElementById('btnNewProject');
  if(btnInvite) btnInvite.style.display = '';
  if(btnNew) btnNew.style.display = '';
}

// =====================================================================
// CREATE PROJECT
// =====================================================================

document.getElementById('btnNewProject').addEventListener('click', async () => {
  document.getElementById('npName').value = '';
  document.querySelectorAll('.sp-type-btn').forEach(b => b.classList.remove('active'));
  const firstTypeBtn = document.querySelector('.sp-type-btn');
  if(firstTypeBtn) firstTypeBtn.classList.add('active');
  // Load encryption policy from admin settings
  try {
    const sec = await apiFetch('/api/encryption/policy');
    const row = document.getElementById('npEncryptionRow');
    const cb = document.getElementById('npEncrypted');
    const methodLabel = document.getElementById('npEncMethod');
    if(sec && sec.encryption_enabled){
      row.style.display = '';
      const methods = {light:'AES-128-GCM', standard:'AES-256-GCM', maximum:'AES-256-GCM + ChaCha20-Poly1305'};
      methodLabel.textContent = methods[sec.encryption_method] || sec.encryption_method;
      if(sec.encryption_force_new_projects){
        cb.checked = true;
        cb.disabled = true;
      } else {
        cb.checked = true;
        cb.disabled = false;
      }
    } else {
      row.style.display = 'none';
      cb.checked = false;
    }
  } catch(e){ /* ignore — encryption not available */ }
  showModal('modalNewProject');
  document.getElementById('npName').focus();
});

// Enter key in project name input triggers submit
document.getElementById('npName').addEventListener('keydown', (e) => {
  if(e.key === 'Enter'){
    e.preventDefault();
    document.getElementById('npSubmit').click();
  }
});

document.getElementById('npSubmit').addEventListener('click', async () => {
  if(!_ws){ showToast(t('projects.toast.no_data'),'warning'); return; }
  let name = document.getElementById('npName').value.trim();
  if(!name){ showToast(t('projects.toast.enter_name'),'warning'); return; }
  // Auto-append date+time if name already exists
  const existing = (_ws.subprojects || []).map(s => s.name.toLowerCase());
  if(existing.includes(name.toLowerCase())){
    const now = new Date();
    const ts = now.getFullYear() + '-'
      + String(now.getMonth()+1).padStart(2,'0') + '-'
      + String(now.getDate()).padStart(2,'0') + ' '
      + String(now.getHours()).padStart(2,'0') + ':'
      + String(now.getMinutes()).padStart(2,'0');
    name = name + ' ' + ts;
  }
  const type = document.querySelector('.sp-type-btn.active')?.dataset?.type || 'analysis';
  const linkTo = document.getElementById('npLinkTo').value;
  const encrypted = document.getElementById('npEncrypted')?.checked || false;
  try {
    const data = await apiFetch(API+'/'+_ws.id+'/subprojects', {
      method:'POST', body:JSON.stringify({name, type, link_to:linkTo, encrypted})
    });
    hideModal('modalNewProject');
    showToast(t('projects.toast.created'),'success');

    // Auto-redirect to the matching page for typed projects
    const route = TYPE_ROUTES[type];
    if(route && route !== '/projects'){
      const sp = data.subproject || {};
      const dir = sp.data_dir || '';
      const projectId = dir.replace('projects/', '');
      if(projectId){
        AISTATE.projectId = projectId;
        AISTATE.audioFile = sp.audio_file || '';
        localStorage.setItem('aistate_workspace_id', _ws.id);
        localStorage.setItem('aistate_workspace_name', _ws.name);
        localStorage.setItem('aistate_subproject_name', sp.name || name);
        localStorage.setItem('aistate_subproject_type', type || '');
      }
      window.location.href = route;
      return;
    }
    // For "general" type — stay on projects page
    await loadProjects();
  } catch(e){
    console.error('Create project error:', e);
    showToast(e.message || t('projects.toast.create_error'),'error');
  }
});

// =====================================================================
// INVITE USER
// =====================================================================

/** Open invite modal, optionally pre-selecting a project. */
function _openInviteModal(preSelectProjectId) {
  document.getElementById('invUsername').value = '';
  document.getElementById('invMessage').value = '';
  // Populate project selector
  const sel = document.getElementById('invProject');
  sel.innerHTML = '<option value="">' + t('projects.invite.all_projects') + '</option>';
  if(_ws && _ws.subprojects){
    _ws.subprojects.forEach(sp => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.textContent = sp.name;
      sel.appendChild(opt);
    });
  }
  if(preSelectProjectId) sel.value = preSelectProjectId;
  showModal('modalInviteUser');
  document.getElementById('invUsername').focus();
}

document.getElementById('btnInviteUser').addEventListener('click', () => {
  _openInviteModal(null);
});

// Enter key in invite username input triggers submit
document.getElementById('invUsername').addEventListener('keydown', (e) => {
  if(e.key === 'Enter'){
    e.preventDefault();
    document.getElementById('invSubmit').click();
  }
});

document.getElementById('invSubmit').addEventListener('click', async () => {
  if(!_ws) return;
  const username = document.getElementById('invUsername').value.trim();
  if(!username){ showToast(t('projects.toast.invite_name'),'warning'); return; }
  const role = document.querySelector('input[name="invRole"]:checked')?.value || 'viewer';
  const projSel = document.getElementById('invProject');
  const subproject_id = projSel.value || '';
  const projName = projSel.options[projSel.selectedIndex]?.textContent || '';
  let message = document.getElementById('invMessage').value.trim();
  if(subproject_id && projName){
    message = (message ? message + '\n' : '') + 'Projekt: ' + projName;
  }
  try {
    await apiFetch(API+'/'+_ws.id+'/invite', {
      method:'POST', body:JSON.stringify({username, role, message, subproject_id})
    });
    hideModal('modalInviteUser');
    showToast(t('projects.toast.invite_sent'),'success');
    loadProjects();
  } catch(e){ showToast(e.message,'error'); }
});

// =====================================================================
// MANAGE MEMBERS (per-project)
// =====================================================================

/** Open the members modal filtered for a specific project's shared members. */
function _openMembersForProject(sp, others){
  const list = document.getElementById('memberList');
  const empty = document.getElementById('memberEmpty');
  list.innerHTML = '';
  empty.style.display = 'none';

  document.querySelector('#modalManageMembers .modal-title').textContent = 'Członkowie — ' + (sp.name || '?');
  showModal('modalManageMembers');

  if(!others.length){ empty.style.display = ''; return; }

  others.forEach(m => {
    const name = m.display_name || m.username || m.name || '?';
    const role = ROLE_LABELS[m.role] || m.role || '?';

    const row = document.createElement('div');
    row.className = 'subcard';
    row.style.cssText = 'padding:8px 12px;';
    row.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <div style="min-width:0;flex:1">
          <div style="font-weight:700;font-size:.82rem">${esc(name)}</div>
          <div class="small" style="font-size:.7rem;opacity:.6">${esc(role)}</div>
        </div>
        <button class="btn pill-icon" title="Usuń członka" style="flex-shrink:0" data-uid="${m.user_id}"><img src="/static/icons/akcje/remove.svg" alt="Usuń" draggable="false"></button>
      </div>`;

    row.querySelector('.btn.pill-icon').addEventListener('click', async (e) => {
      e.stopPropagation();
      const userId = e.currentTarget.dataset.uid;
      if(!confirm('Usunąć użytkownika ' + name + '?')) return;
      // Find the sharing workspace that contains this user
      try {
        const data = await apiFetch(API + '/members/all');
        const match = (data.members || []).find(mm => mm.user_id === userId && (mm.project_names || []).some(pn => pn === sp.name));
        if(match){
          await apiFetch(API + '/' + match.workspace_id + '/members/' + userId, {method:'DELETE'});
        }
        showToast('Użytkownik usunięty', 'success');
        row.remove();
        if(!list.children.length) empty.style.display = '';
        loadProjects();
      } catch(err){ showToast(err.message, 'error'); }
    });

    list.appendChild(row);
  });
}

// =====================================================================
// MANAGE MEMBERS (all workspaces)
// =====================================================================

document.getElementById('btnManageMembers').addEventListener('click', async () => {
  document.querySelector('#modalManageMembers .modal-title').textContent = 'Członkowie';
  const list = document.getElementById('memberList');
  const empty = document.getElementById('memberEmpty');
  list.innerHTML = '<div class="small" style="padding:8px;opacity:.5">Ładowanie...</div>';
  empty.style.display = 'none';
  showModal('modalManageMembers');

  try {
    const data = await apiFetch(API + '/members/all');
    const members = data.members || [];
    list.innerHTML = '';
    if(!members.length){
      empty.style.display = '';
      return;
    }
    members.forEach(m => {
      const name = m.display_name || m.username || m.name || '?';
      const role = ROLE_LABELS[m.role] || m.role || '?';
      const projects = (m.project_names || []).join(', ') || '—';
      const wsName = m.workspace_name || '?';

      const row = document.createElement('div');
      row.className = 'subcard';
      row.style.cssText = 'padding:8px 12px;';
      row.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
          <div style="min-width:0;flex:1">
            <div style="font-weight:700;font-size:.82rem">${esc(name)}</div>
            <div class="small" style="font-size:.7rem;opacity:.6">
              ${esc(role)} · ${esc(projects)}
            </div>
          </div>
          <button class="btn danger" style="padding:4px 12px;font-size:.72rem;flex-shrink:0" data-ws="${m.workspace_id}" data-uid="${m.user_id}">Usuń</button>
        </div>`;

      row.querySelector('.btn.danger').addEventListener('click', async (e) => {
        e.stopPropagation();
        const wsId = e.currentTarget.dataset.ws;
        const userId = e.currentTarget.dataset.uid;
        if(!confirm('Usunąć użytkownika ' + name + ' z projektu?')) return;
        try {
          await apiFetch(API + '/' + wsId + '/members/' + userId, {method:'DELETE'});
          showToast('Użytkownik usunięty', 'success');
          row.remove();
          if(!list.children.length) empty.style.display = '';
          loadProjects();
        } catch(err){ showToast(err.message, 'error'); }
      });

      list.appendChild(row);
    });
  } catch(e){
    list.innerHTML = '<div class="small" style="color:red">Błąd: ' + esc(e.message) + '</div>';
  }
});

// =====================================================================
// DELETE PROJECT (with wipe options)
// =====================================================================

/** Open the delete modal with a specific project pre-selected. */
function _openDeleteModalForProject(ws, preSelectId) {
  if(!ws) return;
  const subs = ws.subprojects || [];
  const select = document.getElementById('delProjSelect');
  if(!select) return;
  select.innerHTML = '';
  if(!subs.length){
    showToast(t('projects.toast.no_projects_delete'), 'warning');
    return;
  }
  subs.forEach(sp => {
    const opt = document.createElement('option');
    opt.value = sp.id;
    opt.dataset.dir = sp.data_dir || '';
    opt.textContent = sp.name;
    select.appendChild(opt);
  });
  if(preSelectId) select.value = preSelectId;
  showModal('modalDeleteProject');
}

(function(){
  const btn = document.getElementById('btnDeleteProject');
  const select = document.getElementById('delProjSelect');
  const wipeSelect = document.getElementById('delProjWipeMethod');
  const confirmBtn = document.getElementById('delProjConfirm');
  if(!btn) return;

  btn.addEventListener('click', () => {
    _openDeleteModalForProject(_ws, null);
  });

  if(confirmBtn) confirmBtn.addEventListener('click', async () => {
    if(!_ws || !select.value) return;
    const spId = select.value;
    const sp = (_ws.subprojects||[]).find(s => s.id === spId);
    const wipe = wipeSelect ? wipeSelect.value : 'none';

    if(!confirm(t('projects.confirm_delete').replace('{name}', sp?sp.name:spId))) return;

    try {
      await apiFetch(API + '/' + _ws.id + '/subprojects/' + spId + '?wipe_method=' + encodeURIComponent(wipe), {method:'DELETE'});
      // Clear active project if the deleted one was selected
      const dir = sp ? (sp.data_dir || '') : '';
      const activePid = localStorage.getItem('aistate_project_id') || '';
      if(activePid && (activePid === spId || dir.includes(activePid))){
        localStorage.removeItem('aistate_project_id');
        localStorage.removeItem('aistate_audio_file');
        localStorage.removeItem('aistate_subproject_name');
        if(typeof AISTATE !== 'undefined'){ AISTATE.projectId = ''; AISTATE.audioFile = ''; }
      }
      hideModal('modalDeleteProject');
      showToast(t('projects.toast.deleted'), 'success');
      await loadProjects();
    } catch(err){
      console.error(err);
      showToast(err.message || t('projects.toast.delete_error'), 'error');
    }
  });
})();

// =====================================================================
// EXPORT PROJECT (.aistate)
// =====================================================================

(function(){
  const btn = document.getElementById('btnExportProject');
  const select = document.getElementById('expProjSelect');
  const confirmBtn = document.getElementById('expProjConfirm');
  if(!btn) return;

  btn.addEventListener('click', () => {
    if(!_ws) return;
    const subs = _ws.subprojects || [];
    select.innerHTML = '';
    if(!subs.length){
      showToast(t('projects.toast.no_projects_export'), 'warning');
      return;
    }
    subs.forEach(sp => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.dataset.dir = sp.data_dir || '';
      opt.dataset.name = sp.name || '';
      opt.textContent = sp.name;
      select.appendChild(opt);
    });
    showModal('modalExportProject');
  });

  if(confirmBtn) confirmBtn.addEventListener('click', async () => {
    if(!select.value) return;
    const opt = select.options[select.selectedIndex];
    const dir = (opt.dataset.dir || '').replace('projects/','');
    const fname = (opt.dataset.name || dir || 'project').replace(/[\\\/:*?"<>|]+/g,'_').trim() || 'project';

    if(!dir){
      showToast(t('projects.toast.export_no_data'), 'warning');
      return;
    }

    try {
      const res = await fetch('/api/projects/' + encodeURIComponent(dir) + '/export.aistate');
      if(!res.ok) throw new Error('HTTP ' + res.status);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = fname + '.aistate';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      hideModal('modalExportProject');
      showToast(t('projects.toast.exported'), 'success');
    } catch(err){
      console.error(err);
      showToast(err.message || t('projects.toast.export_error'), 'error');
    }
  });
})();

// =====================================================================
// IMPORT PROJECT (.aistate)
// =====================================================================

(function(){
  const importBtn = document.getElementById('btnImportProject');
  const importInput = document.getElementById('importAistateFile');
  if(!importBtn || !importInput) return;

  importBtn.addEventListener('click', () => importInput.click());

  importInput.addEventListener('change', async (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = '';
    if(!f) return;

    const name = (f.name || '').toLowerCase();
    if(!name.endsWith('.aistate')){
      showToast(t('projects.toast.import_bad_file'), 'error');
      return;
    }

    const fd = new FormData();
    fd.append('file', f);

    try {
      const r = await fetch('/api/projects/import', {method:'POST', body: fd});
      const j = await r.json();
      if(!r.ok) throw new Error(j.message || j.detail || 'Import failed');
      showToast(t('projects.toast.imported'), 'success');
      await loadProjects();
    } catch(err){
      console.error(err);
      showToast(err.message || t('projects.toast.import_error'), 'error');
    }
  });
})();

// =====================================================================
// PENDING INVITATIONS
// =====================================================================

async function loadInvitations(){
  try {
    const data = await apiFetch(API + '/invitations/mine');
    const invitations = data.invitations || [];
    const card = document.getElementById('invitationsCard');
    const list = document.getElementById('invitationList');
    const countBadge = document.getElementById('invitationCount');
    if(!card || !list) return;

    if(!invitations.length){
      card.style.display = 'none';
      return;
    }

    card.style.display = '';
    countBadge.textContent = invitations.length;
    list.innerHTML = '';

    invitations.forEach(inv => {
      const displayName = inv.display_name || inv.workspace_name || '?';
      const inviterName = inv.inviter_name || '?';
      const role = ROLE_LABELS[inv.role] || inv.role || 'viewer';
      const date = shortDate(inv.created_at);
      // Filter out "Projekt: ..." line from displayed message (already shown in title)
      const rawMsg = inv.message || '';
      const filteredMsg = rawMsg.split('\n').filter(l => !l.startsWith('Projekt: ')).join('\n').trim();
      const msg = filteredMsg ? esc(filteredMsg) : '';

      const row = document.createElement('div');
      row.className = 'subcard';
      row.style.cssText = 'padding:10px 14px;';
      row.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap">
          <div style="min-width:0;flex:1">
            <div style="font-weight:700;font-size:.85rem">${esc(displayName)}</div>
            <div class="small" style="font-size:.72rem;opacity:.7">
              ${t('projects.invitations.from') || 'Od'}: <b>${esc(inviterName)}</b> · ${t('projects.invitations.role') || 'Rola'}: <b>${esc(role)}</b> · ${date}
            </div>
            ${msg ? '<div class="small" style="font-size:.72rem;margin-top:2px;opacity:.6;font-style:italic">' + msg + '</div>' : ''}
          </div>
          <div style="display:flex;gap:4px;flex-shrink:0">
            <button class="btn pill-icon inv-accept" title="Zaakceptuj zaproszenie" data-id="${inv.id}"><img src="/static/icons/akcje/accept.svg" alt="Akceptuj" draggable="false"></button>
            <button class="btn pill-icon inv-reject" title="Odrzuć zaproszenie" data-id="${inv.id}"><img src="/static/icons/akcje/remove.svg" alt="Odrzuć" draggable="false"></button>
          </div>
        </div>`;

      row.querySelector('.inv-accept').addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          await apiFetch(API + '/invitations/' + inv.id + '/accept', {method:'POST'});
          showToast(t('projects.invitations.accepted') || 'Zaproszenie zaakceptowane', 'success');
          await Promise.all([loadInvitations(), loadProjects()]);
        } catch(err){ showToast(err.message, 'error'); }
      });

      row.querySelector('.inv-reject').addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          await apiFetch(API + '/invitations/' + inv.id + '/reject', {method:'POST'});
          showToast(t('projects.invitations.rejected') || 'Zaproszenie odrzucone', 'info');
          await loadInvitations();
        } catch(err){ showToast(err.message, 'error'); }
      });

      list.appendChild(row);
    });
  } catch(e){
    console.error('Load invitations error:', e);
  }
}

// =====================================================================
// INIT
// =====================================================================

loadProjects();
loadInvitations();

})();
