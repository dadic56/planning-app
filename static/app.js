const wdNames = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"];
const DEFAULT_LUNCH_START = "12:00";
const DEFAULT_LUNCH_END   = "13:00";
const EVENING_START       = "17:00"; // seuil "soirée"

let employeesCache = [];
const weekContexts = Array.from({length:2}, (_,idx)=>{
  const root = document.getElementById(`weekBlock${idx}`);
  if(!root) return null;
  return {
    root,
    tbody: document.getElementById(`tbody${idx}`),
    tbodyAdjusted: document.getElementById(`tbody${idx}_adjusted`),
    coverCells: Array.from(root.querySelectorAll('td[data-cover]')),
    coverCellsAdjusted: Array.from(root.querySelectorAll('td[data-cover-Adj]')),
    ocov: root.querySelector('[data-role="open-label"]'),
    fcov: root.querySelector('[data-role="close-label"]'),
    ocovAdj: root.querySelector('[data-role="open-label-Adj"]'),
    fcovAdj: root.querySelector('[data-role="close-label-Adj"]'),
    title: document.getElementById(`weekTitle${idx}`),
    subtitle: document.getElementById(`weekSubtitle${idx}`),
  };
});

function toISO(d){
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
function addDays(d, n){ const x=new Date(d); x.setDate(x.getDate()+n); return x; }
function minStr(s){ const [h,m]=String(s).split(":").map(Number); return h*60+m; }
function spanStr(m){ return (m/60).toFixed(2); }
function slotMinutes(slot){ return Math.max(0, minStr(slot.end) - minStr(slot.start)); }

function formatDateFR(iso){
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("fr-FR", {day:"2-digit", month:"2-digit"});
}

function isoWeekNumber(d){
  // d is Date
  const date = new Date(d.getTime());
  // Set to nearest Thursday: current date + 4 - current day number (Mon=1..Sun=7)
  const day = date.getDay() || 7;
  date.setDate(date.getDate() + 4 - day);
  const yearStart = new Date(date.getFullYear(), 0, 1);
  const weekNo = Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
  return weekNo;
}

function normalizeToMonday(isoDateStr){
  if(!isoDateStr) return isoDateStr;
  const d = new Date(isoDateStr + 'T00:00:00');
  const wd = (d.getDay()+6)%7; // 0=Mon..6=Sun
  if(wd === 0) return isoDateStr;
  const monday = addDays(d, -wd);
  return toISO(monday);
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
async function saveSnapshotForWeek(mondayISO, sundayOpen, label, status, weeks){
  const payload = {monday: mondayISO, sunday_open: sundayOpen ? 1 : 0};
  if(label && label.trim()){
    payload.label = label.trim();
  }
  if(status){
    payload.status = status;
  }
  if(weeks && Number(weeks) > 1){
    payload.weeks = Number(weeks);
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

function weeklyHours(map, useAdjusted, absenceByName, weekDates){
  const sum = {};
  Object.entries(map).forEach(([name, days])=>{
    let total = 0;
    const perNameAbs = absenceByName?.get(name);
    days.forEach((day, idx)=>{
      const iso = weekDates ? weekDates[idx] : null;
      if(perNameAbs && iso && perNameAbs.has(iso)){
        return;
      }
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
  // inline styles to avoid external theme/extension overriding layout
  tag.style.display = 'flex';
  tag.style.alignItems = 'center';
  tag.style.justifyContent = 'space-between';
  tag.style.gap = '8px';
  tag.style.padding = '4px 8px';
  tag.style.boxSizing = 'border-box';

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
    const reasonLabel = (a.reason || "").trim();
    const reasonText = reasonLabel ? `Absence – ${reasonLabel}` : "Absence";
    const span = document.createElement("span");
    span.textContent = `${a.employee || `#${a.employee_id}`} : ${dates} (${reasonText})`;
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
  const weekDates = opts.weekDates || [];
  const absenceDays = opts.absenceDays || new Map();
  const ctx = opts.context;
  if(!ctx || !ctx.tbody) return;
  const tbody = ctx.tbody;
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
    // Le badge "Absente" ne doit apparaître que dans le planning ajusté
    if(useAdjusted && empId && absentIds.has(empId)){
      tdName.classList.add("absent");
      tdName.innerHTML = `${name} <span class="badge-absence">Absente</span>`;
    }else{
      tdName.textContent = name;
    }
    tr.appendChild(tdName);

    days.forEach((dayEntry, dayIndex)=>{
      const td=document.createElement("td");
      td.className="cell";

      const cellInner = document.createElement('div');
      cellInner.className = 'cell-inner';

      const tagsWrap = document.createElement('div');
      tagsWrap.className = 'slot-list';

      let effective = effectiveSlots(dayEntry, useAdjusted).slice();
      const isoDate = (dayEntry.base[0]?.date) || (dayEntry.adjusted[0]?.date) || weekDates[dayIndex] || null;
      
      // Les absences n'affectent QUE le planning ajusté, jamais le planning de base
      const absenceReason = useAdjusted ? (()=>{
        if(!isoDate) return null;
        const byEmp = absenceDays.get(empId);
        if(!byEmp) return null;
        if(!byEmp.has(isoDate)) return null;
        return byEmp.get(isoDate);
      })() : null;
      
      if(absenceReason === null){
        const removed = useAdjusted ? removedShifts(dayEntry.base, dayEntry.adjusted) : [];
        removed.sort((a,b)=>minStr(a.start)-minStr(b.start)).forEach(s=>{
          tagsWrap.appendChild(makeTag(s, {ghost:true}));
        });
      }
      if(absenceReason !== null){
        effective = [];
      }
      let totalDay=0;
      effective.slice().sort((a,b)=>minStr(a.start)-minStr(b.start))
        .forEach(s=>{
          const tag = makeTag(s);
          totalDay += slotMinutes(s);
          tagsWrap.appendChild(tag);
        });

      if(!effective.length && absenceReason !== null){
        const badge=document.createElement("div");
        badge.className = "day-flag absence";
        badge.textContent = absenceReason ? `Absence – ${absenceReason}` : "Absence";
        tagsWrap.appendChild(badge);
      }

      cellInner.appendChild(tagsWrap);

      const totalLine = document.createElement("div");
      totalLine.className = "day-total";
      totalLine.textContent = `Total: ${spanStr(totalDay)}h`;
      cellInner.appendChild(totalLine);

      td.appendChild(cellInner);
      tr.appendChild(td);
    });

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
    const cell = ctx.coverCells ? ctx.coverCells[d] : null;
    if(cell){
      const okOpen = (cov.covOpen[d] >= RULE_OPEN);
      const okClose = (cov.covClose[d] >= RULE_CLOSE);
      cell.innerHTML = `
        <div class="${okOpen?'ok':'ko'} small">Ouv: ${cov.covOpen[d]||0}/${RULE_OPEN}</div>
        <div class="${okClose?'ok':'ko'} small">Ferm: ${cov.covClose[d]||0}/${RULE_CLOSE}</div>
      `;
    }
  }
}

async function refresh(){
  const monday = document.getElementById("monday").value;
  if(!monday) return;
  try{
    const weekCount = Number(document.getElementById("weekCount")?.value || 1);
    const baseDate = new Date(`${monday}T00:00:00`);
    const weekMondays = Array.from({length:weekCount}, (_,idx)=> toISO(addDays(baseDate, idx*7)));

    const perWeek = await Promise.all(weekMondays.map(async startISO => {
      const [base, adjusted, violations, absences] = await Promise.all([
        loadBase(startISO),
        loadAdjusted(startISO),
        loadViolations(startISO),
        loadAbsencesRange(startISO)
      ]);
      return {
        monday: startISO,
        sunday: toISO(addDays(new Date(`${startISO}T00:00:00`), 6)),
        base,
        adjusted,
        violations,
        absences,
      };
    }));

    const allAdjusted = perWeek.flatMap(w => w.adjusted);
    const allViolations = perWeek.flatMap(w => w.violations);
    const allAbsences = perWeek.flatMap(w => w.absences);
    const uniqueAbsences = Array.from(new Map(allAbsences.map(a => [a.id, a])).values());

    // Debug info: expose counts so we can see what the browser received
    try{
      const dbg = document.getElementById('debugInfo');
      if(dbg){
        const baseCounts = perWeek.map(w=> (w.base||[]).length );
        const adjCounts = perWeek.map(w=> (w.adjusted||[]).length );
        dbg.textContent = `emps=${(employeesCache||[]).length} base=[${baseCounts.join(',')}] adj=[${adjCounts.join(',')}]`;
      }
    }catch(_e){/* ignore */}

    renderChanges(allAdjusted, allViolations);
    renderAbsenceSummary(uniqueAbsences);

    // Update main week info under header (show week number and range for first displayed week)
    try{
      const mainInfo = document.getElementById('mainWeekInfo');
      if(mainInfo && perWeek.length>0){
        const first = perWeek[0];
        const mondayISO = first.monday;
        const sundayISO = first.sunday;
        const wno = isoWeekNumber(new Date(mondayISO + 'T00:00:00'));
        mainInfo.textContent = `Semaine n°${wno} — du ${formatDateFR(mondayISO)} au ${formatDateFR(sundayISO)}`;
      }
    }catch(_e){/* ignore */}

    const nameToId = new Map((employeesCache||[]).map(e=>[e.name, e.id]));
    const caps = new Map((employeesCache||[]).map(e=>[
      e.id,
      {
        base: typeof e.base_week_hours === "number" ? e.base_week_hours : (typeof e.max_week_hours === "number" ? e.max_week_hours : null),
        max: typeof e.max_week_hours_with_sup === "number" ? e.max_week_hours_with_sup : (typeof e.max_week_hours === "number" ? e.max_week_hours : null)
      }
    ]));

    perWeek.forEach((weekData, idx) => {
      const ctx = weekContexts[idx];
      if(!ctx) return;
      ctx.root.classList.remove('hidden');
      if(ctx.title) ctx.title.textContent = `Semaine ${idx+1}`;
      if(ctx.subtitle) ctx.subtitle.textContent = `${formatDateFR(weekData.monday)} → ${formatDateFR(weekData.sunday)}`;

      const map = groupByEmployeeAndDay(weekData.base, weekData.adjusted);
      const mondayDate = new Date(`${weekData.monday}T00:00:00`);
      const weekDates = Array.from({length:7}, (_,dayIdx)=> toISO(addDays(mondayDate, dayIdx)));

      const absenceById = new Map();
      weekData.absences.forEach(abs => {
        const start = new Date(`${abs.start_date}T00:00:00`);
        const end = new Date(`${abs.end_date}T00:00:00`);
        for(let cursor = new Date(start); cursor <= end; cursor.setDate(cursor.getDate()+1)){
          const iso = toISO(cursor);
          const empMap = absenceById.get(abs.employee_id) || new Map();
          empMap.set(iso, (abs.reason || "").trim());
          absenceById.set(abs.employee_id, empMap);
        }
      });
      const absenceByName = new Map();
      absenceById.forEach((mapVal, empId) => {
        const employee = employeesCache.find(e=>e.id === empId);
        if(employee){
          absenceByName.set(employee.name, mapVal);
        }
      });

      // compute coverage and hours separately for base and adjusted views
      const covBase = coverageByDay(map, false);
      const covAdj = coverageByDay(map, true);
      const hoursBase = weeklyHours(map, false, absenceByName, weekDates);
      const hoursAdj = weeklyHours(map, true, absenceByName, weekDates);
      const absentIds = new Set(weekData.absences.map(a=>a.employee_id));

      // render base into primary tbody
      renderGrid(map, covBase, hoursBase, {useAdjusted:false, nameToId, absentIds, caps, weekDates, absenceDays: absenceById, context: ctx});

      // render adjusted into adjusted tbody (if element exists)
      const adjustedBlockEl = document.getElementById(`adjustedBlock${idx}`);
      if(ctx && ctx.tbodyAdjusted){
        if(weekData.adjusted && weekData.adjusted.length > 0){
          adjustedBlockEl && adjustedBlockEl.classList.remove('hidden');
          const adjCtx = Object.assign({}, ctx, { tbody: ctx.tbodyAdjusted, coverCells: ctx.coverCellsAdjusted, ocov: ctx.ocovAdj, fcov: ctx.fcovAdj });
          renderGrid(map, covAdj, hoursAdj, {useAdjusted:true, nameToId, absentIds, caps, weekDates, absenceDays: absenceById, context: adjCtx});
        }else{
          adjustedBlockEl && adjustedBlockEl.classList.add('hidden');
          if(ctx.tbodyAdjusted) ctx.tbodyAdjusted.innerHTML = "";
          if(ctx.coverCellsAdjusted) ctx.coverCellsAdjusted.forEach(c=>c.innerHTML='');
          if(ctx.ocovAdj) ctx.ocovAdj.textContent = "";
          if(ctx.fcovAdj) ctx.fcovAdj.textContent = "";
        }
      }
    });

    for(let idx = perWeek.length; idx < weekContexts.length; idx++){
      const ctx = weekContexts[idx];
      if(!ctx) continue;
      ctx.root.classList.add('hidden');
      if(ctx.tbody) ctx.tbody.innerHTML = "";
      if(ctx.coverCells){
        ctx.coverCells.forEach(cell => cell.innerHTML = "");
      }
      if(ctx.subtitle) ctx.subtitle.textContent = "";
    }
  }catch(e){
    alert("Erreur chargement: "+e.message);
    console.error(e);
  }
}

// --- Tabs for view selection (base / adjusted / both)
function setupViewTabs(){
  const tabs = Array.from(document.querySelectorAll('.tab-btn'));
  if(!tabs.length) return;
  const setView = (view)=>{
    const baseTables = document.querySelectorAll('.subtable:not(.adjusted-block)');
    const adjTables = document.querySelectorAll('.adjusted-block');
    if(view === 'both'){
      baseTables.forEach(el=>el.classList.remove('hidden'));
      adjTables.forEach(el=>el.classList.remove('hidden'));
    }else if(view === 'base'){
      baseTables.forEach(el=>el.classList.remove('hidden'));
      adjTables.forEach(el=>el.classList.add('hidden'));
    }else if(view === 'adjusted'){
      baseTables.forEach(el=>el.classList.add('hidden'));
      adjTables.forEach(el=>el.classList.remove('hidden'));
    }
    tabs.forEach(t=>t.classList.toggle('active', t.getAttribute('data-view')===view));
  };
  tabs.forEach(t=> t.addEventListener('click', ()=> setView(t.getAttribute('data-view'))));
  // default
  setView('both');
}

(function(){
  // init tabs after DOM ready
  document.addEventListener('DOMContentLoaded', ()=>{
    setupViewTabs();
  });
})();

// Temporary: enforce light theme to avoid browser/extension dark-mode overrides
function enforceLightTheme(){
  try{
    if(document.getElementById('force-light-mode')) return;
    const css = `
      :root{ --bg:#fff !important; --fg:#111 !important; --muted:#666 !important; --line:#e6e6e6 !important; }
      html,body{ background:#fff !important; color:#111 !important; }
      header, .week-block, table, .panel, .changes, .meta-block{ background:#fff !important; }
      .tag{ background-clip:padding-box !important }
    `;
    const s = document.createElement('style'); s.id = 'force-light-mode'; s.appendChild(document.createTextNode(css));
    document.head && document.head.appendChild(s);
  }catch(e){ console.warn('enforceLightTheme failed', e); }
}

// More aggressive: apply inline styles repeatedly to override extensions that inject dark mode
function enforceLightThemeInline(){
  try{
    const applyOnce = ()=>{
      try{
        document.documentElement.style.backgroundColor = '#fff';
        document.documentElement.style.color = '#111';
        document.body && (document.body.style.backgroundColor = '#fff');
        document.body && (document.body.style.color = '#111');
        const els = document.querySelectorAll('header, .week-block, table, th, td, .panel, .changes, .meta-block');
        els.forEach(el=>{
          try{ el.style.backgroundColor = '#fff'; el.style.color = '#111'; }catch(_){}
        });
        // ensure tags look correct
        document.querySelectorAll('.tag').forEach(t=>{
          try{
            t.style.backgroundClip = 'padding-box';
            t.style.display = 'flex'; t.style.justifyContent = 'space-between'; t.style.gap = '8px';
            t.style.padding = '4px 8px';
          }catch(_){ }
        });
      }catch(_){ }
    };
    // apply multiple times over a short period
    for(let i=0;i<8;i++) setTimeout(applyOnce, i*300);
  }catch(e){ console.warn('enforceLightThemeInline failed', e); }
}

document.addEventListener('DOMContentLoaded', ()=>{
  // apply after short delay so it's visible even if an extension toggles theme later
  setTimeout(enforceLightTheme, 50);
});

// Absences
document.getElementById("absBtn").addEventListener("click", async ()=>{
  const ids = Array.from(document.getElementById("absEmp").selectedOptions).map(o=>o.value);
  const start = document.getElementById("absStart").value;
  const end = document.getElementById("absEnd").value;
  const reason = document.getElementById("absReason").value;
  let monday = document.getElementById("monday").value;
  monday = normalizeToMonday(monday);
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
    const weeks = Number(document.getElementById("weekCount").value || 1);
    const baseDate = new Date(`${monday}T00:00:00`);
    const sundayOpen = document.getElementById("sun").checked;
    for(let i=0;i<weeks;i++){
      const weekMonday = toISO(addDays(baseDate, i*7));
      await generateWeek(weekMonday, sundayOpen);
    }
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
    const weeks = Number(document.getElementById("weekCount").value || 1);
    const sundayOpen = document.getElementById("sun").checked;
    const normalized = normalizeToMonday(monday);
    if(normalized !== monday){ document.getElementById("monday").value = normalized; }
    const baseDate = new Date(`${normalized}T00:00:00`);
    for(let i=0;i<weeks;i++){
      const weekMonday = toISO(addDays(baseDate, i*7));
      await generateWeek(weekMonday, sundayOpen);
    }
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
      const weeks = Number(document.getElementById("weekCount").value || 1);
      const res = await saveSnapshotForWeek(monday, document.getElementById("sun").checked, input ? input : null, status, weeks);
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

  // normalize manual changes: if user picks a non-Monday date, coerce to that week's Monday
  inp.addEventListener('change', (ev)=>{
    const val = ev.target.value;
    const norm = normalizeToMonday(val);
    if(norm !== val){ ev.target.value = norm; }
    // refresh view for the corrected monday
    refresh();
  });

  const weekSelect = document.getElementById("weekCount");
  if(weekSelect){
    weekSelect.addEventListener('change', refresh);
  }

  await loadEmployees();
  await refresh();
})();
