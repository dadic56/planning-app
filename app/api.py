from flask import Blueprint, request, jsonify, current_app
import json
from app import db
from .models import Employee, BaseShift, Absence, PlanningSnapshot
from datetime import datetime, date
import re


def _hm_to_minutes(hm: str) -> int:
    parts = hm.split(':')
    if len(parts) != 2:
        raise ValueError('invalid time')
    h, m = int(parts[0]), int(parts[1])
    return h * 60 + m


def _overlaps(s1_start, s1_end, s2_start, s2_end) -> bool:
    return _hm_to_minutes(s1_start) < _hm_to_minutes(s2_end) and _hm_to_minutes(s2_start) < _hm_to_minutes(s1_end)

from .generator import generate_week as gen_week

bp = Blueprint('api', __name__)


@bp.route('/employees', methods=['GET'])
def list_employees():
    qs = Employee.query.order_by(Employee.name.asc()).all()
    return jsonify([e.to_dict() for e in qs])


@bp.route('/employees', methods=['POST'])
def create_employee():
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400
    if Employee.query.filter_by(name=name).first():
        return jsonify({'error': 'name must be unique'}), 400
    emp = Employee(
        name=name,
        contract_type=data.get('contract_type', '35h'),
        max_week_hours=int(data.get('max_week_hours', 35)),
        therapeutic_part_time=bool(data.get('therapeutic_part_time', False)),
        therapeutic_percent=data.get('therapeutic_percent'),
        allow_overtime=bool(data.get('allow_overtime', False)),
        sunday_available=bool(data.get('sunday_available', False)),
        special_rules=data.get('special_rules'),
    )
    db.session.add(emp)
    db.session.commit()
    return jsonify(emp.to_dict()), 201


@bp.route('/base-shifts', methods=['GET'])
def list_base_shifts():
    weekday = request.args.get('weekday')
    q = BaseShift.query
    if weekday is not None:
        try:
            wd = int(weekday)
            q = q.filter_by(weekday=wd)
        except ValueError:
            pass
    return jsonify([bs.to_dict() for bs in q.all()])


@bp.route('/base-shifts', methods=['POST'])
def create_base_shift():
    data = request.get_json() or {}
    required = ['employee_id', 'weekday', 'start_time', 'end_time']
    for r in required:
        if r not in data:
            return jsonify({'error': f'{r} required'}), 400
    # validate times format HH:MM
    try:
        start = data['start_time']
        end = data['end_time']
        s_min = _hm_to_minutes(start)
        e_min = _hm_to_minutes(end)
    except Exception:
        return jsonify({'error': 'invalid start_time or end_time (expected HH:MM)'}), 400
    if e_min <= s_min:
        return jsonify({'error': 'end_time must be after start_time'}), 400
    duration = e_min - s_min
    if duration > 10 * 60:
        return jsonify({'error': 'shift duration cannot exceed 10 hours'}), 400

    lunch_start = data.get('lunch_start')
    lunch_end = data.get('lunch_end')
    if lunch_start and lunch_end:
        try:
            ls = _hm_to_minutes(lunch_start)
            le = _hm_to_minutes(lunch_end)
        except Exception:
            return jsonify({'error': 'invalid lunch_start or lunch_end (expected HH:MM)'}), 400
        if not (s_min <= ls < le <= e_min):
            return jsonify({'error': 'lunch times must be within shift and valid'}), 400
        lunch_dur = le - ls
        if lunch_dur <= 0:
            return jsonify({'error': 'lunch duration must be positive'}), 400

    employee_id = int(data['employee_id'])
    weekday = int(data['weekday'])

    # check overlaps for same employee and weekday
    existing = BaseShift.query.filter_by(employee_id=employee_id, weekday=weekday).all()
    for ex in existing:
        if _overlaps(start, end, ex.start_time, ex.end_time):
            return jsonify({'error': 'shift overlaps with existing shift for this employee'}), 400

    bs = BaseShift(
        employee_id=employee_id,
        weekday=weekday,
        start_time=start,
        end_time=end,
        lunch_start=lunch_start,
        lunch_end=lunch_end,
        note=data.get('note'),
    )
    db.session.add(bs)
    db.session.commit()
    return jsonify(bs.to_dict()), 201


@bp.route('/absences', methods=['GET'])
def list_absences():
    from_s = request.args.get('from')
    to_s = request.args.get('to')
    q = Absence.query
    if from_s:
        q = q.filter(Absence.end_date >= datetime.fromisoformat(from_s).date())
    if to_s:
        q = q.filter(Absence.start_date <= datetime.fromisoformat(to_s).date())
    return jsonify([a.to_dict() for a in q.all()])


