import sqlite3
import os
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash

# Op Railway: gebruik persistente volume map, anders lokaal
_DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH",
                            os.path.dirname(__file__))
DB_PATH = os.path.join(_DATA_DIR, "tracker.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL DEFAULT 'employee',
            created_at    TEXT    NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            email      TEXT    NOT NULL,
            employee   TEXT    NOT NULL,
            start_time TEXT    NOT NULL,
            end_time   TEXT,
            total_sec  INTEGER DEFAULT 0,
            pause_sec  INTEGER DEFAULT 0,
            date       TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Migraties voor bestaande databases
    for col in ["pause_sec INTEGER DEFAULT 0", "work_sec INTEGER DEFAULT 0",
                "is_paused INTEGER DEFAULT 0"]:
        try:
            c.execute(f"ALTER TABLE sessions ADD COLUMN {col}")
            conn.commit()
        except Exception:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS screenshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            email      TEXT    NOT NULL,
            employee   TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL,
            filename   TEXT    NOT NULL,
            activity   INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)

    conn.commit()
    conn.close()


def has_any_manager():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE role='manager'").fetchone()
    conn.close()
    return row["cnt"] > 0


# ── Gebruikers ────────────────────────────────────────────────────────────────

def create_user(name: str, email: str, password: str, role: str = "employee") -> bool:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            (name.strip(), email.strip().lower(), generate_password_hash(password), role, datetime.now().isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_user(email: str, password: str):
    user = get_user_by_email(email)
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def get_all_users(role: str = None):
    conn = get_db()
    if role:
        rows = conn.execute("SELECT id,name,email,role,created_at FROM users WHERE role=? ORDER BY name", (role,)).fetchall()
    else:
        rows = conn.execute("SELECT id,name,email,role,created_at FROM users ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_role(user_id: int, new_role: str):
    conn = get_db()
    conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
    conn.commit()
    conn.close()


def update_password(user_id: int, new_password: str):
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_password), user_id))
    conn.commit()
    conn.close()


def delete_user(user_id: int):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()


# ── Sessies ───────────────────────────────────────────────────────────────────

def start_session(user_id: int, email: str, name: str) -> int:
    conn = get_db()
    now   = datetime.now().isoformat()
    today = date.today().isoformat()
    conn.execute(
        "INSERT INTO sessions (user_id, email, employee, start_time, date) VALUES (?,?,?,?,?)",
        (user_id, email, name, now, today),
    )
    session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return session_id


def stop_session(session_id: int, work_sec: int = 0, pause_sec: int = 0):
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET end_time=?, total_sec=?, work_sec=?, pause_sec=? WHERE id=?",
        (datetime.now().isoformat(), work_sec, work_sec, pause_sec, session_id)
    )
    conn.commit()
    conn.close()


def sync_work_sec(session_id: int, work_sec: int, is_paused: bool = False):
    """Tussentijds de gewerkte seconden en pauze-status opslaan."""
    conn = get_db()
    conn.execute("UPDATE sessions SET work_sec=?, is_paused=? WHERE id=?",
                 (work_sec, 1 if is_paused else 0, session_id))
    conn.commit()
    conn.close()


