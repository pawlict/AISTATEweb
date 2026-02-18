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
    const data = await apiFetch(API + '/default');
    _ws = data.workspace;
    renderProjects(_ws);
  } catch(e){
    console.error('Load projects error:', e);
    _updateStatusLine('Błąd ładowania');
  }
}

function renderProjects(ws){
  const projects = ws.subprojects || [];
  const pList = document.getElementById('projectList');
  const pEmpty = document.getElementById('projectEmpty');
  pList.innerHTML = '';

  _updateStatusLine(projects.length + ' projekt' + (projects.length === 1 ? '' : (projects.length < 5 ? 'y' : 'ów')));

  if(!projects.length){ pEmpty.style.display = 'block'; }
  else { pEmpty.style.display = 'none'; }

  projects.forEach(sp => {
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
          <button class="btn secondary sp-open" style="font-size:.78rem;padding:3px 10px">Otwórz</button>
          <button class="btn danger sp-del" style="font-size:.78rem;padding:3px 8px" title="Usuń">${aiIcon('delete',14)}</button>
        </div>
      </div>`;

    // Open project → navigate to the right page
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
      }
      const route = TYPE_ROUTES[sp.subproject_type] || '/analysis';
      window.location.href = route;
    });

    // Inline delete
    card.querySelector('.sp-del').addEventListener('click', async(e) => {
      e.stopPropagation();
      if(!confirm('Usunąć projekt "' + sp.name + '"?')) return;
      try {
        await apiFetch(API + '/' + ws.id + '/subprojects/' + sp.id, {method:'DELETE'});
        showToast('Projekt usunięty','info');
        await loadProjects();
      } catch(err) { showToast(err.message, 'error'); }
    });

    // Click card → also open
    card.addEventListener('click', () => {
      card.querySelector('.sp-open').click();
    });

    pList.appendChild(card);
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
        try {
          await apiFetch(API+'/'+ws.id+'/members/'+m.user_id, {method:'DELETE'});
          showToast('Użytkownik usunięty','info');
          loadProjects();
        } catch(err){ showToast(err.message || 'Błąd','error'); }
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
  const btnInvite = document.getElementById('btnInviteUser');
  const btnNew = document.getElementById('btnNewProject');
  if(btnInvite) btnInvite.style.display = canManage ? '' : 'none';
  if(btnNew) btnNew.style.display = (ws.my_role === 'owner' || ws.my_role === 'manager' || ws.my_role === 'editor') ? '' : 'none';
}

// =====================================================================
// CREATE PROJECT
// =====================================================================

document.getElementById('btnNewProject').addEventListener('click', () => {
  document.getElementById('npName').value = '';
  document.querySelectorAll('.sp-type-btn').forEach(b => b.classList.remove('active'));
  const firstTypeBtn = document.querySelector('.sp-type-btn');
  if(firstTypeBtn) firstTypeBtn.classList.add('active');
  showModal('modalNewProject');
  document.getElementById('npName').focus();
});

document.getElementById('npSubmit').addEventListener('click', async () => {
  if(!_ws){ showToast('Brak danych','warning'); return; }
  const name = document.getElementById('npName').value.trim();
  if(!name){ showToast('Podaj nazwę','warning'); return; }
  const type = document.querySelector('.sp-type-btn.active')?.dataset?.type || 'analysis';
  const linkTo = document.getElementById('npLinkTo').value;
  try {
    const data = await apiFetch(API+'/'+_ws.id+'/subprojects', {
      method:'POST', body:JSON.stringify({name, type, link_to:linkTo})
    });
    hideModal('modalNewProject');
    showToast('Projekt utworzony','success');

    // Auto-redirect to the matching page for typed projects
    const route = TYPE_ROUTES[type];
    console.log('[projects] Created project:', {type, route, hasSubproject: !!data.subproject, data});
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
      }
      console.log('[projects] Redirecting to:', route, 'projectId:', projectId);
      window.location.href = route;
      return;
    }
    // For "general" type — stay on projects page
    await loadProjects();
  } catch(e){
    console.error('Create project error:', e);
    showToast(e.message || 'Błąd tworzenia projektu','error');
  }
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
  if(!_ws) return;
  const username = document.getElementById('invUsername').value.trim();
  if(!username){ showToast('Podaj nazwę użytkownika','warning'); return; }
  const role = document.querySelector('input[name="invRole"]:checked')?.value || 'viewer';
  const message = document.getElementById('invMessage').value.trim();
  try {
    await apiFetch(API+'/'+_ws.id+'/invite', {
      method:'POST', body:JSON.stringify({username, role, message})
    });
    hideModal('modalInviteUser');
    showToast('Zaproszenie wysłane','success');
    loadProjects();
  } catch(e){ showToast(e.message,'error'); }
});

// =====================================================================
// DELETE PROJECT (with wipe options)
// =====================================================================

(function(){
  const btn = document.getElementById('btnDeleteProject');
  const select = document.getElementById('delProjSelect');
  const wipeSelect = document.getElementById('delProjWipeMethod');
  const confirmBtn = document.getElementById('delProjConfirm');
  if(!btn) return;

  btn.addEventListener('click', () => {
    if(!_ws) return;
    const subs = _ws.subprojects || [];
    select.innerHTML = '';
    if(!subs.length){
      showToast('Brak projektów do usunięcia', 'warning');
      return;
    }
    subs.forEach(sp => {
      const opt = document.createElement('option');
      opt.value = sp.id;
      opt.dataset.dir = sp.data_dir || '';
      opt.textContent = (TYPE_ICONS[sp.subproject_type]||'') + ' ' + sp.name;
      select.appendChild(opt);
    });
    showModal('modalDeleteProject');
  });

  if(confirmBtn) confirmBtn.addEventListener('click', async () => {
    if(!_ws || !select.value) return;
    const spId = select.value;
    const sp = (_ws.subprojects||[]).find(s => s.id === spId);
    const wipe = wipeSelect ? wipeSelect.value : 'none';
    const dir = sp && sp.data_dir ? sp.data_dir.replace('projects/','') : '';

    if(!confirm('Na pewno usunąć projekt "' + (sp?sp.name:spId) + '"?')) return;

    try {
      if(dir){
        await fetch('/api/projects/' + encodeURIComponent(dir) + '?wipe_method=' + encodeURIComponent(wipe), {method:'DELETE'});
      }
      await apiFetch(API + '/' + _ws.id + '/subprojects/' + spId, {method:'DELETE'});
      hideModal('modalDeleteProject');
      showToast('Projekt usunięty', 'success');
      await loadProjects();
    } catch(err){
      console.error(err);
      showToast(err.message || 'Błąd usuwania', 'error');
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
      showToast('Brak projektów do eksportu', 'warning');
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
    showModal('modalExportProject');
  });

  if(confirmBtn) confirmBtn.addEventListener('click', async () => {
    if(!select.value) return;
    const opt = select.options[select.selectedIndex];
    const dir = (opt.dataset.dir || '').replace('projects/','');
    const fname = (opt.dataset.name || dir || 'project').replace(/[\\\/:*?"<>|]+/g,'_').trim() || 'project';

    if(!dir){
      showToast('Projekt nie ma katalogu danych', 'warning');
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
      showToast('Eksport zakończony', 'success');
    } catch(err){
      console.error(err);
      showToast(err.message || 'Błąd eksportu', 'error');
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
      await loadProjects();
    } catch(err){
      console.error(err);
      showToast(err.message || 'Błąd importu', 'error');
    }
  });
})();

// =====================================================================
// INIT
// =====================================================================

loadProjects();

})();
