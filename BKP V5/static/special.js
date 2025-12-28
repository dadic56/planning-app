let employees = [];
let openings = [];
let currentId = null;

const tableBody = document.getElementById('openingTable');
const form = document.getElementById('openingForm');
const btnNew = document.getElementById('newOpening');
const btnDelete = document.getElementById('deleteOpening');
const shiftList = document.getElementById('shiftList');

async function fetchJSON(url){
  const resp = await fetch(url);
  if(!resp.ok){ throw new Error(await resp.text() || `HTTP ${resp.status}`); }
  return resp.json();
}

async function loadEmployees(){
  employees = await fetchJSON('/api/employees');
}

async function loadOpenings(){
  openings = await fetchJSON('/api/special-openings');
  renderList();
  if(openings.length){
    const id = currentId || openings[0].id;
    selectOpening(id);
  }else{
    resetForm();
  }
}

function renderList(){
  tableBody.innerHTML = '';
  if(!openings.length){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="3" style="text-align:center;padding:24px;color:#64748b">Aucune ouverture planifiée.</td>';
    tableBody.appendChild(tr);
    return;
  }
  openings.forEach(entry => {
    const tr = document.createElement('tr');
    tr.dataset.id = entry.id;
    if(String(entry.id) === String(currentId)){
      tr.classList.add('selected');
    }
    const statusText = entry.is_closed ? 'Fermé' : (entry.sunday_mode ? 'Dimanche ouvert' : 'Ouvert');
    tr.innerHTML = `
      <td>${formatDateFR(entry.date)}</td>
      <td>${entry.label || '—'}</td>
      <td>${statusText}</td>`;
    tr.addEventListener('click', ()=> selectOpening(entry.id));
    tableBody.appendChild(tr);
  });
}

function formatDateFR(iso){
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('fr-FR', {weekday:'short', day:'2-digit', month:'2-digit'});
}

function resetForm(){
  currentId = null;
  form.reset();
  document.getElementById('openingId').value = '';
  document.getElementById('openingNotes').value = '';
  shiftList.innerHTML = '';
  btnDelete.style.display = 'none';
  updateHoursBlock();
}

async function selectOpening(id){
  try{
    currentId = id;
    const data = await fetchJSON(`/api/special-openings/${id}`);
    fillForm(data);
    tableBody.querySelectorAll('tr').forEach(tr => tr.classList.toggle('selected', String(tr.dataset.id) === String(id)));
  }catch(err){
    alert(`Impossible de charger : ${err.message}`);
    console.error(err);
  }
}

function fillForm(data){
  document.getElementById('openingId').value = data.id;
  document.getElementById('openingDate').value = data.date;
  document.getElementById('openingLabel').value = data.label || '';
  document.getElementById('openingSunday').checked = !!data.sunday_mode;
  document.getElementById('openingClosed').checked = !!data.is_closed;
  document.getElementById('openingOpen').value = data.open_time || '';
  document.getElementById('openingClose').value = data.close_time || '';
  document.getElementById('openingNotes').value = data.notes || '';
  shiftList.innerHTML = '';
  (data.shifts || []).forEach(shift => addShiftRow(shift));
  btnDelete.style.display = 'inline-flex';
  updateHoursBlock();
}

function addShiftRow(shift){
  const row = document.createElement('div');
  row.className = 'shift-row';
  const select = document.createElement('select');
  const sundayMode = document.getElementById('openingSunday').checked;
  if(!shift){ shift = {}; }
  employees.forEach(emp => {
    const option = document.createElement('option');
    option.value = emp.id;
    option.textContent = emp.name;
    if(sundayMode && !emp.sunday_available){
      option.disabled = true;
      option.textContent += ' (pas dimanche)';
    }
    select.appendChild(option);
  });
  if(shift.employee_id){
    select.value = shift.employee_id;
  }else{
    const firstAvailable = employees.find(e => !sundayMode || e.sunday_available);
    if(firstAvailable){ select.value = firstAvailable.id; }
  }

  const start = document.createElement('input');
  start.type = 'time'; start.value = shift.start_time || '';
  const end = document.createElement('input');
  end.type = 'time'; end.value = shift.end_time || '';
  const lstart = document.createElement('input');
  lstart.type = 'time'; lstart.value = shift.lunch_start || '';
  const lend = document.createElement('input');
  lend.type = 'time'; lend.value = shift.lunch_end || '';
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button'; removeBtn.className = 'btn-ghost';
  removeBtn.textContent = '✕';
  removeBtn.addEventListener('click', ()=> row.remove());

  row.appendChild(select);
  row.appendChild(start);
  row.appendChild(end);
  row.appendChild(lstart);
  row.appendChild(lend);
  row.appendChild(removeBtn);
  shiftList.appendChild(row);
}

