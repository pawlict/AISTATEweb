/* Admin GPU Resource Manager (English-only logic; UI texts translated via i18n keys) */
"use strict";

function $(id){ return document.getElementById(id); }

let cfgDirty = false;

function markCfgDirty(){
  cfgDirty = true;
  const msg = $("gpu_cfg_msg");
  if(msg && !msg.textContent) msg.textContent = "Unsaved changes…";
}

async function apiJson(url, opts){
  const r = await fetch(url, opts || {});
  if(!r.ok){
    const txt = await r.text();
    throw new Error(`HTTP ${r.status}: ${txt}`);
  }
  return await r.json();
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
  refreshAll().catch(e=>console.error(e));
  setInterval(()=>{ refreshAll().catch(()=>{}); }, 2000);
});
