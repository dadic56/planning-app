const wd = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"];

let employeesCache = [];
const empForm = document.getElementById("empForm");
const empFormDock = document.getElementById("empFormDock");
const shiftForm = document.getElementById("form");
const shiftFormDock = document.getElementById("shiftFormDock");
const empSubmitBtn = empForm ? empForm.querySelector("button[type='submit']") : null;
const shiftSubmitBtn = shiftForm ? shiftForm.querySelector("button[type='submit']") : null;
let empInitialSnapshot = null;
let currentEmpRow = null;
let currentShiftRow = null;
let shiftInitialSnapshot = null;

async function j(url, opt){
  const r = await fetch(url, opt);
  if(!r.ok){
    let detail;
    try{ detail = await r.text(); }catch{ detail = r.statusText; }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}

function hoursFromContract(contract){
  if(!contract) return null;
  const normalized = contract.toString().replace(',', '.');
  const match = normalized.match(/\d+(?:\.\d+)?/);
  return match ? parseFloat(match[0]) : null;
}

function formatHours(value){
  if(value === null || value === undefined) return "—";
  const num = Number(value);
  if(Number.isNaN(num)) return String(value);
  const rounded = Math.round(num * 100) / 100;
  const text = Number.isInteger(rounded) ? rounded.toString() : rounded.toString().replace(/0+$/, '').replace(/\.$/, '');
  return `${text}h`;
}

function minutesBetween(start, end){
  const toMinutes = (t)=>{
    if(!t) return 0;
    const [h,m] = t.split(":").map(Number);
    return h*60 + m;
  };
  return Math.max(0, toMinutes(end) - toMinutes(start));
}

function toggleTheraField(){
  const cb = document.getElementById("empThera");
  const field = document.getElementById("theraField");
  if(cb.checked){
    field.style.display = "flex";
  }else{
    field.style.display = "none";
    document.getElementById("empTheraPct").value = "";
  }
}

function employeeFormData(){
  return {
    id: document.getElementById("empId").value,
    name: document.getElementById("empName").value.trim(),
    contract: document.getElementById("empContract").value,
    hours: document.getElementById("empHours").value,
    allowOvertime: document.getElementById("empAllowOvertime").checked,
    thera: document.getElementById("empThera").checked,
    theraPct: document.getElementById("empTheraPct").value,
    sunday: document.getElementById("empSunday").checked,
    rules: document.getElementById("empRules").value.trim(),
  };
}

function isEmployeeDirty(){
  if(!empForm) return false;
  const editing = Boolean(document.getElementById("empId").value);
  if(!editing){
    const data = employeeFormData();
    return Boolean(data.name || data.hours || data.rules || data.thera || data.theraPct || !data.allowOvertime || data.sunday);
  }
  if(!empInitialSnapshot) return true;
  const current = employeeFormData();
  return Object.keys(empInitialSnapshot).some(key => {
    const prev = empInitialSnapshot[key];
    const now = current[key];
    if(typeof prev === "boolean" || typeof now === "boolean"){
      return Boolean(prev) !== Boolean(now);
    }
    return (prev || "") !== (now || "");
  });
}

function updateEmployeeSubmitLabel(){
  if(!empSubmitBtn) return;
  const editing = Boolean(document.getElementById("empId").value);
  if(!editing){
    empSubmitBtn.textContent = "Enregistrer vendeuse";
    return;
  }
  empSubmitBtn.textContent = isEmployeeDirty() ? "Mettre à jour" : "Fermer";
}

function dockEmployeeForm(){
  if(!empForm || !empFormDock) return;
  if(currentEmpRow){
    currentEmpRow.remove();
    currentEmpRow = null;
  }
  if(empForm.parentElement !== empFormDock){
    empFormDock.appendChild(empForm);
  }
  empForm.classList.remove("editing");
}

function showEmployeeFormInline(anchorRow){
  if(!empForm) return;
  if(!anchorRow){
    dockEmployeeForm();
    return;
  }
  if(currentEmpRow && currentEmpRow.previousElementSibling === anchorRow){
    return;
  }
  dockEmployeeForm();
  const inline = document.createElement("tr");
  inline.className = "emp-inline";
  const cell = document.createElement("td");
  cell.colSpan = 8;
  inline.appendChild(cell);
  anchorRow.after(inline);
  cell.appendChild(empForm);
  empForm.classList.add("editing");
  currentEmpRow = inline;
}

function renderEmployeeSelect(){
  const sel = document.getElementById("employee");
  if(!sel) return;
  const current = sel.value;
  sel.innerHTML = "";
  employeesCache.forEach(e => {
    const opt = document.createElement("option");
    opt.value = e.id;
    const thera = e.therapeutic_part_time && e.therapeutic_percent ? ` • ${e.therapeutic_percent}%` : "";
    opt.textContent = `${e.name} (${e.contract_type}${thera})`;
    sel.appendChild(opt);
  });
  if(current){
    sel.value = current;
    if(sel.value !== current && sel.options.length){
      sel.selectedIndex = 0;
    }
  }
}

function renderEmployeeTable(){
  const tbody = document.getElementById("empTableBody");
  if(!tbody) return;
  tbody.innerHTML = "";
  employeesCache.slice().sort((a,b)=>a.name.localeCompare(b.name)).forEach(emp => {
    const tr = document.createElement("tr");
    const baseHours = emp.base_week_hours ?? emp.max_week_hours;
    const supHours = emp.max_week_hours_with_sup ?? emp.max_week_hours;
    const thera = emp.therapeutic_part_time ? `${emp.therapeutic_percent || ""}%` : "—";
    const overtimeLabel = emp.allow_overtime ? '<span class="badge-mini" style="background:#eaf8f2;color:#0b6c3c">Autorisé</span>' : '<span class="badge-mini" style="background:#ffe6e6;color:#a10e0e">Interdit</span>';
    const sundayLabel = emp.sunday_available ? '<span class="badge-mini" style="background:#fef3c7;color:#92400e">Oui</span>' : '—';
    tr.innerHTML = `
      <td>${emp.name}</td>
      <td>${emp.contract_type || "—"}</td>
      <td>${formatHours(baseHours)}</td>
      <td>${emp.therapeutic_part_time ? `<span class="badge-mini">${thera}</span>` : '—'}</td>
      <td>${formatHours(supHours)}</td>
      <td>${sundayLabel}</td>
      <td>${overtimeLabel}</td>
      <td style="width:1%;white-space:nowrap">
        <button type="button" class="ghost emp-edit" data-id="${emp.id}">Modifier</button>
      </td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".emp-edit").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.id);
      const emp = employeesCache.find(e => e.id === id);
      if(emp){
        fillEmployeeForm(emp);
        const row = btn.closest("tr");
        showEmployeeFormInline(row);
      }
    });
  });
}

function fillEmployeeForm(emp){
  document.getElementById("empId").value = emp.id;
  document.getElementById("empName").value = emp.name;
  const contractValue = (emp.contract_type || "").trim();
  const contractSel = document.getElementById("empContract");
  if(["24h","35h"].includes(contractValue)){
    contractSel.value = contractValue;
  }else{
    contractSel.value = "autre";
  }
  const hours = emp.max_week_hours || hoursFromContract(contractValue) || "";
  document.getElementById("empHours").value = hours;
  document.getElementById("empAllowOvertime").checked = emp.allow_overtime !== false;
  document.getElementById("empThera").checked = !!emp.therapeutic_part_time;
  document.getElementById("empTheraPct").value = emp.therapeutic_part_time && emp.therapeutic_percent ? emp.therapeutic_percent : "";
  document.getElementById("empSunday").checked = !!emp.sunday_available;
  document.getElementById("empRules").value = emp.special_rules || "";
  toggleTheraField();
  empInitialSnapshot = employeeFormData();
  updateEmployeeSubmitLabel();
}

function resetEmployeeForm(){
  if(!empForm) return;
  empForm.reset();
  document.getElementById("empId").value = "";
  document.getElementById("empContract").value = "35h";
  document.getElementById("empHours").value = "35";
  document.getElementById("empAllowOvertime").checked = true;
  document.getElementById("empThera").checked = false;
  document.getElementById("empTheraPct").value = "";
  document.getElementById("empSunday").checked = false;
  document.getElementById("empRules").value = "";
  toggleTheraField();
  dockEmployeeForm();
  empInitialSnapshot = null;
  updateEmployeeSubmitLabel();
}

async function loadEmployees(){
  dockEmployeeForm();
  employeesCache = await j("/api/employees");
  renderEmployeeSelect();
  renderEmployeeTable();
}

async function loadList(){
  dockShiftForm();
  const day = document.getElementById("filterDay").value;
  const url = day ? `/api/base-shifts?weekday=${day}` : "/api/base-shifts";
  const rows = await j(url);
  const tb = document.getElementById("tbody");
  tb.innerHTML = "";
  const renderShiftRow = (r)=>{
    const tr=document.createElement("tr");
    const pause = r.lunch_start && r.lunch_end ? `${r.lunch_start} – ${r.lunch_end}` : "";
    const durationMinutes = minutesBetween(r.start_time, r.end_time);
    const durationLabel = formatHours(durationMinutes/60);
    tr.innerHTML = `
      <td>${r.employee}</td>
      <td>${wd[r.weekday]}</td>
      <td>${r.start_time}</td>
      <td>${r.end_time}</td>
      <td>${durationLabel}</td>
      <td>${pause}</td>
      <td>${r.note||""}</td>
      <td class="actions">
        <button type="button" title="éditer" data-id="${r.id}" class="edit">Modifier</button>
        <button type="button" title="supprimer" data-id="${r.id}" class="del">Supprimer</button>
      </td>`;
    tb.appendChild(tr);
  };

  const totals = {};
  rows.forEach(r=>{
    const minutes = minutesBetween(r.start_time, r.end_time);
    totals[r.employee] = (totals[r.employee] || 0) + minutes;
  });

  if(day){
    rows.sort((a,b)=> a.employee.localeCompare(b.employee) || a.start_time.localeCompare(b.start_time));
    rows.forEach(renderShiftRow);

    const workingIds = new Set(rows.map(r=>r.employee_id));
    const weekdayLabel = wd[Number(day)] || "";
    employeesCache
      .slice()
      .sort((a,b)=>a.name.localeCompare(b.name))
      .forEach(emp => {
        if(workingIds.has(emp.id)) return;
        const tr = document.createElement("tr");
        tr.className = "rest-row";
        tr.innerHTML = `
          <td>${emp.name}</td>
          <td>${weekdayLabel}</td>
          <td colspan="5" class="rest-label">Repos</td>
          <td></td>`;
        tb.appendChild(tr);
      });
  }else{
    const grouped = new Map();
    rows.forEach(r=>{
      if(!grouped.has(r.employee)) grouped.set(r.employee, []);
      grouped.get(r.employee).push(r);
    });

    employeesCache.forEach(emp => {
      if(!grouped.has(emp.name)){
        grouped.set(emp.name, []);
      }
    });

    const names = Array.from(grouped.keys()).sort((a,b)=>a.localeCompare(b));
    names.forEach(name=>{
      const section=document.createElement("tr");
      section.className="section-row";
      const totalBadge = totals[name] ? `<span class="hours-badge">${formatHours(totals[name]/60)}</span>` : '';
      section.innerHTML = `<td colspan="8">${name} ${totalBadge}</td>`;
      tb.appendChild(section);

      const entries = grouped.get(name)
        .sort((a,b)=> (a.weekday - b.weekday) || a.start_time.localeCompare(b.start_time));

      if(entries.length === 0){
        const empty = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 8;
        cell.textContent = "Aucun créneau enregistré.";
        empty.appendChild(cell);
        tb.appendChild(empty);
        return;
      }

      entries.forEach(renderShiftRow);
    });
  }

  tb.querySelectorAll("button.edit").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = parseInt(btn.dataset.id, 10);
      const anchor = btn.closest("tr");
      editRow(id, rows, anchor);
    });
  });
  tb.querySelectorAll("button.del").forEach(b=> b.onclick = ()=> delRow(parseInt(b.dataset.id)));
}

function formData(){
  return {
    employee_id: document.getElementById("employee").value,
    weekday:     document.getElementById("weekday").value,
    start_time:  document.getElementById("start").value,
    end_time:    document.getElementById("end").value,
    lunch_start: document.getElementById("lstart").value || null,
    lunch_end:   document.getElementById("lend").value || null,
    note:        document.getElementById("note").value || null
  };
}

function isShiftDirty(){
  if(!shiftForm) return false;
  const data = formData();
  const id = document.getElementById("editingId").value;
  if(!id){
    return Boolean(data.employee_id && data.weekday && data.start_time && data.end_time);
  }
  if(!shiftInitialSnapshot) return true;
  return Object.keys(shiftInitialSnapshot).some(key => {
    const prev = shiftInitialSnapshot[key] ?? "";
    const now = data[key] ?? "";
    return prev !== now;
  });
}

function updateShiftSubmitLabel(){
  if(!shiftSubmitBtn) return;
  const editing = Boolean(document.getElementById("editingId").value);
  if(editing && !isShiftDirty()){
    shiftSubmitBtn.textContent = "Fermer";
  }else{
    shiftSubmitBtn.textContent = "Enregistrer";
  }
}

async function save(ev){
  ev.preventDefault();
  const payload = formData();
  const id = document.getElementById("editingId").value;
  try {
    if(id){
      await j(`/api/base-shifts/${id}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    }else{
      await j(`/api/base-shifts`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    }
    resetForm();
    await loadList();
  } catch(e){
    alert("Erreur lors de la création/modification du créneau : " + e.message);
    console.error(e);
  }
}

function resetForm(){
  dockShiftForm();
  if(shiftForm){
    shiftForm.reset();
  }
  document.getElementById("editingId").value = "";
  shiftInitialSnapshot = null;
  updateShiftSubmitLabel();
}

function editRow(id, rows, anchorRow){
  const r = rows.find(x=>x.id===id); if(!r) return;
  document.getElementById("editingId").value = r.id;
  document.getElementById("employee").value = r.employee_id;
  document.getElementById("weekday").value = r.weekday;
  document.getElementById("start").value = r.start_time;
  document.getElementById("end").value = r.end_time;
  document.getElementById("lstart").value = r.lunch_start || "";
  document.getElementById("lend").value = r.lunch_end || "";
  document.getElementById("note").value = r.note || "";
  if(!anchorRow){
    anchorRow = document.querySelector(`button.edit[data-id="${id}"]`)?.closest("tr");
  }
  showShiftFormInline(anchorRow);
  shiftInitialSnapshot = formData();
  updateShiftSubmitLabel();
}

function dockShiftForm(){
  if(!shiftForm || !shiftFormDock) return;
  if(currentShiftRow){
    currentShiftRow.remove();
    currentShiftRow = null;
  }
  if(shiftForm.parentElement !== shiftFormDock){
    shiftFormDock.appendChild(shiftForm);
  }
  shiftForm.classList.remove("editing");
}

function showShiftFormInline(anchorRow){
  if(!shiftForm) return;
  if(!anchorRow){
    dockShiftForm();
    return;
  }
  if(currentShiftRow && currentShiftRow.previousElementSibling === anchorRow){
    return;
  }
  dockShiftForm();
  const inline = document.createElement("tr");
  inline.className = "inline-editor";
  const cell = document.createElement("td");
  cell.colSpan = 8;
  inline.appendChild(cell);
  anchorRow.after(inline);
  cell.appendChild(shiftForm);
  shiftForm.classList.add("editing");
  currentShiftRow = inline;
}

async function delRow(id){
  if(!confirm("Supprimer ce créneau ?")) return;
  await j(`/api/base-shifts/${id}`, {method:"DELETE"});
  resetForm();
  await loadList();
}

async function saveEmployee(ev){
  ev.preventDefault();
  const id = document.getElementById("empId").value;
  const name = document.getElementById("empName").value.trim();
  if(!name){
    alert("Indiquer le prénom de la vendeuse.");
    return;
  }
  const contractSelect = document.getElementById("empContract").value;
  let contractType = contractSelect;
  if(contractSelect === "autre"){
    const customHours = document.getElementById("empHours").value;
    contractType = customHours ? `${customHours}h` : "";
  }
  if(!contractType){
    contractType = "35h";
  }
  const hoursRawValue = document.getElementById("empHours").value;
  const hoursRaw = hoursRawValue !== "" ? Number(hoursRawValue) : null;
  if(hoursRaw !== null && (Number.isNaN(hoursRaw) || hoursRaw <= 0)){
    alert("Les heures hebdomadaires doivent être supérieures à 0.");
    return;
  }
  const thera = document.getElementById("empThera").checked;
  const pctRawValue = document.getElementById("empTheraPct").value;
  if(thera && pctRawValue === ""){
    alert("Indiquer le pourcentage du mi-temps thérapeutique.");
    return;
  }
  const pctValue = pctRawValue !== "" ? Number(pctRawValue) : null;
  if(thera && (pctValue === null || Number.isNaN(pctValue))){
    alert("Pourcentage invalide.");
    return;
  }
  if(id && !isEmployeeDirty()){
    resetEmployeeForm();
    return;
  }
  const payload = {
    name,
    contract_type: contractType,
    max_week_hours: hoursRaw !== null ? hoursRaw : null,
    therapeutic_part_time: thera,
    therapeutic_percent: thera ? pctValue : null,
    allow_overtime: document.getElementById("empAllowOvertime").checked,
    sunday_available: document.getElementById("empSunday").checked,
    special_rules: document.getElementById("empRules").value.trim(),
  };

  try {
    if(id){
      await j(`/api/employees/${id}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    }else{
      await j(`/api/employees`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    }
    resetEmployeeForm();
    await loadEmployees();
    await loadList();
  } catch(err){
    alert(`Erreur enregistrement vendeuse : ${err.message || err}`);
    console.error(err);
  }
}

// --- événements ---

if(empForm){
  empForm.addEventListener("submit", saveEmployee);
  empForm.addEventListener("reset", ()=>{
    empInitialSnapshot = null;
    dockEmployeeForm();
    updateEmployeeSubmitLabel();
  });
  empForm.querySelectorAll("input, select, textarea").forEach(el=>{
    el.addEventListener("input", updateEmployeeSubmitLabel);
    el.addEventListener("change", updateEmployeeSubmitLabel);
  });
}
const empReset = document.getElementById("empReset");
if(empReset){
  empReset.addEventListener("click", ()=>{
    resetEmployeeForm();
    empInitialSnapshot = null;
  });
}
const empAdd = document.getElementById("empAdd");
if(empAdd){
  empAdd.addEventListener("click", ()=>{
    resetEmployeeForm();
    empInitialSnapshot = null;
  });
}
const empContract = document.getElementById("empContract");
if(empContract){
  empContract.addEventListener("change", (ev)=>{
    if(ev.target.value !== "autre"){
      const hours = hoursFromContract(ev.target.value);
      if(hours) document.getElementById("empHours").value = hours;
    }
  });
}
const empThera = document.getElementById("empThera");
if(empThera){
  empThera.addEventListener("change", toggleTheraField);
}

if(shiftForm){
  shiftForm.addEventListener("submit", save);
  shiftForm.querySelectorAll("input, select, textarea").forEach(el=>{
    el.addEventListener("input", updateShiftSubmitLabel);
    el.addEventListener("change", updateShiftSubmitLabel);
  });
}
const shiftReset = document.getElementById("shiftReset");
if(shiftReset){
  shiftReset.addEventListener("click", resetForm);
}
document.getElementById("filterDay").addEventListener("change", loadList);

(async function init(){
  resetEmployeeForm();
  await loadEmployees();
  await loadList();
})();
