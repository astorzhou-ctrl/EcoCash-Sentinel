"""Start Sentinel:  py run.py   (then open http://127.0.0.1:8000)"""
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import config, server  # noqa: E402


def main():
    if sys.version_info < (3, 9):
        print("Sentinel needs Python 3.9 or newer. Found %s." % sys.version.split()[0])
        return 1
    import socket
    probe = socket.socket()
    if os.name != "nt":
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((config.HOST, config.PORT))
    except OSError:
        print("\nSentinel is ALREADY RUNNING on port %d (another window, or an older copy). Close that window first, or in PowerShell run:" % config.PORT)
        print("    netstat -ano | findstr :%d" % config.PORT)
        print("    taskkill /PID <the number at the end of the line> /F")
        print("Then start Sentinel again. Two copies on one data folder make each other wait.")
        return 1
    finally:
        probe.close()
    pw = server.prepare()
    url = "http://%s:%d/login" % (config.HOST, config.PORT)
    print("=" * 70)
    print(" EcoCash Sentinel %s  -  %s" % (config.VERSION, config.BUILD))
    print(" Process id  : %d" % os.getpid())
    print(" Data folder : %s" % config.DATA)
    print(" Address     : %s" % url)
    if pw:
        print("-" * 70)
        print(" FIRST RUN. Sign in as:  admin   with the temporary password:")
        print("     %s" % pw)
        print(" (also saved in data\\FIRST_RUN_ADMIN.txt). You will be asked to choose a new password.")
    print("=" * 70)
    print(" Keep this window open while you use Sentinel. Press Ctrl+C to stop.")
    if os.environ.get("SENTINEL_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve()
    except KeyboardInterrupt:
        print("\nSentinel stopped.")
    except OSError as e:
        print("\nCould not start the server: %s\nIf port %d is busy, set SENTINEL_PORT=8001 and run again." % (e, config.PORT))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
