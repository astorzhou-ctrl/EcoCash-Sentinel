"""Start-up: prepare the database and serve the WSGI app with a threaded standard-library server."""
import os
import socketserver
import threading
import time
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from . import api, config, core, db as dbm, web


class ThreadedServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = (os.name != "nt")  # on Windows this option would let a second copy share the port
    request_queue_size = 64


class Quiet(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        if os.environ.get("SENTINEL_LOG") == "1":
            super().log_message(fmt, *args)


def prepare():
    """Create tables, roles and (on first run) the administrator. Returns the first-run admin password or None."""
    dbm.init_schema()
    c = dbm.connect()
    try:
        pw = core.seed(c)
        api.purge_expired(c)
        from . import p1
        p1.seed_appetite(c)
        p1.load_thresholds(c)
        core.migrate_roles(c)
        core.migrate_ai_roles(c)
        core.migrate_adv_roles(c)
        core.migrate_kit_roles(c)
        from . import ai_gov
        ai_gov.add_default_sources(c)
        from . import depts
        depts.seed(c)
        c.commit()
    finally:
        c.close()
    if pw:
        with open(os.path.join(config.DATA, "FIRST_RUN_ADMIN.txt"), "w", encoding="utf-8") as f:
            f.write("Sentinel first administrator\nUsername: admin\nTemporary password: %s\nYou must change it at first sign-in (valid 48 hours).\nDelete this file after use.\n" % pw)
    return pw


def _purge_loop():
    while True:
        time.sleep(3600)
        try:
            c = dbm.connect()
            with web.hold("server #1"):
                api.purge_expired(c)
                c.commit()
            c.close()
        except Exception:
            pass


def _kpi_loop():
    """Once a day, after 06:00 local time: Sentinel's own KPI measures, then the approved feeds (see Weekly KPI > Sources and automation)."""
    time.sleep(30)
    while True:
        try:
            if time.localtime().tm_hour >= 6:
                from . import p2
                c = dbm.connect()
                try:
                    with web.hold("server #2"):
                        p2.daily_job(c)
                        c.commit()
                finally:
                    c.close()
                from . import kpi_auto
                kpi_auto.daily()  # internet research: no lock held while pages download
        except Exception:
            pass
        time.sleep(900)


def make(host=None, port=None):
    app = web.App(api.router)
    srv = make_server(host or config.HOST, port if port is not None else config.PORT, app, server_class=ThreadedServer, handler_class=Quiet)
    return srv


def serve(host=None, port=None):
    srv = make(host, port)
    threading.Thread(target=_purge_loop, daemon=True).start()
    threading.Thread(target=_kpi_loop, daemon=True).start()
    threading.Thread(target=web.watchdog, daemon=True).start()
    from . import live_data
    threading.Thread(target=live_data.loop, daemon=True).start()  # market prices, currencies and stablecoins whenever the computer is online
    from . import ai_horizon
    ai_horizon.start_scheduler()  # horizon scans run only when AI is on, approved and in Advanced mode
    from . import mailer
    mailer.start_scheduler()  # daily reminders, queued messages and scheduled reports: nothing is sent until an administrator switches e-mail on
    srv.serve_forever()
