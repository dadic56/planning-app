from __future__ import annotations
from datetime import date, timedelta, time as TimeType
from typing import List, Dict, Any, Tuple
import logging

from .models import db, Employee, BaseShift, AdjustedShift, Absence, OpeningHours, RuleViolation, SpecialOpening, SpecialOpeningShift

logger = logging.getLogger(__name__)

# ---------- Helpers ----------
def to_iso(d: date) -> str:
    return d.isoformat()

def hhmm(v) -> str:
    if v is None:
        return None
    if isinstance(v, str):
        parts = v.split(":")
        if len(parts) >= 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return v
    if isinstance(v, TimeType):
        return v.strftime("%H:%M")
    return str(v)

def mins(hhmm_str: str) -> int:
    if hhmm_str is None:
        raise ValueError("heure invalide: None")
    s = hhmm(hhmm_str)
    if s is None:
        raise ValueError(f"heure invalide: {hhmm_str}")
    parts = s.split(":")
    if len(parts) < 2:
        raise ValueError(f"format horaire invalide: {s}")
    h, m = int(parts[0]), int(parts[1])
    return h * 60 + m

def span_minutes(start, end) -> int:
    return max(0, mins(end) - mins(start))


def human_hours(minutes: int) -> str:
    hours = minutes / 60
    return f"{hours:.2f}".rstrip("0").rstrip(".") + "h"


MIN_BREAK_MINUTES = 30
MIN_LUNCH_MINUTES = 30
MAX_LUNCH_MINUTES = 60
LUNCH_WINDOW_START = mins("12:00")
LUNCH_WINDOW_END = mins("15:00")


def recommended_week_minutes(emp: Employee) -> int:
    base_hours = None
    if getattr(emp, "max_week_hours", None) is not None:
        base_hours = float(emp.max_week_hours)
    ctype = (emp.contract_type or "").lower().strip()
    import re
    match = re.search(r"\d+(?:[\.,]\d+)?", ctype)
    if base_hours is None and match:
        try:
            base_hours = float(match.group(0).replace(',', '.'))
        except ValueError:
            base_hours = None
    if base_hours is None:
        base_hours = 35.0

    if getattr(emp, "therapeutic_part_time", False):
        pct = getattr(emp, "therapeutic_percent", None)
        if pct is not None:
            pct = max(0.0, min(100.0, float(pct)))
            base_hours = base_hours * (pct / 100.0)

    return int(round(base_hours * 60))


def overtime_allowance_minutes(emp: Employee) -> int:
    if not getattr(emp, "allow_overtime", True):
        return 0
    ctype = (emp.contract_type or "").lower().strip()
    import re
    match = re.search(r"\d+", ctype)
    hours = None
    if getattr(emp, "max_week_hours", None) is not None:
        hours = float(emp.max_week_hours)
    if hours is None and match:
        hours = float(match.group(0))
    if hours == 24:
        return 8 * 60
    if hours == 35:
        return 6 * 60
    return 0


def max_week_minutes(emp: Employee) -> int:
    base = recommended_week_minutes(emp)
    return base + overtime_allowance_minutes(emp)


def respects_special_rules(emp: Employee, weekday: int, start: str, end: str) -> bool:
    rules = (emp.special_rules or "").lower()
    name = (emp.name or "").lower()
    # Rule: jamais le vendredi
    if ("jamais" in rules and "vendredi" in rules) and weekday == 4:
        return False
    if name.startswith("st") and weekday == 4:
        return False
    # Rule: lundi après-midi libre
    if ("lundi" in rules and "après-midi" in rules) and weekday == 0:
        if mins(end) > mins("12:00"):
            return False
    if name.startswith("na") and weekday == 0 and mins(end) > mins("12:00"):
        return False
    return True


