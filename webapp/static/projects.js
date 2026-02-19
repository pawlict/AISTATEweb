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

    // Build team section — owner first, then up to 2 others
    const members = ws.members || [];
    const owner = members.find(m => m.role === 'owner');
    const others = members.filter(m => m.role !== 'owner');
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
    if(!members.length){
      teamHtml = '<div style="font-size:.7rem;opacity:.35">—</div>';
    }

    const card = document.createElement('div');
    card.className = 'subcard sp-card';
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
          <button class="btn pill-icon sp-invite" title="Zaproś użytkownika"><img src="/static/icons/uzytkownicy/user_invite.svg" alt="Zaproś" draggable="false"></button>
          <button class="btn pill-icon sp-del" title="Usuń"><img src="/static/icons/akcje/remove.svg" alt="Usuń" draggable="false"></button>
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

    // Inline invite → open invite modal with this project pre-selected
    card.querySelector('.sp-invite').addEventListener('click', (e) => {
      e.stopPropagation();
      _openInviteModal(sp.id);
    });

    // Inline delete → open modal with this project pre-selected
    card.querySelector('.sp-del').addEventListener('click', (e) => {
      e.stopPropagation();
      _openDeleteModalForProject(ws, sp.id);
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

// Enter key in project name input triggers submit
document.getElementById('npName').addEventListener('keydown', (e) => {
  if(e.key === 'Enter'){
    e.preventDefault();
    document.getElementById('npSubmit').click();
  }
});

document.getElementById('npSubmit').addEventListener('click', async () => {
  if(!_ws){ showToast('Brak danych','warning'); return; }
  let name = document.getElementById('npName').value.trim();
  if(!name){ showToast('Podaj nazwę','warning'); return; }
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
  try {
    const data = await apiFetch(API+'/'+_ws.id+'/subprojects', {
      method:'POST', body:JSON.stringify({name, type, link_to:linkTo})
    });
    hideModal('modalNewProject');
    showToast('Projekt utworzony','success');

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
      }
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

/** Open invite modal, optionally pre-selecting a project. */
function _openInviteModal(preSelectProjectId) {
  document.getElementById('invUsername').value = '';
  document.getElementById('invMessage').value = '';
  // Populate project selector
  const sel = document.getElementById('invProject');
  sel.innerHTML = '<option value="">— wszystkie projekty —</option>';
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
  if(!username){ showToast('Podaj nazwę użytkownika','warning'); return; }
  const role = document.querySelector('input[name="invRole"]:checked')?.value || 'viewer';
  const projSel = document.getElementById('invProject');
  const projName = projSel.options[projSel.selectedIndex]?.textContent || '';
  let message = document.getElementById('invMessage').value.trim();
  if(projSel.value && projName){
    message = (message ? message + '\n' : '') + 'Projekt: ' + projName;
  }
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

/** Open the delete modal with a specific project pre-selected. */
function _openDeleteModalForProject(ws, preSelectId) {
  if(!ws) return;
  const subs = ws.subprojects || [];
  const select = document.getElementById('delProjSelect');
  if(!select) return;
  select.innerHTML = '';
  if(!subs.length){
    showToast('Brak projektów do usunięcia', 'warning');
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

    if(!confirm('Na pewno usunąć projekt "' + (sp?sp.name:spId) + '"?')) return;

    try {
      await apiFetch(API + '/' + _ws.id + '/subprojects/' + spId + '?wipe_method=' + encodeURIComponent(wipe), {method:'DELETE'});
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
