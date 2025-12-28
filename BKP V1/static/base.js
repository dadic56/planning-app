const wd = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"];

let employeesCache = [];

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
  const digits = (contract || "").replace(/[^0-9]/g, "");
  return digits ? parseInt(digits, 10) : null;
}

function formatHours(value){
  if(value === null || value === undefined) return "—";
  const num = Number(value);
  if(Number.isNaN(num)) return String(value);
  const rounded = Math.round(num * 100) / 100;
  const text = Number.isInteger(rounded) ? rounded.toString() : rounded.toString().replace(/0+$/, '').replace(/\.$/, '');
  return `${text}h`;
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
    tr.innerHTML = `
      <td>${emp.name}</td>
      <td>${emp.contract_type || "—"}</td>
      <td>${formatHours(baseHours)}</td>
      <td>${emp.therapeutic_part_time ? `<span class="badge-mini">${thera}</span>` : '—'}</td>
      <td>${formatHours(supHours)}</td>
      <td style="width:1%;white-space:nowrap">
        <button type="button" class="ghost emp-edit" data-id="${emp.id}">Modifier</button>
      </td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".emp-edit").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.id);
      const emp = employeesCache.find(e => e.id === id);
      if(emp) fillEmployeeForm(emp);
      window.scrollTo({top:0, behavior:"smooth"});
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
  document.getElementById("empThera").checked = !!emp.therapeutic_part_time;
  document.getElementById("empTheraPct").value = emp.therapeutic_part_time && emp.therapeutic_percent ? emp.therapeutic_percent : "";
  document.getElementById("empRules").value = emp.special_rules || "";
  toggleTheraField();
  document.getElementById("empSubmit").textContent = "Mettre à jour";
}

function resetEmployeeForm(){
  document.getElementById("empForm").reset();
  document.getElementById("empId").value = "";
  document.getElementById("empContract").value = "35h";
  document.getElementById("empHours").value = "35";
  document.getElementById("empThera").checked = false;
  document.getElementById("empTheraPct").value = "";
  document.getElementById("empRules").value = "";
  toggleTheraField();
  document.getElementById("empSubmit").textContent = "Enregistrer vendeuse";
}

async function loadEmployees(){
  employeesCache = await j("/api/employees");
  renderEmployeeSelect();
  renderEmployeeTable();
}

async function loadList(){
  const day = document.getElementById("filterDay").value;
  const url = day ? `/api/base-shifts?weekday=${day}` : "/api/base-shifts";
  const rows = await j(url);
  const tb = document.getElementById("tbody");
  tb.innerHTML = "";
  const renderShiftRow = (r)=>{
    const tr=document.createElement("tr");
    const pause = r.lunch_start && r.lunch_end ? `${r.lunch_start} – ${r.lunch_end}` : "";
    tr.innerHTML = `
      <td>${r.employee}</td>
      <td>${wd[r.weekday]}</td>
      <td>${r.start_time}</td>
      <td>${r.end_time}</td>
      <td>${pause}</td>
      <td>${r.note||""}</td>
      <td class="actions">
        <button type="button" title="éditer" data-id="${r.id}" class="edit">Modifier</button>
        <button type="button" title="supprimer" data-id="${r.id}" class="del">Supprimer</button>
      </td>`;
    tb.appendChild(tr);
  };

  if(day){
    rows.sort((a,b)=> a.employee.localeCompare(b.employee) || a.start_time.localeCompare(b.start_time));
    rows.forEach(renderShiftRow);
  }else{
    const grouped = new Map();
    rows.forEach(r=>{
      if(!grouped.has(r.employee)) grouped.set(r.employee, []);
      grouped.get(r.employee).push(r);
    });
    const names = Array.from(grouped.keys()).sort((a,b)=>a.localeCompare(b));
    names.forEach(name=>{
      const section=document.createElement("tr");
      section.className="section-row";
      section.innerHTML = `<td colspan="7">${name}</td>`;
      tb.appendChild(section);
      grouped.get(name)
        .sort((a,b)=> (a.weekday - b.weekday) || a.start_time.localeCompare(b.start_time))
        .forEach(renderShiftRow);
    });
  }

  tb.querySelectorAll("button.edit").forEach(b=> b.onclick = ()=> editRow(parseInt(b.dataset.id), rows));
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

async function save(ev){
  ev.preventDefault();
  const payload = formData();
  const id = document.getElementById("editingId").value;
  if(id){
    await j(`/api/base-shifts/${id}`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  }else{
    await j(`/api/base-shifts`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  }
  resetForm();
  await loadList();
}

function resetForm(){
  document.getElementById("form").reset();
  document.getElementById("editingId").value = "";
}

function editRow(id, rows){
  const r = rows.find(x=>x.id===id); if(!r) return;
  document.getElementById("editingId").value = r.id;
  document.getElementById("employee").value = r.employee_id;
  document.getElementById("weekday").value = r.weekday;
  document.getElementById("start").value = r.start_time;
  document.getElementById("end").value = r.end_time;
  document.getElementById("lstart").value = r.lunch_start || "";
  document.getElementById("lend").value = r.lunch_end || "";
  document.getElementById("note").value = r.note || "";
  window.scrollTo({top:0, behavior:"smooth"});
}

async function delRow(id){
  if(!confirm("Supprimer ce créneau ?")) return;
  await j(`/api/base-shifts/${id}`, {method:"DELETE"});
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
  const payload = {
    name,
    contract_type: contractType,
    max_week_hours: hoursRaw !== null ? hoursRaw : null,
    therapeutic_part_time: thera,
    therapeutic_percent: thera ? pctValue : null,
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

const empForm = document.getElementById("empForm");
if(empForm){
  empForm.addEventListener("submit", saveEmployee);
}
const empReset = document.getElementById("empReset");
if(empReset){
  empReset.addEventListener("click", resetEmployeeForm);
}
const empAdd = document.getElementById("empAdd");
if(empAdd){
  empAdd.addEventListener("click", resetEmployeeForm);
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

document.getElementById("form").addEventListener("submit", save);
document.getElementById("reset").addEventListener("click", resetForm);
document.getElementById("filterDay").addEventListener("change", loadList);

(async function init(){
  resetEmployeeForm();
  await loadEmployees();
  await loadList();
})();
