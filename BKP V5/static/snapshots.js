const tbody = document.getElementById("snapBody");
const preview = document.getElementById("preview");
let currentSelection = null;
const WD_NAMES = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"];
const SHORT_WD = ["Lu","Ma","Me","Je","Ve","Sa","Di"];

function isoWeekdayIndex(iso){
  const date = new Date(iso + "T00:00:00");
  return (date.getDay()+6)%7;
}

function minStrLocal(s){
  const [h,m] = String(s||'0:0').split(':').map(Number);
  return h*60 + m;
}

function spanStr(minutes){
  return (minutes/60).toFixed(2);
}

function slotMinutes(slot){
  return Math.max(0, minStrLocal(slot.end) - minStrLocal(slot.start));
}

function removedShiftsSnapshot(base, adjusted){
  const counts = new Map();
  adjusted.forEach(s => {
    const key = `${s.start}|${s.end}`;
    counts.set(key, (counts.get(key)||0)+1);
  });
  const removed = [];
  base.forEach(s => {
    const key = `${s.start}|${s.end}`;
    const count = counts.get(key) || 0;
    if(count > 0){
      counts.set(key, count - 1);
    }else{
      removed.push(s);
    }
  });
  return removed;
}

function effectiveSlotsSnapshot(dayEntry, useAdjusted){
  return useAdjusted ? dayEntry.adjusted : dayEntry.base;
}

function groupSnapshotByEmployee(base, adjusted){
  const map = {};
  const ensure = name => {
    if(!map[name]){
      map[name] = Array.from({length:7}, () => ({base:[], adjusted:[]}));
    }
  };

  base.forEach(r=>{
    const wd = isoWeekdayIndex(r.date);
    ensure(r.employee);
    map[r.employee][wd].base.push({
      type:"base",
      source:"base",
      modified:false,
      start:r.start,
      end:r.end,
      lunch_start: r.lunch_start || null,
      lunch_end: r.lunch_end || null,
      date:r.date,
      employee:r.employee,
    });
  });

  adjusted.forEach(r=>{
    const wd = isoWeekdayIndex(r.date);
    ensure(r.employee);
    const src = r.source || "adjust";
    let t = "adjust";
    if(src === "base") t = "base";
    else if(src === "replacement" || src === "reassigned") t = "replacement";
    else if(src === "generated") t = "adjust";
    map[r.employee][wd].adjusted.push({
      type:t,
      source:src,
      modified: src !== "base",
      start:r.start,
      end:r.end,
      lunch_start: r.lunch_start || null,
      lunch_end: r.lunch_end || null,
      date:r.date,
      employee:r.employee,
    });
  });

  const ordered = {};
  Object.keys(map).sort((a,b)=>a.localeCompare(b)).forEach(k => { ordered[k] = map[k]; });
  return ordered;
}

function coverageSnapshot(map, useAdjusted, specialMap){
  const covOpen=[0,0,0,0,0,0,0], covClose=[0,0,0,0,0,0,0];
  const defaultOpen = minStrLocal('09:30');
  const defaultClose = minStrLocal('19:15') - 1;
  Object.values(map).forEach(days=>{
    days.forEach((day, idx)=>{
      const slots = effectiveSlotsSnapshot(day, useAdjusted);
      if(!slots.length) return;
      const special = specialMap ? specialMap[idx] : null;
      const openM = special && special.open_time ? minStrLocal(special.open_time) : defaultOpen;
      const closeM = special && special.close_time ? minStrLocal(special.close_time) - 1 : defaultClose;
      const coversOpen = slots.some(s=>{
        const start=minStrLocal(s.start), end=minStrLocal(s.end)-1;
        return start<=openM && openM<=end;
      });
      if(coversOpen) covOpen[idx]++;
      const coversClose = slots.some(s=>{
        const start=minStrLocal(s.start), end=minStrLocal(s.end)-1;
        return start<=closeM && closeM<=end;
      });
      if(coversClose) covClose[idx]++;
    });
  });
  return {covOpen, covClose};
}

