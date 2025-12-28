#!/usr/bin/env bash
set -euo pipefail

mkdir -p backend static

cat > requirements.txt << 'EOF'
Flask==2.2.5
Flask-SQLAlchemy==3.1.1
Flask-Migrate==4.0.7
EOF

cat > .flaskenv << 'EOF'
FLASK_APP=wsgi.py
FLASK_ENV=development
EOF

cat > backend/__init__.py << 'EOF'
from flask import Flask
from flask_migrate import Migrate
from .models import db
from .routes import bp as api_bp

migrate = Migrate()

def create_app():
    app = Flask(__name__, static_folder="../static", static_url_path="/")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///planning.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    migrate.init_app(app, db)

    @app.get("/health")
    def health():
        return {"ok": True}

    app.register_blueprint(api_bp, url_prefix="/api")
    return app
EOF

cat > backend/models.py << 'EOF'
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    contract_type = db.Column(db.String(10), nullable=False)  # "24h" | "35h"
    special_rules = db.Column(db.String(200), default="")

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
EOF

cat > backend/rules.py << 'EOF'
RULES = {
    "OPENING_TEAM_MIN": 3,
    "CLOSING_TEAM_MIN": 3,
    "LUNCH_MAX_MINUTES": 60,
    "LUNCH_WINDOW_START": "12:00",
    "LUNCH_WINDOW_END": "15:00",
    "MAX_CONSECUTIVE_HOURS_NO_BREAK": 6,
    "MAX_DAILY_HOURS": 10,
    "STRICT_24H": True,
    "MAX_WEEKLY_35H": 35
}
EOF

cat > backend/services.py << 'EOF'
from datetime import date, timedelta
from .models import db, Employee, BaseShift, AdjustedShift, Absence, OpeningHours, Holiday, RuleViolation
from .rules import RULES

def str_to_minutes(s):
    h,m = map(int, s.split(":")); return h*60+m
def minutes_to_str(x):
    return f"{x//60:02d}:{x%60:02d}"
def overlap(a_start,a_end,b_start,b_end):
    return max(a_start,b_start) < min(a_end,b_end)

def _is_holiday(day):
    return Holiday.query.filter_by(date=day).first() is not None

def _opening_for_weekday(wd):
    return OpeningHours.query.filter_by(weekday=wd).first()

def _is_absent(emp_id, day):
    q = Absence.query.filter(Absence.employee_id==emp_id,
                             Absence.start_date<=day,
                             Absence.end_date>=day)
    return db.session.query(q.exists()).scalar()

def _employee_week_minutes(emp_id, monday):
    sunday = monday + timedelta(days=6)
    shifts = AdjustedShift.query.filter(AdjustedShift.employee_id==emp_id,
                                        AdjustedShift.date.between(monday, sunday)).all()
    total = 0
    for s in shifts:
        total += str_to_minutes(s.end_time)-str_to_minutes(s.start_time)
    return total

def _can_add(emp, monday, start, end):
    add = end-start
    wk = _employee_week_minutes(emp.id, monday)
    if emp.contract_type == "24h" and RULES["STRICT_24H"]:
        return wk + add <= 24*60
    else:
        return wk + add <= RULES["MAX_WEEKLY_35H"]*60

def generate_adjusted_week(monday: date, sunday_open=False):
    sunday = monday + timedelta(days=6)
    AdjustedShift.query.filter(AdjustedShift.date.between(monday, sunday)).delete()
    RuleViolation.query.filter(RuleViolation.date.between(monday, sunday)).delete()
    db.session.commit()

    base = BaseShift.query.all()
    for b in base:
        day = monday + timedelta(days=b.weekday)
        oh = _opening_for_weekday(b.weekday)
        if not oh: 
            continue
        if b.weekday == 6 and not sunday_open and not oh.sunday_open:
            continue
        if _is_holiday(day):
            continue
        if _is_absent(b.employee_id, day):
            continue
        db.session.add(AdjustedShift(
            date=day, employee_id=b.employee_id,
            start_time=b.start_time, end_time=b.end_time,
            lunch_start=b.lunch_start, lunch_end=b.lunch_end, source="auto"
        ))
    db.session.commit()

    for d in range(7):
        day = monday + timedelta(days=d)
        oh = _opening_for_weekday(d)
        if not oh: continue
        if d==6 and not sunday_open and not oh.sunday_open: 
            continue

        open_min = str_to_minutes(oh.open_time)
        close_min = str_to_minutes(oh.close_time)

        day_shifts = AdjustedShift.query.filter_by(date=day).all()
        def count_at(t): 
            return sum(1 for s in day_shifts 
                       if str_to_minutes(s.start_time) <= t < str_to_minutes(s.end_time))

        need = max(0, RULES["OPENING_TEAM_MIN"] - count_at(open_min))
        if need>0:
            for emp in Employee.query.all():
                if _is_absent(emp.id, day): 
                    continue
                busy = any(overlap(str_to_minutes(s.start_time), str_to_minutes(s.end_time), open_min, open_min+120)
                           for s in day_shifts if s.employee_id==emp.id)
                if busy: continue
                s_start, s_end = open_min, min(open_min+120, close_min)
                if _can_add(emp, monday, s_start, s_end):
                    ns = AdjustedShift(date=day, employee_id=emp.id,
                                       start_time=minutes_to_str(s_start),
                                       end_time=minutes_to_str(s_end),
                                       source="auto", note="renfort ouverture")
                    db.session.add(ns); day_shifts.append(ns)
                    need -= 1
                    if need==0: break

        need = max(0, RULES["CLOSING_TEAM_MIN"] - count_at(close_min-1))
        if need>0:
            for emp in Employee.query.all():
                if _is_absent(emp.id, day): 
                    continue
                busy = any(overlap(str_to_minutes(s.start_time), str_to_minutes(s.end_time), close_min-120, close_min)
                           for s in day_shifts if s.employee_id==emp.id)
                if busy: continue
                s_start, s_end = max(open_min, close_min-120), close_min
                if _can_add(emp, monday, s_start, s_end):
                    ns = AdjustedShift(date=day, employee_id=emp.id,
                                       start_time=minutes_to_str(s_start),
                                       end_time=minutes_to_str(s_end),
                                       source="auto", note="renfort fermeture")
                    db.session.add(ns); day_shifts.append(ns)
                    need -= 1
                    if need==0: break
    db.session.commit()

    _validate_week(monday)

