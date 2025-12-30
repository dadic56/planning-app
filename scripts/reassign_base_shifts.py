#!/usr/bin/env python3
"""Redistribute BaseShift weekdays.

Usage:
  python scripts/reassign_base_shifts.py --dry-run
  python scripts/reassign_base_shifts.py --apply

Strategy (default): for each employee, spread their shifts across weekdays 0..5 in round-robin order preserving start/end times.
"""
import sys
from collections import defaultdict

def main(apply=False):
    from backend import create_app
    from backend.models import db, BaseShift, Employee

    app = create_app()
    with app.app_context():
        employees = {e.id: e for e in Employee.query.order_by(Employee.id).all()}
        shifts = BaseShift.query.order_by(BaseShift.employee_id, BaseShift.start_time).all()
        by_emp = defaultdict(list)
        for s in shifts:
            by_emp[s.employee_id].append(s)

        planned_changes = []
        for emp_idx, (emp_id, slist) in enumerate(sorted(by_emp.items())):
            # start weekday offset to stagger employees
            offset = emp_idx % 6
            for i, s in enumerate(slist):
                target_weekday = (offset + i) % 6  # 0..5 (Mon..Sat)
                if s.weekday != target_weekday:
                    planned_changes.append({
                        'id': s.id,
                        'employee_id': emp_id,
                        'employee': employees.get(emp_id).name if employees.get(emp_id) else f'#{emp_id}',
                        'old_weekday': s.weekday,
                        'new_weekday': target_weekday,
                        'start_time': s.start_time,
                        'end_time': s.end_time,
                    })

        if not planned_changes:
            print('No changes planned; base shifts already distributed.')
            return 0

        print(f'Planned {len(planned_changes)} changes (dry-run={not apply}):')
        for c in planned_changes:
            print(f"- Shift id={c['id']} {c['employee']} {c['start_time']}-{c['end_time']}: {c['old_weekday']} -> {c['new_weekday']}")

        if apply:
            # apply updates
            for c in planned_changes:
                s = BaseShift.query.get(c['id'])
                s.weekday = c['new_weekday']
                db.session.add(s)
            db.session.commit()
            print('Applied changes to DB.')
        else:
            print('\nRun with --apply to commit these changes.')
    return 0

if __name__ == '__main__':
    apply_flag = '--apply' in sys.argv[1:]
    try:
        sys.exit(main(apply=apply_flag))
    except Exception as e:
        print('Error:', e)
        sys.exit(2)
