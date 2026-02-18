/* projects.js — Workspace dashboard frontend logic */
(function(){
"use strict";

const API = '/api/workspaces';
let _currentWs = null;  // workspace detail being viewed
let _activeCount = 0;
let _archivedCount = 0;

// --- Toolbar view toggle ---
const _toolbarListEls = ['toolbarListActions'];
const _toolbarDetailEls = ['toolbarDetailActions','toolbarDetailSep1','toolbarDetailActions2','toolbarDetailSep2','toolbarDetailActions3'];

function _setView(mode){
  const isList = mode === 'list';
  document.getElementById('viewWorkspaceList').style.display = isList ? 'block' : 'none';
  document.getElementById('viewWorkspaceDetail').style.display = isList ? 'none' : 'block';
  _toolbarListEls.forEach(id => { const el = document.getElementById(id); if(el) el.style.display = isList ? '' : 'none'; });
  _toolbarDetailEls.forEach(id => { const el = document.getElementById(id); if(el) el.style.display = isList ? 'none' : ''; });
}

function _updateStatusLine(text){
  const el = document.getElementById('projects_status_line');
  if(el) el.textContent = text;
}

// --- Helpers ---
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function shortDate(iso){ return iso ? iso.replace('T',' ').slice(0,16) : '—'; }

async function apiFetch(url, opts){
  const r = await fetch(url, {headers:{'Content-Type':'application/json'}, ...opts});
  let j;
  try { j = await r.json(); } catch(_){ throw new Error(`HTTP ${r.status} — nieprawidłowa odpowiedź serwera`); }
  if(!r.ok || j.status === 'error') throw new Error(j.message || j.detail || `HTTP ${r.status}`);
  return j;
}

const TYPE_ICONS = {
  transcription: aiIcon('transcription', 18),
  diarization:   aiIcon('diarization', 18),
  analysis:      aiIcon('brain', 18),
  chat:          aiIcon('robot', 18),
  translation:   aiIcon('globe', 18),
  finance:       aiIcon('finance', 18),
  general:       aiIcon('document', 18),
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
  owner: 'Owner', manager: 'Manager', editor: 'Editor', commenter: 'Commenter', viewer: 'Viewer'
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

// --- Color chips ---
document.querySelectorAll('#nwColors .color-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('#nwColors .color-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
  });
});