function weeklyHoursSnapshot(map, useAdjusted){
  const sum = {};
  Object.entries(map).forEach(([name, days])=>{
    let total = 0;
    days.forEach(day=>{
      const slots = effectiveSlotsSnapshot(day, useAdjusted);
      slots.forEach(s=>{ total += slotMinutes(s); });
    });
    sum[name] = total;
  });
  return sum;
}

function makeTag(slot, opts={}){
  const ghost = !!opts.ghost;
  const modClass = slot.modified ? " modified" : "";
  const ghostClass = ghost ? " ghost" : "";
  const tag=document.createElement("div");
  tag.className = `tag ${slot.type}${modClass}${ghostClass}`;

  const spanRange=document.createElement("span");
  spanRange.className="range";
  spanRange.textContent = `${slot.start}–${slot.end}`;
  tag.appendChild(spanRange);

  const spanDur=document.createElement("span");
  spanDur.className="duration";
  spanDur.textContent = `${spanStr(slotMinutes(slot))}h`;
  tag.appendChild(spanDur);

  return tag;
}

function formatDateFR(iso){
  if(!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("fr-FR", {day:"2-digit", month:"2-digit", year:"numeric"});
}

async function fetchSnapshots(){
  const r = await fetch("/api/snapshots");
  if(!r.ok){ throw new Error(await r.text() || `HTTP ${r.status}`); }
  return r.json();
}

async function fetchSnapshot(id){
  const r = await fetch(`/api/snapshots/${id}`);
  if(!r.ok){ throw new Error(await r.text() || `HTTP ${r.status}`); }
  return r.json();
}

async function deleteSnapshot(id){
  const r = await fetch(`/api/snapshots/${id}`, {method:"DELETE"});
  if(!r.ok){ throw new Error(await r.text() || `HTTP ${r.status}`); }
}

function renderList(items){
  tbody.innerHTML = "";
  if(!items.length){
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="7" class="muted">Aucune archive disponible.</td>';
    tbody.appendChild(row);
    return;
  }
  items.forEach(item => {
    const tr = document.createElement("tr");
    tr.dataset.id = item.id;
    if(String(currentSelection) === String(item.id)){
      tr.classList.add('selected');
    }
    const created = item.created_at ? `${formatDateFR(item.created_at.slice(0,10))} ${item.created_at.slice(11,16)}` : '';
    const week = item.week_number ? `Semaine ${item.week_number}` : '';
    const statusLabel = item.status === 'valide' ? 'Validé' : (item.status === 'prévisionnel' ? 'Prévisionnel' : 'Brouillon');
    const badge = `<span class="badge ${item.status || 'draft'}">${statusLabel}</span>`;
    const constraints = [];
    if(item.constraints && item.constraints.length){
      constraints.push(item.constraints.join(', '));
    }
    if(item.sunday_open){
      constraints.push('Dimanche ouvert');
    }
    const constraintsText = constraints.length ? constraints.join(' • ') : '—';
    tr.innerHTML = `
      <td>${item.label || ''}</td>
      <td>${week ? week + ' – ' : ''}${formatDateFR(item.monday)} → ${formatDateFR(item.sunday)}</td>
      <td>${badge}<br><select data-id="${item.id}" data-action="status">
            <option value="draft" ${item.status === 'draft' ? 'selected' : ''}>Brouillon</option>
            <option value="prévisionnel" ${item.status === 'prévisionnel' ? 'selected' : ''}>Prévisionnel</option>
            <option value="valide" ${item.status === 'valide' ? 'selected' : ''}>Validé</option>
          </select></td>
      <td>${constraintsText}</td>
      <td>${created}</td>
      <td>${item.counts?.adjusted ?? 0}</td>
      <td class="actions">
        <button class="ghost" data-id="${item.id}" data-action="view">Voir</button>
        <button class="btn" data-id="${item.id}" data-action="restore">Restaurer</button>
        <button class="danger" data-id="${item.id}" data-action="delete">Supprimer</button>
      </td>`;
    tbody.appendChild(tr);
  });
}

function renderPreview(data){
  if(!data){
    preview.innerHTML = '<h3>Aucune archive sélectionnée</h3><p class="muted">Choisissez une archive pour afficher son contenu. Vous pourrez la télécharger au format JSON.</p>';
    return;
  }
  const counts = data.counts || {};
  const details = data.data || {};
  preview.innerHTML = '';
  const title = document.createElement('h3');
  title.textContent = data.label || 'Archive';
  preview.appendChild(title);

  const info = document.createElement('p');
  info.className = 'muted';
  info.textContent = `Semaine du ${formatDateFR(data.monday)} au ${formatDateFR(data.sunday)} – ${counts.adjusted || 0} créneaux, ${counts.violations || 0} alertes, ${counts.absences || 0} absences.`;
  preview.appendChild(info);

  const status = document.createElement('span');
  status.className = `badge ${data.status || 'draft'}`;
  status.textContent = data.status === 'valide' ? 'Validé' : (data.status === 'prévisionnel' ? 'Prévisionnel' : 'Brouillon');
  preview.appendChild(status);

  const meta = document.createElement('p');
  meta.className = 'muted';
  const weekInfo = data.week_number ? `Semaine ${data.week_number}` : '';
  const sundayInfo = details.sunday_open ? 'Dimanche ouvert' : 'Dimanche fermé';
  meta.textContent = `${weekInfo ? weekInfo + ' – ' : ''}${sundayInfo}`;
  preview.appendChild(meta);

  if(details.special_openings && details.special_openings.length){
    const spBlock = document.createElement('div');
    spBlock.className = 'muted';
    const title = document.createElement('strong');
    title.textContent = 'Ouvertures spéciales :';
    spBlock.appendChild(title);
    const list = document.createElement('ul');
    list.className = 'muted';
    details.special_openings.forEach(op => {
      const li = document.createElement('li');
      const status = op.is_closed ? 'Fermé' : `${op.open_time || ''} → ${op.close_time || ''}`;
      li.textContent = `${formatDateFR(op.date)} : ${op.label || '—'} (${status})`;
      list.appendChild(li);
    });
    spBlock.appendChild(list);
    preview.appendChild(spBlock);
  }

  const constraintsWrap = document.createElement('div');
  constraintsWrap.className = 'muted';
  if(details.absences && details.absences.length){
    const list = document.createElement('ul');
    list.className = 'muted';
    details.absences.forEach(abs => {
      const li = document.createElement('li');
      const reason = abs.reason ? ` (${abs.reason})` : '';
      li.textContent = `${abs.employee}: ${formatDateFR(abs.start_date)} → ${formatDateFR(abs.end_date)}${reason}`;
      list.appendChild(li);
    });
    const titleAbs = document.createElement('strong');
    titleAbs.textContent = 'Absences :';
    constraintsWrap.appendChild(titleAbs);
    constraintsWrap.appendChild(list);
  }else{
    constraintsWrap.textContent = 'Aucune absence enregistrée sur cette semaine.';
  }
  preview.appendChild(constraintsWrap);

  const downloadBtn = document.createElement('button');
  downloadBtn.className = 'btn';
  downloadBtn.textContent = 'Télécharger (JSON)';
  downloadBtn.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(details, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.label || 'planning'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
  preview.appendChild(downloadBtn);

  const tableWrapper = buildSnapshotTable(details);
  preview.appendChild(tableWrapper);

  if(details.violations && details.violations.length){
    const vioTitle = document.createElement('strong');
    vioTitle.textContent = 'Alertes :';
    preview.appendChild(vioTitle);
    const vioList = document.createElement('ul');
    vioList.className = 'muted';
    details.violations.forEach(v => {
      const li = document.createElement('li');
      li.textContent = `${formatDateFR(v.date)} – ${v.code}${v.details ? ' : ' + v.details : ''}`;
      vioList.appendChild(li);
    });
    preview.appendChild(vioList);
  }
}

async function refreshList(){
  try{
    const items = await fetchSnapshots();
    renderList(items);
    if(items.length && !currentSelection){
      await selectSnapshot(items[0].id);
    }
  }catch(err){
    tbody.innerHTML = `<tr><td colspan="7" class="muted">Erreur chargement : ${err.message}</td></tr>`;
    console.error(err);
  }
}

tbody.addEventListener('click', async (ev)=>{
  const btn = ev.target.closest('button[data-action]');
  if(!btn) return;
  const id = btn.dataset.id;
  if(btn.dataset.action === 'view'){
    await selectSnapshot(id);
  }else if(btn.dataset.action === 'restore'){
    if(!confirm('Remplacer le planning ajusté de cette semaine par cette archive ?')) return;
    try{
      const r = await fetch(`/api/snapshots/${id}/restore`, {method:'POST'});
      if(!r.ok){ throw new Error(await r.text() || `HTTP ${r.status}`); }
      alert('Archive restaurée. Rafraîchissez la semaine correspondante dans le planning.');
    }catch(err){
      alert(`Restauration impossible : ${err.message}`);
      console.error(err);
    }
  }else if(btn.dataset.action === 'delete'){
    if(!confirm('Supprimer cette archive ?')) return;
    try{
      await deleteSnapshot(id);
      renderPreview(null);
      await refreshList();
    }catch(err){
      alert(`Suppression impossible : ${err.message}`);
      console.error(err);
    }
  }
});

tbody.addEventListener('change', async (ev)=>{
  const select = ev.target.closest('select[data-action="status"]');
  if(!select) return;
  const id = select.dataset.id;
  const value = select.value;
  const previous = currentSelection;
  currentSelection = id;
  try{
    const r = await fetch(`/api/snapshots/${id}`, {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({status:value})
    });
    if(!r.ok){ throw new Error(await r.text() || `HTTP ${r.status}`); }
    await refreshList();
    if(previous){
      await selectSnapshot(previous);
    }
  }catch(err){
    alert(`Mise à jour statut impossible : ${err.message}`);
    console.error(err);
    await refreshList();
    if(previous){
      await selectSnapshot(previous);
    }
  }
});

renderPreview(null);
refreshList();

async function selectSnapshot(id){
  currentSelection = id;
  tbody.querySelectorAll('tr[data-id]').forEach(tr=>{
    tr.classList.toggle('selected', String(tr.dataset.id) === String(id));
  });
  try{
    const data = await fetchSnapshot(id);
    renderPreview(data);
  }catch(err){
    alert(`Erreur lecture archive : ${err.message}`);
    console.error(err);
  }
}

function buildSnapshotTable(details){
  const wrapper = document.createElement('div');
  wrapper.className = 'plan-wrapper';
  const table = document.createElement('table');
  table.className = 'plan-table';

  const thead = document.createElement('thead');
  const trHead = document.createElement('tr');
  trHead.innerHTML = '<th>Vendeuse</th><th>Lundi</th><th>Mardi</th><th>Mercredi</th><th>Jeudi</th><th>Vendredi</th><th>Samedi</th><th>Dimanche</th><th>Ouv.</th><th>Ferm.</th><th>Total (h)</th>';
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbodyEl = document.createElement('tbody');
  const base = details.base || [];
  const adjusted = details.adjusted || [];
  const map = groupSnapshotByEmployee(base, adjusted);
  const useAdjusted = adjusted.length > 0;
  const specialsByDate = {};
  (details.special_openings || []).forEach(op => {
    const dt = new Date(op.date + 'T00:00:00');
    const idx = (dt.getDay()+6)%7;
    specialsByDate[idx] = op;
  });
  const coverage = coverageSnapshot(map, useAdjusted, specialsByDate);
  const hours = weeklyHoursSnapshot(map, useAdjusted);

  Object.entries(map).forEach(([name, days])=>{
    const tr = document.createElement('tr');
    const tdName = document.createElement('td');
    tdName.textContent = name;
    tr.appendChild(tdName);

    const openDays = [];
    const closeDays = [];

    days.forEach((dayEntry, dayIndex)=>{
      const td = document.createElement('td');
      const removed = useAdjusted ? removedShiftsSnapshot(dayEntry.base, dayEntry.adjusted) : [];
      removed.sort((a,b)=>minStrLocal(a.start)-minStrLocal(b.start)).forEach(s=>{
        td.appendChild(makeTag(s, {ghost:true}));
      });

      const effective = effectiveSlotsSnapshot(dayEntry, useAdjusted);
      let totalDay = 0;
      const special = specialsByDate[dayIndex];
      const openMinute = special && special.open_time ? minStrLocal(special.open_time) : minStrLocal('09:30');
      const closeMinute = special && special.close_time ? minStrLocal(special.close_time) - 1 : minStrLocal('19:15') - 1;
      effective.slice().sort((a,b)=>minStrLocal(a.start)-minStrLocal(b.start)).forEach(s=>{
        td.appendChild(makeTag(s));
        totalDay += slotMinutes(s);
      });

      const coversOpen = effective.some(s=>{
        const start = minStrLocal(s.start);
        const end = minStrLocal(s.end) - 1;
        return start <= openMinute && openMinute <= end;
      });
      const coversClose = effective.some(s=>{
        const start = minStrLocal(s.start);
        const end = minStrLocal(s.end) - 1;
        return start <= closeMinute && closeMinute <= end;
      });
      if(coversOpen) openDays.push(SHORT_WD[dayIndex]);
      if(coversClose) closeDays.push(SHORT_WD[dayIndex]);

      const totalLine = document.createElement('div');
      totalLine.className = 'day-total';
      totalLine.textContent = `Total: ${spanStr(totalDay)}h`;
      td.appendChild(totalLine);

      tr.appendChild(td);
    });

    const tdOpen = document.createElement('td');
    tdOpen.textContent = openDays.length ? openDays.join(', ') : '—';
    tr.appendChild(tdOpen);

    const tdClose = document.createElement('td');
    tdClose.textContent = closeDays.length ? closeDays.join(', ') : '—';
    tr.appendChild(tdClose);

    const tdTotal = document.createElement('td');
    tdTotal.textContent = `${spanStr(hours[name] || 0)}h`;
    tr.appendChild(tdTotal);

    tbodyEl.appendChild(tr);
  });

  table.appendChild(tbodyEl);

  const tfoot = document.createElement('tfoot');
  const trFoot = document.createElement('tr');
  trFoot.innerHTML = '<td>Couverture (personnes)</td>';
  for(let d=0; d<7; d++){
    const cell = document.createElement('td');
    const okOpen = coverage.covOpen[d] >= 3;
    const okClose = coverage.covClose[d] >= 3;
    cell.innerHTML = `<div class="${okOpen?'ok':'ko'} small">Ouv: ${coverage.covOpen[d]||0}/3</div><div class="${okClose?'ok':'ko'} small">Ferm: ${coverage.covClose[d]||0}/3</div>`;
    trFoot.appendChild(cell);
  }
  const tdOpen = document.createElement('td');
  tdOpen.textContent = '≥3 à 09:30';
  trFoot.appendChild(tdOpen);
  const tdClose = document.createElement('td');
  tdClose.textContent = '≥3 à 19:15';
  trFoot.appendChild(tdClose);
  const tdEmpty = document.createElement('td');
  trFoot.appendChild(tdEmpty);
  tfoot.appendChild(trFoot);
  table.appendChild(tfoot);

  wrapper.appendChild(table);
  return wrapper;
}