@bp.route('/absences', methods=['POST'])
def create_absence():
    data = request.get_json() or {}
    try:
        start = date.fromisoformat(data['start_date'])
        end = date.fromisoformat(data['end_date'])
    except Exception:
        return jsonify({'error': 'invalid dates'}), 400
    a = Absence(
        employee_id=data['employee_id'],
        start_date=start,
        end_date=end,
        reason=data.get('reason'),
    )
    db.session.add(a)
    db.session.commit()
    return jsonify(a.to_dict()), 201


@bp.route('/generate-week', methods=['POST'])
def generate_week():
    monday = request.args.get('monday')
    if not monday:
        return jsonify({'error': 'monday param required YYYY-MM-DD'}), 400
    sunday_open = request.args.get('sunday_open', '0')
    try:
        result = gen_week(monday, sunday_open in ('1', 'true', 'True', True))
    except Exception as exc:
        current_app.logger.exception('generate_week error')
        return jsonify({'error': str(exc)}), 500
    return jsonify(result)


@bp.route('/snapshots', methods=['GET'])
def list_snapshots():
    snaps = PlanningSnapshot.query.order_by(PlanningSnapshot.monday.desc()).all()
    return jsonify([s.to_dict() for s in snaps])


@bp.route('/snapshots', methods=['POST'])
def create_snapshot():
    data = request.get_json() or {}
    try:
        monday = date.fromisoformat(data['monday'])
    except Exception:
        return jsonify({'error': 'monday date required (YYYY-MM-DD)'}), 400
    weeks = int(data.get('weeks', 1))
    sunday = monday
    if weeks == 1:
        sunday = monday
    else:
        sunday = monday
    snap = PlanningSnapshot(
        monday=monday,
        sunday=sunday,
        label=data.get('label'),
        status=data.get('status', 'draft'),
        data=data.get('data', {}),
    )
    db.session.add(snap)
    db.session.commit()
    return jsonify(snap.to_dict()), 201


@bp.route('/snapshots/<int:id>', methods=['GET'])
def get_snapshot(id):
    snap = PlanningSnapshot.query.get_or_404(id)
    return jsonify(snap.to_dict())


@bp.route('/snapshots/<int:id>', methods=['PUT'])
def update_snapshot(id):
    snap = PlanningSnapshot.query.get_or_404(id)
    data = request.get_json() or {}
    if 'label' in data:
        snap.label = data['label']
    if 'status' in data:
        snap.status = data['status']
    db.session.commit()
    return jsonify(snap.to_dict())


@bp.route('/snapshots/<int:id>', methods=['DELETE'])
def delete_snapshot(id):
    snap = PlanningSnapshot.query.get_or_404(id)
    db.session.delete(snap)
    db.session.commit()
    return '', 204


@bp.route('/snapshots/<int:id>/restore', methods=['POST'])
def restore_snapshot(id):
    snap = PlanningSnapshot.query.get_or_404(id)
    data = snap.data or {}
    # expected data format: {'adjusted': [...], 'violations': [...]} minimal
    monday = snap.monday
    sunday = snap.sunday
    # delete existing adjusted shifts and violations in range
    from .models import AdjustedShift, RuleViolation
    AdjustedShift.query.filter(AdjustedShift.date >= monday, AdjustedShift.date <= sunday).delete(synchronize_session=False)
    RuleViolation.query.filter(RuleViolation.date >= monday, RuleViolation.date <= sunday).delete(synchronize_session=False)
    db.session.commit()

    # restore adjusted shifts
    for s in data.get('adjusted', []):
        try:
            adj = AdjustedShift(
                employee_id=s['employee_id'],
                date=datetime.fromisoformat(s['date']).date(),
                start_time=s['start_time'],
                end_time=s['end_time'],
                lunch_start=s.get('lunch_start'),
                lunch_end=s.get('lunch_end'),
                source=s.get('source', 'snapshot'),
                note=s.get('note'),
            )
            db.session.add(adj)
        except Exception:
            continue

    # restore violations
    for v in data.get('violations', []):
        try:
            rv = RuleViolation(
                date=datetime.fromisoformat(v['date']).date(),
                employee_id=v.get('employee_id'),
                code=v.get('code', 'RESTORED'),
                details=v.get('details'),
                severity=v.get('severity', 'warning')
            )
            db.session.add(rv)
        except Exception:
            continue

    db.session.commit()
    return jsonify({'restored': True, 'snapshot_id': id})


@bp.route('/snapshots/<int:id>/download', methods=['GET'])
def download_snapshot(id):
    snap = PlanningSnapshot.query.get_or_404(id)
    content = json.dumps(snap.to_dict(), indent=2, ensure_ascii=False, default=str)
    from flask import make_response
    resp = make_response(content)
    resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename="snapshot-{id}.json"'
    return resp
