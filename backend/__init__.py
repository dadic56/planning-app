from flask import Flask, jsonify, request, render_template
from flask_migrate import Migrate
from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
import os

from .models import (
    db,
    Employee,
    BaseShift,
    AdjustedShift,
    Absence,
    RuleViolation,
    PlanningSnapshot,
    SpecialOpening,
)
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
    from datetime import datetime, timedelta
    now = datetime.now().date()
    wd = (now.weekday())  # 0=lundi
    return now - timedelta(days=wd)

def create_app():
    base_dir = os.path.dirname(__file__)
    static_dir = os.path.join(base_dir, "../static")
    template_dir = os.path.join(base_dir, "../templates")
    app = Flask(__name__, static_folder=static_dir, static_url_path="", template_folder=template_dir)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///planning.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    manifest_path = os.path.join(static_dir, "dist", "asset-manifest.json")
    asset_manifest = {}
    if os.path.exists(manifest_path):
        try:
            import json

            with open(manifest_path, "r", encoding="utf-8") as fh:
                asset_manifest = json.load(fh)
        except Exception:
            asset_manifest = {}
    app.config["ASSET_MANIFEST"] = asset_manifest

    @app.context_processor
    def asset_context():
        manifest = app.config.get("ASSET_MANIFEST", {})

        def asset_url(filename: str) -> str:
            return "/" + manifest.get(filename, filename)

        return {"asset_url": asset_url}

    db.init_app(app)
    Migrate(app, db)

    # ---------------- Pages ----------------
    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/base")
    def base_editor_page():
        return render_template("base.html")

    @app.get("/snapshots")
    def snapshots_page():
        return render_template("snapshots.html")

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
        weeks_payload = payload.get("weeks") or []
        if weeks_payload:
            adjusted_count = sum(len(w.get("adjusted") or []) for w in weeks_payload)
            violations_count = sum(len(w.get("violations") or []) for w in weeks_payload)
            absences_payload = []
            for w in weeks_payload:
                absences_payload.extend(w.get("absences") or [])
        else:
            adjusted_count = len(payload.get("adjusted") or [])
            violations_count = len(payload.get("violations") or [])
            absences_payload = payload.get("absences") or []
        label = (snap.label or f"Semaine du {snap.monday.strftime('%d/%m/%Y')}").strip()
        try:
            week_no = snap.monday.isocalendar()[1]
        except Exception:
            week_no = None
        reasons = []
        for abs_info in absences_payload:
            reason = (abs_info.get("reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        duration_weeks = int(payload.get("duration_weeks", max(1, len(weeks_payload) or 1)))
        return {
            "id": snap.id,
            "label": label,
            "monday": snap.monday.isoformat(),
            "sunday": snap.sunday.isoformat(),
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "status": snap.status or "draft",
            "week_number": week_no,
            "sunday_open": bool(payload.get("sunday_open")),
            "duration_weeks": duration_weeks,
            "constraints": reasons,
            "counts": {
                "adjusted": adjusted_count,
                "violations": violations_count,
                "absences": len(absences_payload),
            },
        }

    def _special_opening_to_json(opening: SpecialOpening):
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

    def _normalize_time(value, field_name):
        if value in (None, "", "null"):
            raise ValueError(f"Champ {field_name} obligatoire.")
        value = str(value).strip()
        if len(value) != 5 or value[2] != ":":
            raise ValueError(f"Format horaire invalide pour {field_name} (attendu HH:MM).")
        hh, mm = value.split(":", 1)
        if not (hh.isdigit() and mm.isdigit()):
            raise ValueError(f"Format horaire invalide pour {field_name} (attendu HH:MM).")
        h, m = int(hh), int(mm)
        if h < 0 or h > 23 or m < 0 or m > 59:
            raise ValueError(f"Horaire hors plage pour {field_name}.")
        return f"{h:02d}:{m:02d}", h * 60 + m

    def _normalize_optional_time(value, field_name):
        if value in (None, "", "null"):
            return None, None
        norm, mins = _normalize_time(value, field_name)
        return norm, mins

    def _normalize_base_shift_payload(payload, existing: Optional[BaseShift] = None):
        if not isinstance(payload, dict):
            raise ValueError("Requête invalide : JSON attendu.")

        if existing is None:
            required_fields = {"employee_id", "weekday", "start_time", "end_time"}
            missing = [f for f in required_fields if payload.get(f) in (None, "", "null")]
            if missing:
                raise ValueError(f"Champs manquants : {', '.join(missing)}")

        employee_id = payload.get("employee_id") if payload.get("employee_id") is not None else (existing.employee_id if existing else None)
        weekday = payload.get("weekday") if payload.get("weekday") is not None else (existing.weekday if existing else None)
        start_val = payload.get("start_time") if payload.get("start_time") is not None else (existing.start_time if existing else None)
        end_val = payload.get("end_time") if payload.get("end_time") is not None else (existing.end_time if existing else None)
        lunch_start_val = payload.get("lunch_start") if payload.get("lunch_start") is not None else (existing.lunch_start if existing else None)
        lunch_end_val = payload.get("lunch_end") if payload.get("lunch_end") is not None else (existing.lunch_end if existing else None)
        note_val = payload.get("note") if "note" in payload else (existing.note if existing else None)

        if employee_id is None or weekday is None:
            raise ValueError("Préciser la vendeuse et le jour.")
        try:
            employee_id = int(employee_id)
        except (TypeError, ValueError):
            raise ValueError("Identifiant vendeuse invalide.")
        try:
            weekday = int(weekday)
        except (TypeError, ValueError):
            raise ValueError("Jour invalide.")
        if weekday < 0 or weekday > 6:
            raise ValueError("Jour hors plage (0=lundi … 6=dimanche).")

        start_time, start_minutes = _normalize_time(start_val, "début")
        end_time, end_minutes = _normalize_time(end_val, "fin")
        if start_minutes >= end_minutes:
            raise ValueError("L'heure de fin doit être après l'heure de début.")

        lunch_start, lunch_start_minutes = _normalize_optional_time(lunch_start_val, "début pause")
        lunch_end, lunch_end_minutes = _normalize_optional_time(lunch_end_val, "fin pause")
        if (lunch_start is None) != (lunch_end is None):
            raise ValueError("Préciser début et fin de pause ou laisser vide.")
        if lunch_start is not None:
            if not (start_minutes < lunch_start_minutes < lunch_end_minutes < end_minutes):
                raise ValueError("La pause doit être comprise entre début et fin et respecter l'ordre.")

        # vérifier chevauchement
        q = BaseShift.query.filter_by(employee_id=employee_id, weekday=weekday)
        if existing is not None:
            q = q.filter(BaseShift.id != existing.id)
        siblings = q.all()
        for other in siblings:
            try:
                other_start = _normalize_time(other.start_time, "autre début")[1]
                other_end = _normalize_time(other.end_time, "autre fin")[1]
            except ValueError:
                continue
            if not (end_minutes <= other_start or other_end <= start_minutes):
                raise ValueError("Chevauchement avec un autre créneau de cette vendeuse.")

        return {
            "employee_id": employee_id,
            "weekday": weekday,
            "start_time": start_time,
            "end_time": end_time,
            "lunch_start": lunch_start,
            "lunch_end": lunch_end,
            "note": note_val.strip() if isinstance(note_val, str) else note_val,
        }

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
            digits = "".join(ch for ch in contract_type if ch.isdigit())
            max_hours = int(digits) if digits else 35
        else:
            try:
                max_hours = int(round(float(max_hours_input)))
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

            weeks_param = int(payload.get("weeks", 1) or 1)
            if weeks_param < 1 or weeks_param > 2:
                return jsonify({"ok": False, "error": "validation", "detail": "Durée invalide (1 ou 2 semaines)."}), 400

            weeks_payload = []
            for offset in range(weeks_param):
                cur_monday = monday + timedelta(days=7 * offset)
                cur_sunday = cur_monday + timedelta(days=6)

                adjusted = list_adjusted_between(cur_monday, cur_sunday)
                if offset == 0 and not adjusted:
                    return jsonify({"ok": False, "error": "empty", "detail": "Aucun planning ajusté pour cette semaine."}), 400
                base_week = compute_base_week_for(cur_monday)

                violations_rows = (RuleViolation.query
                                   .filter(RuleViolation.date >= cur_monday, RuleViolation.date <= cur_sunday)
                                   .order_by(RuleViolation.date)
                                   .all())
                violations = [{
                    "date": r.date.isoformat(),
                    "code": r.code,
                    "details": r.details,
                    "severity": r.severity,
                    "employee_id": r.employee_id,
                } for r in violations_rows]

                abs_q = (Absence.query
                         .join(Employee, Employee.id == Absence.employee_id)
                         .filter(Absence.end_date >= cur_monday)
                         .filter(Absence.start_date <= cur_sunday)
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
                                     .filter(SpecialOpening.date >= cur_monday, SpecialOpening.date <= cur_sunday)
                                     .order_by(SpecialOpening.date)
                                     .all()]

                weeks_payload.append({
                    "monday": cur_monday.isoformat(),
                    "sunday": cur_sunday.isoformat(),
                    "base": base_week,
                    "adjusted": adjusted,
                    "violations": violations,
                    "absences": absences,
                    "special_openings": specials_payload,
                })

            label = (payload.get("label") or "").strip() or None
            status = (payload.get("status") or "draft").strip().lower()
            if status in {"previsionnel"}:
                status = "prévisionnel"
            if status in {"valide", "validé"}:
                status = "valide"
            if status not in {"draft", "prévisionnel", "valide"}:
                status = "draft"
            sunday_open = bool(payload.get("sunday_open"))
            first_week = weeks_payload[0]
            snapshot_payload = {
                "monday": first_week["monday"],
                "sunday": first_week["sunday"],
                "label": label,
                "captured_at": datetime.utcnow().isoformat(),
                "sunday_open": sunday_open,
                "base": first_week["base"],
                "adjusted": first_week["adjusted"],
                "violations": first_week["violations"],
                "absences": first_week["absences"],
                "special_openings": first_week["special_openings"],
                "weeks": weeks_payload,
                "duration_weeks": weeks_param,
            }

            snap = PlanningSnapshot(
                monday=monday,
                sunday=monday + timedelta(days=7 * weeks_param - 1),
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
            weeks_payload = payload.get("weeks") or []
            if weeks_payload:
                first_monday = None
                last_sunday = None
                for week in weeks_payload:
                    week_monday = date.fromisoformat(week["monday"])
                    week_sunday = date.fromisoformat(week["sunday"])
                    if first_monday is None or week_monday < first_monday:
                        first_monday = week_monday
                    if last_sunday is None or week_sunday > last_sunday:
                        last_sunday = week_sunday
                if first_monday and last_sunday:
                    AdjustedShift.query.filter(AdjustedShift.date >= first_monday, AdjustedShift.date <= last_sunday).delete(synchronize_session=False)
                    RuleViolation.query.filter(RuleViolation.date >= first_monday, RuleViolation.date <= last_sunday).delete(synchronize_session=False)

                for week in weeks_payload:
                    adjusted = week.get("adjusted") or []
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

                    for v in week.get("violations") or []:
                        rv = RuleViolation(
                            date=date.fromisoformat(v["date"]),
                            employee_id=v.get("employee_id"),
                            code=v.get("code"),
                            details=v.get("details"),
                            severity=v.get("severity") or "warn",
                        )
                        db.session.add(rv)
            else:
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
                emp = db.session.get(Employee, b.employee_id)
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
            payload = request.get_json(force=True)
            values = _normalize_base_shift_payload(payload)
            b = BaseShift(**values)
            db.session.add(b)
            db.session.commit()
            return jsonify({"ok": True, "id": b.id}), 201
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "where": "create-base-shift", "error": type(e).__name__, "detail": str(e)}), 500

    @app.put("/api/base-shifts/<int:bid>")
    def api_update_base_shift(bid):
        try:
            b = BaseShift.query.get_or_404(bid)
            payload = request.get_json(force=True)
            values = _normalize_base_shift_payload(payload, existing=b)
            for key, value in values.items():
                setattr(b, key, value)
            db.session.commit()
            return jsonify({"ok": True})
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"ok": False, "error": "validation", "detail": str(exc)}), 400
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