function collectShifts(){
  const rows = Array.from(shiftList.querySelectorAll('.shift-row'));
  return rows.map(row => {
    const [sel, start, end, lstart, lend] = row.querySelectorAll('select,input');
    return {
      employee_id: sel.value,
      start_time: start.value,
      end_time: end.value,
      lunch_start: lstart.value,
      lunch_end: lend.value,
    };
  });
}

function updateHoursBlock(){
  const closed = document.getElementById('openingClosed').checked;
  const sunday = document.getElementById('openingSunday').checked;
  document.getElementById('openingOpen').disabled = closed;
  document.getElementById('openingClose').disabled = closed;
  document.getElementById('openingOpen').required = !closed;
  document.getElementById('openingClose').required = !closed;
  shiftList.parentElement.style.display = closed ? 'none' : 'block';
  if(closed){
    shiftList.innerHTML = '';
  }else{
    if(shiftList.children.length === 0){
      addShiftRow({});
    }
    // update select options to reflect sunday availability
    shiftList.querySelectorAll('select').forEach(select => {
      const current = select.value;
      select.innerHTML = '';
      employees.forEach(emp => {
        const option = document.createElement('option');
        option.value = emp.id;
        option.textContent = emp.name;
        if(sunday && !emp.sunday_available){
          option.disabled = true;
          option.textContent += ' (pas dimanche)';
        }
        select.appendChild(option);
      });
      if(current){ select.value = current; }
      if(!select.value){
        const firstAvail = employees.find(e => !sunday || e.sunday_available);
        if(firstAvail){ select.value = firstAvail.id; }
      }
    });
  }
}

form.addEventListener('submit', async (ev)=>{
  ev.preventDefault();
  const payload = {
    date: document.getElementById('openingDate').value,
    label: document.getElementById('openingLabel').value,
    sunday_mode: document.getElementById('openingSunday').checked,
    is_closed: document.getElementById('openingClosed').checked,
    open_time: document.getElementById('openingOpen').value,
    close_time: document.getElementById('openingClose').value,
    notes: document.getElementById('openingNotes').value,
    shifts: collectShifts(),
  };
  const id = document.getElementById('openingId').value;
  const method = id ? 'PUT' : 'POST';
  const url = id ? `/api/special-openings/${id}` : '/api/special-openings';
  try{
    const resp = await fetch(url, {
      method,
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    if(!resp.ok){ throw new Error(await resp.text() || `HTTP ${resp.status}`); }
    const result = await resp.json();
    if(result && result.opening){
      currentId = result.opening.id;
    }
    await loadOpenings();
    alert('Ouverture spéciale enregistrée.');
  }catch(err){
    alert(`Enregistrement impossible : ${err.message}`);
    console.error(err);
  }
});

btnDelete.addEventListener('click', async ()=>{
  const id = document.getElementById('openingId').value;
  if(!id) return;
  if(!confirm('Supprimer cette ouverture spéciale ?')) return;
  try{
    const resp = await fetch(`/api/special-openings/${id}`, {method:'DELETE'});
    if(!resp.ok){ throw new Error(await resp.text() || `HTTP ${resp.status}`); }
    await loadOpenings();
    resetForm();
  }catch(err){
    alert(`Suppression impossible : ${err.message}`);
    console.error(err);
  }
});

btnNew.addEventListener('click', ()=>{
  resetForm();
  tableBody.querySelectorAll('tr').forEach(tr=>tr.classList.remove('selected'));
});

document.getElementById('addShift').addEventListener('click', ()=> addShiftRow({}));
document.getElementById('openingClosed').addEventListener('change', updateHoursBlock);
document.getElementById('openingSunday').addEventListener('change', updateHoursBlock);

(async function init(){
  try{
    await loadEmployees();
    await loadOpenings();
  }catch(err){
    alert(`Erreur initialisation : ${err.message}`);
    console.error(err);
  }
})();
