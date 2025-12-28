function el(id){return document.getElementById(id)}

// map employee_id -> name
const employeeMap = {};

async function loadEmployees(){
  try{
    const r = await fetch('/api/employees');
    if(!r.ok) return;
    const arr = await r.json();
    for(const e of arr) employeeMap[e.id] = e.name;
  }catch(e){
    console.warn('unable to load employees', e);
  }
}

function renderAdjusted(adjusted){
  if(!adjusted || adjusted.length===0){ el('adjusted').innerHTML = '<p>Aucun shift ajusté.</p>'; return }
  let html = '<table><tr><th>Employée</th><th>Date</th><th>Début</th><th>Fin</th><th>Pause</th><th>Source</th><th>Note</th></tr>';
  for(const s of adjusted){
    const pause = s.lunch_start ? `${s.lunch_start}-${s.lunch_end||''}` : '';
    const name = employeeMap[s.employee_id] || (`#${s.employee_id}`);
    html += `<tr><td>${name}</td><td>${s.date}</td><td>${s.start_time}</td><td>${s.end_time}</td><td>${pause}</td><td>${s.source||''}</td><td>${s.note||''}</td></tr>`;
  }
  html += '</table>';
  el('adjusted').innerHTML = html;
}

function renderViolations(violations){
  if(!violations || violations.length===0){ el('violations').innerHTML = '<p>Aucune violation.</p>'; return }
  let html = '<table><tr><th>Date</th><th>Employée</th><th>Code</th><th>Détails</th><th>Sévérité</th></tr>';
  for(const v of violations){
    const name = v.employee_id ? (employeeMap[v.employee_id] || `#${v.employee_id}`) : '';
    html += `<tr><td>${v.date}</td><td>${name}</td><td>${v.code}</td><td>${v.details||''}</td><td>${v.severity||''}</td></tr>`;
  }
  html += '</table>';
  el('violations').innerHTML = html;
}

async function load(){
  await loadEmployees();
  const path = window.location.pathname;
  const match = path.match(/\/snapshots\/(\d+)\/view/);
  if(!match) return;
  const id = match[1];
  const res = await fetch('/api/snapshots/'+id);
  if(!res.ok){ alert('Impossible de charger l archive'); return }
  const data = await res.json();
  el('meta').innerHTML = `<p><strong>${data.label||''}</strong> — ${data.monday} → ${data.sunday} — <em>${data.status||''}</em></p>`;
  renderAdjusted(data.data && data.data.adjusted ? data.data.adjusted : []);
  renderViolations(data.data && data.data.violations ? data.data.violations : []);

  el('back').onclick = ()=> window.history.back();
  el('download').onclick = ()=> { window.location.href = `/api/snapshots/${id}/download`; };
  el('restore').onclick = async ()=>{
    if(!confirm('Restaurer cet archive ?')) return;
    const r = await fetch(`/api/snapshots/${id}/restore`, {method:'POST'});
    if(r.ok) alert('Restauration terminée'); else alert('Erreur');
  };
}

window.addEventListener('load', load);
