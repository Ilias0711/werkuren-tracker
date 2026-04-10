"""
WerkTracker – Medewerker Client
Inloggen met e-mail + wachtwoord, dan uren bijhouden met screenshots.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading, time, datetime, io, base64
import requests
from PIL import ImageGrab, Image

import config

C_BLUE   = "#1e3a5f"
C_ACCENT = "#2196f3"
C_GREEN  = "#22c55e"
C_ORANGE = "#f97316"
C_RED    = "#ef4444"
C_BG     = "#f0f4f8"
C_WHITE  = "#ffffff"


class TrackerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WerkTracker")
        self.root.geometry("360x540")
        self.root.resizable(False, False)
        self.root.configure(bg=C_BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # State
        self.logged_in     = False
        self.user_id       = None
        self.user_name     = None
        self.user_email    = None
        self.is_tracking   = False
        self.is_paused     = False
        self.session_id    = None
        self.start_time    = None
        self.paused_at     = None
        self.total_paused  = 0        # totaal aantal seconden gepauzeerd
        self.mouse_events  = 0
        self.key_events    = 0

        self._build_login_ui()
        self._start_activity_monitor()

    # ══════════════════════════════════════════════════════════════════════════
    #   LOGIN SCHERM
    # ══════════════════════════════════════════════════════════════════════════

    def _build_login_ui(self):
        self._clear_window()
        self.root.geometry("360x420")

        header = tk.Frame(self.root, bg=C_BLUE, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="⏱  WerkTracker",
                 font=("Segoe UI", 17, "bold"), fg="white", bg=C_BLUE).pack(expand=True)

        body = tk.Frame(self.root, bg=C_BG, padx=28, pady=24)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Inloggen met je account",
                 font=("Segoe UI", 11, "bold"), fg=C_BLUE, bg=C_BG).pack(anchor="w", pady=(0, 16))

        tk.Label(body, text="E-mailadres", font=("Segoe UI", 9, "bold"),
                 fg="#6b7280", bg=C_BG).pack(anchor="w")
        self.email_var = tk.StringVar()
        tk.Entry(body, textvariable=self.email_var, font=("Segoe UI", 11),
                 relief="flat", highlightthickness=1,
                 highlightbackground="#d1d5db", highlightcolor=C_ACCENT
                 ).pack(fill="x", pady=(3, 12), ipady=7)

        tk.Label(body, text="Wachtwoord", font=("Segoe UI", 9, "bold"),
                 fg="#6b7280", bg=C_BG).pack(anchor="w")
        self.pw_var = tk.StringVar()
        tk.Entry(body, textvariable=self.pw_var, show="•",
                 font=("Segoe UI", 11), relief="flat",
                 highlightthickness=1, highlightbackground="#d1d5db",
                 highlightcolor=C_ACCENT
                 ).pack(fill="x", pady=(3, 16), ipady=7)

        self.login_error = tk.Label(body, text="", font=("Segoe UI", 9),
                                     fg=C_RED, bg=C_BG, wraplength=280)
        self.login_error.pack(pady=(0, 8))

        tk.Button(body, text="Inloggen",
                  font=("Segoe UI", 12, "bold"),
                  fg="white", bg=C_ACCENT,
                  activeforeground="white", activebackground="#1976d2",
                  relief="flat", cursor="hand2",
                  command=self._do_login
                  ).pack(fill="x", ipady=11)

        tk.Label(body, text=f"Server: {config.SERVER_URL}",
                 font=("Segoe UI", 8), fg="#9ca3af", bg=C_BG).pack(pady=(10, 0))

        self.root.bind("<Return>", lambda e: self._do_login())

    def _do_login(self):
        email    = self.email_var.get().strip()
        password = self.pw_var.get()
        if not email or not password:
            self.login_error.config(text="Vul je e-mail en wachtwoord in.")
            return

        self.login_error.config(text="Verbinden…", fg="#6b7280")
        self.root.update()

        try:
            r    = requests.post(f"{config.SERVER_URL}/api/login",
                                  json={"email": email, "password": password}, timeout=6)
            data = r.json()
            if r.status_code == 200 and data.get("ok"):
                self.user_id    = data["user_id"]
                self.user_name  = data["name"]
                self.user_email = data["email"]
                self.logged_in  = True
                self.root.unbind("<Return>")
                self._build_tracker_ui()
            else:
                self.login_error.config(
                    text=data.get("error", "Ongeldig e-mail of wachtwoord."), fg=C_RED)
        except requests.exceptions.ConnectionError:
            self.login_error.config(
                text=f"Server niet bereikbaar.\n{config.SERVER_URL}", fg=C_RED)
        except Exception as e:
            self.login_error.config(text=f"Fout: {e}", fg=C_RED)

    # ══════════════════════════════════════════════════════════════════════════
    #   TRACKER SCHERM
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tracker_ui(self):
        self._clear_window()
        self.root.geometry("360x540")

        # Header
        header = tk.Frame(self.root, bg=C_BLUE, height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="⏱  WerkTracker",
                 font=("Segoe UI", 16, "bold"), fg="white", bg=C_BLUE).pack(expand=True)

        body = tk.Frame(self.root, bg=C_BG, padx=22, pady=16)
        body.pack(fill="both", expand=True)

        # Welkomstbalk
        wb = tk.Frame(body, bg="#e0f2fe", padx=14, pady=8)
        wb.pack(fill="x", pady=(0, 14))
        wb.configure(highlightthickness=1, highlightbackground="#bae6fd")
        tk.Label(wb, text=f"👋  {self.user_name}",
                 font=("Segoe UI", 11, "bold"), fg="#0284c7", bg="#e0f2fe").pack(anchor="w")
        tk.Label(wb, text=self.user_email,
                 font=("Segoe UI", 9), fg="#0369a1", bg="#e0f2fe").pack(anchor="w")

        # Timer
        tf = tk.Frame(body, bg=C_WHITE)
        tf.pack(fill="x", pady=(0, 6))
        tf.configure(highlightthickness=1, highlightbackground="#e5e7eb")
        self.timer_label = tk.Label(tf, text="00:00:00",
                                     font=("Segoe UI", 40, "bold"),
                                     fg=C_BLUE, bg=C_WHITE)
        self.timer_label.pack(pady=14)

        # Status label
        self.status_label = tk.Label(body, text="● Klaar om te starten",
                                      font=("Segoe UI", 10, "bold"),
                                      fg="#9ca3af", bg=C_BG)
        self.status_label.pack(pady=(4, 12))

        # ── Knoppen rij ──────────────────────────────────────────────────────
        btn_frame = tk.Frame(body, bg=C_BG)
        btn_frame.pack(fill="x", pady=(0, 14))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)

        # START knop
        self.btn_start = tk.Button(
            btn_frame, text="▶\nSTART",
            font=("Segoe UI", 11, "bold"),
            fg="white", bg=C_GREEN,
            activeforeground="white", activebackground="#16a34a",
            relief="flat", cursor="hand2", pady=12,
            command=self._start_tracking)
        self.btn_start.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        # PAUZE knop
        self.btn_pause = tk.Button(
            btn_frame, text="⏸\nPAUZE",
            font=("Segoe UI", 11, "bold"),
            fg="white", bg="#d1d5db",
            activeforeground="white", activebackground=C_ORANGE,
            relief="flat", cursor="hand2", pady=12,
            state="disabled",
            command=self._toggle_pause)
        self.btn_pause.grid(row=0, column=1, padx=5, sticky="ew")

        # STOP knop
        self.btn_stop = tk.Button(
            btn_frame, text="⏹\nSTOP",
            font=("Segoe UI", 11, "bold"),
            fg="white", bg="#d1d5db",
            activeforeground="white", activebackground="#b91c1c",
            relief="flat", cursor="hand2", pady=12,
            state="disabled",
            command=self._stop_tracking)
        self.btn_stop.grid(row=0, column=2, padx=(5, 0), sticky="ew")

        # Activiteits balk
        tk.Label(body, text="Activiteitsniveau", font=("Segoe UI", 9, "bold"),
                 fg="#6b7280", bg=C_BG).pack(anchor="w", pady=(4, 3))
        self.activity_var = tk.IntVar(value=0)
        style = ttk.Style()
        style.theme_use("default")
        style.configure("act.Horizontal.TProgressbar",
                         troughcolor="#e5e7eb", background=C_GREEN, thickness=10)
        ttk.Progressbar(body, variable=self.activity_var, maximum=100,
                         style="act.Horizontal.TProgressbar").pack(fill="x")
        self.activity_label = tk.Label(body, text="0%",
                                        font=("Segoe UI", 9), fg="#6b7280", bg=C_BG)
        self.activity_label.pack(anchor="e")

        # Screenshot info
        self.ss_label = tk.Label(body, text="",
                                  font=("Segoe UI", 9), fg="#9ca3af", bg=C_BG)
        self.ss_label.pack(pady=(6, 0))

        # Uitloggen
        tk.Button(body, text="Uitloggen",
                  font=("Segoe UI", 9), fg="#9ca3af", bg=C_BG,
                  relief="flat", cursor="hand2",
                  command=self._uitloggen).pack(pady=(10, 0))

    # ══════════════════════════════════════════════════════════════════════════
    #   TRACKING – START / PAUZE / STOP
    # ══════════════════════════════════════════════════════════════════════════

    def _start_tracking(self):
        try:
            r = requests.post(
                f"{config.SERVER_URL}/api/session/start",
                json={"user_id": self.user_id, "email": self.user_email, "name": self.user_name},
                timeout=5)
            self.session_id = r.json().get("session_id")
        except Exception:
            self.session_id = f"offline_{int(time.time())}"

        self.is_tracking  = True
        self.is_paused    = False
        self.start_time   = datetime.datetime.now()
        self.total_paused = 0

        self.btn_start.config(state="disabled", bg="#d1d5db")
        self.btn_pause.config(state="normal",   bg=C_ORANGE, activebackground="#ea580c")
        self.btn_stop.config( state="normal",   bg=C_RED,    activebackground="#b91c1c")
        self.status_label.config(text="● Aan het werk", fg=C_GREEN)

        threading.Thread(target=self._screenshot_loop, daemon=True).start()
        self._update_timer()

    def _toggle_pause(self):
        if not self.is_paused:
            # → Pauzeren
            self.is_paused  = True
            self.paused_at  = datetime.datetime.now()
            self.btn_pause.config(text="▶\nHERVAT", bg=C_GREEN, activebackground="#16a34a")
            self.status_label.config(text="⏸ Gepauzeerd", fg=C_ORANGE)
            self.timer_label.config(fg=C_ORANGE)
        else:
            # → Hervatten
            if self.paused_at:
                paused_secs    = (datetime.datetime.now() - self.paused_at).total_seconds()
                self.total_paused += paused_secs
            self.is_paused  = False
            self.paused_at  = None
            self.btn_pause.config(text="⏸\nPAUZE", bg=C_ORANGE, activebackground="#ea580c")
            self.status_label.config(text="● Aan het werk", fg=C_GREEN)
            self.timer_label.config(fg=C_BLUE)

    def _stop_tracking(self):
        if messagebox.askyesno("Stoppen?", "Wil je de tracking stoppen?", parent=self.root):
            self.is_tracking = False
            self.is_paused   = False

            try:
                requests.post(f"{config.SERVER_URL}/api/session/stop",
                              json={"session_id": self.session_id}, timeout=5)
            except Exception:
                pass

            self.session_id   = None
            self.start_time   = None
            self.total_paused = 0

            self.btn_start.config(state="normal",    bg=C_GREEN)
            self.btn_pause.config(state="disabled",  bg="#d1d5db", text="⏸\nPAUZE")
            self.btn_stop.config( state="disabled",  bg="#d1d5db")
            self.status_label.config(text="● Gestopt", fg="#9ca3af")
            self.timer_label.config(text="00:00:00",  fg=C_BLUE)
            self.activity_var.set(0)
            self.activity_label.config(text="0%")
            self.ss_label.config(text="")

    def _update_timer(self):
        if not self.is_tracking:
            return
        if self.is_paused:
            # Timer staat stil — check elke seconde opnieuw
            self.root.after(1000, self._update_timer)
            return
        elapsed = datetime.datetime.now() - self.start_time
        netto   = int(elapsed.total_seconds() - self.total_paused)
        netto   = max(0, netto)
        h, rem  = divmod(netto, 3600)
        m, s    = divmod(rem, 60)
        self.timer_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._update_timer)

    # ══════════════════════════════════════════════════════════════════════════
    #   ACTIVITEIT
    # ══════════════════════════════════════════════════════════════════════════

    def _start_activity_monitor(self):
        try:
            from pynput import mouse as pm, keyboard as pk
            pm.Listener(
                on_move=lambda *_:  setattr(self, 'mouse_events', self.mouse_events + 1),
                on_click=lambda *_: setattr(self, 'mouse_events', self.mouse_events + 1)
            ).start()
            pk.Listener(
                on_press=lambda *_: setattr(self, 'key_events', self.key_events + 1)
            ).start()
        except Exception:
            pass

    def _get_activity(self) -> int:
        interval_sec = config.SCREENSHOT_INTERVAL * 60
        total        = self.mouse_events + self.key_events * 3
        pct          = min(100, int(total / max(interval_sec * 5, 1) * 100))
        self.mouse_events = 0
        self.key_events   = 0
        return pct

    # ══════════════════════════════════════════════════════════════════════════
    #   SCREENSHOTS
    # ══════════════════════════════════════════════════════════════════════════

    def _screenshot_loop(self):
        # Wacht het eerste interval
        for _ in range(config.SCREENSHOT_INTERVAL * 60):
            if not self.is_tracking:
                return
            time.sleep(1)

        while self.is_tracking:
            # Geen screenshot als gepauzeerd
            if not self.is_paused:
                self._take_screenshot()
            # Wacht volgend interval
            for _ in range(config.SCREENSHOT_INTERVAL * 60):
                if not self.is_tracking:
                    return
                time.sleep(1)

    def _take_screenshot(self):
        try:
            img      = ImageGrab.grab()
            w, h     = img.size
            img      = img.resize((w // 2, h // 2), Image.LANCZOS)
            buf      = io.BytesIO()
            img.save(buf, format="JPEG", quality=config.SCREENSHOT_QUALITY)
            img_b64  = base64.b64encode(buf.getvalue()).decode()
            activity = self._get_activity()

            requests.post(
                f"{config.SERVER_URL}/api/screenshot",
                json={
                    "session_id": self.session_id,
                    "user_id":    self.user_id,
                    "email":      self.user_email,
                    "name":       self.user_name,
                    "image":      img_b64,
                    "activity":   activity,
                },
                timeout=15,
            )

            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.ss_label.config(text=f"📸  Screenshot: {ts}")
            self.activity_var.set(activity)
            self.activity_label.config(text=f"{activity}%")
        except Exception as e:
            print(f"Screenshot fout: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    #   HULP
    # ══════════════════════════════════════════════════════════════════════════

    def _uitloggen(self):
        if self.is_tracking:
            if not messagebox.askyesno("Uitloggen", "Tracking is actief. Stoppen en uitloggen?", parent=self.root):
                return
            self._stop_tracking()
        self.logged_in  = False
        self.user_id    = None
        self.user_name  = None
        self.user_email = None
        self._build_login_ui()

    def _clear_window(self):
        for w in self.root.winfo_children():
            w.destroy()

    def on_close(self):
        if self.is_tracking:
            if messagebox.askyesno("Afsluiten", "Tracking is actief. Stoppen en afsluiten?", parent=self.root):
                self.is_tracking = False
                try:
                    requests.post(f"{config.SERVER_URL}/api/session/stop",
                                  json={"session_id": self.session_id}, timeout=3)
                except Exception:
                    pass
                self.root.destroy()
        else:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    TrackerApp(root)
    root.mainloop()
