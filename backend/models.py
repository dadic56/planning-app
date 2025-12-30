from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    contract_type = db.Column(db.String(10), nullable=False)
    max_week_hours = db.Column(db.Float, nullable=True)
    special_rules = db.Column(db.String(200), default="")
    therapeutic_part_time = db.Column(db.Boolean, default=False)
    therapeutic_percent = db.Column(db.Float, nullable=True)
    allow_overtime = db.Column(db.Boolean, default=True)
    sunday_available = db.Column(db.Boolean, default=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'contract_type': self.contract_type,
            'max_week_hours': self.max_week_hours,
            'special_rules': self.special_rules,
            'therapeutic_part_time': self.therapeutic_part_time,
            'therapeutic_percent': self.therapeutic_percent,
            'allow_overtime': self.allow_overtime,
            'sunday_available': self.sunday_available
        }

class OpeningHours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    weekday = db.Column(db.Integer, nullable=False)
    open_time = db.Column(db.String(5), nullable=False)
    close_time = db.Column(db.String(5), nullable=False)
    sunday_open = db.Column(db.Boolean, default=False)

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    name = db.Column(db.String(80))

class BaseShift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    lunch_start = db.Column(db.String(5))
    lunch_end = db.Column(db.String(5))
    note = db.Column(db.String(200))

class Absence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(80))

class AdjustedShift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, index=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    lunch_start = db.Column(db.String(5))
    lunch_end = db.Column(db.String(5))
    source = db.Column(db.String(20), default="auto")
    note = db.Column(db.String(200))
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'employee_id': self.employee_id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'lunch_start': self.lunch_start,
            'lunch_end': self.lunch_end,
            'source': self.source,
            'note': self.note
        }

class RuleViolation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    code = db.Column(db.String(50), nullable=False)
    details = db.Column(db.String(200))
    severity = db.Column(db.String(10), default="warn")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'employee_id': self.employee_id,
            'code': self.code,
            'details': self.details,
            'severity': self.severity,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class PlanningSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monday = db.Column(db.Date, nullable=False, index=True)
    sunday = db.Column(db.Date, nullable=False)
    label = db.Column(db.String(120))
    status = db.Column(db.String(20), default="draft")
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'monday': self.monday.isoformat() if self.monday else None,
            'sunday': self.sunday.isoformat() if self.sunday else None,
            'label': self.label,
            'status': self.status,
            'data': self.data,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class SpecialOpening(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    label = db.Column(db.String(120))
    open_time = db.Column(db.String(5))
    close_time = db.Column(db.String(5))
    is_closed = db.Column(db.Boolean, default=False)
    sunday_mode = db.Column(db.Boolean, default=False)
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    shifts = db.relationship('SpecialOpeningShift', backref='opening', cascade="all, delete-orphan")

class SpecialOpeningShift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    opening_id = db.Column(db.Integer, db.ForeignKey('special_opening.id', ondelete='CASCADE'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    lunch_start = db.Column(db.String(5))
    lunch_end = db.Column(db.String(5))
