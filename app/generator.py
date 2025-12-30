from datetime import datetime, timedelta
from app import db
from .models import BaseShift, AdjustedShift, RuleViolation, Absence, Employee


def _hm_to_minutes(hm: str) -> int:
    parts = hm.split(':')
    if len(parts) != 2:
        raise ValueError('invalid time')
    h, m = int(parts[0]), int(parts[1])
    return h * 60 + m


def _minutes_to_hm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _time_in_shift(hm: str, start: str, end: str) -> bool:
    return _hm_to_minutes(start) <= _hm_to_minutes(hm) < _hm_to_minutes(end)


def _shifts_overlap(s1_start, s1_end, s2_start, s2_end):
    """Check if two time ranges overlap"""
    s1_s = _hm_to_minutes(s1_start)
    s1_e = _hm_to_minutes(s1_end)
    s2_s = _hm_to_minutes(s2_start)
    s2_e = _hm_to_minutes(s2_end)
    return max(s1_s, s2_s) < min(s1_e, s2_e)


def _compute_shift_duration(start, end, lunch_start=None, lunch_end=None):
    """Compute effective worked minutes (excluding lunch)"""
    worked = _hm_to_minutes(end) - _hm_to_minutes(start)
    if lunch_start and lunch_end:
        lunch_dur = _hm_to_minutes(lunch_end) - _hm_to_minutes(lunch_start)
        worked -= max(0, lunch_dur)
    return worked