// --- Type buttons ---
document.querySelectorAll('.sp-type-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sp-type-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

// =====================================================================
// WORKSPACE LIST
// =====================================================================

async function loadWorkspaces(){
  try {
    const data = await apiFetch(API);
    renderWorkspaceList(data.workspaces || []);
  } catch(e) {
    console.error(e);
  }
  loadInvitations();
  loadArchivedWorkspaces();
}

function renderWorkspaceList(workspaces){
  const list = document.getElementById('workspaceList');
  const empty = document.getElementById('workspaceEmpty');
  list.innerHTML = '';
  _activeCount = workspaces.length;
  _updateStatusLine(_activeCount + ' aktywnych' + (_archivedCount ? ', ' + _archivedCount + ' w archiwum' : ''));
  if(!workspaces.length){ empty.style.display = 'block'; return; }
  empty.style.display = 'none';

  workspaces.forEach(ws => {
    const role = ws.my_role ? `<span style="font-size:.68rem;padding:1px 6px;border-radius:4px;background:${ws.my_role==='owner'?'var(--accent)':'#888'};color:#fff;font-weight:600">${ROLE_LABELS[ws.my_role]||ws.my_role}</span>` : '';
    const card = document.createElement('div');
    card.className = 'ws-card';
    card.style.cssText = 'cursor:pointer;border-left:3px solid '+esc(ws.color||'#4a6cf7');
    card.innerHTML = `
      <span class="ws-card-chevron">&#9654;</span>
      <div class="ws-card-name">${esc(ws.name)}</div>
      <div class="ws-card-info small">${ws.subproject_count||0} podpr. · ${ws.member_count||1} czł. · ${shortDate(ws.updated_at)} ${role}</div>
    `;
    card.addEventListener('click', () => openWorkspace(ws.id));
    list.appendChild(card);
  });
}

async function loadInvitations(){
  try {
    const data = await apiFetch(API + '/invitations/mine');
    const invs = data.invitations || [];
    const section = document.getElementById('invitationsSection');
    const list = document.getElementById('invitationsList');
    document.getElementById('invCount').textContent = invs.length;
    if(!invs.length){ section.style.display = 'none'; return; }
    section.style.display = 'block';
    list.innerHTML = '';
    invs.forEach(inv => {
      const card = document.createElement('div');
      card.className = 'subcard';
      card.style.borderLeft = '4px solid ' + esc(inv.workspace_color || '#4a6cf7');
      card.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
          <div>
            <div style="font-weight:700">"${esc(inv.workspace_name)}" od ${esc(inv.inviter_name)}</div>
            <div class="small">Rola: <b>${ROLE_LABELS[inv.role]||inv.role}</b>${inv.message ? ' · '+esc(inv.message) : ''} · ${shortDate(inv.created_at)}</div>
          </div>
          <div style="display:flex;gap:6px">
            <button class="btn" data-accept="${inv.id}" style="padding:4px 14px;font-size:.85rem">${aiIcon('success',14)} Akceptuj</button>
            <button class="btn danger" data-reject="${inv.id}" style="padding:4px 14px;font-size:.85rem">${aiIcon('close',14)} Odrzuć</button>
          </div>
        </div>
      `;
      card.querySelector('[data-accept]').addEventListener('click', async(e)=>{
        e.stopPropagation();
        try {
          await apiFetch(API+'/invitations/'+inv.id+'/accept', {method:'POST'});
          showToast('Zaproszenie zaakceptowane','success');
          loadWorkspaces();
        } catch(err){
          console.error('Accept invitation error:', err);
          showToast(err.message || 'Błąd akceptacji zaproszenia','error');
        }
      });
      card.querySelector('[data-reject]').addEventListener('click', async(e)=>{
        e.stopPropagation();
        try {
          await apiFetch(API+'/invitations/'+inv.id+'/reject', {method:'POST'});
          showToast('Zaproszenie odrzucone','info');
          loadWorkspaces();
        } catch(err){
          console.error('Reject invitation error:', err);
          showToast(err.message || 'Błąd odrzucenia zaproszenia','error');
        }
      });
      list.appendChild(card);
    });
  } catch(e){ console.error(e); }
}

async function loadArchivedWorkspaces(){
  try {
    const data = await apiFetch(API + '?status=archived');
    const ws = data.workspaces || [];
    _archivedCount = ws.length;
    _updateStatusLine(_activeCount + ' aktywnych' + (_archivedCount ? ', ' + _archivedCount + ' w archiwum' : ''));
    const section = document.getElementById('archivedSection');
    const list = document.getElementById('archivedList');
    if(!ws.length){ section.style.display = 'none'; return; }
    section.style.display = 'block';
    list.innerHTML = '';
    ws.forEach(w => {
      const card = document.createElement('div');
      card.className = 'subcard';
      card.style.opacity = '.6';
      card.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-weight:600">${esc(w.name)}</span>
          <button class="btn secondary btn-restore" style="font-size:.78rem;padding:3px 10px" data-id="${w.id}">Przywróć</button>
        </div>`;
      card.querySelector('.btn-restore').addEventListener('click', async(e) => {
        e.stopPropagation();
        await apiFetch(API+'/'+w.id, {method:'PATCH', body:JSON.stringify({status:'active'})});
        loadWorkspaces();
      });
      list.appendChild(card);
    });
  } catch(e){ console.error(e); }
}

// =====================================================================
// WORKSPACE DETAIL
// =====================================================================

async function openWorkspace(wsId){
  try {
    const data = await apiFetch(API + '/' + wsId);
    _currentWs = data.workspace;
    renderWorkspaceDetail(_currentWs);
    _setView('detail');
    // Update URL without reload
    history.pushState({wsId}, '', '/projects/' + wsId);
  } catch(e){
    console.error(e);
    showToast(e.message || 'Błąd', 'error');
  }
}

function renderWorkspaceDetail(ws){
  document.getElementById('wsDetailName').textContent = ws.name;
  document.getElementById('wsDetailDesc').textContent = ws.description || '';
  document.getElementById('wsDetailRole').textContent = ROLE_LABELS[ws.my_role] || ws.my_role || '';
  const spCount = (ws.subprojects || []).length;
  const mCount = (ws.members || []).length;
  _updateStatusLine(ws.name + ' · ' + spCount + ' podpr. · ' + mCount + ' czł.');

  // Subprojects
  const spList = document.getElementById('subprojectList');
  const spEmpty = document.getElementById('subprojectEmpty');
  const subs = ws.subprojects || [];
  spList.innerHTML = '';
  if(!subs.length){ spEmpty.style.display = 'block'; }
  else { spEmpty.style.display = 'none'; }

  subs.forEach(sp => {
    const icon = TYPE_ICONS[sp.subproject_type] || aiIcon('document', 18);
    const typeLabel = TYPE_LABELS[sp.subproject_type] || sp.subproject_type;
    const links = (sp.links || []).map(l =>
      `<span class="small" style="opacity:.7">► ${esc(l.target_name||l.source_id)}</span>`
    ).join(' ');

    const card = document.createElement('div');
    card.className = 'subcard';
    card.style.cssText = 'cursor:pointer;transition:transform .15s';
    card.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <div>
          <div style="font-weight:700">${icon} ${esc(sp.name)}</div>
          <div class="small">${esc(typeLabel)} · ${esc(sp.status)} · ${shortDate(sp.created_at)}</div>
          ${links ? '<div style="margin-top:2px">'+links+'</div>' : ''}
        </div>
        <div style="display:flex;gap:4px">
          <button class="btn secondary sp-open" data-id="${sp.id}" data-type="${sp.subproject_type}" data-dir="${esc(sp.data_dir)}" data-audio="${esc(sp.audio_file)}" style="font-size:.78rem;padding:3px 10px">Otwórz</button>
          <button class="btn danger sp-del" data-id="${sp.id}" style="font-size:.78rem;padding:3px 8px" title="Usuń">${aiIcon('delete',14)}</button>
        </div>
      </div>`;

    // Open subproject → navigate to the right page with projectId set
    card.querySelector('.sp-open').addEventListener('click', (e) => {
      e.stopPropagation();
      const dir = sp.data_dir || '';
      const projectId = dir.replace('projects/', '');
      if(projectId) {
        AISTATE.projectId = projectId;
        AISTATE.audioFile = sp.audio_file || '';
        // Store workspace context
        localStorage.setItem('aistate_workspace_id', ws.id);
        localStorage.setItem('aistate_workspace_name', ws.name);
        localStorage.setItem('aistate_subproject_name', sp.name);
      }
      const route = TYPE_ROUTES[sp.subproject_type] || '/analysis';
      window.location.href = route;
    });

    card.querySelector('.sp-del').addEventListener('click', async(e) => {
      e.stopPropagation();
      if(!confirm('Usunąć podprojekt "' + sp.name + '"?')) return;
      try {
        await apiFetch(API + '/' + ws.id + '/subprojects/' + sp.id, {method:'DELETE'});
        openWorkspace(ws.id);
      } catch(err) { showToast(err.message, 'error'); }
    });

    spList.appendChild(card);
  });

  // Populate link-to dropdown in new subproject modal
  const linkSelect = document.getElementById('nsLinkTo');
  linkSelect.innerHTML = '<option value="">— brak —</option>';
  subs.forEach(sp => {
    const opt = document.createElement('option');
    opt.value = sp.id;
    opt.textContent = sp.name;
    linkSelect.appendChild(opt);
  });

  // Members
  const mList = document.getElementById('membersList');
  const members = ws.members || [];
  mList.innerHTML = '';
  members.forEach(m => {
    const name = m.display_name || m.username || '?';
    const role = m.role;
    const isOwner = role === 'owner';
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:3px 0;font-size:.85rem';
    div.innerHTML = `
      <span><b>${esc(name)}</b> <span class="small" style="opacity:.7">${ROLE_LABELS[role]||role}</span></span>
      ${!isOwner && (ws.my_role === 'owner' || ws.my_role === 'manager')
        ? '<button class="btn danger" style="font-size:.7rem;padding:2px 6px" data-remove="'+m.user_id+'">' + aiIcon('close',12) + '</button>'
        : ''}
    `;
    const removeBtn = div.querySelector('[data-remove]');
    if(removeBtn){
      removeBtn.addEventListener('click', async () => {
        if(!confirm('Usunąć '+name+' z projektu?')) return;
        await apiFetch(API+'/'+ws.id+'/members/'+m.user_id, {method:'DELETE'});
        openWorkspace(ws.id);
      });
    }
    mList.appendChild(div);
  });

  // Activity
  const aList = document.getElementById('activityList');
  const activity = ws.activity || [];
  aList.innerHTML = '';
  if(!activity.length){ aList.innerHTML = '<div class="small" style="opacity:.5">Brak aktywności</div>'; }
  activity.forEach(a => {
    const div = document.createElement('div');
    div.style.cssText = 'padding:3px 0;border-bottom:1px solid var(--border,#eee)';
    div.innerHTML = `<b>${esc(a.user_name||a.user_id?.slice(0,8)||'?')}</b> — ${esc(a.action)} <span style="opacity:.5;float:right">${shortDate(a.created_at)}</span>`;
    aList.appendChild(div);
  });

  // Show/hide management buttons based on role
  const canManage = ws.my_role === 'owner' || ws.my_role === 'manager';
  document.getElementById('btnInviteUser').style.display = canManage ? '' : 'none';
  document.getElementById('btnArchiveWorkspace').style.display = canManage ? '' : 'none';
  document.getElementById('btnDeleteWorkspace').style.display = ws.my_role === 'owner' ? '' : 'none';
  document.getElementById('btnNewSubproject').style.display =
    (ws.my_role === 'owner' || ws.my_role === 'manager' || ws.my_role === 'editor') ? '' : 'none';
}

// =====================================================================
// CREATE WORKSPACE
// =====================================================================

document.getElementById('btnNewWorkspace').addEventListener('click', () => {
  document.getElementById('nwName').value = '';
  document.getElementById('nwDesc').value = '';
  showModal('modalNewWorkspace');
  document.getElementById('nwName').focus();
});

document.getElementById('nwSubmit').addEventListener('click', async () => {
  const name = document.getElementById('nwName').value.trim();
  if(!name){ showToast('Podaj nazwę','warning'); return; }
  const desc = document.getElementById('nwDesc').value.trim();
  const color = document.querySelector('#nwColors .color-chip.active')?.dataset?.color || '#4a6cf7';
  try {
    const data = await apiFetch(API, {method:'POST', body:JSON.stringify({name, description:desc, color})});
    if(data && data.workspace && data.workspace.id){
      hideModal('modalNewWorkspace');
      showToast('Projekt utworzony','success');
      await openWorkspace(data.workspace.id);
      // Auto-open new subproject modal with workspace name pre-filled
      const subs = (_currentWs && _currentWs.subprojects) || [];
      if(subs.length === 0){
        document.getElementById('nsName').value = name;
        showModal('modalNewSubproject');
        document.getElementById('nsName').focus();
      }
    } else {
      hideModal('modalNewWorkspace');
      showToast('Projekt utworzony','success');
      loadWorkspaces();
    }
  } catch(e){
    console.error('Create workspace error:', e);
    showToast(e.message || 'Błąd tworzenia projektu','error');
  }
});

// =====================================================================
// CREATE SUBPROJECT
// =====================================================================

document.getElementById('btnNewSubproject').addEventListener('click', () => {
  const subs = (_currentWs && _currentWs.subprojects) || [];
  // Pre-fill name with workspace name if no subprojects yet
  document.getElementById('nsName').value = (subs.length === 0 && _currentWs) ? _currentWs.name : '';
  showModal('modalNewSubproject');
  document.getElementById('nsName').focus();
});

document.getElementById('nsSubmit').addEventListener('click', async () => {
  if(!_currentWs) return;
  const name = document.getElementById('nsName').value.trim();
  if(!name){ showToast('Podaj nazwę','warning'); return; }
  const type = document.querySelector('.sp-type-btn.active')?.dataset?.type || 'analysis';
  const linkTo = document.getElementById('nsLinkTo').value;
  try {
    await apiFetch(API+'/'+_currentWs.id+'/subprojects', {
      method:'POST', body:JSON.stringify({name, type, link_to:linkTo})
    });
    hideModal('modalNewSubproject');
    openWorkspace(_currentWs.id);
    showToast('Podprojekt utworzony','success');
  } catch(e){ showToast(e.message,'error'); }
});

// =====================================================================
// INVITE USER
// =====================================================================

document.getElementById('btnInviteUser').addEventListener('click', () => {
  document.getElementById('invUsername').value = '';
  document.getElementById('invMessage').value = '';
  showModal('modalInviteUser');
  document.getElementById('invUsername').focus();
});

document.getElementById('invSubmit').addEventListener('click', async () => {
  if(!_currentWs) return;
  const username = document.getElementById('invUsername').value.trim();
  if(!username){ showToast('Podaj nazwę użytkownika','warning'); return; }
  const role = document.querySelector('input[name="invRole"]:checked')?.value || 'viewer';
  const message = document.getElementById('invMessage').value.trim();
  try {
    await apiFetch(API+'/'+_currentWs.id+'/invite', {
      method:'POST', body:JSON.stringify({username, role, message})
    });
    hideModal('modalInviteUser');
    showToast('Zaproszenie wysłane','success');
    openWorkspace(_currentWs.id);
  } catch(e){ showToast(e.message,'error'); }
});

// =====================================================================
// WORKSPACE ACTIONS
// =====================================================================

document.getElementById('btnBackToList').addEventListener('click', () => {
  _setView('list');
  _currentWs = null;
  history.pushState({}, '', '/projects');
  loadWorkspaces();
});

document.getElementById('btnArchiveWorkspace').addEventListener('click', async () => {
  if(!_currentWs) return;
  if(!confirm('Archiwizować projekt "'+_currentWs.name+'"?')) return;
  await apiFetch(API+'/'+_currentWs.id, {method:'PATCH', body:JSON.stringify({status:'archived'})});
  _setView('list');
  _currentWs = null;
  history.pushState({}, '', '/projects');
  loadWorkspaces();
  showToast('Projekt zarchiwizowany','success');
});

document.getElementById('btnDeleteWorkspace').addEventListener('click', async () => {
  if(!_currentWs) return;
  if(!confirm('USUNĄĆ projekt "'+_currentWs.name+'"? Ta operacja jest nieodwracalna!')) return;
  await apiFetch(API+'/'+_currentWs.id, {method:'DELETE'});
  _setView('list');
  _currentWs = null;
  history.pushState({}, '', '/projects');
  loadWorkspaces();
  showToast('Projekt usunięty','info');
});

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
      showToast('Wybierz plik .aistate', 'error');
      return;
    }

    const fd = new FormData();
    fd.append('file', f);

    try {
      const r = await fetch('/api/projects/import', {method:'POST', body: fd});
      const j = await r.json();
      if(!r.ok) throw new Error(j.message || j.detail || 'Import failed');
      showToast('Projekt zaimportowany', 'success');
      // If inside a workspace, reload detail; otherwise reload list
      if(_currentWs){
        openWorkspace(_currentWs.id);
      } else {
        loadWorkspaces();
      }
    } catch(err){
      console.error(err);
      showToast(err.message || 'Błąd importu', 'error');
    }
  });
})();

// =====================================================================
// DELETE SUBPROJECT (with wipe options)
// =====================================================================

(function(){
  const btn = document.getElementById('btnDeleteSubproject');
  const select = document.getElementById('delSubSelect');
  const wipeSelect = document.getElementById('delSubWipeMethod');
  const confirmBtn = document.getElementById('delSubConfirm');
  if(!btn) return;

  btn.addEventListener('click', () => {
    if(!_currentWs) return;
    const subs = _currentWs.subprojects || [];
    select.innerHTML = '';
    if(!subs.length){
      showToast('Brak podprojektów do usunięcia', 'warning');
      return;
    }
    subs.forEach(sp => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.dataset.dir = sp.data_dir || '';
      opt.textContent = (TYPE_ICONS[sp.subproject_type]||'') + ' ' + sp.name;
      select.appendChild(opt);
    });
    showModal('modalDeleteSubproject');
  });

  if(confirmBtn) confirmBtn.addEventListener('click', async () => {
    if(!_currentWs || !select.value) return;
    const spId = select.value;
    const sp = (_currentWs.subprojects||[]).find(s => s.id === spId);
    const wipe = wipeSelect ? wipeSelect.value : 'none';
    const dir = sp && sp.data_dir ? sp.data_dir.replace('projects/','') : '';

    if(!confirm('Na pewno usunąć podprojekt "' + (sp?sp.name:spId) + '"?')) return;

    try {
      // Delete underlying project data with wipe if data_dir exists
      if(dir){
        await fetch('/api/projects/' + encodeURIComponent(dir) + '?wipe_method=' + encodeURIComponent(wipe), {method:'DELETE'});
      }
      // Delete subproject record from workspace
      await apiFetch(API + '/' + _currentWs.id + '/subprojects/' + spId, {method:'DELETE'});
      hideModal('modalDeleteSubproject');
      showToast('Podprojekt usunięty', 'success');
      openWorkspace(_currentWs.id);
    } catch(err){
      console.error(err);
      showToast(err.message || 'Błąd usuwania', 'error');
    }
  });
})();

// =====================================================================
// EXPORT SUBPROJECT (.aistate)
// =====================================================================

(function(){
  const btn = document.getElementById('btnExportSubproject');
  const select = document.getElementById('expSubSelect');
  const confirmBtn = document.getElementById('expSubConfirm');
  if(!btn) return;

  btn.addEventListener('click', () => {
    if(!_currentWs) return;
    const subs = _currentWs.subprojects || [];
    select.innerHTML = '';
    if(!subs.length){
      showToast('Brak podprojektów do eksportu', 'warning');
      return;
    }
    subs.forEach(sp => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.dataset.dir = sp.data_dir || '';
      opt.dataset.name = sp.name || '';
      opt.textContent = (TYPE_ICONS[sp.subproject_type]||'') + ' ' + sp.name;
      select.appendChild(opt);
    });
    showModal('modalExportSubproject');
  });

  if(confirmBtn) confirmBtn.addEventListener('click', async () => {
    if(!select.value) return;
    const opt = select.options[select.selectedIndex];
    const dir = (opt.dataset.dir || '').replace('projects/','');
    const fname = (opt.dataset.name || dir || 'project').replace(/[\\\/:*?"<>|]+/g,'_').trim() || 'project';

    if(!dir){
      showToast('Podprojekt nie ma katalogu danych', 'warning');
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
      hideModal('modalExportSubproject');
      showToast('Eksport zakończony', 'success');
    } catch(err){
      console.error(err);
      showToast(err.message || 'Błąd eksportu', 'error');
    }
  });
})();

// =====================================================================
// URL-BASED NAVIGATION (handle /projects/{id} on page load)
// =====================================================================

(function init(){
  const path = window.location.pathname;
  const match = path.match(/^\/projects\/([a-f0-9]+)$/);
  if(match){
    openWorkspace(match[1]);
  } else {
    loadWorkspaces();
  }

  // Handle browser back/forward
  window.addEventListener('popstate', (e) => {
    if(e.state && e.state.wsId){
      openWorkspace(e.state.wsId);
    } else {
      _setView('list');
      _currentWs = null;
      loadWorkspaces();
    }
  });
})();

})();
