"""Startmenue: Tray-Icon (Windows) und Kachel-Fenster-Modus.

Tray: reines ctypes (Shell_NotifyIconW), keine Zusatzpakete noetig.
Menueeintraege: Kategorien als Untermenues mit installierten Apps.
Klick startet die App mit Arbeitsverzeichnis = App-Ordner.
"""

import ctypes
import ctypes.wintypes as wt
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from . import catalog as cat
from . import launcher
from . import settings as cfg

# ---------- Fenster-Modus (alle Plattformen) ----------

def show_menu_window(parent=None):
    """Oeffnet das Startmenue als Kachel-Fenster."""
    win = tk.Toplevel(parent) if parent else tk.Tk()
    win.title("PortableHub - Startmenü")
    win.geometry("720x480")

    canvas = tk.Canvas(win, highlightthickness=0)
    scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units"))

    _fill_menu_frame(inner)
    return win


def _fill_menu_frame(parent):
    for w in parent.winfo_children():
        w.destroy()
    installed = cfg.load_installed()
    if not installed:
        tk.Label(parent, text="Keine Apps installiert.\nDownload-Manager zum Installieren oeffnen.",
                 font=("Segoe UI", 12), fg="gray").pack(pady=40)
        return
    catalog = cat.load_catalog_offline()
    catmap = {a["id"]: a for a in catalog.get("apps", [])}
    categories = {}
    for app_id, entry in installed.items():
        cname = entry.get("category") or catmap.get(app_id, {}).get("category") or "Sonstiges"
        categories.setdefault(cname, []).append((app_id, entry))

    for cname in sorted(categories):
        tk.Label(parent, text=cname, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=12, pady=(14, 4))
        row = tk.Frame(parent)
        row.pack(fill="x", padx=12)
        for app_id, entry in sorted(categories[cname], key=lambda x: x[1].get("name", x[0])):
            btn = tk.Button(row, text=entry.get("name", app_id), width=18,
                            command=lambda i=app_id: _launch_safe(i))
            btn.pack(side="left", padx=4, pady=4)


def _launch_safe(app_id):
    try:
        launcher.launch(app_id)
    except Exception as e:
        tk.messagebox.showerror("Start fehlgeschlagen", f"{app_id}:\n{e}")


# ---------- Tray (Windows) ----------

WM_TRAY = 0x0400 + 1          # WM_APP+1: Tray-Callback
NIN_SELECT = 0x0400
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIM_MODIFY = 0x00000001
IDI_APPLICATION = 32512
HWND_MESSAGE = -3
WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_NULL = 0x0000
MF_STRING = 0x00000000
MF_GRAYED = 0x00000001
MF_POPUP = 0x00000010
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080
TPM_RIGHTBUTTON = 0x0002
GWLP_WNDPROC = -4
MIIM_BITMAP = 0x00000080
SHGFI_ICON = 0x000000100
SHGFI_SMALLICON = 0x000000001
MAX_PATH = 260