def generate_week(monday_iso: str, sunday_open: bool = False):
    """Generate adjusted shifts for the week starting on `monday_iso` (YYYY-MM-DD).
    
    Main features:
    - Skip shifts on days where employee has Absence
    - Automatically redistribute absent employee shifts to available replacements
    - Priority: 24h contracts first, then 35h contracts
    - Respect all constraints: hours, overlap, lunch breaks, special rules
    - Create detailed change metadata for UI display
    """
    monday = datetime.fromisoformat(monday_iso).date()
    sunday = monday + timedelta(days=6)

    # remove existing adjusted shifts and violations for this period
    AdjustedShift.query.filter(AdjustedShift.date >= monday, AdjustedShift.date <= sunday).delete(synchronize_session=False)
    RuleViolation.query.filter(RuleViolation.date >= monday, RuleViolation.date <= sunday).delete(synchronize_session=False)
    db.session.commit()

    created_shifts = []
    created_violations = []
    reassignments = []  # Track all reassignments for detailed summary
    unassigned_shifts = []  # Track shifts that couldn't be covered

    OPEN_TIME = '09:30'
    CLOSE_TIME = '19:15'

    # Load all employees once
    all_employees = Employee.query.all()
    employees_by_id = {e.id: e for e in all_employees}
    
    # Separate by contract type for prioritization
    employees_24h = [e for e in all_employees if e.contract_type == '24h']
    employees_35h = [e for e in all_employees if e.contract_type == '35h']
    employees_other = [e for e in all_employees if e.contract_type not in ('24h', '35h')]

    # Track absences for the week
    absences_cache = {}
    for emp in all_employees:
        absences_cache[emp.id] = Absence.query.filter(
            Absence.employee_id == emp.id,
            Absence.start_date <= sunday,
            Absence.end_date >= monday
        ).all()

    def is_absent(emp_id, date):
        """Check if employee is absent on specific date"""
        for absence in absences_cache.get(emp_id, []):
            if absence.start_date <= date <= absence.end_date:
                return True, absence.reason
        return False, None

    def get_weekly_minutes(emp_id, up_to_date):
        """Get total minutes worked so far this week for an employee"""
        shifts = AdjustedShift.query.filter(
            AdjustedShift.employee_id == emp_id,
            AdjustedShift.date >= monday,
            AdjustedShift.date <= up_to_date
        ).all()
        total = 0
        for s in shifts:
            total += _compute_shift_duration(s.start_time, s.end_time, s.lunch_start, s.lunch_end)
        return total

    def can_take_shift(emp, date, start, end, lunch_start, lunch_end, new_shift_minutes):
        """Check if employee can take this shift respecting all constraints"""
        reasons = []
        
        # Check absence
        absent, _ = is_absent(emp.id, date)
        if absent:
            reasons.append(f"absente ce jour")
            return False, reasons
        
        # Check weekday restrictions (special rules)
        weekday = date.weekday()
        if emp.special_rules:
            rules_lower = emp.special_rules.lower()
            # Nathalie: lundi après-midi libre
            if 'lundi' in rules_lower and 'après-midi' in rules_lower and weekday == 0:
                shift_start_min = _hm_to_minutes(start)
                if shift_start_min < 15 * 60 and shift_start_min > 12 * 60:  # between 12:00 and 15:00
                    reasons.append("règle: lundi après-midi libre")
                    return False, reasons
            # Stéphanie: jamais le vendredi
            if 'vendredi' in rules_lower and 'jamais' in rules_lower and weekday == 4:
                reasons.append("règle: jamais le vendredi")
                return False, reasons
        
        # Check Sunday availability
        if weekday == 6 and not emp.sunday_available:
            reasons.append("non disponible le dimanche")
            return False, reasons
        
        # Check overlap with existing shifts
        existing = AdjustedShift.query.filter(
            AdjustedShift.employee_id == emp.id,
            AdjustedShift.date == date
        ).all()
        for ex in existing:
            if _shifts_overlap(start, end, ex.start_time, ex.end_time):
                reasons.append(f"chevauchement avec shift {ex.start_time}-{ex.end_time}")
                return False, reasons
            # Check 1h gap between shifts
            ex_end_min = _hm_to_minutes(ex.end_time)
            new_start_min = _hm_to_minutes(start)
            ex_start_min = _hm_to_minutes(ex.start_time)
            new_end_min = _hm_to_minutes(end)
            
            if 0 < new_start_min - ex_end_min < 60:
                reasons.append(f"pause <1h après shift {ex.start_time}-{ex.end_time}")
                return False, reasons
            if 0 < ex_start_min - new_end_min < 60:
                reasons.append(f"pause <1h avant shift {ex.start_time}-{ex.end_time}")
                return False, reasons
        
        # Check weekly hours limit
        current_minutes = get_weekly_minutes(emp.id, date)
        projected_minutes = current_minutes + new_shift_minutes
        projected_hours = projected_minutes / 60.0
        
        # Determine hour limits
        if emp.therapeutic_part_time and emp.therapeutic_percent:
            hard_limit = emp.max_week_hours * (emp.therapeutic_percent / 100.0)
        elif emp.contract_type == '24h':
            hard_limit = 32 if emp.allow_overtime else 24
        elif emp.contract_type == '35h':
            hard_limit = 41 if emp.allow_overtime else 35
        else:
            hard_limit = emp.max_week_hours or 35
            if emp.allow_overtime:
                hard_limit += 6
        
        if projected_hours > hard_limit:
            reasons.append(f"dépasserait plafond {hard_limit}h (aurait {projected_hours:.1f}h)")
            return False, reasons
        
        return True, reasons

    def find_replacement(original_emp_id, date, start, end, lunch_start, lunch_end):
        """Find a replacement employee for this shift, prioritizing 24h contracts"""
        shift_minutes = _compute_shift_duration(start, end, lunch_start, lunch_end)
        original_emp = employees_by_id.get(original_emp_id)
        original_name = original_emp.name if original_emp else f"Employée #{original_emp_id}"
        
        # Try 24h contracts first
        for emp in employees_24h:
            if emp.id == original_emp_id:
                continue  # Skip the absent employee
            can_take, reasons = can_take_shift(emp, date, start, end, lunch_start, lunch_end, shift_minutes)
            if can_take:
                return emp, f"24h"
        
        # Then try 35h contracts
        for emp in employees_35h:
            if emp.id == original_emp_id:
                continue
            can_take, reasons = can_take_shift(emp, date, start, end, lunch_start, lunch_end, shift_minutes)
            if can_take:
                return emp, f"35h"
        
        # Finally try others
        for emp in employees_other:
            if emp.id == original_emp_id:
                continue
            can_take, reasons = can_take_shift(emp, date, start, end, lunch_start, lunch_end, shift_minutes)
            if can_take:
                return emp, f"{emp.contract_type}"
        
        # No one available - collect reasons from all employees
        all_reasons = {}
        for emp in all_employees:
            if emp.id == original_emp_id:
                continue
            can_take, reasons = can_take_shift(emp, date, start, end, lunch_start, lunch_end, shift_minutes)
            if not can_take and reasons:
                all_reasons[emp.name] = reasons
        
        return None, all_reasons

    # Process each day
    for day_offset in range(7):
        d = monday + timedelta(days=day_offset)
        weekday = d.weekday()  # 0=Mon..6=Sun

        base_shifts = BaseShift.query.filter_by(weekday=weekday).all()

        for bs in base_shifts:
            absent, absence_reason = is_absent(bs.employee_id, d)
            
            if absent:
                # Try to find a replacement
                replacement_emp, info = find_replacement(
                    bs.employee_id, d, bs.start_time, bs.end_time, 
                    bs.lunch_start, bs.lunch_end
                )
                
                if replacement_emp:
                    # Create reassigned shift
                    adj = AdjustedShift(
                        employee_id=replacement_emp.id,
                        date=d,
                        start_time=bs.start_time,
                        end_time=bs.end_time,
                        lunch_start=bs.lunch_start,
                        lunch_end=bs.lunch_end,
                        source='reassigned',
                        note=f"Remplace {employees_by_id[bs.employee_id].name} (absence: {absence_reason or 'non spécifiée'})",
                    )
                    db.session.add(adj)
                    db.session.flush()
                    created_shifts.append(adj.to_dict())
                    
                    # Track reassignment for summary
                    shift_dur = _compute_shift_duration(bs.start_time, bs.end_time, bs.lunch_start, bs.lunch_end)
                    reassignments.append({
                        'date': d.isoformat(),
                        'original_employee': employees_by_id[bs.employee_id].name,
                        'replacement_employee': replacement_emp.name,
                        'replacement_contract': info,
                        'shift': f"{bs.start_time}-{bs.end_time}",
                        'duration_hours': shift_dur / 60.0,
                        'reason': absence_reason or 'absence'
                    })
                else:
                    # No replacement found - record violation
                    original_emp = employees_by_id[bs.employee_id]
                    reasons_text = "; ".join([f"{name}: {', '.join(r)}" for name, r in list(info.items())[:3]])  # Limit to 3 employees
                    rv = RuleViolation(
                        date=d,
                        employee_id=bs.employee_id,
                        code='SHIFT_UNASSIGNED',
                        details=f"Créneau {bs.start_time}-{bs.end_time} non couvert (absence de {original_emp.name}). Raisons: {reasons_text}",
                        severity='error'
                    )
                    db.session.add(rv)
                    db.session.flush()
                    created_violations.append(rv.to_dict())
                    
                    unassigned_shifts.append({
                        'date': d.isoformat(),
                        'employee': original_emp.name,
                        'shift': f"{bs.start_time}-{bs.end_time}",
                        'reasons': info
                    })
                
                continue  # Don't create base shift for absent employee
            
            # Employee not absent - validate and create base shift
            try:
                s_min = _hm_to_minutes(bs.start_time)
                e_min = _hm_to_minutes(bs.end_time)
            except Exception:
                rv = RuleViolation(date=d, employee_id=bs.employee_id, code='INVALID_TIME', details='invalid time format', severity='error')
                db.session.add(rv)
                db.session.flush()
                created_violations.append(rv.to_dict())
                continue

            dur = e_min - s_min
            if dur > 10 * 60:
                rv = RuleViolation(date=d, employee_id=bs.employee_id, code='SHIFT_TOO_LONG', details=f'shift {dur/60:.1f}h > 10h', severity='error')
                db.session.add(rv)
                db.session.flush()
                created_violations.append(rv.to_dict())

            # Check lunch requirement
            lunch_ok = True
            if dur > 6 * 60:
                if not (bs.lunch_start and bs.lunch_end):
                    lunch_ok = False
                else:
                    try:
                        ls = _hm_to_minutes(bs.lunch_start)
                        le = _hm_to_minutes(bs.lunch_end)
                        if not (12 * 60 <= ls <= 15 * 60):
                            lunch_ok = False
                        if not (60 <= (le - ls) <= 120):
                            lunch_ok = False
                    except Exception:
                        lunch_ok = False
                if not lunch_ok:
                    rv = RuleViolation(date=d, employee_id=bs.employee_id, code='MISSING_PAUSE', details='shift >6h without valid lunch between 12:00-15:00 (1h-2h)', severity='warning')
                    db.session.add(rv)
                    db.session.flush()
                    created_violations.append(rv.to_dict())

            adj = AdjustedShift(
                employee_id=bs.employee_id,
                date=d,
                start_time=bs.start_time,
                end_time=bs.end_time,
                lunch_start=bs.lunch_start,
                lunch_end=bs.lunch_end,
                source='base',
                note=bs.note,
            )
            db.session.add(adj)
            db.session.flush()
            try:
                created_shifts.append(adj.to_dict())
            except Exception:
                created_shifts.append({'id': adj.id})

        # Coverage checks at open and close
        if weekday == 6 and not sunday_open:
            continue

        opens = 0
        closes = 0
        shifts = AdjustedShift.query.filter(AdjustedShift.date == d).all()
        for s in shifts:
            if _time_in_shift(OPEN_TIME, s.start_time, s.end_time):
                opens += 1
            if _time_in_shift(CLOSE_TIME, s.start_time, s.end_time):
                closes += 1

        if opens < 3:
            rv = RuleViolation(date=d, employee_id=None, code='COVER_OPEN', details=f'only {opens} covering open', severity='warning')
            db.session.add(rv)
            db.session.flush()
            created_violations.append(rv.to_dict())
        if closes < 3:
            rv2 = RuleViolation(date=d, employee_id=None, code='COVER_CLOSE', details=f'only {closes} covering close', severity='warning')
            db.session.add(rv2)
            db.session.flush()
            created_violations.append(rv2.to_dict())

    db.session.commit()

    # Compute weekly totals per employee
    totals = {}
    for s in AdjustedShift.query.filter(AdjustedShift.date >= monday, AdjustedShift.date <= sunday).all():
        try:
            worked = _compute_shift_duration(s.start_time, s.end_time, s.lunch_start, s.lunch_end)
        except Exception:
            worked = 0
        totals.setdefault(s.employee_id, 0)
        totals[s.employee_id] += worked

    # Check contract ceilings
    for emp_id, minutes in totals.items():
        emp = db.session.get(Employee, emp_id)
        if not emp:
            continue
        hours = minutes / 60.0
        if emp.therapeutic_part_time and emp.therapeutic_percent:
            allowed = emp.max_week_hours * (emp.therapeutic_percent / 100.0)
            hard_limit = allowed
        else:
            if emp.contract_type == '24h':
                allowed = 24
                hard_limit = 32 if emp.allow_overtime else 24
            else:
                allowed = emp.max_week_hours or 35
                hard_limit = 41 if (emp.contract_type == '35h' and emp.allow_overtime) else (emp.max_week_hours or 35)

        if hours > hard_limit:
            rv = RuleViolation(date=monday, employee_id=emp_id, code='HOURS_EXCEEDED', details=f'{hours:.2f}h > hard limit {hard_limit}h', severity='error')
            db.session.add(rv)
            db.session.flush()
            created_violations.append(rv.to_dict())
        elif hours > allowed:
            rv = RuleViolation(date=monday, employee_id=emp_id, code='HOURS_WARNING', details=f'{hours:.2f}h > allowed {allowed}h', severity='warning')
            db.session.add(rv)
            db.session.flush()
            created_violations.append(rv.to_dict())

    db.session.commit()

    return {
        'adjusted': created_shifts,
        'violations': created_violations,
        'reassignments': reassignments,
        'unassigned': unassigned_shifts,
        'monday': monday_iso,
        'sunday_open': bool(sunday_open)
    }
