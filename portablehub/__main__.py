"""Einstiegspunkt: python -m portablehub [--manager|--menu|--tray]"""

import argparse
import sys
import tkinter as tk


def main():
    parser = argparse.ArgumentParser(prog="PortableHub")
    parser.add_argument("--manager", action="store_true", help="nur Download-Manager")
    parser.add_argument("--menu", action="store_true", help="nur Startmenue-Fenster")
    parser.add_argument("--tray", action="store_true", help="nur Tray-Icon")
    args = parser.parse_args()

    from . import gui, menu, settings as cfg

    root = tk.Tk()
    root.withdraw()

    tray = None
    manager = None
    menu_win = None

    event_queue = __import__("queue").Queue()

    def open_manager():
        nonlocal manager
        if manager is None or not manager.winfo_exists():
            manager = gui.DownloadManager(root)
        else:
            manager.deiconify()
            manager.lift()

    def quit_app():
        root.quit()

    # Tray starten (Windows). Unter Linux: Fenster-Modus.
    tray_ok = False
    if sys.platform == "win32" and not args.menu:
        t = menu.TrayIcon(on_open_manager=open_manager, on_quit=quit_app,
                          event_queue=event_queue)
        tray_ok = t.start()
        tray = t if tray_ok else None

    if args.tray and tray is None:
        # Kein Tray unter dieser Plattform: Fenster-Modus
        menu_win = menu.show_menu_window(root)
    elif args.menu or (not tray_ok and not args.manager):
        menu_win = menu.show_menu_window(root)
    else:
        open_manager()

    # Tray-Ereignisse an Tk-Thread weiterreichen
    def poll_events():
        try:
            while True:
                kind, _ = event_queue.get_nowait()
                if kind == "open_manager":
                    open_manager()
                elif kind == "quit":
                    quit_app()
        except __import__("queue").Empty:
            pass
        root.after(200, poll_events)

    poll_events()
    root.mainloop()

    if tray:
        tray.stop()


if __name__ == "__main__":
    main()
