import os, base64, sys
from datetime import datetime
from functools import wraps

from flask import (Flask, request, jsonify, render_template,
                   send_from_directory, abort, redirect, url_for,
                   session as flask_session, flash)
from flask_cors import CORS
import database as db

# Screenshot interval (standaard 10 min)
SCREENSHOT_INTERVAL = int(os.environ.get("SCREENSHOT_INTERVAL", 10))

# ── Paden (werkt zowel lokaal als op Railway) ─────────────────────────────────
BASE_DIR       = os.path.dirname(__file__)
# Op Railway: gebruik /data voor persistente opslag, anders lokale map
DATA_DIR       = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH",
                                os.path.join(BASE_DIR, ".."))
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "werktracker-geheim-2024-xK9p")
CORS(app)
db.init_db()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in flask_session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in flask_session:
            return redirect(url_for("login"))
        if flask_session.get("role") != "manager":
            return redirect(url_for("mijn_dashboard"))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
#   AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Eerste keer: manager account aanmaken."""
    if db.has_any_manager():
        return redirect(url_for("login"))
    error = None
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")
        if not name or not email or not password:
            error = "Vul alle velden in."
        elif password != confirm:
            error = "Wachtwoorden komen niet overeen."
        elif len(password) < 6:
            error = "Wachtwoord moet minimaal 6 tekens zijn."
        else:
            ok = db.create_user(name, email, password, role="manager")
            if ok:
                flash("Manager account aangemaakt! Log nu in.", "success")
                return redirect(url_for("login"))
            else:
                error = "E-mailadres is al in gebruik."
    return render_template("setup.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in flask_session:
        return redirect(url_for("dashboard") if flask_session.get("role") == "manager" else url_for("mijn_dashboard"))

    if not db.has_any_manager():
        return redirect(url_for("setup"))

    error = None
    if request.method == "POST":
        email    = request.form.get("email", "")
        password = request.form.get("password", "")
        user     = db.verify_user(email, password)
        if user:
            flask_session["user_id"] = user["id"]
            flask_session["name"]    = user["name"]
            flask_session["email"]   = user["email"]
            flask_session["role"]    = user["role"]
            if user["role"] == "manager":
                return redirect(url_for("dashboard"))
            else:
                return redirect(url_for("mijn_dashboard"))
        else:
            error = "Ongeldig e-mailadres of wachtwoord."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    flask_session.clear()
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════════════════════════════════
#   MANAGER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
@manager_required
def dashboard():
    employees      = db.get_all_users(role="employee")
    active_sessions = db.get_active_sessions()
    active_ids     = {s["user_id"] for s in active_sessions}
    today_sessions = db.get_today_sessions()

    # Tel vandaag-uren per user_id
    today_secs = {}
    for s in today_sessions:
        uid = s["user_id"]
        today_secs[uid] = today_secs.get(uid, 0) + s["total_sec"]

    # Tel actieve sessies mee (nog bezig)
    for s in active_sessions:
        uid   = s["user_id"]
        start = datetime.fromisoformat(s["start_time"])
        secs  = int((datetime.now() - start).total_seconds())
        today_secs[uid] = today_secs.get(uid, 0) + secs

    stats = []
    for emp in employees:
        uid  = emp["id"]
        s    = db.get_user_stats(uid)
        stats.append({
            "id":          uid,
            "name":        emp["name"],
            "email":       emp["email"],
            "online":      uid in active_ids,
            "today":       db.format_duration(today_secs.get(uid, 0)),
            "week":        db.format_duration(s["week_sec"]),
            "month":       db.format_duration(s["month_sec"]),
            "screenshots": s["screenshot_count"],
        })

    stats.sort(key=lambda x: (not x["online"], x["name"]))
    return render_template("index.html",
                           stats=stats,
                           active_count=len(active_ids),
                           manager_name=flask_session.get("name"))


@app.route("/medewerkers")
@manager_required
def medewerkers():
    employees = db.get_all_users()  # alle rollen — manager kan iedereen zien
    return render_template("medewerkers.html",
                           employees=employees,
                           manager_name=flask_session.get("name"))


@app.route("/medewerkers/toevoegen", methods=["POST"])
@manager_required
def medewerker_toevoegen():
    name     = request.form.get("name", "").strip()
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    role     = request.form.get("role", "employee")
    if role not in ("manager", "employee"):
        role = "employee"
    if name and email and password:
        ok = db.create_user(name, email, password, role=role)
        if ok:
            label = "Manager" if role == "manager" else "Medewerker"
            flash(f"{label} '{name}' succesvol aangemaakt.", "success")
        else:
            flash("E-mailadres is al in gebruik.", "error")
    else:
        flash("Vul alle velden in.", "error")
    return redirect(url_for("medewerkers"))


@app.route("/medewerkers/verwijderen/<int:user_id>", methods=["POST"])
@manager_required
def medewerker_verwijderen(user_id):
    db.delete_user(user_id)
    flash("Medewerker verwijderd.", "success")
    return redirect(url_for("medewerkers"))


@app.route("/sessie/<int:session_id>/bewerken", methods=["POST"])
@manager_required
def sessie_bewerken(session_id):
    start_time = request.form.get("start_time", "").replace("T", " ").strip()
    end_time   = request.form.get("end_time", "").replace("T", " ").strip()
    # Voeg seconden toe als die ontbreken
    if len(start_time) == 16:
        start_time += ":00"
    if len(end_time) == 16:
        end_time += ":00"
    user_id = request.form.get("user_id")
    ok = db.edit_session(session_id, start_time, end_time)
    if ok:
        flash("Sessie bijgewerkt.", "success")
    else:
        flash("Fout bij bijwerken sessie.", "error")
    return redirect(url_for("medewerker_detail", user_id=user_id))


@app.route("/sessie/<int:session_id>/verwijderen", methods=["POST"])
@manager_required
def sessie_verwijderen(session_id):
    user_id = request.form.get("user_id")
    db.delete_session(session_id)
    flash("Sessie verwijderd.", "success")
    return redirect(url_for("medewerker_detail", user_id=user_id))


@app.route("/medewerkers/wachtwoord/<int:user_id>", methods=["POST"])
@manager_required
def medewerker_wachtwoord(user_id):
    new_pw = request.form.get("password", "")
    if len(new_pw) >= 6:
        db.update_password(user_id, new_pw)
        flash("Wachtwoord bijgewerkt.", "success")
    else:
        flash("Wachtwoord moet minimaal 6 tekens zijn.", "error")
    return redirect(url_for("medewerkers"))


@app.route("/medewerkers/rol/<int:user_id>", methods=["POST"])
@manager_required
def medewerker_rol(user_id):
    new_role = request.form.get("role", "employee")
    if new_role not in ("manager", "employee"):
        flash("Ongeldige rol.", "error")
        return redirect(url_for("medewerkers"))
    # Voorkom dat je jezelf degradeert
    if user_id == flask_session["user_id"]:
        flash("Je kunt je eigen rol niet wijzigen.", "error")
        return redirect(url_for("medewerkers"))
    user = db.get_user_by_id(user_id)
    db.update_role(user_id, new_role)
    label = "Manager" if new_role == "manager" else "Medewerker"
    flash(f"{user['name']} is nu {label}.", "success")
    return redirect(url_for("medewerkers"))


@app.route("/medewerker/<int:user_id>")
@manager_required
def medewerker_detail(user_id):
    user        = db.get_user_by_id(user_id)
    if not user:
        abort(404)
    sessions    = db.get_sessions_by_user(user_id)
    screenshots = db.get_screenshots_by_user(user_id, limit=60)
    emp_stats   = db.get_user_stats(user_id)
    active      = any(s["end_time"] is None for s in sessions)
    return render_template("employee.html",
                           user=user,
                           sessions=sessions,
                           screenshots=screenshots,
                           stats=emp_stats,
                           active=active,
                           format_duration=db.format_duration,
                           manager_name=flask_session.get("name"))


# ── Manager: Rapporten ───────────────────────────────────────────────────────

@app.route("/rapporten")
@manager_required
def rapporten():
    from datetime import date, timedelta
    date_from = request.args.get("van",  (date.today().replace(day=1)).isoformat())
    date_to   = request.args.get("tot",  date.today().isoformat())
    emp_id    = request.args.get("medewerker", None)
    if emp_id:
        emp_id = int(emp_id)

    summary   = db.get_report_summary(date_from, date_to)
    sessions  = db.get_sessions_range(date_from, date_to, emp_id)
    employees = db.get_all_users(role="employee")
    total_sec = sum(r["total_sec"] for r in summary)

    return render_template("rapporten.html",
                           summary=summary,
                           sessions=sessions,
                           employees=employees,
                           date_from=date_from,
                           date_to=date_to,
                           selected_emp=emp_id,
                           total_sec=total_sec,
                           format_duration=db.format_duration,
                           manager_name=flask_session.get("name"))


# ── Manager: Rapport detail per medewerker ───────────────────────────────────

@app.route("/rapport/<int:user_id>")
@manager_required
def rapport_detail(user_id):
    from datetime import date
    user      = db.get_user_by_id(user_id)
    if not user:
        abort(404)
    date_from = request.args.get("van",  date.today().replace(day=1).isoformat())
    date_to   = request.args.get("tot",  date.today().isoformat())

    sessions    = db.get_sessions_range(date_from, date_to, user_id)
    daily       = db.get_daily_hours(user_id, date_from, date_to)
    ss_by_day   = db.get_screenshots_by_date(user_id, date_from, date_to)
    stats       = db.get_user_stats(user_id)
    total_sec   = sum(s["total_sec"] for s in sessions)

    return render_template("rapport_detail.html",
                           user=user,
                           sessions=sessions,
                           daily=daily,
                           ss_by_day=ss_by_day,
                           stats=stats,
                           date_from=date_from,
                           date_to=date_to,
                           total_sec=total_sec,
                           format_duration=db.format_duration,
                           manager_name=flask_session.get("name"))


# ── Manager: Screenshots overzicht ───────────────────────────────────────────

@app.route("/screenshots-overzicht")
@manager_required
def screenshots_overzicht():
    emp_id    = request.args.get("medewerker", None)
    if emp_id:
        emp_id = int(emp_id)
    screenshots = db.get_all_screenshots(employee_id=emp_id, limit=120)
    employees   = db.get_all_users(role="employee")
    return render_template("screenshots_overzicht.html",
                           screenshots=screenshots,
                           employees=employees,
                           selected_emp=emp_id,
                           manager_name=flask_session.get("name"))


# ── Tracking pagina (voor iedereen) ──────────────────────────────────────────

@app.route("/tracking")
@login_required
def tracking():
    user_id     = flask_session["user_id"]
    today_sec   = db.get_today_seconds_for_user(user_id)
    # Tel actieve sessie mee
    active = next((s for s in db.get_active_sessions() if s["user_id"] == user_id), None)
    if active:
        from datetime import datetime as dt
        extra = int((dt.now() - dt.fromisoformat(active["start_time"])).total_seconds())
        today_sec += extra

    return render_template("tracking.html",
                           name=flask_session["name"],
                           email=flask_session["email"],
                           role=flask_session["role"],
                           user_id=user_id,
                           today_worked=db.format_duration(today_sec),
                           ss_interval=SCREENSHOT_INTERVAL)


# ══════════════════════════════════════════════════════════════════════════════
#   MEDEWERKER ROUTES (eigen dashboard)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/mijn-dashboard")
@login_required
def mijn_dashboard():
    if flask_session.get("role") == "manager":
        return redirect(url_for("dashboard"))

    user_id     = flask_session["user_id"]
    sessions    = db.get_sessions_by_user(user_id)
    screenshots = db.get_screenshots_by_user(user_id, limit=30)
    emp_stats   = db.get_user_stats(user_id)
    active      = any(s["end_time"] is None for s in sessions)

    return render_template("mijn_dashboard.html",
                           name=flask_session["name"],
                           email=flask_session["email"],
                           sessions=sessions,
                           screenshots=screenshots,
                           stats=emp_stats,
                           active=active,
                           format_duration=db.format_duration)


@app.route("/mijn-uren")
@login_required
def mijn_uren():
    if flask_session.get("role") == "manager":
        return redirect(url_for("rapporten"))
    from datetime import date
    user_id   = flask_session["user_id"]
    date_from = request.args.get("van", date.today().replace(day=1).isoformat())
    date_to   = request.args.get("tot", date.today().isoformat())
    sessions  = db.get_sessions_range(date_from, date_to, user_id)
    daily     = db.get_daily_hours(user_id, date_from, date_to)
    total_sec = sum(s["total_sec"] for s in sessions)
    return render_template("mijn_uren.html",
                           name=flask_session["name"],
                           email=flask_session["email"],
                           sessions=sessions,
                           daily=daily,
                           date_from=date_from,
                           date_to=date_to,
                           total_sec=total_sec,
                           format_duration=db.format_duration)


@app.route("/mijn-screenshots")
@login_required
def mijn_screenshots():
    if flask_session.get("role") == "manager":
        return redirect(url_for("screenshots_overzicht"))
    user_id     = flask_session["user_id"]
    screenshots = db.get_screenshots_by_user(user_id, limit=120)
    return render_template("mijn_screenshots.html",
                           name=flask_session["name"],
                           email=flask_session["email"],
                           screenshots=screenshots)


# ══════════════════════════════════════════════════════════════════════════════
#   API – voor de client-app van medewerkers
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})


