import pytest
from app import create_app, db
from app.models import Employee


def test_employee_unique_name(tmp_path):
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        e1 = Employee(name='Alice', contract_type='35h', max_week_hours=35)
        db.session.add(e1)
        db.session.commit()
        e2 = Employee(name='Alice', contract_type='24h', max_week_hours=24)
        db.session.add(e2)
        with pytest.raises(Exception):
            db.session.commit()
