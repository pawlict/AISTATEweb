/* Admin GPU Resource Manager (English-only logic; UI texts translated via i18n keys) */
"use strict";

function $(id){ return document.getElementById(id); }

function tr(key){
  try{ return (typeof window.t === "function") ? window.t(key) : key; }catch(_){ return key; }
}

function trLabel(key, fallbackPl, fallbackEn){
  const v = tr(key);
  if(v && v !== key) return v;
  const lang = (localStorage.getItem("aistate_ui_lang") || "pl").toLowerCase();
  if(lang.startsWith("pl")) return fallbackPl || fallbackEn || key;
  return fallbackEn || fallbackPl || key;
}


let cfgDirty = false;
let prioDirty = false;
let prioSaveTimer = null;

// SVG icons — matching new Digital Brush sidebar icons
const ICON_SVGS = {
  transcription: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path class="brush" d="M2 12c1-3 2 3 3 0s2 3 3 0 2-3 3 0"/>
      <path d="M14 9v6M16 8v8M18 10v4" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M13 12l1.5-.5" opacity=".3" stroke-dasharray="1 1.5"/>
    </svg>`,
  diarization: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="7" cy="8" r="2.8" stroke-width="1.4"/>
      <path d="M3 17c0-2.5 1.8-4 4-4s4 1.5 4 4" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="17" cy="8" r="2.8" stroke-width="1.4"/>
      <path d="M13 17c0-2.5 1.8-4 4-4s4 1.5 4 4" stroke-width="1.4" stroke-linecap="round"/>
      <path class="brush" d="M10 10.5c.6.4 1.2.4 2 .4s1.4 0 2-.4" stroke-dasharray="1.5 1"/>
    </svg>`,
  analysis: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3C8 3 5 5.5 5 9c0 2 .8 3.5 2 4.5L8 19h8l1-5.5c1.2-1 2-2.5 2-4.5 0-3.5-3-6-7-6z" stroke-linejoin="round"/>
      <path d="M9 19h6v1.5a1.5 1.5 0 0 1-1.5 1.5h-3A1.5 1.5 0 0 1 9 20.5V19z" stroke-width="1.3"/>
      <path class="brush" d="M12 7v4M10 9h4" stroke-linecap="round" opacity=".6"/>
      <circle cx="8.5" cy="11" r=".8" fill="currentColor" opacity=".5"/>
      <circle cx="15.5" cy="11" r=".8" fill="currentColor" opacity=".5"/>
    </svg>`,
  translation: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="5" width="8" height="14" rx="2" stroke-width="1.3"/>
      <rect x="14" y="5" width="8" height="14" rx="2" stroke-width="1.3"/>
      <path class="brush" d="M5 9h3M5 11h2" stroke-linecap="round" opacity=".5"/>
      <path d="M17 9h3M17 11h2" stroke-linecap="round" opacity=".5"/>
      <path d="M10 10c.8-.3 1.5-.3 2-.3s1.2 0 2 .3" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M10 14c.8.3 1.5.3 2 .3s1.2 0 2-.3" stroke-width="1.5" stroke-linecap="round"/>
    </svg>`,
  chat: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M21 12c0 4.4-4 8-9 8a9.9 9.9 0 0 1-3.4-.6L3 21l1.6-4A7.3 7.3 0 0 1 3 12c0-4.4 4-8 9-8s9 3.6 9 8z" stroke-linejoin="round"/>
      <path class="brush" d="M8 11h8M8 14h5" stroke-linecap="round" opacity=".5"/>
    </svg>`,
};

const PRIO_CATS = [
  { key: "transcription", icon: "transcription", titleKey: "admin.gpu.prio.transcription", fbPl: "Transkrypcja", fbEn: "Transcription" },
  { key: "diarization", icon: "diarization", titleKey: "admin.gpu.prio.diarization", fbPl: "Diaryzacja", fbEn: "Diarization" },
  { key: "translation", icon: "translation", titleKey: "admin.gpu.prio.translation", fbPl: "Tłumaczenia", fbEn: "Translation" },
  { key: "analysis_quick", icon: "analysis", badgeIcon: "lightning", titleKey: "admin.gpu.prio.analysis_quick", fbPl: "Szybka analiza", fbEn: "Quick analysis" },
  { key: "analysis", icon: "analysis", badgeIcon: "deep_search", titleKey: "admin.gpu.prio.analysis_deep", fbPl: "Głęboka analiza", fbEn: "Deep analysis" },
  { key: "chat", icon: "chat", titleKey: "admin.gpu.prio.chat", fbPl: "Chat LLM", fbEn: "Chat LLM" },
];

function markCfgDirty(){
  cfgDirty = true;
  const msg = $("gpu_cfg_msg");
  if(msg && !msg.textContent) msg.textContent = "Unsaved changes…";
}

function markPrioDirty(){
  prioDirty = true;
  const msg = $("gpu_prio_msg");
  if(msg) msg.textContent = trLabel("admin.gpu.prio.saving","Zapisuję…","Saving…");
  scheduleSavePriorities();
}

async function apiJson(url, opts){
  const r = await fetch(url, opts || {});
  if(!r.ok){
    const txt = await r.text();
    throw new Error(`HTTP ${r.status}: ${txt}`);
  }
  return await r.json();
}

function scheduleSavePriorities(){
  if(prioSaveTimer) clearTimeout(prioSaveTimer);
  prioSaveTimer = setTimeout(()=>{ savePriorities(); }, 450);
}

function fmtGB(bytes){
  if(bytes == null) return "-";
  const gb = bytes / (1024*1024*1024);
  return gb.toFixed(1) + " GB";
}

function esc(s){
  return String(s||"").replace(/[&<>"']/g, c=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function renderStatus(data){
  const sum = $("gpu_status_summary");
  if(sum){
    const cuda = data.cuda_available ? "CUDA: YES" : "CUDA: NO";
    const gcount = Array.isArray(data.gpus) ? data.gpus.length : 0;
    sum.textContent = `${cuda} • GPUs: ${gcount} • queue=${data.queue_size||0}`;
  }

  // Fill config inputs (do not overwrite while user is editing)
  const mfIn = $("gpu_mem_fraction");
  const spgIn = $("gpu_slots_per_gpu");
  const csIn = $("gpu_cpu_slots");
  const active = document.activeElement;
  if(!cfgDirty && mfIn && active !== mfIn) mfIn.value = data.config?.gpu_mem_fraction ?? 0.85;
  if(!cfgDirty && spgIn && active !== spgIn) spgIn.value = data.config?.gpu_slots_per_gpu ?? 1;
  if(!cfgDirty && csIn && active !== csIn) csIn.value = data.config?.cpu_slots ?? 1;

  // Priorities (do not overwrite while user is editing)
  const pr = data.config?.priorities || {};
  renderPriorityList(pr);

  const body = $("gpu_table_body");
  if(!body) return;
  body.innerHTML = "";
  const gpus = Array.isArray(data.gpus) ? data.gpus : [];
  if(gpus.length === 0){
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>cpu</td><td>-</td><td>-</td><td>${data.running?.cpu||0}</td><td>${data.config?.cpu_slots||1}</td>`;
    body.appendChild(tr);
    return;
  }
  for(const g of gpus){
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(g.id)}</td>
      <td>${esc(g.name)}</td>
      <td>${fmtGB(g.total_vram_bytes)}</td>
      <td>${esc((data.running?.[String(g.id)] ?? 0))}</td>
      <td>${esc(data.config?.gpu_slots_per_gpu ?? 1)}</td>
    `;
    body.appendChild(tr);
  }
}

function orderFromPriorities(pr){
  const p = pr || {};
  const cats = PRIO_CATS.map(c => c.key);
  cats.sort((a,b)=>{
    const pa = (p[a] != null ? parseInt(p[a], 10) : 0);
    const pb = (p[b] != null ? parseInt(p[b], 10) : 0);
    // higher first
    return (pb - pa) || a.localeCompare(b);
  });
  return cats;
}

function getOrderFromDOM(){
  const list = $("prio_list");
  if(!list) return [];
  return Array.from(list.querySelectorAll(".prio-item")).map(el => el.getAttribute("data-cat")).filter(Boolean);
}

function updateRankBadges(){
  const list = $("prio_list");
  if(!list) return;
  const items = Array.from(list.querySelectorAll(".prio-item"));
  items.forEach((it, idx)=>{
    const b = it.querySelector(".prio-rank");
    if(b) b.textContent = String(idx+1);
  });
}

function updatePriorityNumbers(pr){
  const list = $("prio_list");
  if(!list) return;
  const p = pr || {};
  Array.from(list.querySelectorAll(".prio-item")).forEach(it=>{
    const cat = it.getAttribute("data-cat") || "";
    const num = it.querySelector(".prio-num");
    if(num) num.textContent = (p[cat] != null) ? `prio ${p[cat]}` : "";
  });
}

function buildPriorityList(order, pr){
  const list = $("prio_list");
  if(!list) return;
  list.innerHTML = "";
  const priorities = pr || {};

  const byKey = {};
  PRIO_CATS.forEach(c=>{ byKey[c.key] = c; });

  let dragged = null;

  function clearDropTargets(){
    list.querySelectorAll(".drop-target").forEach(el=>el.classList.remove("drop-target"));
  }

  function moveItem(item, dir){
    if(!item) return;
    if(dir === "up"){
      const prev = item.previousElementSibling;
      if(prev) list.insertBefore(item, prev);
    }else{
      const next = item.nextElementSibling;
      if(next) list.insertBefore(item, next.nextSibling);
    }
    markPrioDirty();
    updateRankBadges();
  }

  for(const cat of order){
    const meta = byKey[cat] || { key: cat, icon: "analysis", titleKey: "" };

    const row = document.createElement("div");
    row.className = "prio-item";
    row.setAttribute("draggable", "true");
    row.setAttribute("data-cat", cat);
    row.setAttribute("data-icon", meta.icon || "");

    const svg = ICON_SVGS[meta.icon] || ICON_SVGS.analysis;
    const badge = meta.badgeIcon && typeof aiIcon === "function"
      ? `<span class="prio-badge" aria-hidden="true">${aiIcon(meta.badgeIcon, 14)}</span>`
      : (meta.badge ? `<span class="prio-badge" aria-hidden="true">${esc(meta.badge)}</span>` : "");

    row.innerHTML = `
      <div class="prio-left">
        <div class="prio-rank">?</div>
        <div class="prio-handle" title="${esc(trLabel('admin.gpu.prio.drag','Przeciągnij, aby zmienić kolejność','Drag to reorder'))}">⋮⋮</div>
        <div class="prio-icon" data-tip="${esc(trLabel(meta.titleKey||'', meta.fbPl, meta.fbEn))}" role="img" aria-label="${esc(trLabel(meta.titleKey||'', meta.fbPl, meta.fbEn))}">
          ${svg}
          ${badge}
          <span class="sr-only">${esc(trLabel(meta.titleKey||'', meta.fbPl, meta.fbEn))}</span>
        </div>
      </div>
      <div class="prio-right">
        <div class="prio-num">${(priorities[cat]!=null) ? `prio ${esc(priorities[cat])}` : ""}</div>
        <div class="prio-move">
          <button class="btn small" data-act="up" title="${esc(trLabel('admin.gpu.prio.move_up','Przenieś wyżej','Move up'))}">↑</button>
          <button class="btn small" data-act="down" title="${esc(trLabel('admin.gpu.prio.move_down','Przenieś niżej','Move down'))}">↓</button>
        </div>
      </div>
    `;
    // Drag & drop
    row.addEventListener("dragstart", (e)=>{
      dragged = row;
      row.classList.add("dragging");
      try{ e.dataTransfer.effectAllowed = "move"; }catch(_){ }
    });
    row.addEventListener("dragend", ()=>{
      row.classList.remove("dragging");
      clearDropTargets();
      dragged = null;
      updateRankBadges();
    });
    row.addEventListener("dragover", (e)=>{
      if(!dragged || dragged === row) return;
      e.preventDefault();
      row.classList.add("drop-target");
    });
    row.addEventListener("dragleave", ()=>row.classList.remove("drop-target"));
    row.addEventListener("drop", (e)=>{
      if(!dragged || dragged === row) return;
      e.preventDefault();
      row.classList.remove("drop-target");
      const items = Array.from(list.querySelectorAll(".prio-item"));
      const from = items.indexOf(dragged);
      const to = items.indexOf(row);
      if(from < 0 || to < 0) return;
      if(from < to) list.insertBefore(dragged, row.nextSibling);
      else list.insertBefore(dragged, row);
      markPrioDirty();
      updateRankBadges();
    });

    // Up/down
    row.querySelectorAll("button[data-act]").forEach(b=>{
      b.addEventListener("click", ()=>{
        const act = b.getAttribute("data-act");
        moveItem(row, act);
      });
    });

    list.appendChild(row);
  }

  updateRankBadges();

  // Let i18n apply after DOM exists
  if(window && typeof window.applyI18n === "function"){
    try{ window.applyI18n(); }catch(_){ }
  }
}

function renderPriorityList(pr){
  const list = $("prio_list");
  if(!list) return;

  if(!prioDirty){
    const order = orderFromPriorities(pr);
    buildPriorityList(order, pr);
  }else{
    // User is reordering - only refresh numeric hints.
    updatePriorityNumbers(pr);
  }
}

function renderJobs(data){
  const body = $("gpu_jobs_body");
  if(!body) return;
  body.innerHTML = "";
  const rows = Array.isArray(data.jobs) ? data.jobs : [];
  for(const j of rows){
    const canCancel = j.status === "queued" || j.status === "running";
    const btn = canCancel ? `<button class="btn small" data-task="${esc(j.task_id)}">Cancel</button>` : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="small muted">${esc(j.created_at||"")}</td>
      <td><code>${esc(j.task_id||"")}</code></td>
      <td>${esc(j.kind||"")}</td>
      <td>${esc(j.job_type||"")}</td>
      <td>${esc(j.priority!=null ? String(j.priority) : "")}</td>
      <td>${esc(j.project_id||"")}</td>
      <td>${esc(j.status||"")}</td>
      <td>${esc(j.device||"-")}</td>
      <td>${btn}</td>
    `;
    body.appendChild(tr);
  }
  body.querySelectorAll("button[data-task]").forEach(b=>{
    b.addEventListener("click", async ()=>{
      const tid = b.getAttribute("data-task");
      if(!tid) return;
      try{
        await apiJson("/api/admin/gpu/cancel", {
          method: "POST",
          headers: {"content-type":"application/json"},
          body: JSON.stringify({task_id: tid})
        });
        await refreshAll();
      }catch(e){
        alert(String(e.message||e));
      }
    });
  });
}

