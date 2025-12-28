import json
from backend import create_app
from backend.models import db, PlanningSnapshot, AdjustedShift, RuleViolation


def test_snapshots_crud_and_restore(tmp_path):
    app = create_app()
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        # create necessary DB rows so backend snapshot creation finds adjusted/violations
        from backend.models import Employee
        emp = Employee(name='Tester', contract_type='35h', max_week_hours=35)
        db.session.add(emp)
        db.session.commit()
        # insert adjusted shift and a violation that will be captured
        from datetime import date as _date
        adj_row = AdjustedShift(employee_id=emp.id, date=_date.fromisoformat("2025-12-01"), start_time='09:30', end_time='13:30')
        db.session.add(adj_row)
        rv_row = RuleViolation(date=_date.fromisoformat("2025-12-01"), employee_id=emp.id, code='TEST', details='test violation', severity='warning')
        db.session.add(rv_row)
        db.session.commit()

        # create a snapshot via POST
        payload = {
            'monday': '2025-12-01',
            'weeks': 1,
            'label': 'Test Snap',
            'status': 'previsionnel',
            'data': {
                'adjusted': [
                    {'employee_id': 1, 'date': '2025-12-01', 'start_time': '09:30', 'end_time': '13:30'}
                ],
                'violations': [
                    {'date': '2025-12-01', 'code': 'TEST', 'details': 'test violation', 'severity': 'warning'}
                ]
            }
        }
        rv = client.post('/api/snapshots', json=payload)
        assert rv.status_code == 201
        resp = rv.get_json()
        snap = resp.get('snapshot') if isinstance(resp, dict) and 'snapshot' in resp else resp
        snap_id = snap['id']

        # GET snapshot
        rv = client.get(f'/api/snapshots/{snap_id}')
        assert rv.status_code == 200
        data = rv.get_json()
        assert data['label'] == 'Test Snap'

        # update snapshot
        rv = client.put(f'/api/snapshots/{snap_id}', json={'status': 'validé', 'label': 'Updated'})
        assert rv.status_code == 200
        resp_up = rv.get_json()
        updated = resp_up.get('snapshot') if isinstance(resp_up, dict) and 'snapshot' in resp_up else resp_up
        assert updated['status'] == 'valide' or updated['status'] == 'validé'

        # restore snapshot
        rv = client.post(f'/api/snapshots/{snap_id}/restore')
        assert rv.status_code == 200
        res = rv.get_json()
        assert 'restored' in res

        # check adjusted shifts and violations exist
        adj = AdjustedShift.query.first()
        rvio = RuleViolation.query.filter_by(code='TEST').first()
        assert adj is not None
        assert rvio is not None

        # delete snapshot
        rv = client.delete(f'/api/snapshots/{snap_id}')
        assert rv.status_code in (200, 204)
from datetime import date

from backend.models import AdjustedShift, Employee
from backend.models import db


def test_snapshot_requires_adjusted(app, client):
    res = client.post("/api/snapshots", json={"monday": "2024-03-04"})
    assert res.status_code == 400
    assert res.json["error"] == "empty"


def test_snapshot_creation(app, client):
    with app.app_context():
        emp = Employee(name="Eva", contract_type="35h", max_week_hours=35)
        db.session.add(emp)
        db.session.commit()
        monday = date(2024, 3, 4)
        adj = AdjustedShift(
            date=monday,
            employee_id=emp.id,
            start_time="09:30",
            end_time="12:30",
        )
        db.session.add(adj)
        db.session.commit()

    res = client.post("/api/snapshots", json={"monday": "2024-03-04"})
    assert res.status_code == 201
    data = res.json["snapshot"]
    assert data["monday"] == "2024-03-04"
    assert data["counts"]["adjusted"] == 1

    list_res = client.get("/api/snapshots")
    assert list_res.status_code == 200
    assert len(list_res.json) == 1


def test_snapshot_two_weeks(app, client):
    with app.app_context():
        emp = Employee(name="Fiona", contract_type="35h", max_week_hours=35)
        db.session.add(emp)
        db.session.commit()
        first_monday = date(2024, 3, 4)
        second_monday = date(2024, 3, 11)
        db.session.add_all([
            AdjustedShift(date=first_monday, employee_id=emp.id, start_time="09:30", end_time="12:30"),
            AdjustedShift(date=second_monday, employee_id=emp.id, start_time="14:00", end_time="18:00"),
        ])
        db.session.commit()

    res = client.post("/api/snapshots", json={"monday": "2024-03-04", "weeks": 2})
    assert res.status_code == 201
    snap = res.json["snapshot"]
    assert snap["duration_weeks"] == 2
    assert snap["counts"]["adjusted"] == 2

    detail = client.get(f"/api/snapshots/{snap['id']}")
    assert detail.status_code == 200
    payload = detail.json["data"]
    assert len(payload.get("weeks")) == 2
