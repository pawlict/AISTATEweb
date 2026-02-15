/* projects.js — Workspace dashboard frontend logic */
(function(){
"use strict";

const API = '/api/workspaces';
let _currentWs = null;  // workspace detail being viewed

// --- Helpers ---
function esc(s){ return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function shortDate(iso){ return iso ? iso.replace('T',' ').slice(0,16) : '—'; }

async function apiFetch(url, opts){
  const r = await fetch(url, {headers:{'Content-Type':'application/json'}, ...opts});
  const j = await r.json();
  if(j.status !== 'ok' && r.status >= 400) throw new Error(j.message || `HTTP ${r.status}`);
  return j;
}

const TYPE_ICONS = {
  transcription: '🎤', diarization: '👥', analysis: '📊',
  chat: '💬', translation: '🌐', finance: '🏦'
};
const TYPE_LABELS = {
  transcription: 'Transkrypcja', diarization: 'Diaryzacja', analysis: 'Analiza',
  chat: 'Chat', translation: 'Tłumaczenie', finance: 'Finanse'
};
const TYPE_ROUTES = {
  transcription: '/transcription', diarization: '/diarization', analysis: '/analysis',
  chat: '/chat', translation: '/translation', finance: '/analysis'
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
  if(!workspaces.length){ empty.style.display = 'block'; return; }
  empty.style.display = 'none';

  workspaces.forEach(ws => {
    const members = (ws.members || []).slice(0,4);
    const avatars = members.map(m =>
      `<span title="${esc(m.name || m.display_name || m.username || '?')} (${m.role})" style="display:inline-block;width:24px;height:24px;border-radius:50%;background:${esc(ws.color||'#4a6cf7')};color:#fff;text-align:center;line-height:24px;font-size:.65rem;font-weight:700;margin-right:-4px;border:2px solid var(--card-bg,#fff)">${esc((m.name||m.display_name||m.username||'?')[0].toUpperCase())}</span>`
    ).join('');

    const role = ws.my_role ? `<span style="font-size:.72rem;padding:2px 8px;border-radius:6px;background:${ws.my_role==='owner'?'var(--accent)':'#888'};color:#fff;font-weight:600">${ROLE_LABELS[ws.my_role]||ws.my_role}</span>` : '';
    const card = document.createElement('div');
    card.className = 'subcard';
    card.style.cssText = 'cursor:pointer;border-left:4px solid '+esc(ws.color||'#4a6cf7')+';transition:transform .15s';
    card.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <div>
          <div style="font-weight:700;font-size:1rem;color:var(--text)">${esc(ws.name)}</div>
          <div class="small" style="margin-top:2px">${ws.subproject_count||0} podprojektów · Zaktualizowano: ${shortDate(ws.updated_at)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          ${role}
          <span class="small">${ws.member_count||1} czł.</span>
        </div>
      </div>
      <div style="margin-top:6px;display:flex;align-items:center;gap:2px">${avatars}</div>
      ${ws.description ? '<div class="small" style="margin-top:4px;opacity:.7">'+esc(ws.description)+'</div>' : ''}
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
            <button class="btn" data-accept="${inv.id}" style="padding:4px 14px;font-size:.85rem">✓ Akceptuj</button>
            <button class="btn danger" data-reject="${inv.id}" style="padding:4px 14px;font-size:.85rem">✕ Odrzuć</button>
          </div>
        </div>
      `;
      card.querySelector('[data-accept]').addEventListener('click', async(e)=>{
        e.stopPropagation();
        await apiFetch(API+'/invitations/'+inv.id+'/accept', {method:'POST'});
        showToast('Zaproszenie zaakceptowane','success');
        loadWorkspaces();
      });
      card.querySelector('[data-reject]').addEventListener('click', async(e)=>{
        e.stopPropagation();
        await apiFetch(API+'/invitations/'+inv.id+'/reject', {method:'POST'});
        showToast('Zaproszenie odrzucone','info');
        loadWorkspaces();
      });
      list.appendChild(card);
    });
  } catch(e){ console.error(e); }
}

async function loadArchivedWorkspaces(){
  try {
    const data = await apiFetch(API + '?status=archived');
    const ws = data.workspaces || [];
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
    document.getElementById('viewWorkspaceList').style.display = 'none';
    document.getElementById('viewWorkspaceDetail').style.display = 'block';
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

  // Subprojects
  const spList = document.getElementById('subprojectList');
  const spEmpty = document.getElementById('subprojectEmpty');
  const subs = ws.subprojects || [];
  spList.innerHTML = '';
  if(!subs.length){ spEmpty.style.display = 'block'; }
  else { spEmpty.style.display = 'none'; }

  subs.forEach(sp => {
    const icon = TYPE_ICONS[sp.subproject_type] || '📄';
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
          <button class="btn danger sp-del" data-id="${sp.id}" style="font-size:.78rem;padding:3px 8px" title="Usuń">✕</button>
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
        ? '<button class="btn danger" style="font-size:.7rem;padding:2px 6px" data-remove="'+m.user_id+'">✕</button>'
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
    await apiFetch(API, {method:'POST', body:JSON.stringify({name, description:desc, color})});
    hideModal('modalNewWorkspace');
    loadWorkspaces();
    showToast('Projekt utworzony','success');
  } catch(e){ showToast(e.message,'error'); }
});

// =====================================================================
// CREATE SUBPROJECT
// =====================================================================

document.getElementById('btnNewSubproject').addEventListener('click', () => {
  document.getElementById('nsName').value = '';
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
  document.getElementById('viewWorkspaceDetail').style.display = 'none';
  document.getElementById('viewWorkspaceList').style.display = 'block';
  _currentWs = null;
  history.pushState({}, '', '/projects');
  loadWorkspaces();
});

document.getElementById('btnArchiveWorkspace').addEventListener('click', async () => {
  if(!_currentWs) return;
  if(!confirm('Archiwizować projekt "'+_currentWs.name+'"?')) return;
  await apiFetch(API+'/'+_currentWs.id, {method:'PATCH', body:JSON.stringify({status:'archived'})});
  document.getElementById('viewWorkspaceDetail').style.display = 'none';
  document.getElementById('viewWorkspaceList').style.display = 'block';
  _currentWs = null;
  history.pushState({}, '', '/projects');
  loadWorkspaces();
  showToast('Projekt zarchiwizowany','success');
});

document.getElementById('btnDeleteWorkspace').addEventListener('click', async () => {
  if(!_currentWs) return;
  if(!confirm('USUNĄĆ projekt "'+_currentWs.name+'"? Ta operacja jest nieodwracalna!')) return;
  await apiFetch(API+'/'+_currentWs.id, {method:'DELETE'});
  document.getElementById('viewWorkspaceDetail').style.display = 'none';
  document.getElementById('viewWorkspaceList').style.display = 'block';
  _currentWs = null;
  history.pushState({}, '', '/projects');
  loadWorkspaces();
  showToast('Projekt usunięty','info');
});

document.getElementById('btnLegacyView').addEventListener('click', () => {
  window.location.href = '/new-project';
});

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
      document.getElementById('viewWorkspaceDetail').style.display = 'none';
      document.getElementById('viewWorkspaceList').style.display = 'block';
      _currentWs = null;
      loadWorkspaces();
    }
  });
})();

})();
