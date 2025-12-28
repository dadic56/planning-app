import datetime
from app import db
from sqlalchemy import UniqueConstraint


class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    contract_type = db.Column(db.String(20), nullable=False)
    max_week_hours = db.Column(db.Integer, nullable=False, default=35)
    therapeutic_part_time = db.Column(db.Boolean, default=False)
    therapeutic_percent = db.Column(db.Integer, nullable=True)
    allow_overtime = db.Column(db.Boolean, default=False)
    sunday_available = db.Column(db.Boolean, default=False)
    special_rules = db.Column(db.Text, nullable=True)

    base_shifts = db.relationship('BaseShift', backref='employee', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'contract_type': self.contract_type,
            'max_week_hours': self.max_week_hours,
            'therapeutic_part_time': self.therapeutic_part_time,
            'therapeutic_percent': self.therapeutic_percent,
            'allow_overtime': self.allow_overtime,
            'sunday_available': self.sunday_available,
            'special_rules': self.special_rules,
        }


class BaseShift(db.Model):
    __tablename__ = 'base_shifts'
    __table_args__ = (
        UniqueConstraint('employee_id', 'weekday', 'start_time', 'end_time', 'lunch_start', name='uix_employee_weekday_shift'),
    )
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0=Monday .. 6=Sunday
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5), nullable=False)
    lunch_start = db.Column(db.String(5), nullable=True)
    lunch_end = db.Column(db.String(5), nullable=True)
    note = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'weekday': self.weekday,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'lunch_start': self.lunch_start,
            'lunch_end': self.lunch_end,
            'note': self.note,
        }


class Absence(db.Model):
    __tablename__ = 'absences'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(255), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'reason': self.reason,
        }


class AdjustedShift(db.Model):
    __tablename__ = 'adjusted_shifts'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    lunch_start = db.Column(db.String(5), nullable=True)
    lunch_end = db.Column(db.String(5), nullable=True)
    source = db.Column(db.String(50), nullable=True)
    note = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'date': self.date.isoformat(),
            'start_time': self.start_time,
            'end_time': self.end_time,
            'lunch_start': self.lunch_start,
            'lunch_end': self.lunch_end,
            'source': self.source,
            'note': self.note,
        }


class RuleViolation(db.Model):
    __tablename__ = 'rule_violations'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    code = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(20), nullable=False, default='warning')
    created_at = db.Column(db.Date, default=datetime.date.today)

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'employee_id': self.employee_id,
            'code': self.code,
            'details': self.details,
            'severity': self.severity,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class PlanningSnapshot(db.Model):
    __tablename__ = 'planning_snapshots'
    id = db.Column(db.Integer, primary_key=True)
    monday = db.Column(db.Date, nullable=False)
    sunday = db.Column(db.Date, nullable=False)
    label = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), nullable=True)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.Date, default=datetime.date.today)

    def to_dict(self):
        return {
            'id': self.id,
            'monday': self.monday.isoformat(),
            'sunday': self.sunday.isoformat(),
            'label': self.label,
            'status': self.status,
            'data': self.data,
            'created_at': self.created_at.isoformat(),
        }
