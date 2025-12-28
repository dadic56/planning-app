"""Seed demo data into the SQLite database."""
import argparse
from app import create_app, db
from app.models import Employee, BaseShift


def seed(reset=False):
    app = create_app()
    with app.app_context():
        if reset:
            # drop all then create
            db.drop_all()
            db.create_all()

        if Employee.query.count() == 0:
            names = [
                ('Clara', '24h', 24),
                ('Nathalie', '24h', 24),
                ('Alexandra', '35h', 35),
                ('Stéphanie', '35h', 35),
                ('Julie', '24h', 24),
                ('Marie', '24h', 24),
            ]
            for name, ct, mh in names:
                e = Employee(name=name, contract_type=ct, max_week_hours=mh)
                db.session.add(e)
            db.session.commit()

        # add simple base shifts for Clara (Mon-Fri 09:30-13:30)
        clara = Employee.query.filter_by(name='Clara').first()
        if clara and BaseShift.query.filter_by(employee_id=clara.id).count() == 0:
            for wd in range(5):
                bs = BaseShift(employee_id=clara.id, weekday=wd, start_time='09:30', end_time='13:30')
                db.session.add(bs)
            db.session.commit()

    print('Seed complete')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--reset', action='store_true')
    args = p.parse_args()
    seed(reset=args.reset)
#!/usr/bin/env python3
"""Seed de données de base pour l'application planning.

Usage :
    python scripts/seed_demo.py --reset   # purge les tables cibles avant insertion
"""

from __future__ import annotations

import argparse

from backend import create_app
from backend.models import (
    db,
    Employee,
    OpeningHours,
    BaseShift,
    Absence,
    AdjustedShift,
    RuleViolation,
    SpecialOpening,
    SpecialOpeningShift,
)

EMPLOYEES = [
    {"name": "Alexandra", "contract_type": "35h", "max_week_hours": 35, "allow_overtime": True},
    {"name": "Aurélia", "contract_type": "35h", "max_week_hours": 35, "allow_overtime": True},
    {"name": "Clara", "contract_type": "24h", "max_week_hours": 24, "allow_overtime": False, "special_rules": "Heures sup interdites"},
    {"name": "Nathalie", "contract_type": "24h", "max_week_hours": 24, "allow_overtime": True, "special_rules": "Lundi après-midi libre"},
    {"name": "Stéphanie", "contract_type": "35h", "max_week_hours": 35, "allow_overtime": True, "special_rules": "Jamais le vendredi"},
    {"name": "Guylan", "contract_type": "35h", "max_week_hours": 35, "allow_overtime": True},
    {"name": "Julie", "contract_type": "17.5h", "max_week_hours": 17.5, "allow_overtime": False},
]

BASE_SHIFTS = {
    "Alexandra": [
        (1, "09:30", "13:30"), (1, "14:15", "19:15"),
        (2, "09:30", "13:30"), (2, "14:15", "19:15"),
        (3, "09:30", "13:30"),
        (4, "09:30", "14:00"), (4, "14:45", "19:15"),
        (5, "15:00", "19:00"),
    ],
    "Aurélia": [
        (0, "09:30", "13:30"), (0, "14:30", "19:15"),
        (1, "09:30", "13:00"), (1, "14:00", "19:00"),
        (2, "09:30", "13:15"),
        (3, "13:30", "19:15"),
        (5, "10:30", "13:00"), (5, "14:00", "19:15"),
    ],
    "Clara": [
        (0, "09:30", "13:15"),
        (1, "15:15", "19:00"),
        (2, "09:30", "12:30"),
        (4, "09:30", "12:30"),
        (5, "15:00", "19:00"),
    ],
    "Nathalie": [
        (2, "10:00", "13:00"),
        (3, "09:30", "13:00"), (3, "15:00", "19:15"),
        (4, "09:30", "13:00"), (4, "14:00", "19:15"),
        (5, "14:45", "19:15"),
    ],
    "Stéphanie": [
        (0, "14:00", "19:00"),
        (1, "09:30", "12:00"), (1, "13:00", "17:30"),
        (2, "13:00", "19:00"),
        (3, "09:30", "12:00"), (3, "13:00", "19:00"),
        (5, "09:30", "12:00"), (5, "13:00", "19:00"),
    ],
    "Guylan": [
        (0, "09:30", "12:15"), (0, "13:15", "19:15"),
        (1, "13:30", "19:00"),
        (2, "13:30", "19:00"),
        (5, "09:30", "13:45"),
    ],
    "Julie": [
        (1, "10:15", "13:15"),
        (2, "15:00", "19:00"),
        (4, "13:15", "19:15"),
        (5, "09:30", "14:00"),
    ],
}

OPENING_HOURS = [
    (0, "09:30", "19:15"),
    (1, "09:30", "19:15"),
    (2, "09:30", "19:15"),
    (3, "09:30", "19:15"),
    (4, "09:30", "19:15"),
    (5, "09:30", "19:15"),
    (6, "09:30", "19:15", False),
]


def main():
    parser = argparse.ArgumentParser(description="Seed des données planning")
    parser.add_argument("--reset", action="store_true", help="Purge les tables avant insertion")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db.create_all()

        if args.reset:
            for model in [SpecialOpeningShift, SpecialOpening, RuleViolation, AdjustedShift, BaseShift, Absence, OpeningHours, Employee]:
                db.session.query(model).delete()
            db.session.commit()

        # Employées
        name_to_employee = {}
        for data in EMPLOYEES:
            emp = Employee.query.filter_by(name=data["name"]).first()
            if not emp:
                emp = Employee(**data)
                db.session.add(emp)
            else:
                for key, value in data.items():
                    setattr(emp, key, value)
            name_to_employee[data["name"]] = emp
        db.session.commit()

        # Horaires d'ouverture
        for wd, open_time, close_time, *rest in OPENING_HOURS:
            sunday_flag = bool(rest[0]) if rest else False
            oh = OpeningHours.query.filter_by(weekday=wd).first()
            if not oh:
                oh = OpeningHours(weekday=wd)
                db.session.add(oh)
            oh.open_time = open_time
            oh.close_time = close_time
            oh.sunday_open = sunday_flag
        db.session.commit()

        # Créneaux de base
        BaseShift.query.delete()
        db.session.commit()
        for name, slots in BASE_SHIFTS.items():
            emp = name_to_employee.get(name)
            if not emp:
                continue
            for entry in slots:
                weekday, start, end, *rest = entry
                lunch = rest or [None, None]
                b = BaseShift(
                    employee_id=emp.id,
                    weekday=weekday,
                    start_time=start,
                    end_time=end,
                    lunch_start=lunch[0] if len(lunch) >= 1 else None,
                    lunch_end=lunch[1] if len(lunch) >= 2 else None,
                )
                db.session.add(b)
        db.session.commit()
        print("Seed terminé :", Employee.query.count(), "employées /", BaseShift.query.count(), "créneaux")


if __name__ == "__main__":
    main()