def _validate_week(monday):
    for d in range(7):
        day = monday + timedelta(days=d)
        oh = _opening_for_weekday(d)
        if not oh: continue
        open_min = str_to_minutes(oh.open_time)
        close_min = str_to_minutes(oh.close_time)
        shifts = AdjustedShift.query.filter_by(date=day).all()
        open_count = sum(1 for s in shifts if str_to_minutes(s.start_time) <= open_min < str_to_minutes(s.end_time))
        if open_count < RULES["OPENING_TEAM_MIN"]:
            db.session.add(RuleViolation(date=day, code="OPENING_COVERAGE",
                                         details=f"Ouverture < {RULES['OPENING_TEAM_MIN']}"))
        close_count = sum(1 for s in shifts if str_to_minutes(s.start_time) < close_min <= str_to_minutes(s.end_time))
        if close_count < RULES["CLOSING_TEAM_MIN"]:
            db.session.add(RuleViolation(date=day, code="CLOSING_COVERAGE",
                                         details=f"Fermeture < {RULES['CLOSING_TEAM_MIN']}"))
    db.session.commit()
EOF

cat > backend/routes.py << 'EOF'
from flask import Blueprint, request, jsonify
from datetime import datetime
from .models import db, Employee, Absence, OpeningHours, AdjustedShift, RuleViolation
from .services import generate_adjusted_week

bp = Blueprint("api", __name__)

@bp.get("/employees")
def employees():
    data = [{"id":e.id,"name":e.name,"contract_type":e.contract_type,"special_rules":e.special_rules}
            for e in Employee.query.order_by(Employee.name).all()]
    return jsonify(data)

@bp.post("/absences")
def add_absence():
    payload = request.get_json()
    a = Absence(employee_id=payload["employee_id"],
                start_date=datetime.fromisoformat(payload["start_date"]).date(),
                end_date=datetime.fromisoformat(payload["end_date"]).date(),
                reason=payload.get("reason",""))
    db.session.add(a); db.session.commit()
    return {"ok":True,"id":a.id}

@bp.post("/generate-week")
def gen_week():
    monday = datetime.fromisoformat(request.args.get("monday")).date()
    sunday_open = request.args.get("sunday_open","0") == "1"
    generate_adjusted_week(monday, sunday_open=sunday_open)
    return {"ok":True}

@bp.get("/adjusted")
def adjusted():
    start = datetime.fromisoformat(request.args.get("from")).date()
    end = datetime.fromisoformat(request.args.get("to")).date()
    rows = (db.session.query(AdjustedShift, Employee.name)
            .join(Employee, Employee.id==AdjustedShift.employee_id)
            .filter(AdjustedShift.date.between(start,end))
            .order_by(AdjustedShift.date, Employee.name).all())
    data = [{
        "date": r.AdjustedShift.date.isoformat(),
        "employee": r.name,
        "start": r.AdjustedShift.start_time,
        "end": r.AdjustedShift.end_time,
        "note": r.AdjustedShift.note,
        "source": r.AdjustedShift.source,
    } for r in rows]
    return jsonify(data)

@bp.get("/violations")
def violations():
    start = datetime.fromisoformat(request.args.get("from")).date()
    end = datetime.fromisoformat(request.args.get("to")).date()
    v = RuleViolation.query.filter(RuleViolation.date.between(start,end)).order_by(RuleViolation.date).all()
    data = [{"date":x.date.isoformat(),"code":x.code,"details":x.details,"severity":x.severity} for x in v]
    return jsonify(data)