async function refreshAll(){
  const st = await apiJson("/api/admin/gpu/status");
  renderStatus(st);
  const jobs = await apiJson("/api/admin/gpu/jobs");
  renderJobs(jobs);
}

async function saveConfig(){
  const msg = $("gpu_cfg_msg");
  const mfIn = $("gpu_mem_fraction");
  const spgIn = $("gpu_slots_per_gpu");
  const csIn = $("gpu_cpu_slots");
  if(msg) msg.textContent = "";
  const payload = {
    gpu_mem_fraction: parseFloat($("gpu_mem_fraction").value || "0.85"),
    gpu_slots_per_gpu: parseInt($("gpu_slots_per_gpu").value || "1", 10),
    cpu_slots: parseInt($("gpu_cpu_slots").value || "1", 10),
  };
  try{
    const resp = await apiJson("/api/admin/gpu/config", {
      method: "POST",
      headers: {"content-type":"application/json"},
      body: JSON.stringify(payload)
    });
    cfgDirty = false;
    // reflect server-clamped values
    if(resp && resp.config){
      if(mfIn) mfIn.value = resp.config.gpu_mem_fraction ?? (mfIn.value||"0.85");
      if(spgIn) spgIn.value = resp.config.gpu_slots_per_gpu ?? (spgIn.value||"1");
      if(csIn) csIn.value = resp.config.cpu_slots ?? (csIn.value||"1");
    }
    if(msg) msg.textContent = "Saved ✅";
  }catch(e){
    if(msg) msg.textContent = "Error: " + String(e.message||e);
  }
}

