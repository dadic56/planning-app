from backend import create_app
from backend.models import db, Employee, OpeningHours, BaseShift

app = create_app()

def add_shift(name, weekday, start, end, lstart=None, lend=None):
    emp = Employee.query.filter_by(name=name).first()
    db.session.add(BaseShift(employee_id=emp.id, weekday=weekday,
                             start_time=start, end_time=end,
                             lunch_start=lstart, lunch_end=lend))

with app.app_context():
    emps = [
        ("Clara","24h",""),
        ("Nathalie","24h","Lundi après-midi libre"),
        ("Stéphanie","35h","Jamais le vendredi"),
        ("Alexandra","35h",""),
        ("Aurélia","35h",""),
        ("Noémie","35h",""),
    ]
    for n,c,s in emps: db.session.add(Employee(name=n, contract_type=c, special_rules=s))
    db.session.commit()

    for wd in range(0,6):
        db.session.add(OpeningHours(weekday=wd, open_time="09:30", close_time="19:15", sunday_open=False))
    db.session.add(OpeningHours(weekday=6, open_time="09:30", close_time="19:15", sunday_open=False))
    db.session.commit()

    # Alexandra
    add_shift("Alexandra",1,"09:30","14:00"); add_shift("Alexandra",1,"15:00","19:45")
    add_shift("Alexandra",2,"09:30","13:30"); add_shift("Alexandra",2,"14:30","19:15")
    add_shift("Alexandra",3,"09:30","13:30")
    add_shift("Alexandra",4,"09:30","14:00"); add_shift("Alexandra",4,"15:00","19:15")
    add_shift("Alexandra",5,"15:15","19:00")

    # Aurélia
    add_shift("Aurélia",0,"09:30","13:30"); add_shift("Aurélia",0,"14:30","19:15")
    add_shift("Aurélia",1,"09:30","13:00"); add_shift("Aurélia",1,"14:00","19:00")
    add_shift("Aurélia",2,"09:30","13:15")
    add_shift("Aurélia",3,"13:30","19:15")
    add_shift("Aurélia",5,"10:30","13:00"); add_shift("Aurélia",5,"14:00","19:15")

    # Noémie
    add_shift("Noémie",0,"09:30","12:15"); add_shift("Noémie",0,"13:15","19:15")
    add_shift("Noémie",1,"13:30","19:00")
    add_shift("Noémie",2,"13:30","19:00")
    add_shift("Noémie",5,"09:30","13:45")

    # Nathalie (24h)
    add_shift("Nathalie",2,"10:00","13:00")
    add_shift("Nathalie",3,"09:30","13:00"); add_shift("Nathalie",3,"15:00","19:15")
    add_shift("Nathalie",4,"09:30","13:00"); add_shift("Nathalie",4,"14:00","19:15")
    add_shift("Nathalie",5,"14:45","19:15")

    # Stéphanie (pas de vendredi)
    add_shift("Stéphanie",0,"14:00","19:00")
    add_shift("Stéphanie",1,"09:30","12:00"); add_shift("Stéphanie",1,"13:00","17:30")
    add_shift("Stéphanie",2,"13:00","19:00")
    add_shift("Stéphanie",3,"09:30","12:00"); add_shift("Stéphanie",3,"13:00","19:00")
    add_shift("Stéphanie",5,"09:30","12:00"); add_shift("Stéphanie",5,"13:00","19:00")

    # Clara (24h)
    add_shift("Clara",0,"09:30","13:15")
    add_shift("Clara",1,"10:45","13:00"); add_shift("Clara",1,"14:00","19:15")
    add_shift("Clara",2,"09:30","12:30"); add_shift("Clara",2,"14:00","19:15")
    add_shift("Clara",4,"09:30","12:00"); add_shift("Clara",4,"13:00","19:00")
    add_shift("Clara",5,"09:30","12:00"); add_shift("Clara",5,"14:00","19:00")

    db.session.commit()
    print("Seed de base OK")
