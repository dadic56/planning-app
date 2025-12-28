import pytest

from backend.models import BaseShift, Employee


def create_employee(app, name="Test"):
    with app.app_context():
        emp = Employee(name=name, contract_type="35h", max_week_hours=35)
        from backend.models import db

        db.session.add(emp)
        db.session.commit()
        return emp.id


def test_create_base_shift_valid(app, client):
    emp_id = create_employee(app, "Alice")
    payload = {
        "employee_id": emp_id,
        "weekday": 1,
        "start_time": "09:30",
        "end_time": "13:30",
    }
    res = client.post("/api/base-shifts", json=payload)
    assert res.status_code == 201
    with app.app_context():
        assert BaseShift.query.count() == 1


def test_create_base_shift_invalid_hours(app, client):
    emp_id = create_employee(app, "Bob")
    payload = {
        "employee_id": emp_id,
        "weekday": 2,
        "start_time": "13:30",
        "end_time": "12:30",
    }
    res = client.post("/api/base-shifts", json=payload)
    assert res.status_code == 400
    assert "fin" in res.json["detail"].lower()


def test_create_base_shift_overlap(app, client):
    emp_id = create_employee(app, "Charlie")
    payload = {
        "employee_id": emp_id,
        "weekday": 3,
        "start_time": "09:00",
        "end_time": "12:00",
    }
    first = client.post("/api/base-shifts", json=payload)
    assert first.status_code == 201

    res = client.post("/api/base-shifts", json={**payload, "start_time": "11:00", "end_time": "13:00"})
    assert res.status_code == 400
    assert "chevauchement" in res.json["detail"].lower()


def test_update_base_shift_validate(app, client):
    emp_id = create_employee(app, "Dana")
    payload = {
        "employee_id": emp_id,
        "weekday": 4,
        "start_time": "09:00",
        "end_time": "12:00",
    }
    create_res = client.post("/api/base-shifts", json=payload)
    bid = create_res.json["id"]
    update = client.put(f"/api/base-shifts/{bid}", json={"start_time": "11:30", "end_time": "10:30"})
    assert update.status_code == 400
    assert "fin" in update.json["detail"].lower()
