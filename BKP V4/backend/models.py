from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    contract_type = db.Column(db.String(10), nullable=False)  # "24h" | "35h"
    max_week_hours = db.Column(db.Integer, nullable=True)
    special_rules = db.Column(db.String(200), default="")
    therapeutic_part_time = db.Column(db.Boolean, default=False)
    therapeutic_percent = db.Column(db.Float, nullable=True)
    allow_overtime = db.Column(db.Boolean, default=True)

class OpeningHours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    weekday = db.Column(db.Integer, nullable=False)   # 0=Mon..6=Sun
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
    weekday = db.Column(db.Integer, nullable=False)  # 0..6
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
    source = db.Column(db.String(20), default="auto")  # auto | manuel
    note = db.Column(db.String(200))

class RuleViolation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    code = db.Column(db.String(50), nullable=False)
    details = db.Column(db.String(200))
    severity = db.Column(db.String(10), default="warn")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PlanningSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monday = db.Column(db.Date, nullable=False, index=True)
    sunday = db.Column(db.Date, nullable=False)
    label = db.Column(db.String(120))
    status = db.Column(db.String(20), default="draft")
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