@app.route("/api/login", methods=["POST"])
def api_login():
    """Client-app inloggen."""
    data     = request.json or {}
    email    = data.get("email", "")
    password = data.get("password", "")
    user     = db.verify_user(email, password)
    if user:
        return jsonify({
            "ok":      True,
            "user_id": user["id"],
            "name":    user["name"],
            "email":   user["email"],
            "role":    user["role"],
        })
    return jsonify({"ok": False, "error": "Ongeldig e-mail of wachtwoord"}), 401


@app.route("/api/session/start", methods=["POST"])
def session_start():
    data     = request.json or {}
    user_id  = data.get("user_id")
    email    = data.get("email", "")
    name     = data.get("name", "")
    if not user_id:
        return jsonify({"error": "user_id vereist"}), 400
    session_id = db.start_session(int(user_id), email, name)
    return jsonify({"session_id": session_id})


@app.route("/api/session/stop", methods=["POST"])
def session_stop():
    data       = request.json or {}
    session_id = data.get("session_id")
    pause_sec  = int(data.get("pause_sec", 0))
    if session_id:
        db.stop_session(int(session_id), pause_sec)
    return jsonify({"status": "gestopt"})


@app.route("/api/session/active")
def session_active():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"session": None})
    session = db.get_active_session_for_user(int(user_id))
    return jsonify({"session": session})


