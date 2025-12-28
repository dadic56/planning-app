const wdNames = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"];
const DEFAULT_LUNCH_START = "12:00";
const DEFAULT_LUNCH_END   = "13:00";
const EVENING_START       = "17:00"; // seuil "soirée"

let employeesCache = [];

function toISO(d){ return d.toISOString().slice(0,10); }
function addDays(d, n){ const x=new Date(d); x.setDate(x.getDate()+n); return x; }
function minStr(s){ const [h,m]=String(s).split(":").map(Number); return h*60+m; }
function spanStr(m){ return (m/60).toFixed(2); }
function slotMinutes(slot){ return Math.max(0, minStr(slot.end) - minStr(slot.start)); }

function formatDateFR(iso){
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("fr-FR", {day:"2-digit", month:"2-digit"});
}

function employeeById(id){
  return employeesCache.find(e=>e.id === id);
}

function removedShifts(base, adjusted){
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

function effectiveSlots(dayEntry, useAdjusted){
  if(useAdjusted){
    return dayEntry.adjusted;
  }
  return dayEntry.base;
}

async function fetchJSON(url){
  const r = await fetch(url);
  if(!r.ok){ throw new Error(`HTTP ${r.status}: ${await r.text()}`); }
  return r.json();
}

async function loadBase(mondayISO){
  return await fetchJSON(`/api/base-week?monday=${encodeURIComponent(mondayISO)}`);
}
async function loadAdjusted(mondayISO){
  const endISO = toISO(addDays(new Date(mondayISO),6));
  return await fetchJSON(`/api/adjusted?from=${encodeURIComponent(mondayISO)}&to=${encodeURIComponent(endISO)}`);
}
async function loadViolations(mondayISO){
  const endISO = toISO(addDays(new Date(mondayISO),6));
  return await fetchJSON(`/api/violations?from=${encodeURIComponent(mondayISO)}&to=${encodeURIComponent(endISO)}`);
}
async function loadAbsencesRange(mondayISO){
  const endISO = toISO(addDays(new Date(mondayISO),6));
  return await fetchJSON(`/api/absences?from=${encodeURIComponent(mondayISO)}&to=${encodeURIComponent(endISO)}`);
}
async function deleteAbsence(aid){
  const r = await fetch(`/api/absences/${aid}`, {method:"DELETE"});
  if(!r.ok){ throw new Error(`HTTP ${r.status}: ${await r.text()}`); }
}
async function generateWeek(mondayISO, sundayOpen){
  const r = await fetch(`/api/generate-week?monday=${encodeURIComponent(mondayISO)}&sunday_open=${sundayOpen?"1":"0"}`, {method:"POST"});
  if(!r.ok){ throw new Error(`HTTP ${r.status}: ${await r.text()}`); }
}
async function saveSnapshotForWeek(mondayISO, sundayOpen, label, status){
  const payload = {monday: mondayISO, sunday_open: sundayOpen ? 1 : 0};
  if(label && label.trim()){
    payload.label = label.trim();
  }
  if(status){
    payload.status = status;
  }
  const r = await fetch("/api/snapshots", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });
  if(!r.ok){
    const detail = await r.text();
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json();
}
async function loadEmployees(){
  employeesCache = await fetchJSON("/api/employees");
  const sel = document.getElementById("absEmp");
  sel.innerHTML = "";
  employeesCache.forEach(e=>{
    const opt=document.createElement("option");
    opt.value=e.id; opt.textContent=`${e.name}${e.contract_type?` (${e.contract_type})`:""}`;
    sel.appendChild(opt);
  });
}

// -------- mapping & calculs -------
function groupByEmployeeAndDay(base, adjusted){
  const map = {};
  const ensure = name => {
    if(!map[name]){
      map[name] = Array.from({length:7}, () => ({base:[], adjusted:[]}));
    }
  };

  base.forEach(r=>{
    const d = new Date(r.date); const wd = (d.getDay()+6)%7;
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
    const d = new Date(r.date); const wd = (d.getDay()+6)%7;
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

function coverageByDay(map, useAdjusted, open="09:30", close="19:15"){
  const covOpen=[0,0,0,0,0,0,0], covClose=[0,0,0,0,0,0,0];
  const openM=minStr(open), closeM=minStr(close)-1;
  Object.values(map).forEach(days=>{
    days.forEach((day, idx)=>{
      const slots = effectiveSlots(day, useAdjusted);
      if(!slots.length) return;
      const coversOpen = slots.some(s=>{
        const start=minStr(s.start), end=minStr(s.end)-1;
        return start<=openM && openM<=end;
      });
      if(coversOpen) covOpen[idx]++;
      const coversClose = slots.some(s=>{
        const start=minStr(s.start), end=minStr(s.end)-1;
        return start<=closeM && closeM<=end;
      });
      if(coversClose) covClose[idx]++;
    });
  });
  return {covOpen, covClose};
}

function weeklyHours(map, useAdjusted){
  const sum = {};
  Object.entries(map).forEach(([name, days])=>{
    let total = 0;
    days.forEach(day=>{
      const slots = effectiveSlots(day, useAdjusted);
      slots.forEach(s=>{ total += slotMinutes(s); });
    });
    sum[name] = total;
  });
  return sum;
}

function renderChanges(adjusted, violations){
  const ul = document.getElementById("changes");
  if(!ul) return;
  ul.innerHTML = "";

  const changeLabels = {
    replacement: "Remplacement",
    reassigned: "Réaffecté",
    generated: "Créneau généré",
    manual: "Saisi manuellement"
  };
  const severityMeta = {
    critical: { text: "Critique", cls: "sev-critical" },
    high: { text: "Grave", cls: "sev-high" },
    medium: { text: "À surveiller", cls: "sev-medium" },
    low: { text: "Info", cls: "sev-low" },
    ok: { text: "Négligeable", cls: "sev-ok" }
  };
  const changeSeverity = {
    replacement: "medium",
    reassigned: "medium",
    generated: "low",
    manual: "low"
  };
  const violationLabels = {
    SHIFT_UNASSIGNED: "Créneau non couvert",
    COVER_OPEN: "Couverture insuffisante à l'ouverture",
    COVER_CLOSE: "Couverture insuffisante à la fermeture"
  };
  const violationSeverity = {
    SHIFT_UNASSIGNED: "critical",
    COVER_CLOSE: "high",
    COVER_OPEN: "high"
  };
  const violationHints = {
    SHIFT_UNASSIGNED: "Proposer un renfort (CDD 20h / CDI 24h) ou redistribuer les pauses pour étendre les amplitudes.",
    COVER_OPEN: "Augmenter la présence à 09:30 : avancer une prise de poste, autoriser un extra, ou décaler une absence.",
    COVER_CLOSE: "Prévoir un renfort jusqu'à 19:15 (CDD soir, heures sup autorisées) ou déplacer un créneau tardif d'une autre vendeuse."
  };

  const changeItems = [];
  adjusted.forEach(r => {
    if(r.source && r.source !== "base"){
      const d = new Date(r.date);
      const wd = wdNames[(d.getDay()+6)%7];
      const labelText = changeLabels[r.source] || r.source;
      const severityKey = changeSeverity[r.source] || "low";
      changeItems.push({
        severity: severityKey,
        label: `${labelText} → ${r.employee}`,
        detail: `${wd} ${r.start}–${r.end}`
      });
    }
  });

  const violationItems = (violations || []).map(v => {
    const d = new Date(v.date);
    const wd = wdNames[(d.getDay()+6)%7];
    const labelText = violationLabels[v.code] || (v.details ? v.details.split(" – ")[0] : v.code);
    const detailText = v.details || "";
    const sevFromCode = violationSeverity[v.code];
    let severityKey = sevFromCode;
    if(!severityKey){
      if(v.severity === "warn") severityKey = "high";
      else if(v.severity === "info") severityKey = "low";
      else severityKey = "medium";
    }
    const hint = violationHints[v.code] || (v.code === 'SHIFT_UNASSIGNED' ? violationHints.SHIFT_UNASSIGNED : null);
    const detailsWithHint = hint ? (detailText ? `${detailText} – ${hint}` : hint) : detailText;
    return {
      severity: severityKey,
      label: labelText,
      detail: detailsWithHint ? `${wd} – ${detailsWithHint}` : wd
    };
  });

  const appendSection = (title, items) => {
    if(!items.length) return;
    const head = document.createElement("li");
    head.className = "section";
    head.textContent = title;
    ul.appendChild(head);

    items
      .slice()
      .sort((a, b) => {
        if(a.detail && b.detail){
          return a.detail.localeCompare(b.detail);
        }
        return a.label.localeCompare(b.label);
      })
      .forEach(entry => {
        const meta = severityMeta[entry.severity] || severityMeta.medium;
        const li = document.createElement("li");
        li.className = "item";

        const badge = document.createElement("span");
        badge.className = `badge ${meta.cls}`;
        badge.textContent = meta.text;
        li.appendChild(badge);

        const textWrap = document.createElement("span");
        textWrap.className = "text";

        const labelSpan = document.createElement("span");
        labelSpan.className = "label";
        labelSpan.textContent = entry.label;
        textWrap.appendChild(labelSpan);

        if(entry.detail){
          const detailSpan = document.createElement("span");
          detailSpan.className = "details";
          detailSpan.textContent = entry.detail;
          textWrap.appendChild(detailSpan);
        }

        li.appendChild(textWrap);
        ul.appendChild(li);
      });
  };

  if(!changeItems.length && !violationItems.length){
    const li=document.createElement("li");
    li.className="small muted";
    li.textContent = "Aucune modification cette semaine.";
    ul.appendChild(li);
    return;
  }

  appendSection("Remplacements & ajustements", changeItems);
  appendSection("Alertes & contraintes", violationItems);
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

function renderAbsenceSummary(absences){
  const ul = document.getElementById("absSummary");
  if(!ul) return;
  ul.innerHTML = "";
  if(!absences.length){
    ul.innerHTML = '<li class="small muted">Aucune absence déclarée cette semaine.</li>';
    return;
  }
  const sorted = absences.slice().sort((a,b)=>{
    if(a.start_date === b.start_date){
      return (a.employee || "").localeCompare(b.employee || "");
    }
    return a.start_date.localeCompare(b.start_date);
  });
  sorted.forEach(a=>{
    const li = document.createElement("li");
    const dates = `${formatDateFR(a.start_date)} → ${formatDateFR(a.end_date)}`;
    const reason = a.reason ? ` (${a.reason})` : "";
    const span = document.createElement("span");
    span.textContent = `${a.employee || `#${a.employee_id}`} : ${dates}${reason}`;
    li.appendChild(span);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "abs-delete";
    btn.textContent = "Supprimer";
    btn.addEventListener("click", async ()=>{
      if(!confirm("Supprimer cette absence ?")) return;
      try {
        await deleteAbsence(a.id);
        const monday = document.getElementById("monday").value;
        await generateWeek(monday, document.getElementById("sun").checked);
        await refresh();
      } catch(e){
        alert("Erreur suppression absence: "+e.message);
        console.error(e);
      }
    });
    li.appendChild(btn);
    ul.appendChild(li);
  });
}

function renderGrid(map, cov, hours, opts={}){
  const useAdjusted = !!opts.useAdjusted;
  const absentIds = opts.absentIds || new Set();
  const nameToId = opts.nameToId || new Map();
  const caps = opts.caps || new Map();
  const tbody = document.getElementById("tbody");
  tbody.innerHTML = "";
  const RULE_OPEN=3, RULE_CLOSE=3;
  const openMinute = minStr("09:30");
  const closeMinute = minStr("19:15") - 1;
  const shortWd = ["Lu","Ma","Me","Je","Ve","Sa","Di"];

  Object.entries(map).forEach(([name, days])=>{
    const tr = document.createElement("tr");

    const tdName = document.createElement("td");
    tdName.className = "left-sticky name";
    const empId = nameToId.get(name);
    if(empId && absentIds.has(empId)){
      tdName.classList.add("absent");
      tdName.innerHTML = `${name} <span class="badge-absence">Absente</span>`;
    }else{
      tdName.textContent = name;
    }
    tr.appendChild(tdName);

    const openDays = [];
    const closeDays = [];

    days.forEach((dayEntry, dayIndex)=>{
      const td=document.createElement("td");
      td.className="cell";
      const removed = useAdjusted ? removedShifts(dayEntry.base, dayEntry.adjusted) : [];
      removed.sort((a,b)=>minStr(a.start)-minStr(b.start)).forEach(s=>{
        td.appendChild(makeTag(s, {ghost:true}));
      });

      const effective = effectiveSlots(dayEntry, useAdjusted);
      let totalDay=0;
      effective.slice().sort((a,b)=>minStr(a.start)-minStr(b.start))
        .forEach(s=>{
          const tag = makeTag(s);
          totalDay += slotMinutes(s);
          td.appendChild(tag);
        });

      const coversOpen = effective.some(s=>{
        const start = minStr(s.start);
        const end = minStr(s.end) - 1;
        return start <= openMinute && openMinute <= end;
      });
      const coversClose = effective.some(s=>{
        const start = minStr(s.start);
        const end = minStr(s.end) - 1;
        return start <= closeMinute && closeMinute <= end;
      });
      if(coversOpen) openDays.push(shortWd[dayIndex]);
      if(coversClose) closeDays.push(shortWd[dayIndex]);

      const totalLine = document.createElement("div");
      totalLine.className = "day-total";
      totalLine.textContent = `Total: ${spanStr(totalDay)}h`;
      td.appendChild(totalLine);

      tr.appendChild(td);
    });

    const tdO = document.createElement("td");
    const tdF = document.createElement("td");
    tdO.className="small"; tdF.className="small";
    tdO.textContent = openDays.length ? openDays.join(', ') : "—";
    tdF.textContent = closeDays.length ? closeDays.join(', ') : "—";
    tr.appendChild(tdO); tr.appendChild(tdF);

    const tdT = document.createElement("td");
    const m = hours[name]||0;
    const totalWrap = document.createElement("div");
    totalWrap.className = "total-hours";
    totalWrap.textContent = `${spanStr(m)}h`;
    tdT.appendChild(totalWrap);

    if(empId){
      const meta = caps.get(empId);
      if(meta){
        const baseHours = meta.base ?? meta.max ?? null;
        const maxHours = meta.max ?? baseHours;
        if(baseHours !== null){
          const deltaMinutes = m - baseHours * 60;
          if(deltaMinutes > 0.5){
            const sup = document.createElement("span");
            sup.className = "overtime-flag";
            sup.textContent = `+${spanStr(deltaMinutes)}h`;
            tdT.appendChild(sup);
          }
        }
        if(maxHours !== null){
          const maxMinutes = maxHours * 60;
          const diff = m - maxMinutes;
          if(diff > 0.5){
            tdT.classList.add("overtime-exceeded");
            const warn = document.createElement("span");
            warn.className = "overtime-cap-warning";
            warn.textContent = `> ${spanStr(maxMinutes)}h`;
            tdT.appendChild(warn);
          }
        }
      }
    }
    tr.appendChild(tdT);

    tbody.appendChild(tr);
  });

  for(let d=0; d<7; d++){
    const cell = document.getElementById(`c${d}`);
    const okOpen = (cov.covOpen[d] >= RULE_OPEN);
    const okClose = (cov.covClose[d] >= RULE_CLOSE);
    cell.innerHTML = `
      <div class="${okOpen?'ok':'ko'} small">Ouv: ${cov.covOpen[d]||0}/${RULE_OPEN}</div>
      <div class="${okClose?'ok':'ko'} small">Ferm: ${cov.covClose[d]||0}/${RULE_CLOSE}</div>
    `;
  }
  document.getElementById("ocov").textContent = "≥3 à 09:30";
  document.getElementById("fcov").textContent = "≥3 à 19:00";
}

async function refresh(){
  const monday = document.getElementById("monday").value;
  if(!monday) return;
  try{
    const [base, adjusted, violations, absences] = await Promise.all([
      loadBase(monday),
      loadAdjusted(monday),
      loadViolations(monday),
      loadAbsencesRange(monday)
    ]);
    const map = groupByEmployeeAndDay(base, adjusted);
    const useAdjusted = adjusted.length > 0;
    const cov = coverageByDay(map, useAdjusted);
    const hours = weeklyHours(map, useAdjusted);
    const nameToId = new Map((employeesCache||[]).map(e=>[e.name, e.id]));
    const absentIds = new Set(absences.map(a=>a.employee_id));
    const caps = new Map((employeesCache||[]).map(e=>[
      e.id,
      {
        base: typeof e.base_week_hours === "number" ? e.base_week_hours : (typeof e.max_week_hours === "number" ? e.max_week_hours : null),
        max: typeof e.max_week_hours_with_sup === "number" ? e.max_week_hours_with_sup : (typeof e.max_week_hours === "number" ? e.max_week_hours : null)
      }
    ]));
    renderGrid(map, cov, hours, {useAdjusted, nameToId, absentIds, caps});
    renderChanges(adjusted, violations);
    renderAbsenceSummary(absences);
  }catch(e){
    alert("Erreur chargement: "+e.message);
    console.error(e);
  }
}

// Absences
document.getElementById("absBtn").addEventListener("click", async ()=>{
  const ids = Array.from(document.getElementById("absEmp").selectedOptions).map(o=>o.value);
  const start = document.getElementById("absStart").value;
  const end = document.getElementById("absEnd").value;
  const reason = document.getElementById("absReason").value;
  const monday = document.getElementById("monday").value;
  if(!ids.length||!start||!end){ alert("Sélectionnez au moins une vendeuse et des dates"); return; }
  try{
    for(const id of ids){
      const r = await fetch("/api/absences", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({employee_id:id,start_date:start,end_date:end,reason})
      });
      if(!r.ok){ throw new Error(await r.text()); }
    }
    await generateWeek(monday, document.getElementById("sun").checked);
    await refresh();
  }catch(e){
    alert("Erreur absence: "+e.message);
    console.error(e);
  }
});

// Génération
document.getElementById("gen").addEventListener("click", async ()=>{
  const monday = document.getElementById("monday").value;
  if(!monday){ alert("Choisir un lundi"); return; }
  try{
    await generateWeek(monday, document.getElementById("sun").checked);
    await refresh();
  }catch(e){
    alert("Erreur génération: "+e.message);
    console.error(e);
  }
});

const snapshotBtn = document.getElementById("snapshotBtn");
if(snapshotBtn){
  snapshotBtn.addEventListener("click", async ()=>{
    const monday = document.getElementById("monday").value;
    if(!monday){
      alert("Choisir un lundi avant d'archiver.");
      return;
    }
    const defaultLabel = `Semaine du ${formatDateFR(monday)}`;
    const input = prompt("Nom du planning archivé (optionnel)", defaultLabel);
    if(input === null){
      return;
    }
    let status = prompt("Statut de l'archive (draft, prévisionnel, validé)", "prévisionnel");
    if(status === null){
      return;
    }
    status = status.trim().toLowerCase();
    if(status === "previsionnel") status = "prévisionnel";
    if(!["draft","prévisionnel","valide"].includes(status)){
      alert("Statut invalide. Utiliser draft, prévisionnel ou validé.");
      return;
    }
    try {
      const res = await saveSnapshotForWeek(monday, document.getElementById("sun").checked, input ? input : null, status);
      const label = res?.snapshot?.label || defaultLabel;
      alert(`Planning archivé : ${label}`);
    } catch(err){
      alert(`Impossible d'archiver : ${err.message}`);
      console.error(err);
    }
  });
}

// Init
(async function init(){
  const inp = document.getElementById("monday");
  const now = new Date();
  const wd = (now.getDay()+6)%7; // 0=lundi
  const monday = new Date(now);
  monday.setDate(now.getDate()-wd);
  inp.value = monday.toISOString().slice(0,10);

  await loadEmployees();
  await refresh();
})();