async function savePriorities(){
  const msg = $("gpu_prio_msg");
  if(msg) msg.textContent = trLabel("admin.gpu.prio.saving","Zapisuję…","Saving…");
  try{
    const resp = await apiJson("/api/admin/gpu/priorities", {
      method: "POST",
      headers: {"content-type":"application/json"},
      body: JSON.stringify({order: getOrderFromDOM()})
    });
    prioDirty = false;
    if(resp && resp.priorities) updatePriorityNumbers(resp.priorities);
    if(msg) msg.textContent = trLabel("admin.gpu.prio.saved","Zapisano ✅","Saved ✅");
  }catch(e){
    if(msg) msg.textContent = trLabel("admin.gpu.prio.save_error","Błąd zapisu:","Save error:") + " " + String(e.message||e);
  }
}

document.addEventListener("DOMContentLoaded", ()=>{
  const btn = $("gpu_cfg_save");
  if(btn) btn.addEventListener("click", saveConfig);

  // mark dirty on edit so auto-refresh does not reset values
  const mfIn = $("gpu_mem_fraction");
  const spgIn = $("gpu_slots_per_gpu");
  const csIn = $("gpu_cpu_slots");
  if(mfIn) mfIn.addEventListener("input", markCfgDirty);
  if(spgIn) spgIn.addEventListener("input", markCfgDirty);
  if(csIn) csIn.addEventListener("input", markCfgDirty);
  // Priorities: autosave on reorder

  refreshAll().catch(e=>console.error(e));
  // Auto-refresh GPU status — pause when tab hidden to save CPU/network
  var _gpuTimer = setInterval(()=>{ refreshAll().catch(()=>{}); }, 3000);
  document.addEventListener("visibilitychange", function() {
    if (document.hidden) {
      if (_gpuTimer) { clearInterval(_gpuTimer); _gpuTimer = null; }
    } else {
      if (!_gpuTimer) {
        refreshAll().catch(()=>{});
        _gpuTimer = setInterval(()=>{ refreshAll().catch(()=>{}); }, 3000);
      }
    }
  });
});