CMD_MANAGER = 1
CMD_RELOAD = 2
CMD_QUIT = 3
CMD_APP_BASE = 1000

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
        ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HANDLE), ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256), ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD), ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wt.HANDLE),
    ]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", wt.POINT)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class TrayIcon:
    """System-Tray-Icon mit Kontextmenue (Windows)."""

    def __init__(self, on_open_manager, on_quit, event_queue=None):
        self.on_open_manager = on_open_manager
        self.on_quit = on_quit
        self.event_queue = event_queue if event_queue is not None else queue.Queue()
        self._hwnd = None
        self._wndproc = None
        self._thread = None
        self._running = False
        self._nid = None

    # --- oeffentlich ---

    def start(self):
        if sys.platform != "win32" or self._running:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    # --- intern ---

    def _run(self):
        # Message-only Fenster fuer Tray-Callbacks
        self._wndproc = WNDPROC(self._wndproc_fn)
        self._hwnd = user32.CreateWindowExW(
            0, "STATIC", "PortableHubTray", 0, 0, 0, 0, 0,
            HWND_MESSAGE, None, kernel32.GetModuleHandleW(None), None)
        if not self._hwnd:
            return
        user32.SetWindowLongPtrW(self._hwnd, GWLP_WNDPROC, ctypes.cast(self._wndproc, ctypes.c_void_p))
        self._add_icon()

        msg = MSG()
        while self._running:
            # PeekMessage-Schleife mit kleinem Sleep
            import time
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                if msg.message == WM_QUIT:
                    self._running = False
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)
                continue
            break
        self._remove_icon()
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def _wndproc_fn(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_RBUTTONUP, WM_LBUTTONUP):
                self._show_menu()
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            self._handle_command(cmd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _add_icon(self):
        icon = user32.LoadIconW(None, IDI_APPLICATION)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = icon
        nid.szTip = "PortableHub"
        user32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._nid = nid
        # Version setzen fuer korrekte Callbacks
        nid.uVersion = 0
        user32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _remove_icon(self):
        if self._nid:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = 1
            user32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self._nid = None

    # --- Menue ---

    def _installed_apps_by_category(self):
        installed = cfg.load_installed()
        catalog = cat.load_catalog_offline()
        catmap = {a["id"]: a for a in catalog.get("apps", [])}
        cats = {}
        for app_id, entry in installed.items():
            cname = (entry.get("category")
                     or catmap.get(app_id, {}).get("category") or "Sonstiges")
            cats.setdefault(cname, []).append((app_id, entry))
        return cats

    def _show_menu(self):
        # Menue bei jedem Aufruf neu aufbauen ("Menue neu laden")
        hmenu = user32.CreatePopupMenu()
        user32.AppendMenuW(hmenu, MF_STRING, CMD_MANAGER, "Download-Manager öffnen")
        user32.AppendMenuW(hmenu, MF_STRING, CMD_RELOAD, "Menü neu laden")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)

        cats = self._installed_apps_by_category()
        cmd_ids = {}
        next_id = CMD_APP_BASE
        for cname in sorted(cats):
            sub = user32.CreatePopupMenu()
            for app_id, entry in sorted(cats[cname], key=lambda x: x[1].get("name", x[0])):
                label = entry.get("name", app_id)
                user32.AppendMenuW(sub, MF_STRING, next_id, label)
                try:
                    exe = launcher.app_exe_path(app_id)
                    _set_menu_icon(sub, user32.GetMenuItemCount(sub) - 1, str(exe))
                except Exception:
                    pass
                cmd_ids[next_id] = app_id
                next_id += 1
            user32.AppendMenuW(hmenu, MF_POPUP, sub, cname)
        if not cats:
            user32.AppendMenuW(hmenu, MF_STRING | 0x00000001, 0, "(keine Apps installiert)")
            # disabled item: einfacher als String mit MF_GRAYED
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, CMD_QUIT, "Beenden")

        user32.SetForegroundWindow(self._hwnd)
        cmd = user32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
                                    _cursor_pos()[0], _cursor_pos()[1], 0, self._hwnd, None)
        user32.DestroyMenu(hmenu)
        if cmd:
            # WM_COMMAND direkt verarbeiten
            user32.SendMessageW(self._hwnd, WM_COMMAND, cmd, 0)
        else:
            user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)

    def _handle_command(self, cmd):
        if cmd == CMD_MANAGER:
            self.event_queue.put(("open_manager", None))
        elif cmd == CMD_RELOAD:
            self._show_menu()
        elif cmd == CMD_QUIT:
            self.event_queue.put(("quit", None))
        elif cmd >= CMD_APP_BASE:
            app_id = self._app_id_for_cmd(cmd)
            if app_id:
                try:
                    launcher.launch(app_id)
                except Exception:
                    pass

    def _app_id_for_cmd(self, cmd):
        # neu aufbauen, um Mapping zu erhalten
        cats = self._installed_apps_by_categories_safe()
        next_id = CMD_APP_BASE
        for cname in sorted(cats):
            for app_id, _entry in sorted(cats[cname], key=lambda x: x[1].get("name", x[0])):
                if next_id == cmd:
                    return app_id
                next_id += 1
        return None

    def _installed_apps_by_categories_safe(self):
        return self._installed_apps_by_category()


def _cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ---------- Menue-Icons (Best Effort) ----------

class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wt.HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
        ("szDisplayName", wt.WCHAR * MAX_PATH), ("szTypeName", wt.WCHAR * 80),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
        ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP),
    ]


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT),
        ("fState", wt.UINT), ("wID", wt.UINT), ("hSubMenu", wt.HANDLE),
        ("hbmpChecked", wt.HANDLE), ("hbmpUnchecked", wt.HANDLE),
        ("dwItemData", ctypes.c_size_t), ("dwTypeData", wt.LPWSTR),
        ("cch", wt.UINT), ("hbmpItem", wt.HANDLE),
    ]


def _exe_icon_bitmap(exe_path: str):
    """Liefert ein HBITMAP mit dem kleinen Icon der Exe (oder None)."""
    try:
        sfi = SHFILEINFOW()
        res = shell32.SHGetFileInfoW(str(exe_path), 0, ctypes.byref(sfi),
                                     ctypes.sizeof(sfi),
                                     SHGFI_ICON | SHGFI_SMALLICON)
        if not res or not sfi.hIcon:
            return None
        info = ICONINFO()
        if not user32.GetIconInfo(sfi.hIcon, ctypes.byref(info)):
            return None
        bmp = info.hbmColor or info.hbmMask
        if not bmp:
            return None
        return bmp
    except Exception:
        return None


def _set_menu_icon(hmenu, position: int, exe_path: str) -> None:
    """Setzt das Bitmap-Icon eines Menuepunkts (position = Index)."""
    bmp = _exe_icon_bitmap(exe_path)
    if not bmp:
        return
    try:
        mii = MENUITEMINFOW()
        mii.cbSize = ctypes.sizeof(MENUITEMINFOW)
        mii.fMask = MIIM_BITMAP
        mii.hbmpItem = bmp
        user32.SetMenuItemInfoW(hmenu, position, True, ctypes.byref(mii))
    except Exception:
        pass
