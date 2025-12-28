from app import create_app, db
from app.models import Employee, BaseShift, Absence, RuleViolation


def test_generator_shift_length_and_pause(tmp_path):
    app = create_app()
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()

        # create employee
        e = Employee(name='Test', contract_type='35h', max_week_hours=35, allow_overtime=False)
        db.session.add(e)
        db.session.commit()

        # create a too-long shift (11h) on Monday
        bs = BaseShift(employee_id=e.id, weekday=0, start_time='08:00', end_time='19:00')
        db.session.add(bs)
        db.session.commit()

        # generate week
        rv = client.post('/api/generate-week?monday=2025-12-01&sunday_open=0')
        assert rv.status_code == 200
        data = rv.get_json()
        # expect a SHIFT_TOO_LONG violation
        codes = [v['code'] for v in data.get('violations', [])]
        assert 'SHIFT_TOO_LONG' in codes


def test_generator_missing_pause_warning(tmp_path):
    app = create_app()
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()

        e = Employee(name='Test2', contract_type='35h', max_week_hours=35, allow_overtime=False)
        db.session.add(e)
        db.session.commit()

        # create a shift >6h but without lunch
        bs = BaseShift(employee_id=e.id, weekday=1, start_time='09:00', end_time='16:30')
        db.session.add(bs)
        db.session.commit()

        rv = client.post('/api/generate-week?monday=2025-11-30&sunday_open=0')
        assert rv.status_code == 200
        data = rv.get_json()
        codes = [v['code'] for v in data.get('violations', [])]
        assert 'MISSING_PAUSE' in codes