def fits_daily_rules(existing: List[Tuple[str, str]], new_span: Tuple[str, str]) -> bool:
    spans = sorted(existing + [new_span], key=lambda s: mins(s[0]))
    # Overlap check
    for i in range(1, len(spans)):
        if mins(spans[i][0]) < mins(spans[i - 1][1]):
            return False

    # Daily totals and consecutive work
    total_minutes = sum(span_minutes(s[0], s[1]) for s in spans)
    if total_minutes > 10 * 60:
        return False

    stretch_start = mins(spans[0][0])
    stretch_end = mins(spans[0][1])
    for i in range(1, len(spans)):
        start = mins(spans[i][0])
        end = mins(spans[i][1])
        gap = start - stretch_end
        if gap < MIN_BREAK_MINUTES:
            stretch_end = max(stretch_end, end)
        else:
            if stretch_end - stretch_start > 6 * 60:
                return False
            stretch_start = start
            stretch_end = end
    if stretch_end - stretch_start > 6 * 60:
        return False

    if total_minutes > 6 * 60:
        has_lunch = False
        for i in range(len(spans) - 1):
            gap_start = mins(spans[i][1])
            gap_end = mins(spans[i + 1][0])
            gap = gap_end - gap_start
            if gap <= 0:
                continue
            if (
                gap >= MIN_LUNCH_MINUTES
                and gap <= MAX_LUNCH_MINUTES
                and gap_start >= LUNCH_WINDOW_START
                and gap_end <= LUNCH_WINDOW_END
            ):
                has_lunch = True
                break
        if not has_lunch:
            return False

    return True

def week_days_from_monday(monday: date) -> List[date]:
    return [monday + timedelta(days=i) for i in range(7)]

def overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return not (mins(a_end) <= mins(b_start) or mins(b_end) <= mins(a_start))

def day_overlaps(s1: Tuple[str,str], s2: Tuple[str,str]) -> bool:
    return overlaps(s1[0], s1[1], s2[0], s2[1])

def date_in(a_start: date, a_end: date, d: date) -> bool:
    return a_start <= d <= a_end

def clear_adjusted_between(d1: date, d2: date) -> None:
    db.session.query(AdjustedShift)\
        .filter(AdjustedShift.date >= d1, AdjustedShift.date <= d2)\
        .delete(synchronize_session=False)
    db.session.commit()

# -------- 1) Planning de base instancié --------
def compute_base_week_for(monday: date) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    days = week_days_from_monday(monday)
    emp_by_id = {e.id: e for e in Employee.query.all()}

    base = BaseShift.query.order_by(
        BaseShift.weekday, BaseShift.employee_id, BaseShift.start_time
    ).all()

    for b in base:
        cur_date = days[b.weekday]
        emp = emp_by_id.get(b.employee_id)
        out.append({
            "date": to_iso(cur_date),
            "employee": emp.name if emp else f"#{b.employee_id}",
            "employee_id": b.employee_id,
            "start": hhmm(b.start_time),
            "end": hhmm(b.end_time),
            "lunch_start": hhmm(b.lunch_start),
            "lunch_end": hhmm(b.lunch_end),
            "source": "base",
        })
    return out

