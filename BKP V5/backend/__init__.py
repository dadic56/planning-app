from flask import Flask, jsonify, request, send_from_directory
from flask_migrate import Migrate
from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import os

from .models import db, Employee, BaseShift, AdjustedShift, Absence, RuleViolation, PlanningSnapshot, SpecialOpening, SpecialOpeningShift
from .services import (
    compute_base_week_for,
    generate_adjusted_week,
    list_adjusted_between,
    recommended_week_minutes,
    max_week_minutes,
)

def _safe_monday(req):
    """Récupère un lundi ISO depuis la query, ou calcule le lundi courant."""
    val = req.args.get("monday")
    if val:
        return date.fromisoformat(val)
    # lundi courant
    now = datetime.now().date()
    wd = (now.weekday())  # 0=lundi
    return now - timedelta(days=wd)

def create_app():
    static_dir = os.path.join(os.path.dirname(__file__), "../static")
    app = Flask(__name__, static_folder=static_dir, static_url_path="")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///planning.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    Migrate(app, db)

    # ---------------- Pages ----------------
    @app.get("/")
    def home():
        return app.send_static_file("index.html")

    @app.get("/base")
    def base_editor_page():
        return send_from_directory(app.static_folder, "base.html")

    @app.get("/special")
    def special_editor_page():
        return send_from_directory(app.static_folder, "special.html")

    @app.get("/snapshots")
    def snapshots_page():
        return send_from_directory(app.static_folder, "snapshots.html")

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    def _employee_to_json(emp: Employee):
        return {
            "id": emp.id,
            "name": emp.name,
            "contract_type": emp.contract_type,
            "max_week_hours": emp.max_week_hours,
            "special_rules": emp.special_rules or "",
            "therapeutic_part_time": bool(getattr(emp, "therapeutic_part_time", False)),
            "therapeutic_percent": getattr(emp, "therapeutic_percent", None),
            "allow_overtime": bool(getattr(emp, "allow_overtime", True)),
            "sunday_available": bool(getattr(emp, "sunday_available", False)),
            "base_week_hours": recommended_week_minutes(emp) / 60,
            "max_week_hours_with_sup": max_week_minutes(emp) / 60,
        }

    def _snapshot_to_json(snap: PlanningSnapshot):
        payload = snap.data or {}
        adjusted = payload.get("adjusted") or []
        violations = payload.get("violations") or []
        absences = payload.get("absences") or []
        label = (snap.label or f"Semaine du {snap.monday.strftime('%d/%m/%Y')}").strip()
        try:
            week_no = snap.monday.isocalendar()[1]
        except Exception:
            week_no = None
        reasons = []
        for abs_info in absences:
            reason = (abs_info.get("reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        return {
            "id": snap.id,
            "label": label,
            "monday": snap.monday.isoformat(),
            "sunday": snap.sunday.isoformat(),
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "status": snap.status or "draft",
            "week_number": week_no,
            "sunday_open": bool(payload.get("sunday_open")),
            "constraints": reasons,
            "counts": {
                "adjusted": len(adjusted),
                "violations": len(violations),
                "absences": len(absences),
            },
        }

    def _special_opening_to_json(opening: SpecialOpening, include_shifts: bool = True):
        data = {
            "id": opening.id,
            "date": opening.date.isoformat(),
            "label": opening.label or "",
            "open_time": opening.open_time,
            "close_time": opening.close_time,
            "is_closed": bool(opening.is_closed),
            "sunday_mode": bool(opening.sunday_mode),
            "notes": opening.notes or "",
            "created_at": opening.created_at.isoformat() if opening.created_at else None,
        }
        if include_shifts:
            emp_map = {e.id: e.name for e in Employee.query.all()}
            data["shifts"] = [{
                "id": sh.id,
                "employee_id": sh.employee_id,
                "employee": emp_map.get(sh.employee_id, f"#{sh.employee_id}"),
                "start_time": sh.start_time,
                "end_time": sh.end_time,
                "lunch_start": sh.lunch_start,
                "lunch_end": sh.lunch_end,
            } for sh in opening.shifts]
        return data

    def _parse_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _parse_employee_payload(payload, existing: Optional[Employee] = None):
        if not isinstance(payload, dict):
            raise ValueError("Requête invalide : JSON attendu.")
        name = (payload.get("name") or (existing.name if existing else "")).strip()
        if not name:
            raise ValueError("Le prénom est obligatoire.")

        contract_type = payload.get("contract_type")
        if contract_type is None and existing is not None:
            contract_type = existing.contract_type
        contract_type = (contract_type or "35h").strip() or "35h"

        max_hours_input = payload.get("max_week_hours", None)
        if max_hours_input is None and existing is not None:
            max_hours_input = existing.max_week_hours
        if max_hours_input is None:
            import re
            match = re.search(r"\d+(?:[\.,]\d+)?", contract_type)
            max_hours = float(match.group(0).replace(',', '.')) if match else 35.0
        else:
            try:
                max_hours = float(str(max_hours_input).replace(',', '.'))
            except (TypeError, ValueError):
                raise ValueError("Heures hebdomadaires invalides.")
        if max_hours <= 0:
            raise ValueError("Les heures hebdomadaires doivent être positives.")

        therapeutic_flag = _parse_bool(payload.get("therapeutic_part_time"))
        ther_percent = payload.get("therapeutic_percent", None)
        percent_value = None
        if therapeutic_flag:
            if ther_percent in (None, "", "null"):
                raise ValueError("Préciser le pourcentage de mi-temps thérapeutique.")
            try:
                percent_value = float(ther_percent)
            except (TypeError, ValueError):
                raise ValueError("Pourcentage de mi-temps invalide.")
            if percent_value <= 0 or percent_value > 100:
                raise ValueError("Le pourcentage doit être compris entre 1 et 100.")
        special_rules = payload.get("special_rules")
        if special_rules is None and existing is not None:
            special_rules = existing.special_rules

        return {
            "name": name,
            "contract_type": contract_type,
            "max_week_hours": max_hours,
            "special_rules": (special_rules or "").strip(),
            "therapeutic_part_time": therapeutic_flag,
            "therapeutic_percent": percent_value if therapeutic_flag else None,
            "allow_overtime": _parse_bool(payload.get("allow_overtime", existing.allow_overtime if existing else True)),
            "sunday_available": _parse_bool(payload.get("sunday_available", existing.sunday_available if existing else False)),
        }

    # ---------------- API employés ----------------
    @app.get("/api/employees")
    def api_employees():
        try:
            emps = Employee.query.order_by(Employee.name).all()
            return jsonify([_employee_to_json(e) for e in emps])
        except Exception as e:
            return jsonify({"ok": False, "where": "employees", "error": type(e).__name__, "detail": str(e)}), 500

    @app.post("/api/employees")
    def api_create_employee():
        try:
            payload = request.get_json(force=True)
            data = _parse_employee_payload(payload)

            existing = Employee.query.filter(Employee.name == data["name"]).first()
            if existing:
                return jsonify({"ok": False, "error": "duplicate", "detail": "Ce prénom existe déjà."}), 409

            emp = Employee(**data)
            db.session.add(emp)
            db.session.commit()
            return jsonify({"ok": True, "employee": _employee_to_json(emp)}), 201
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.put("/api/employees/<int:eid>")
    def api_update_employee(eid):
        emp = Employee.query.get_or_404(eid)
        try:
            payload = request.get_json(force=True)
            data = _parse_employee_payload(payload, existing=emp)

            duplicate = Employee.query.filter(Employee.name == data["name"], Employee.id != eid).first()
            if duplicate:
                return jsonify({"ok": False, "error": "duplicate", "detail": "Ce prénom existe déjà."}), 409

            for key, value in data.items():
                setattr(emp, key, value)
            db.session.commit()
            return jsonify({"ok": True, "employee": _employee_to_json(emp)})
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": type(exc).__name__, "detail": str(exc)}), 500

    # ---------------- API planning base & ajusté ----------------
    @app.get("/api/base-week")
    def api_base_week():
        try:
            monday = _safe_monday(request)
            items = compute_base_week_for(monday)
            return jsonify(items)
        except Exception as e:
            return jsonify({"ok": False, "where": "base-week", "error": type(e).__name__, "detail": str(e)}), 500

    @app.post("/api/generate-week")
    def api_generate_week():
        try:
            monday = _safe_monday(request)
            sunday_open = request.args.get("sunday_open") == "1"
            generate_adjusted_week(monday, sunday_open=sunday_open)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "where": "generate-week", "error": type(e).__name__, "detail": str(e)}), 500

    @app.get("/api/adjusted")
    def api_adjusted():
        try:
            d1 = date.fromisoformat(request.args["from"])
            d2 = date.fromisoformat(request.args["to"])
            data = list_adjusted_between(d1, d2)
            return jsonify(data)
        except Exception as e:
            return jsonify({"ok": False, "where": "adjusted", "error": type(e).__name__, "detail": str(e)}), 500

    @app.get("/api/violations")
    def api_violations():
        try:
            d1 = date.fromisoformat(request.args["from"])
            d2 = date.fromisoformat(request.args["to"])
            rows = (RuleViolation.query
                    .filter(RuleViolation.date.between(d1, d2))
                    .order_by(RuleViolation.date).all())
            data = [{
                "date": r.date.isoformat(),
                "code": r.code,
                "details": r.details,
                "severity": r.severity,
            } for r in rows]
            return jsonify(data)
        except Exception as e:
            return jsonify({"ok": False, "where": "violations", "error": type(e).__name__, "detail": str(e)}), 500

    # ---------------- API absences ----------------
    @app.post("/api/absences")
    def api_absences():
        try:
            payload = request.get_json(force=True)
            a = Absence(
                employee_id=int(payload["employee_id"]),
                start_date=date.fromisoformat(payload["start_date"]),
                end_date=date.fromisoformat(payload["end_date"]),
                reason=payload.get("reason"),
            )
            db.session.add(a)
            db.session.commit()
            return jsonify({"ok": True, "id": a.id}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "absences", "error": type(e).__name__, "detail": str(e)}), 500

    @app.get("/api/absences")
    def api_list_absences():
        try:
            q = (Absence.query
                 .join(Employee, Employee.id == Absence.employee_id))
            start_arg = request.args.get("from")
            end_arg = request.args.get("to")
            if start_arg:
                d1 = date.fromisoformat(start_arg)
                q = q.filter(Absence.end_date >= d1)
            if end_arg:
                d2 = date.fromisoformat(end_arg)
                q = q.filter(Absence.start_date <= d2)
            rows = (q
                    .add_columns(Employee.name)
                    .order_by(Absence.start_date, Employee.name)
                    .all())
            data = [{
                "id": abs_rec.id,
                "employee_id": abs_rec.employee_id,
                "employee": name,
                "start_date": abs_rec.start_date.isoformat(),
                "end_date": abs_rec.end_date.isoformat(),
                "reason": abs_rec.reason or "",
            } for abs_rec, name in rows]
            return jsonify(data)
        except Exception as e:
            return jsonify({"ok": False, "where": "list-absences", "error": type(e).__name__, "detail": str(e)}), 500

    @app.delete("/api/absences/<int:aid>")
    def api_delete_absence(aid):
        try:
            abs_rec = Absence.query.get_or_404(aid)
            db.session.delete(abs_rec)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "delete-absence", "error": type(e).__name__, "detail": str(e)}), 500

    # ---------------- Snapshots ----------------
    @app.get("/api/snapshots")
    def api_list_snapshots():
        try:
            snaps = (PlanningSnapshot.query
                     .order_by(PlanningSnapshot.created_at.desc())
                     .all())
            return jsonify([_snapshot_to_json(s) for s in snaps])
        except Exception as e:
            return jsonify({"ok": False, "where": "list-snapshots", "error": type(e).__name__, "detail": str(e)}), 500

    @app.post("/api/snapshots")
    def api_create_snapshot():
        try:
            payload = request.get_json(force=True) or {}
            monday_iso = payload.get("monday")
            if not monday_iso:
                return jsonify({"ok": False, "error": "validation", "detail": "Préciser le lundi de référence."}), 400
            monday = date.fromisoformat(monday_iso)
            sunday = monday + timedelta(days=6)

            adjusted = list_adjusted_between(monday, sunday)
            if not adjusted:
                return jsonify({"ok": False, "error": "empty", "detail": "Aucun planning ajusté pour cette semaine."}), 400

            violations_rows = (RuleViolation.query
                               .filter(RuleViolation.date >= monday, RuleViolation.date <= sunday)
                               .order_by(RuleViolation.date)
                               .all())
            violations = [{
                "date": r.date.isoformat(),
                "code": r.code,
                "details": r.details,
                "severity": r.severity,
            } for r in violations_rows]

            abs_q = (Absence.query
                     .join(Employee, Employee.id == Absence.employee_id)
                     .filter(Absence.end_date >= monday)
                     .filter(Absence.start_date <= sunday)
                     .order_by(Absence.start_date, Employee.name))
            abs_rows = abs_q.add_columns(Employee.name).all()
            absences = [{
                "id": abs_rec.id,
                "employee_id": abs_rec.employee_id,
                "employee": name,
                "start_date": abs_rec.start_date.isoformat(),
                "end_date": abs_rec.end_date.isoformat(),
                "reason": abs_rec.reason or "",
            } for abs_rec, name in abs_rows]

            specials_payload = [_special_opening_to_json(op) for op in SpecialOpening.query
                                 .filter(SpecialOpening.date >= monday, SpecialOpening.date <= sunday)
                                 .order_by(SpecialOpening.date)
                                 .all()]

            label = (payload.get("label") or "").strip() or None
            status = (payload.get("status") or "draft").strip().lower()
            if status in {"previsionnel"}:
                status = "prévisionnel"
            if status in {"valide", "validé"}:
                status = "valide"
            if status not in {"draft", "prévisionnel", "valide"}:
                status = "draft"
            sunday_open = bool(payload.get("sunday_open"))
            snapshot_payload = {
                "monday": monday.isoformat(),
                "sunday": sunday.isoformat(),
                "label": label,
                "captured_at": datetime.utcnow().isoformat(),
                "sunday_open": sunday_open,
                "base": compute_base_week_for(monday),
                "adjusted": adjusted,
                "violations": violations,
                "absences": absences,
                "special_openings": specials_payload,
            }

            snap = PlanningSnapshot(
                monday=monday,
                sunday=sunday,
                label=label,
                status=status,
                data=snapshot_payload,
            )
            db.session.add(snap)
            db.session.commit()
            return jsonify({"ok": True, "snapshot": _snapshot_to_json(snap)}), 201
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "create-snapshot", "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.get("/api/snapshots/<int:snap_id>")
    def api_get_snapshot(snap_id):
        snap = PlanningSnapshot.query.get_or_404(snap_id)
        data = _snapshot_to_json(snap)
        data["data"] = snap.data
        return jsonify(data)

    @app.put("/api/snapshots/<int:snap_id>")
    def api_update_snapshot(snap_id):
        snap = PlanningSnapshot.query.get_or_404(snap_id)
        try:
            payload = request.get_json(force=True) or {}
            label = payload.get("label")
            status = payload.get("status")
            updated = False
            if label is not None:
                snap.label = label.strip() or None
                updated = True
            if status is not None:
                normalized = status.strip().lower()
                if normalized in {"previsionnel"}:
                    normalized = "prévisionnel"
                if normalized in {"valide", "validé"}:
                    normalized = "valide"
                if normalized not in {"draft", "prévisionnel", "valide"}:
                    raise ValueError("Statut invalide.")
                snap.status = normalized
                updated = True
            if updated:
                db.session.commit()
            return jsonify({"ok": True, "snapshot": _snapshot_to_json(snap)})
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "update-snapshot", "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.delete("/api/snapshots/<int:snap_id>")
    def api_delete_snapshot(snap_id):
        try:
            snap = PlanningSnapshot.query.get_or_404(snap_id)
            db.session.delete(snap)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "delete-snapshot", "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.post("/api/snapshots/<int:snap_id>/restore")
    def api_restore_snapshot(snap_id):
        snap = PlanningSnapshot.query.get_or_404(snap_id)
        try:
            payload = snap.data or {}
            monday = snap.monday
            sunday = snap.sunday

            AdjustedShift.query.filter(AdjustedShift.date >= monday, AdjustedShift.date <= sunday).delete(synchronize_session=False)
            RuleViolation.query.filter(RuleViolation.date >= monday, RuleViolation.date <= sunday).delete(synchronize_session=False)

            adjusted = payload.get("adjusted") or []
            for item in adjusted:
                shift_date = date.fromisoformat(item["date"])
                adj = AdjustedShift(
                    date=shift_date,
                    employee_id=item["employee_id"],
                    start_time=item["start"],
                    end_time=item["end"],
                    lunch_start=item.get("lunch_start"),
                    lunch_end=item.get("lunch_end"),
                    source=item.get("source") or "adjust",
                    note=item.get("note"),
                )
                db.session.add(adj)

            violations = payload.get("violations") or []
            for v in violations:
                rv = RuleViolation(
                    date=date.fromisoformat(v["date"]),
                    employee_id=v.get("employee_id"),
                    code=v.get("code"),
                    details=v.get("details"),
                    severity=v.get("severity") or "warn",
                )
                db.session.add(rv)

            db.session.commit()
            return jsonify({"ok": True, "restored": _snapshot_to_json(snap)})
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "restore-snapshot", "error": type(exc).__name__, "detail": str(exc)}), 500

    # ---------------- Special openings ----------------

    def _parse_time(value: Optional[str]) -> Optional[str]:
        if value in (None, "", "null"):
            return None
        value = value.strip()
        if len(value) != 5 or value[2] != ":":
            raise ValueError("Format horaire invalide (HH:MM).")
        hh, mm = value.split(":", 1)
        if not (hh.isdigit() and mm.isdigit()):
            raise ValueError("Format horaire invalide (HH:MM).")
        h = int(hh); m = int(mm)
        if h < 0 or h > 23 or m < 0 or m > 59:
            raise ValueError("Horaire hors plage valide.")
        return f"{h:02d}:{m:02d}"

    def _parse_special_opening_payload(payload, existing: Optional[SpecialOpening] = None):
        if not isinstance(payload, dict):
            raise ValueError("Requête invalide : JSON attendu.")
        date_value = payload.get("date")
        if not date_value and existing is not None:
            date_value = existing.date.isoformat()
        if not date_value:
            raise ValueError("Préciser la date de l'ouverture spéciale.")
        try:
            open_date = date.fromisoformat(date_value)
        except ValueError:
            raise ValueError("Date invalide.")

        is_closed = _parse_bool(payload.get("is_closed", existing.is_closed if existing else False))
        sunday_mode = _parse_bool(payload.get("sunday_mode", existing.sunday_mode if existing else False))
        open_time = _parse_time(payload.get("open_time") if not is_closed else None)
        close_time = _parse_time(payload.get("close_time") if not is_closed else None)

        if not is_closed:
            if not open_time or not close_time:
                raise ValueError("Indiquer les horaires d'ouverture et de fermeture.")
            if open_time >= close_time:
                raise ValueError("L'heure d'ouverture doit précéder la fermeture.")

        label = (payload.get("label") or (existing.label if existing else "")).strip() or None
        notes = (payload.get("notes") or (existing.notes if existing else "")).strip() or None

        shifts_payload = payload.get("shifts") or []
        if not isinstance(shifts_payload, list):
            raise ValueError("Le champ 'shifts' doit être une liste.")

        employee_ids = {e.id for e in Employee.query.all()}
        sunday_ok = {e.id for e in Employee.query.filter(Employee.sunday_available == True).all()}

        parsed_shifts = []
        for item in shifts_payload:
            if not isinstance(item, dict):
                raise ValueError("Détail de créneau invalide.")
            emp_id = int(item.get("employee_id"))
            if emp_id not in employee_ids:
                raise ValueError("Vendeuse inconnue pour un créneau spécial.")
            if sunday_mode and emp_id not in sunday_ok:
                raise ValueError("Toutes les vendeuses affectées au dimanche doivent l'avoir accepté dans leur profil.")
            start = _parse_time(item.get("start_time"))
            end = _parse_time(item.get("end_time"))
            if not start or not end:
                raise ValueError("Chaque créneau doit avoir une heure de début et de fin.")
            if start >= end:
                raise ValueError("Le début doit précéder la fin pour chaque créneau.")
            lunch_start = _parse_time(item.get("lunch_start"))
            lunch_end = _parse_time(item.get("lunch_end"))
            parsed_shifts.append({
                "employee_id": emp_id,
                "start_time": start,
                "end_time": end,
                "lunch_start": lunch_start,
                "lunch_end": lunch_end,
            })

        if sunday_mode and not is_closed:
            unique_emps = {s["employee_id"] for s in parsed_shifts}
            if len(unique_emps) < 3:
                raise ValueError("Dimanche ouvert : sélectionner au moins 3 vendeuses disponibles.")
            for emp_id in unique_emps:
                emp = Employee.query.get(emp_id)
                if not emp or not emp.sunday_available:
                    raise ValueError("Toutes les vendeuses affectées au dimanche doivent l'accepter dans leur fiche.")
        if not is_closed and not parsed_shifts:
            raise ValueError("Ajouter au moins un créneau lorsque la journée est ouverte.")

        return {
            "date": open_date,
            "label": label,
            "open_time": open_time,
            "close_time": close_time,
            "is_closed": is_closed,
            "sunday_mode": sunday_mode,
            "notes": notes,
            "shifts": parsed_shifts,
        }

    @app.get("/api/special-openings")
    def api_list_special_openings():
        try:
            q = SpecialOpening.query
            start_arg = request.args.get("from")
            end_arg = request.args.get("to")
            if start_arg:
                q = q.filter(SpecialOpening.date >= date.fromisoformat(start_arg))
            if end_arg:
                q = q.filter(SpecialOpening.date <= date.fromisoformat(end_arg))
            openings = q.order_by(SpecialOpening.date).all()
            return jsonify([_special_opening_to_json(op, include_shifts=True) for op in openings])
        except Exception as exc:
            return jsonify({"ok": False, "where": "list-special-openings", "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.post("/api/special-openings")
    def api_create_special_opening():
        try:
            payload = request.get_json(force=True)
            data = _parse_special_opening_payload(payload)

            existing = SpecialOpening.query.filter(SpecialOpening.date == data["date"]).first()
            if existing:
                return jsonify({"ok": False, "error": "duplicate", "detail": "Une ouverture spéciale existe déjà pour cette date."}), 409

            opening = SpecialOpening(
                date=data["date"],
                label=data["label"],
                open_time=data["open_time"],
                close_time=data["close_time"],
                is_closed=data["is_closed"],
                sunday_mode=data["sunday_mode"],
                notes=data["notes"],
            )
            db.session.add(opening)
            db.session.flush()

            for sh in data["shifts"]:
                db.session.add(SpecialOpeningShift(
                    opening_id=opening.id,
                    employee_id=sh["employee_id"],
                    start_time=sh["start_time"],
                    end_time=sh["end_time"],
                    lunch_start=sh["lunch_start"],
                    lunch_end=sh["lunch_end"],
                ))

            db.session.commit()
            return jsonify({"ok": True, "opening": _special_opening_to_json(opening)})
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "create-special-opening", "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.get("/api/special-openings/<int:oid>")
    def api_get_special_opening(oid):
        opening = SpecialOpening.query.get_or_404(oid)
        return jsonify(_special_opening_to_json(opening))

    @app.put("/api/special-openings/<int:oid>")
    def api_update_special_opening(oid):
        opening = SpecialOpening.query.get_or_404(oid)
        try:
            payload = request.get_json(force=True)
            data = _parse_special_opening_payload(payload, existing=opening)

            if data["date"] != opening.date:
                other = SpecialOpening.query.filter(SpecialOpening.date == data["date"], SpecialOpening.id != oid).first()
                if other:
                    raise ValueError("Une ouverture spéciale existe déjà pour cette date.")
                opening.date = data["date"]

            opening.label = data["label"]
            opening.open_time = data["open_time"]
            opening.close_time = data["close_time"]
            opening.is_closed = data["is_closed"]
            opening.sunday_mode = data["sunday_mode"]
            opening.notes = data["notes"]

            SpecialOpeningShift.query.filter_by(opening_id=opening.id).delete()
            for sh in data["shifts"]:
                db.session.add(SpecialOpeningShift(
                    opening_id=opening.id,
                    employee_id=sh["employee_id"],
                    start_time=sh["start_time"],
                    end_time=sh["end_time"],
                    lunch_start=sh["lunch_start"],
                    lunch_end=sh["lunch_end"],
                ))

            db.session.commit()
            return jsonify({"ok": True, "opening": _special_opening_to_json(opening)})
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "update-special-opening", "error": type(exc).__name__, "detail": str(exc)}), 500

    @app.delete("/api/special-openings/<int:oid>")
    def api_delete_special_opening(oid):
        try:
            opening = SpecialOpening.query.get_or_404(oid)
            db.session.delete(opening)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as exc:
            db.session.rollback()
            return jsonify({"ok": False, "where": "delete-special-opening", "error": type(exc).__name__, "detail": str(exc)}), 500

    # ---------------- CRUD BaseShift ----------------
    @app.get("/api/base-shifts")
    def api_list_base_shifts():
        try:
            q = BaseShift.query
            weekday = request.args.get("weekday")
            if weekday is not None:
                q = q.filter_by(weekday=int(weekday))
            items = q.order_by(BaseShift.weekday, BaseShift.employee_id, BaseShift.start_time).all()
            out = []
            for b in items:
                emp = Employee.query.get(b.employee_id)
                out.append({
                    "id": b.id,
                    "employee_id": b.employee_id,
                    "employee": emp.name if emp else f"#{b.employee_id}",
                    "weekday": b.weekday,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                    "lunch_start": b.lunch_start,
                    "lunch_end": b.lunch_end,
                    "note": getattr(b, "note", None),
                })
            return jsonify(out)
        except Exception as e:
            return jsonify({"ok": False, "where": "base-shifts", "error": type(e).__name__, "detail": str(e)}), 500

    @app.post("/api/base-shifts")
    def api_create_base_shift():
        try:
            data = request.get_json(force=True)
            b = BaseShift(
                employee_id=int(data["employee_id"]),
                weekday=int(data["weekday"]),
                start_time=data["start_time"],
                end_time=data["end_time"],
                lunch_start=data.get("lunch_start"),
                lunch_end=data.get("lunch_end"),
                note=data.get("note"),
            )
            db.session.add(b)
            db.session.commit()
            return jsonify({"ok": True, "id": b.id}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "create-base-shift", "error": type(e).__name__, "detail": str(e)}), 500

    @app.put("/api/base-shifts/<int:bid>")
    def api_update_base_shift(bid):
        try:
            b = BaseShift.query.get_or_404(bid)
            data = request.get_json(force=True)
            if "employee_id" in data: b.employee_id = int(data["employee_id"])
            if "weekday" in data: b.weekday = int(data["weekday"])
            if "start_time" in data: b.start_time = data["start_time"]
            if "end_time" in data: b.end_time = data["end_time"]
            b.lunch_start = data.get("lunch_start")
            b.lunch_end = data.get("lunch_end")
            b.note = data.get("note")
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "update-base-shift", "error": type(e).__name__, "detail": str(e)}), 500

    @app.delete("/api/base-shifts/<int:bid>")
    def api_delete_base_shift(bid):
        try:
            b = BaseShift.query.get_or_404(bid)
            db.session.delete(b)
            db.session.commit()
            return jsonify({"ok": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "delete-base-shift", "error": type(e).__name__, "detail": str(e)}), 500

    # ---------------- DEV : Seed léger (heures texte) ----------------
    @app.get("/api/dev/seed-base")
    def dev_seed_base():
        try:
            with app.app_context():
                db.create_all()

                # Ensure 'note' column exists on base_shift (safe ALTER TABLE for dev)
                try:
                    db.session.execute(text("SELECT note FROM base_shift LIMIT 1"))
                except Exception:
                    try:
                        db.session.execute(text("ALTER TABLE base_shift ADD COLUMN note VARCHAR(200)"))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

            if Employee.query.count() == 0:
                emps = [
                    Employee(name="Alexandra", contract_type="35h", max_week_hours=35),
                    Employee(name="Aurélia",   contract_type="35h", max_week_hours=35),
                    Employee(name="Clara",     contract_type="24h", max_week_hours=24),
                    Employee(name="Nathalie",  contract_type="24h", max_week_hours=24),
                    Employee(name="Noémie",    contract_type="35h", max_week_hours=35),
                    Employee(name="Stéphanie", contract_type="35h", max_week_hours=35),
                ]
                db.session.add_all(emps)
                db.session.commit()

            name_to_id = {e.name: e.id for e in Employee.query.all()}

            def add(name, wd, s, e, ls=None, le=None):
                db.session.add(BaseShift(
                    employee_id=name_to_id[name],
                    weekday=wd,
                    start_time=s,
                    end_time=e,
                    lunch_start=ls,
                    lunch_end=le,
                ))

            # Lundi (échantillon)
            add("Alexandra", 0, "09:30", "14:00"); add("Alexandra", 0, "15:00", "19:45")
            add("Aurélia",   0, "09:30", "13:30"); add("Aurélia",   0, "14:30", "19:15")
            add("Clara",     0, "09:30", "13:15")
            add("Noémie",    0, "09:30", "12:15"); add("Noémie",    0, "13:15", "19:15")
            add("Stéphanie", 0, "14:00", "19:00")
            # Mercredi (Nathalie)
            add("Nathalie",  2, "10:00", "13:00")

            db.session.commit()
            return jsonify({
                "ok": True,
                "employees": Employee.query.count(),
                "shifts": BaseShift.query.count()
            })
        except SQLAlchemyError as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "seed", "error": type(e).__name__, "detail": str(e)}), 500
        except Exception as e:
            return jsonify({"ok": False, "where": "seed", "error": type(e).__name__, "detail": str(e)}), 500

    return app