@app.route("/api/sessie/<int:session_id>/bewerken", methods=["POST"])
@manager_required
def api_sessie_bewerken(session_id):
    data       = request.json or {}
    start_time = data.get("start_time", "")
    end_time   = data.get("end_time", "")
    ok = db.edit_session(session_id, start_time, end_time)
    if ok:
        conn = db.get_db()
        row  = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        conn.close()
        s = dict(row) if row else {}
        return jsonify({"ok": True, "total_sec": s.get("total_sec", 0),
                        "duration": db.format_duration(s.get("total_sec", 0))})
    return jsonify({"ok": False}), 400


@app.route("/api/session/pause", methods=["POST"])
def session_pause_sync():
    data       = request.json or {}
    session_id = data.get("session_id")
    pause_sec  = int(data.get("pause_sec", 0))
    if session_id:
        db.update_session_pause(int(session_id), pause_sec)
    return jsonify({"status": "ok"})


@app.route("/api/screenshot", methods=["POST"])
def upload_screenshot():
    data       = request.json or {}
    session_id = data.get("session_id")
    user_id    = data.get("user_id")
    email      = data.get("email", "onbekend")
    name       = data.get("name", "onbekend")
    img_b64    = data.get("image")
    activity   = int(data.get("activity", 0))

    if not img_b64:
        return jsonify({"error": "Geen afbeelding"}), 400

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_emp = "".join(c if c.isalnum() else "_" for c in name)
    filename = f"{safe_emp}_{ts}.jpg"
    filepath = os.path.join(SCREENSHOT_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(img_b64))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    db.save_screenshot_record(session_id, user_id, email, name, filename, activity)
    return jsonify({"status": "opgeslagen", "filename": filename})


@app.route("/screenshots/<filename>")
@login_required
def serve_screenshot(filename):
    safe = os.path.basename(filename)
    path = os.path.join(SCREENSHOT_DIR, safe)
    if not os.path.exists(path):
        abort(404)

    # Medewerkers mogen alleen hun eigen screenshots zien
    if flask_session.get("role") != "manager":
        uid  = flask_session["user_id"]
        conn = db.get_db()
        row  = conn.execute("SELECT id FROM screenshots WHERE user_id=? AND filename=?", (uid, safe)).fetchone()
        conn.close()
        if not row:
            abort(403)

    return send_from_directory(SCREENSHOT_DIR, safe)


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("=" * 55)
    print("  WerkTracker – Dashboard")
    print(f"  Open je browser:  http://localhost:{port}")
    print("=" * 55)
    app.run(host="0.0.0.0", port=port, debug=False)