# -------- 2) Génération avec remplacements --------
def generate_adjusted_week(monday: date, sunday_open: bool = False) -> None:
    days = week_days_from_monday(monday)
    d1, d7 = days[0], days[-1]
    clear_adjusted_between(d1, d7)

    db.session.query(RuleViolation) \
        .filter(RuleViolation.date >= d1, RuleViolation.date <= d7) \
        .delete(synchronize_session=False)

    abs_by_emp: Dict[int, List[Tuple[date, date]]] = {}
    for a in Absence.query.filter(Absence.start_date <= d7, Absence.end_date >= d1).all():
        abs_by_emp.setdefault(a.employee_id, []).append((a.start_date, a.end_date))

    employees = {e.id: e for e in Employee.query.all()}
    week_minutes: Dict[int, int] = {e_id: 0 for e_id in employees}
    planned_by_day_emp: Dict[date, Dict[int, List[Tuple[str, str]]]] = {
        day: {e_id: [] for e_id in employees} for day in days
    }

    base_shifts = BaseShift.query.order_by(
        BaseShift.weekday, BaseShift.employee_id, BaseShift.start_time
    ).all()

    specials = SpecialOpening.query.filter(SpecialOpening.date >= d1, SpecialOpening.date <= d7).all()
    special_map = {sp.date: sp for sp in specials}

    sunday_date = days[6]
    special_sunday = special_map.get(sunday_date)
    if special_sunday and special_sunday.sunday_mode:
        sunday_open = True

    if sunday_open:
        if not special_sunday or special_sunday.is_closed:
            raise ValueError("Configurer une ouverture spéciale pour le dimanche avant de l'activer.")
        sunday_emps = {s.employee_id for s in special_sunday.shifts}
        sunday_available = [e for e in employees.values() if e.sunday_available]
        if len(sunday_available) < 3:
            raise ValueError("Dimanche ouvert impossible : moins de 3 vendeuses ont accepté de travailler le dimanche.")
        if len(sunday_emps) < 3:
            raise ValueError("Dimanche ouvert : sélectionner au moins 3 vendeuses dans l'ouverture spéciale.")
        for emp_id in sunday_emps:
            emp = employees.get(emp_id)
            if not emp or not emp.sunday_available:
                raise ValueError("Toutes les vendeuses affectées au dimanche doivent l'accepter dans leur fiche.")

    # Regrouper par jour pour traiter d'abord les créneaux "normaux" puis les remplacements.
    base_by_weekday: Dict[int, List[BaseShift]] = {d: [] for d in range(7)}
    for b in base_shifts:
        base_by_weekday[b.weekday].append(b)

    # Normaliser l'ordre de chaque journée (déjà trié par la requête mais restons explicites).
    for lst in base_by_weekday.values():
        lst.sort(key=lambda item: (item.employee_id, item.start_time))

    base_minutes_remaining: Dict[int, int] = {e_id: 0 for e_id in employees}
    for b in base_shifts:
        if b.weekday == 6 and not sunday_open:
            continue
        b_start, b_end = hhmm(b.start_time), hhmm(b.end_time)
        base_minutes_remaining[b.employee_id] = base_minutes_remaining.get(b.employee_id, 0) + span_minutes(b_start, b_end)

    opening_hours = {oh.weekday: oh for oh in OpeningHours.query.all()}
    violations: List[RuleViolation] = []

    def is_absent(emp_id: int, day_date: date) -> bool:
        return any(date_in(as_, ae_, day_date) for (as_, ae_) in abs_by_emp.get(emp_id, []))

    def assign_shift(emp_id: int, shift_date: date, shift_data: Dict[str, Any], source: str) -> None:
        adj = AdjustedShift(
            date=shift_date,
            employee_id=emp_id,
            start_time=shift_data["start"],
            end_time=shift_data["end"],
            lunch_start=shift_data.get("lunch_start"),
            lunch_end=shift_data.get("lunch_end"),
            source=source,
        )
        db.session.add(adj)
        week_minutes[emp_id] += shift_data["duration"]
        planned_by_day_emp[shift_date][emp_id].append((shift_data["start"], shift_data["end"]))

    for wd in range(7):
        if wd == 6 and not sunday_open and days[wd] not in special_map:
            continue
        cur_date = days[wd]
        if cur_date in special_map:
            continue
        day_pending: List[Tuple[BaseShift, Dict[str, Any]]] = []

        for b in base_by_weekday.get(wd, []):
            b_start, b_end = hhmm(b.start_time), hhmm(b.end_time)
            b_l1, b_l2 = hhmm(b.lunch_start), hhmm(b.lunch_end)
            dur = span_minutes(b_start, b_end)
            lunch_minutes = span_minutes(b_l1, b_l2) if b_l1 and b_l2 else 0
            shift_info = {
                "start": b_start,
                "end": b_end,
                "lunch_start": b_l1,
                "lunch_end": b_l2,
                "duration": dur,
                "lunch_minutes": lunch_minutes,
            }

            base_minutes_remaining[b.employee_id] -= dur

            if not is_absent(b.employee_id, cur_date):
                assign_shift(b.employee_id, cur_date, shift_info, source="base")
            else:
                day_pending.append((b, shift_info))

        for b, shift_info in day_pending:
            b_start, b_end = shift_info["start"], shift_info["end"]
            dur = shift_info["duration"]

            candidates: List[int] = []
            failure_reasons: Dict[str, List[Any]] = {}

            def add_failure(reason: str, payload: Any) -> None:
                failure_reasons.setdefault(reason, []).append(payload)

            for e_id, emp in employees.items():
                if e_id == b.employee_id:
                    continue
                if is_absent(e_id, cur_date):
                    add_failure("absent", emp.name)
                    continue
                if not respects_special_rules(emp, wd, b_start, b_end):
                    add_failure("rules", emp.name)
                    continue
                if not fits_daily_rules(planned_by_day_emp[cur_date][e_id], (b_start, b_end)):
                    add_failure("overlap", emp.name)
                    continue
                total_today = sum(span_minutes(s[0], s[1]) for s in planned_by_day_emp[cur_date][e_id]) + dur
                projected = week_minutes[e_id] + dur + base_minutes_remaining.get(e_id, 0)
                limit = max_week_minutes(emp)
                if projected > limit:
                    add_failure("hours", (emp.name, projected - limit, limit))
                    continue
                candidates.append(e_id)

            if candidates:
                def score(e_id: int) -> Tuple[int, int, int, int]:
                    emp = employees[e_id]
                    max_minutes = max_week_minutes(emp)
                    projected_total = week_minutes[e_id] + dur + base_minutes_remaining.get(e_id, 0)
                    reserve = max_minutes - projected_total
                    ctype = (emp.contract_type or "").strip()
                    contract_weight = 0 if ctype.startswith("35") else 1
                    return (
                        contract_weight,
                        week_minutes[e_id],
                        -reserve,
                        e_id,
                    )

                chosen = sorted(candidates, key=score)[0]
                assign_shift(chosen, cur_date, shift_info, source="reassigned")
            else:
                emp_name = employees.get(b.employee_id).name if b.employee_id in employees else f"#{b.employee_id}"
                reasons_text: List[str] = []
                if failure_reasons.get("hours"):
                    parts = []
                    for name, over_minutes, limit in failure_reasons["hours"]:
                        parts.append(f"{name} dépasserait {human_hours(limit)} (+{human_hours(over_minutes)} à ajouter)")
                    reasons_text.append("Limite hebdo atteinte : " + "; ".join(parts))
                if failure_reasons.get("overlap"):
                    names = ", ".join(sorted(set(failure_reasons["overlap"])))
                    reasons_text.append(f"Incompatibilité horaire/pause : {names}")
                if failure_reasons.get("rules"):
                    names = ", ".join(sorted(set(failure_reasons["rules"])))
                    reasons_text.append(f"Règles particulières : {names}")
                if failure_reasons.get("absent"):
                    names = ", ".join(sorted(set(failure_reasons["absent"])))
                    reasons_text.append(f"Absentes / indisponibles : {names}")
                if not reasons_text:
                    reasons_text.append("Aucun profil compatible disponible")
                details = (
                    f"Créneau {b_start}-{b_end} non couvert (remplacement {emp_name}). "
                    f"Aucune remplaçante : {'; '.join(reasons_text)}."
                )
                violations.append(RuleViolation(date=cur_date, employee_id=b.employee_id, code="SHIFT_UNASSIGNED", details=details, severity="warn"))

    # Traiter les ouvertures spéciales (création de créneaux dédiés)
    for sp_date, opening in special_map.items():
        if opening.is_closed:
            continue
        current_day_plan = planned_by_day_emp[sp_date]
        for shift in opening.shifts:
            if is_absent(shift.employee_id, sp_date):
                violations.append(RuleViolation(
                    date=sp_date,
                    employee_id=shift.employee_id,
                    code="SHIFT_UNASSIGNED",
                    details="Absence sur créneau spécial.",
                    severity="warn",
                ))
                continue
            info = {
                "start": hhmm(shift.start_time),
                "end": hhmm(shift.end_time),
                "lunch_start": hhmm(shift.lunch_start),
                "lunch_end": hhmm(shift.lunch_end),
                "duration": span_minutes(shift.start_time, shift.end_time),
                "lunch_minutes": span_minutes(shift.lunch_start, shift.lunch_end) if shift.lunch_start and shift.lunch_end else 0,
            }
            assign_shift(shift.employee_id, sp_date, info, source="special")

    REQUIRED_COVERAGE = 3
    for idx, day in enumerate(days):
        if idx == 6 and not sunday_open and day not in special_map:
            continue
        if day in special_map:
            special = special_map[day]
            if special.is_closed:
                continue
            open_time = hhmm(special.open_time) if special.open_time else "09:30"
            close_time = hhmm(special.close_time) if special.close_time else "19:15"
        else:
            oh = opening_hours.get(idx)
            open_time = hhmm(oh.open_time) if oh and oh.open_time else "09:30"
            close_time = hhmm(oh.close_time) if oh and oh.close_time else "19:15"
        open_minute = mins(open_time)
        close_minute = mins(close_time) - 1
        day_plan = planned_by_day_emp[day]
        cov_open = sum(1 for spans in day_plan.values() if any(mins(s[0]) <= open_minute < mins(s[1]) for s in spans))
        cov_close = sum(1 for spans in day_plan.values() if any(mins(s[0]) <= close_minute < mins(s[1]) for s in spans))
        if cov_open < REQUIRED_COVERAGE:
            violations.append(RuleViolation(
                date=day,
                code="COVER_OPEN",
                details=f"{cov_open}/{REQUIRED_COVERAGE} personnes à l'ouverture {open_time}",
                severity="warn",
            ))
        if cov_close < REQUIRED_COVERAGE:
            violations.append(RuleViolation(
                date=day,
                code="COVER_CLOSE",
                details=f"{cov_close}/{REQUIRED_COVERAGE} personnes à la fermeture {close_time}",
                severity="warn",
            ))

    # Logging summary
    try:
        total_shifts = AdjustedShift.query.filter(AdjustedShift.date >= d1, AdjustedShift.date <= d7).count()
    except Exception:
        total_shifts = None
    logger.info(f"generate_adjusted_week: monday={d1.isoformat()}, shifts={total_shifts}, violations={len(violations)}")

    if violations:
        db.session.add_all(violations)

    db.session.commit()

# -------- 3) Lecture ajusté --------
def list_adjusted_between(d1: date, d2: date) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    emp_by_id = {e.id: e for e in Employee.query.all()}
    q = AdjustedShift.query\
        .filter(AdjustedShift.date >= d1, AdjustedShift.date <= d2)\
        .order_by(AdjustedShift.date, AdjustedShift.employee_id, AdjustedShift.start_time)
    for s in q.all():
        emp = emp_by_id.get(s.employee_id)
        out.append({
            "date": s.date.isoformat(),
            "employee_id": s.employee_id,
            "employee": emp.name if emp else f"#{s.employee_id}",
            "start": hhmm(s.start_time),
            "end": hhmm(s.end_time),
            "lunch_start": hhmm(s.lunch_start),
            "lunch_end": hhmm(s.lunch_end),
            "source": (s.source or "adjust"),
        })
    return out