EOF

cat > static/index.html << 'EOF'
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <title>Planning Vendeuses</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body{font-family:system-ui,Arial;margin:0}
    header{display:flex;gap:8px;align-items:center;padding:12px;border-bottom:1px solid #eee;flex-wrap:wrap}
    main{padding:12px}
    table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #eee;padding:6px;font-size:14px}
    .row{display:flex;gap:12px;flex-wrap:wrap}
    .card{border:1px solid #eee;border-radius:8px;padding:12px;min-width:320px;flex:1}
  </style>
</head>
<body>
  <header>
    <h3 style="margin:0;">Planning Vendeuses</h3>
    <label>Lundi (YYYY-MM-DD): <input id="monday" type="date"/></label>
    <label><input id="sun" type="checkbox"/> Dimanche ouvert</label>
    <button id="gen">Générer semaine</button>
    <a href="/health" target="_blank">health</a>
  </header>
  <main class="row">
    <section class="card">
      <h4>Planning ajusté</h4>
      <table id="tbl"><thead><tr>
        <th>Date</th><th>Vendeuse</th><th>Début</th><th>Fin</th><th>Note</th></tr></thead><tbody></tbody></table>
    </section>
    <section class="card">
      <h4>Alertes</h4>
      <table id="viol"><thead><tr>
        <th>Date</th><th>Code</th><th>Détails</th></tr></thead><tbody></tbody></table>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
EOF

cat > static/app.js << 'EOF'
async function genWeek(){
  const monday = document.getElementById("monday").value;
  const sun = document.getElementById("sun").checked ? "1":"0";
  if(!monday){ alert("Choisir le lundi (YYYY-MM-DD)"); return; }
  await fetch(`/api/generate-week?monday=${monday}&sunday_open=${sun}`, {method:"POST"});
  await loadWeek();
}
async function loadWeek(){
  const monday = document.getElementById("monday").value;
  if(!monday) return;
  const start = monday;
  const end = new Date(monday); end.setDate(end.getDate()+6);
  const endStr = end.toISOString().slice(0,10);

  const res = await fetch(`/api/adjusted?from=${start}&to=${endStr}`);
  const data = await res.json();
  const tb = document.querySelector("#tbl tbody");
  tb.innerHTML = "";
  data.forEach(r=>{
    const tr=document.createElement("tr");
    tr.innerHTML = `<td>${r.date}</td><td>${r.employee}</td><td>${r.start}</td><td>${r.end}</td><td>${r.note||""}</td>`;
    tb.appendChild(tr);
  });

  const rv = await fetch(`/api/violations?from=${start}&to=${endStr}`);
  const v = await rv.json();
  const vb = document.querySelector("#viol tbody");
  vb.innerHTML = "";
  v.forEach(r=>{
    const tr=document.createElement("tr");
    tr.innerHTML = `<td>${r.date}</td><td>${r.code}</td><td>${r.details||""}</td>`;
    vb.appendChild(tr);
  });
}
document.getElementById("gen").addEventListener("click", genWeek);
document.getElementById("monday").addEventListener("change", loadWeek);
EOF

cat > seed_base.py << 'EOF'
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
        db.session.add(OpeningHours(weekday=wd, open_time="09:30", close_time="19:30", sunday_open=False))
    db.session.add(OpeningHours(weekday=6, open_time="09:30", close_time="19:30", sunday_open=False))
    db.session.commit()

    # Alexandra
    add_shift("Alexandra",1,"09:30","14:00"); add_shift("Alexandra",1,"15:00","19:45")
    add_shift("Alexandra",2,"09:30","13:30"); add_shift("Alexandra",2,"14:30","19:30")
    add_shift("Alexandra",3,"09:30","13:30")
    add_shift("Alexandra",4,"09:30","14:00"); add_shift("Alexandra",4,"15:00","19:30")
    add_shift("Alexandra",5,"15:15","19:00")

    # Aurélia
    add_shift("Aurélia",0,"09:30","13:30"); add_shift("Aurélia",0,"14:30","19:15")
    add_shift("Aurélia",1,"09:30","13:00"); add_shift("Aurélia",1,"14:00","19:00")
    add_shift("Aurélia",2,"09:30","13:15")
    add_shift("Aurélia",3,"13:30","19:30")
    add_shift("Aurélia",5,"10:30","13:00"); add_shift("Aurélia",5,"14:00","19:30")

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
EOF

cat > wsgi.py << 'EOF'
from backend import create_app
app = create_app()
EOF

echo "✅ Fichiers créés. Étapes suivantes :"
echo "python3 -m venv .venv && source .venv/bin/activate"
echo "pip install -r requirements.txt"
echo "flask db init && flask db migrate -m 'initial schema' && flask db upgrade"
echo "python seed_base.py"
echo "flask run   # http://127.0.0.1:5000"