def get_active_session_for_user(user_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? AND end_time IS NULL ORDER BY start_time DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_session_pause(session_id: int, pause_sec: int):
    conn = get_db()
    conn.execute("UPDATE sessions SET pause_sec=? WHERE id=?", (pause_sec, session_id))
    conn.commit()
    conn.close()


def edit_session(session_id: int, start_time: str, end_time: str):
    """Manager past start/stoptijd aan. total_sec wordt herberekend."""
    conn = get_db()
    try:
        start = datetime.fromisoformat(start_time)
        end   = datetime.fromisoformat(end_time)
        total_sec = max(0, int((end - start).total_seconds()))
        conn.execute(
            "UPDATE sessions SET start_time=?, end_time=?, total_sec=?, date=? WHERE id=?",
            (start_time, end_time, total_sec, start.date().isoformat(), session_id)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def delete_session(session_id: int):
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()


def get_active_sessions():
    conn = get_db()
    rows = conn.execute("SELECT * FROM sessions WHERE end_time IS NULL ORDER BY start_time DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sessions_by_user(user_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? ORDER BY start_time DESC LIMIT 200", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_sessions():
    today = date.today().isoformat()
    conn  = get_db()
    rows  = conn.execute("SELECT * FROM sessions WHERE date=?", (today,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Screenshots ───────────────────────────────────────────────────────────────

def save_screenshot_record(session_id: int, user_id: int, email: str, name: str, filename: str, activity: int = 0):
    conn = get_db()
    conn.execute(
        "INSERT INTO screenshots (session_id,user_id,email,employee,timestamp,filename,activity) VALUES (?,?,?,?,?,?,?)",
        (session_id, user_id, email, name, datetime.now().isoformat(), filename, activity),
    )
    conn.commit()
    conn.close()


def get_screenshots_by_user(user_id: int, limit: int = 60):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM screenshots WHERE user_id=? ORDER BY timestamp DESC LIMIT ?", (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Statistieken ──────────────────────────────────────────────────────────────

def get_user_stats(user_id: int) -> dict:
    conn  = get_db()
    today = date.today().isoformat()

    today_sec = conn.execute(
        "SELECT COALESCE(SUM(total_sec),0) as s FROM sessions WHERE user_id=? AND date=?",
        (user_id, today)
    ).fetchone()["s"]

    week_sec = conn.execute(
        "SELECT COALESCE(SUM(total_sec),0) as s FROM sessions WHERE user_id=? AND date>=date('now','-6 days')",
        (user_id,)
    ).fetchone()["s"]

    month_sec = conn.execute(
        "SELECT COALESCE(SUM(total_sec),0) as s FROM sessions WHERE user_id=? AND date>=date('now','start of month')",
        (user_id,)
    ).fetchone()["s"]

    ss_count = conn.execute(
        "SELECT COUNT(*) as c FROM screenshots WHERE user_id=?", (user_id,)
    ).fetchone()["c"]

    conn.close()
    return {"today_sec": today_sec, "week_sec": week_sec, "month_sec": month_sec, "screenshot_count": ss_count}


def get_today_seconds_for_user(user_id: int) -> int:
    today = date.today().isoformat()
    conn  = get_db()
    s = conn.execute(
        "SELECT COALESCE(SUM(total_sec),0) as s FROM sessions WHERE user_id=? AND date=?",
        (user_id, today)
    ).fetchone()["s"]
    conn.close()
    return s


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m:02d}m"


# ── Manager: alle screenshots ─────────────────────────────────────────────────

def get_all_screenshots(employee_id: int = None, limit: int = 100):
    conn = get_db()
    if employee_id:
        rows = conn.execute(
            """SELECT s.*, u.name as user_name FROM screenshots s
               JOIN users u ON s.user_id = u.id
               WHERE s.user_id=? ORDER BY s.timestamp DESC LIMIT ?""",
            (employee_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT s.*, u.name as user_name FROM screenshots s
               JOIN users u ON s.user_id = u.id
               ORDER BY s.timestamp DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Manager: rapporten ────────────────────────────────────────────────────────

def get_sessions_range(date_from: str, date_to: str, user_id: int = None):
    conn = get_db()
    if user_id:
        rows = conn.execute(
            """SELECT s.*, u.name as user_name FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.date >= ? AND s.date <= ? AND s.user_id = ?
               ORDER BY s.date DESC, s.start_time DESC""",
            (date_from, date_to, user_id)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT s.*, u.name as user_name FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.date >= ? AND s.date <= ?
               ORDER BY s.date DESC, s.start_time DESC""",
            (date_from, date_to)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_report_summary(date_from: str, date_to: str):
    """Totale uren per medewerker in een periode."""
    conn = get_db()
    rows = conn.execute(
        """SELECT u.id, u.name, u.email,
                  COALESCE(SUM(s.total_sec), 0) as total_sec,
                  COUNT(s.id) as session_count
           FROM users u
           LEFT JOIN sessions s ON s.user_id = u.id
               AND s.date >= ? AND s.date <= ?
           WHERE u.role = 'employee'
           GROUP BY u.id, u.name, u.email
           ORDER BY total_sec DESC""",
        (date_from, date_to)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_hours(user_id: int, date_from: str, date_to: str):
    """Uren per dag voor een medewerker."""
    conn = get_db()
    rows = conn.execute(
        """SELECT date, COALESCE(SUM(total_sec), 0) as total_sec
           FROM sessions
           WHERE user_id=? AND date >= ? AND date <= ?
           GROUP BY date ORDER BY date DESC""",
        (user_id, date_from, date_to)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_screenshots_by_date(user_id: int, date_from: str, date_to: str):
    """Screenshots gegroepeerd per dag."""
    conn = get_db()
    rows = conn.execute(
        """SELECT sc.*, substr(sc.timestamp, 1, 10) as day
           FROM screenshots sc
           WHERE sc.user_id=?
             AND substr(sc.timestamp,1,10) >= ?
             AND substr(sc.timestamp,1,10) <= ?
           ORDER BY sc.timestamp DESC""",
        (user_id, date_from, date_to)
    ).fetchall()
    conn.close()
    # Groepeer per dag
    grouped = {}
    for r in rows:
        d = dict(r)
        day = d['day']
        if day not in grouped:
            grouped[day] = []
        grouped[day].append(d)
    return grouped


def get_report_summary(date_from: str, date_to: str):
    """Totale uren per medewerker in een periode — alle rollen."""
    conn = get_db()
    rows = conn.execute(
        """SELECT u.id, u.name, u.email, u.role,
                  COALESCE(SUM(s.total_sec), 0) as total_sec,
                  COUNT(s.id) as session_count,
                  (SELECT COUNT(*) FROM screenshots sc
                   WHERE sc.user_id=u.id
                     AND substr(sc.timestamp,1,10) >= ?
                     AND substr(sc.timestamp,1,10) <= ?) as ss_count
           FROM users u
           LEFT JOIN sessions s ON s.user_id = u.id
               AND s.date >= ? AND s.date <= ?
           GROUP BY u.id, u.name, u.email, u.role
           ORDER BY total_sec DESC""",
        (date_from, date_to, date_from, date_to)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
