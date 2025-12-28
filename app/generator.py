from datetime import datetime, timedelta
from app import db
from .models import BaseShift, AdjustedShift, RuleViolation, Absence, Employee


def _hm_to_minutes(hm: str) -> int:
    parts = hm.split(':')
    if len(parts) != 2:
        raise ValueError('invalid time')
    h, m = int(parts[0]), int(parts[1])
    return h * 60 + m


def _time_in_shift(hm: str, start: str, end: str) -> bool:
    return _hm_to_minutes(start) <= _hm_to_minutes(hm) < _hm_to_minutes(end)


def generate_week(monday_iso: str, sunday_open: bool = False):
    """Generate adjusted shifts for the week starting on `monday_iso` (YYYY-MM-DD).
    Rules applied:
    - Skip shifts on days where employee has Absence
    - Max shift duration 10h -> violation
    - If shift >6h then lunch (1h-2h) must exist and start between 12:00-15:00 -> violation
    - After creating shifts, compute weekly worked hours (excluding lunch) and emit violations if exceeding thresholds
    """
    monday = datetime.fromisoformat(monday_iso).date()
    sunday = monday + timedelta(days=6)

    # remove existing adjusted shifts and violations for this period
    AdjustedShift.query.filter(AdjustedShift.date >= monday, AdjustedShift.date <= sunday).delete(synchronize_session=False)
    RuleViolation.query.filter(RuleViolation.date >= monday, RuleViolation.date <= sunday).delete(synchronize_session=False)
    db.session.commit()

    created_shifts = []
    created_violations = []

    OPEN_TIME = '09:30'
    CLOSE_TIME = '19:15'

    for day_offset in range(7):
        d = monday + timedelta(days=day_offset)
        weekday = d.weekday()  # 0=Mon..6=Sun

        base_shifts = BaseShift.query.filter_by(weekday=weekday).all()

        for bs in base_shifts:
            # check absences
            absence = Absence.query.filter(
                Absence.employee_id == bs.employee_id,
                Absence.start_date <= d,
                Absence.end_date >= d,
            ).first()
            if absence:
                continue

            # parse times
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

            # pause requirement
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

        # coverage checks at open and close
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

    # compute weekly totals per employee (minutes worked excluding lunch)
    totals = {}
    for s in AdjustedShift.query.filter(AdjustedShift.date >= monday, AdjustedShift.date <= sunday).all():
        try:
            s_min = _hm_to_minutes(s.start_time)
            e_min = _hm_to_minutes(s.end_time)
            worked = e_min - s_min
            if s.lunch_start and s.lunch_end:
                try:
                    ls = _hm_to_minutes(s.lunch_start)
                    le = _hm_to_minutes(s.lunch_end)
                    worked -= max(0, le - ls)
                except Exception:
                    pass
        except Exception:
            worked = 0
        totals.setdefault(s.employee_id, 0)
        totals[s.employee_id] += worked

    # check contract ceilings
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

    return {'adjusted': created_shifts, 'violations': created_violations, 'monday': monday_iso, 'sunday_open': bool(sunday_open)}
 
