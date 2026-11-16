"""Download-Manager: Tkinter-Hauptfenster (deutsche Oberflaeche).

Zeigt alle Katalog-Apps gruppiert nach Kategorie, mit Suche,
Mehrfachauswahl und Installations-Fortschritt im Hintergrund-Thread.
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from . import catalog as cat
from . import installer
from . import launcher
from . import settings as cfg


def _fmt_size(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.1f} MB"
    if n >= 1e3:
        return f"{n / 1e3:.0f} KB"
    return f"{n} B"


class DownloadManager(tk.Toplevel):
    def __init__(self, master=None, autostart_tray=None):
        super().__init__(master)
        self.title("PortableHub - Download-Manager")
        self.geometry("980x600")
        self._apps = []            # gefilterte Katalog-Apps
        self._all_apps = []        # kompletter Katalog
        self._installed = {}
        self._checked = set()      # app_ids zum Installieren/Updaten
        self._uninstall_checked = set()
        self._job_queue = queue.Queue()
        self._cancel = threading.Event()
        self._worker = None
        self._busy = False
        self._source = "empty"

        self._build_ui()
        self.refresh_catalog(background=True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="Suche:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._rebuild_tree())
        ttk.Entry(top, textvariable=self.search_var, width=30).pack(side="left", padx=6)

        self.source_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.source_var, foreground="gray").pack(side="left", padx=12)

        ttk.Button(top, text="Katalog aktualisieren", command=self.refresh_catalog).pack(side="right")

        # Treeview
        cols = ("auswahl", "name", "status", "groesse", "beschreibung")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Kategorie")
        self.tree.heading("auswahl", text="")
        self.tree.heading("name", text="Name")
        self.tree.heading("status", text="Status")
        self.tree.heading("groesse", text="Grösse")
        self.tree.heading("beschreibung", text="Beschreibung")
        self.tree.column("#0", width=140, minwidth=80)
        self.tree.column("auswahl", width=40, anchor="center", stretch=False)
        self.tree.column("name", width=160, minwidth=100)
        self.tree.column("status", width=130, minwidth=90)
        self.tree.column("groesse", width=80, anchor="e", stretch=False)
        self.tree.column("beschreibung", width=300, minwidth=150)
        self.tree.tag_configure("update", foreground="#b06000")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        # Klick auf Auswahl-Spalte schaltet Checkbox um
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", lambda e: self._toggle_selected())

        # Buttons
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=4)
        ttk.Button(btns, text="Installieren / Aktualisieren", command=self.install_selected).pack(side="left")
        ttk.Button(btns, text="Deinstallieren", command=self.uninstall_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Alle Updates installieren", command=self.install_all_updates).pack(side="left", padx=4)
        ttk.Button(btns, text="Startmenü öffnen", command=self._open_menu).pack(side="right")
        ttk.Button(btns, text="Beenden", command=self._quit_app).pack(side="right", padx=4)

        # Fortschritt
        prog = ttk.Frame(self)
        prog.pack(fill="x", padx=8, pady=4)
        self.progress = ttk.Progressbar(prog, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_var = tk.StringVar(value="Bereit")
        ttk.Label(prog, textvariable=self.status_var, width=45).pack(side="left", padx=6)
        self.cancel_btn = ttk.Button(prog, text="Abbrechen", command=self._cancel_job, state="disabled")
        self.cancel_btn.pack(side="left")

        self.after(100, self._poll_queue)

    # ---------- Daten ----------

    def refresh_catalog(self, background=False):
        if background:
            threading.Thread(target=self._load_catalog_thread, daemon=True).start()
        else:
            self._load_catalog_thread()

    def _load_catalog_thread(self):
        try:
            result = cat.load_catalog(self._settings())
        except Exception as e:
            result = {"apps": [], "source": "empty", "error": str(e)}
        self._job_queue.put(("catalog", result))

    @staticmethod
    def _settings():
        return cfg.load_settings()

    def _apply_catalog(self, result):
        self._source = result.get("source", "empty")
        self._all_apps = cat.apps_for_platform({"apps": result.get("apps", [])})
        self._installed = cfg.load_installed()
        labels = {"net": "Katalog: online", "cache": "Katalog: Cache (offline)", "empty": "Kein Katalog verfügbar"}
        self.source_var.set(labels.get(self._source, self._source))
        self._rebuild_tree()

    def _filter(self, app):
        q = self.search_var.get().strip().lower()
        if not q:
            return True
        hay = " ".join(str(app.get(k, "")) for k in ("name", "description", "category", "id")).lower()
        return q in hay

    def _rebuild_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._apps = [a for a in self._all_apps if self._filter(a)]
        # nach Kategorie gruppieren
        cats = {}
        for a in self._apps:
            cats.setdefault(a.get("category") or "Sonstiges", []).append(a)
        for cname in sorted(cats):
            cat_node = self.tree.insert("", "end", text=cname, values=("", "", "", ""), open=True)
            for a in sorted(cats[cname], key=lambda x: x.get("name", "")):
                status = cat.app_status(a, self._installed)
                status_txt = {
                    "installiert": f"Installiert ({self._installed[a['id']].get('version','?')})",
                    "update": f"Update: {self._installed[a['id']].get('version','?')} → {a.get('version','?')}",
                    "nicht installiert": "Nicht installiert",
                }[status]
                checked = "☑" if a["id"] in self._checked or a["id"] in self._uninstall_checked else "☐"
                tags = ("update",) if status == "update" else ()
                self.tree.insert(cat_node, "end", iid=f"app:{a['id']}", text="",
                                 values=(checked, a.get("name", a["id"]), status_txt,
                                         _fmt_size(a.get("size")), a.get("description", "")),
                                 tags=tags)

    # ---------- Auswahl ----------

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or not iid.startswith("app:"):
            return
        col = self.tree.identify_column(event.x)
        # erste Spalte (auswahl) ist #1
        if col == "#1":
            self._toggle_app(iid[4:])
            return "break"

    def _toggle_app(self, app_id):
        if app_id in self._checked:
            self._checked.discard(app_id)
            self._uninstall_checked.discard(app_id)
        elif app_id in self._uninstall_checked:
            self._uninstall_checked.discard(app_id)
        else:
            # Status entscheidet: installierte Apps zum Deinstallieren markieren
            app = next((a for a in self._apps if a["id"] == app_id), None)
            status = cat.app_status(app, self._installed) if app else "nicht installiert"
            if status == "installiert":
                self._uninstall_checked.add(app_id)
            else:
                self._checked.add(app_id)
        self._rebuild_tree()

    def _toggle_selected(self):
        for iid in self.tree.selection():
            if iid.startswith("app:"):
                self._toggle_app(iid[4:])

    # ---------- Aktionen ----------

    def install_selected(self):
        apps = [a for a in self._apps if a["id"] in self._checked]
        if not apps:
            messagebox.showinfo("PortableHub", "Keine Apps ausgewählt.")
            return
        for a in apps:
            warn = installer.check_disk_space(a)
            if warn:
                if not messagebox.askyesno("Wenig Speicher", f"{a['name']}: {warn}\nTrotzdem fortfahren?"):
                    continue
            self._job_queue.put(("install", a))
        self._start_worker()

    def install_all_updates(self):
        apps = [a for a in self._all_apps if cat.app_status(a, self._installed) == "update"]
        if not apps:
            messagebox.showinfo("PortableHub", "Keine Updates verfügbar.")
            return
        for a in apps:
            self._job_queue.put(("install", a))
        self._start_worker()

    def uninstall_selected(self):
        ids = [i for i in self._uninstall_checked]
        if not ids:
            messagebox.showinfo("PortableHub", "Keine installierten Apps ausgewählt.")
            return
        names = [self._installed.get(i, {}).get("name", i) for i in ids]
        if not messagebox.askyesno("Deinstallieren",
                                   "Folgende Apps wirklich entfernen (inkl. Benutzerdaten)?\n\n"
                                   + "\n".join(names)):
            return
        for i in ids:
            self._job_queue.put(("uninstall", i))
        self._start_worker()

    def _start_worker(self):
        if self._busy:
            return
        self._busy = True
        self._cancel.clear()
        self.cancel_btn.config(state="normal")
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                kind, payload = self._job_queue.get_nowait()
            except queue.Empty:
                break
            if self._cancel.is_set():
                self._job_queue.put(("done_cancelled", None))
                break
            try:
                if kind == "install":
                    self._job_queue.put(("progress", ("installiere", payload["name"], 0, None)))
                    installer.install_app(
                        payload,
                        progress=lambda phase, done, total: self._job_queue.put(
                            ("progress", (phase, payload["name"], done, total))),
                        cancel=self._cancel,
                    )
                    self._job_queue.put(("progress", ("fertig", payload["name"], 1, 1)))
                elif kind == "uninstall":
                    installer.uninstall_app(payload)
                    self._job_queue.put(("progress", ("entfernt", payload, 1, 1)))
            except installer.InstallError as e:
                self._job_queue.put(("error", (payload.get("name", payload), str(e))))
        self._job_queue.put(("all_done", None))

    def _cancel_job(self):
        self._cancel.set()
        self.status_var.set("Abbruch wird ausgeführt …")

    def _poll_queue(self):
        try:
            while True:
                msg = self._job_queue.get_nowait()
                kind, payload = msg
                if kind == "catalog":
                    self._apply_catalog(payload)
                elif kind == "progress":
                    phase, name, done, total = payload
                    if phase == "download":
                        if total:
                            pct = done / total * 100
                            self.progress.config(mode="determinate", value=pct)
                            self.status_var.set(f"{name}: {done/1e6:.1f} / {total/1e6:.1f} MB")
                        else:
                            self.progress.config(mode="indeterminate")
                            self.progress.start(10)
                            self.status_var.set(f"{name}: lade …")
                    elif phase == "installiere":
                        self.progress.stop()
                        self.progress.config(mode="indeterminate", value=0)
                        self.progress.start(10)
                        self.status_var.set(f"{name}: entpacke und installiere …")
                    else:
                        self.progress.stop()
                        self.progress.config(mode="determinate", value=100)
                        self.status_var.set(f"{name}: {phase}")
                elif kind == "error":
                    name, err = payload
                    self.status_var.set(f"Fehler bei {name}")
                    messagebox.showerror("Installationsfehler", f"{name}:\n{err}")
                elif kind == "done_cancelled":
                    self.status_var.set("Abgebrochen")
                elif kind == "all_done":
                    self._busy = False
                    self._cancel.clear()
                    self.cancel_btn.config(state="disabled")
                    self.progress.stop()
                    self._installed = cfg.load_installed()
                    self._checked.clear()
                    self._uninstall_checked.clear()
                    self._rebuild_tree()
                    self.status_var.set("Fertig")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ---------- Sonstiges ----------

    def _open_menu(self):
        from . import menu
        menu.show_menu_window(self)

    def _on_close(self):
        # Fenster schliessen, Tray bleibt (falls aktiv)
        self.destroy()

    def _quit_app(self):
        self._cancel.set()
        self.destroy()
        if hasattr(self.master, "quit"):
            self.master.quit()
