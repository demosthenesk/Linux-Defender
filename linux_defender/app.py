"""Entry point: argument parsing, single instance, QApplication bootstrap."""
import argparse
import json
import os
import signal
import sys

from linux_defender import APP_ID, APP_NAME, VERSION


def parse_args(argv):
    p = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME} {VERSION} — antivirus for Linux")
    p.add_argument("--scan", nargs="+", metavar="PATH", help="scan files/folders (opens the scan window)")
    p.add_argument("--quick-scan", action="store_true", help="start a Quick Scan")
    p.add_argument("--system-scan", action="store_true", help="start a System Scan")
    p.add_argument("--update", action="store_true", help="update threat signatures")
    p.add_argument("--tray", action="store_true", help="start minimized in the system tray")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    p.add_argument("paths", nargs="*", help="files/folders to scan (same as --scan)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    # -- single instance: forward the request to a running instance ---------------
    from linux_defender import paths
    server_name = paths.instance_socket()
    request = {"scan": [os.path.abspath(p) for p in (args.scan or []) + args.paths], "quick": args.quick_scan,
               "system": args.system_scan, "update": args.update, "show": not args.tray}
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(1500):
        sock.write(json.dumps(request).encode())
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0

    from linux_defender.controller import Controller
    from linux_defender.ui.main_window import MainWindow, Onboarding

    ctl = Controller()
    win = MainWindow(ctl)

    def handle(req):
        if req.get("show"):
            win.show_normal()
        if req.get("scan"):
            run_when_ready(lambda: win.start_scan("custom", req["scan"]))
        elif req.get("quick"):
            run_when_ready(lambda: win.start_scan("quick"))
        elif req.get("system"):
            run_when_ready(lambda: win.start_scan("system"))
        if req.get("update"):
            ctl.update_now()

    def run_when_ready(fn, waited=0):
        """Run fn once the scan engine is ready; wait while it starts or loads signatures (up to 3 minutes)."""
        from linux_defender import engine as eng
        if ctl.engine.ready:
            fn()
        elif ctl.engine.state in (eng.STATE_LOADING, eng.STATE_STOPPED) and waited < 180:
            QTimer.singleShot(1000, lambda: run_when_ready(fn, waited + 1))
        else:
            fn()          # shows the reason it can't scan

    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(server_name):
        print(f"{APP_NAME}: can't listen on {server_name}: {server.errorString()} — "
              "file-manager scans will open another window", file=sys.stderr)

    def on_conn():
        c = server.nextPendingConnection()

        def read():
            try:
                handle(json.loads(bytes(c.readAll()).decode() or "{}"))
            except ValueError:
                pass
        c.readyRead.connect(read)
    server.newConnection.connect(on_conn)

    signal.signal(signal.SIGINT, lambda *_: win.quit())
    signal.signal(signal.SIGTERM, lambda *_: win.quit())
    keepalive = QTimer()
    keepalive.start(500)
    keepalive.timeout.connect(lambda: None)

    ctl.start()
    start_hidden = args.tray or ctl.settings.get("general.start_minimized")
    if not start_hidden or not hasattr(win, "tray"):
        win.show()
    if not ctl.settings.get("first_run_done"):
        win.show_normal()
        ob = Onboarding(ctl, win)
        ob.exec()
        ctl.settings.set("first_run_done", True)
        win.refresh()
    handle({**request, "show": False})
    rc = app.exec()
    return rc
