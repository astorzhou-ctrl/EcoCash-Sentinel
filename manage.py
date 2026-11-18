"""Administrator command line:  py manage.py <command>
  reset-admin         new temporary password for 'admin' (unlocks and reactivates it)
  unlock <username>   unlock a locked account
  list-users          show all users and their status
  verify-audit        check the tamper-evident audit chain
  reset-mfa <username>  switch off two-step sign-in for a user who lost the device (they set it up again)
  ai-off              kill switch: switch all AI off at once (add --remove-key to delete the stored API key as well)
  backups             list the backups and check each one
  restore <name>      put a backup back (stop Sentinel first; asks you to type RESTORE)
"""
import datetime
import hashlib
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import config, core, db as dbm, server  # noqa: E402

BD = os.path.join(config.DATA, "backups")


def check_backup(path):
    stored = open(path + ".sha256").read().strip() if os.path.isfile(path + ".sha256") else None
    ok_hash = stored == hashlib.sha256(open(path, "rb").read()).hexdigest()
    con = sqlite3.connect(path)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        users, risks = con.execute("SELECT COUNT(*) FROM users").fetchone()[0], con.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
    finally:
        con.close()
    return ok_hash and integrity == "ok", ok_hash, integrity, users, risks


def backups_cmd(argv):
    """Backups are handled before the database is opened, so a restore never touches a database that is in use."""
    if argv[1] == "backups":
        names = sorted((f for f in os.listdir(BD) if f.endswith(".db")), reverse=True) if os.path.isdir(BD) else []
        for n in names:
            ok, h, i, u, r = check_backup(os.path.join(BD, n)); print("%s  %s  %d users, %d risks" % ("GOOD   " if ok else "PROBLEM", n, u, r))
        print("%d backup(s) in %s" % (len(names), BD)); return 0
    if len(argv) != 3:
        print(__doc__); return 1
    src = os.path.join(BD, os.path.basename(argv[2]))
    if not os.path.isfile(src):
        print("There is no backup called %s in %s" % (argv[2], BD)); return 1
    ok, h, i, u, r = check_backup(src)
    if not ok:
        print("This backup is NOT good (%s). Nothing was changed." % ("the file has changed since it was taken" if not h else "the database is damaged: " + i)); return 1
    try:  # Sentinel must be stopped: take the database lock
        lock = sqlite3.connect(config.DB_PATH, timeout=1); lock.execute("BEGIN EXCLUSIVE"); lock.rollback(); lock.close()
    except sqlite3.OperationalError:
        print("Sentinel is still running. Press Ctrl+C in its window first, then try again."); return 1
    print("Backup %s holds %d users and %d risks." % (argv[2], u, r))
    if input("Type RESTORE to replace the current data with it: ").strip() != "RESTORE":
        print("Cancelled. Nothing was changed."); return 1
    keep = os.path.join(BD, "sentinel_%s_pre-restore.db" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    a, b = sqlite3.connect(config.DB_PATH), sqlite3.connect(keep); a.backup(b); a.close(); b.close()
    open(keep + ".sha256", "w").write(hashlib.sha256(open(keep, "rb").read()).hexdigest())
    for ext in ("-wal", "-shm"):
        if os.path.exists(config.DB_PATH + ext):
            os.remove(config.DB_PATH + ext)
    shutil.copyfile(src, config.DB_PATH)
    print("Restored. The data you replaced is kept as %s. Start Sentinel again with py run.py" % os.path.basename(keep)); return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if argv[1] in ("backups", "restore"):
        return backups_cmd(argv)
    server.prepare()
    c = dbm.connect()
    try:
        cmd = argv[1]
        if cmd == "reset-admin":
            u = core.get_user(c, "admin")
            if not u:
                print("No user named admin exists."); return 1
            pw = core.issue_temp_password(c, u, None, "console", "user.password_reset")
            c.execute("UPDATE users SET status='invited' WHERE id=? AND last_login_at IS NULL", (u["id"],))
            c.commit()
            print("Temporary password for admin (valid 48 hours, must be changed at sign-in):\n    %s" % pw)
        elif cmd == "unlock" and len(argv) > 2:
            u = core.get_user(c, argv[2])
            if not u:
                print("User not found."); return 1
            c.execute("UPDATE users SET status=?, failed_attempts=0, locked_at=NULL WHERE id=?", ("invited" if not u["last_login_at"] else "active", u["id"]))
            c.execute("DELETE FROM login_attempts")
            core.audit(c, "user.unlocked", None, "access_management", "Unlocked %s from the console" % u["username"], "console", "console")
            c.commit(); print("Unlocked %s." % u["username"])
        elif cmd == "ai-off":
            import json as _j
            from sentinel import ai_gov
            st = ai_gov.settings(c); st["mode"] = "off"; st["changed_by"], st["changed_at"] = "console", core.now(); ai_gov.save_settings(c, st)
            if "--remove-key" in argv:
                c.execute("DELETE FROM settings WHERE key='ai_key'")
            core.audit(c, "ai.kill_switch", None, "ai_governance", "KILL SWITCH from the console: all AI switched off%s" % (" and the key removed" if "--remove-key" in argv else ""), "console", "console")
            c.commit(); print("All AI is switched off.%s" % (" The stored API key was removed." if "--remove-key" in argv else ""))
        elif cmd == "reset-mfa" and len(argv) > 2:
            u = core.get_user(c, argv[2])
            if not u:
                print("User not found."); return 1
            c.execute("UPDATE users SET mfa_enabled=0, mfa_secret=NULL, mfa_recovery=NULL, mfa_last_step=NULL WHERE id=?", (u["id"],))
            core.revoke_sessions(c, u["id"], "second factor reset")
            core.audit(c, "auth.mfa_reset", None, "access_management", "Second factor of %s reset from the console" % u["username"], "console", "console")
            c.commit(); print("Two-step sign-in switched off for %s. If their role requires it they will set it up again at the next sign-in." % u["username"])
        elif cmd in ("demo-load", "demo-remove"):
            from sentinel import demo_seed
            n = demo_seed.load(c) if cmd == "demo-load" else demo_seed.remove(c)
            c.commit(); print("Demonstration data %s: %d records." % ("loaded" if cmd == "demo-load" else "removed", n))
        elif cmd == "list-users":
            for u in c.execute("SELECT username,full_name,status,last_login_at FROM users WHERE deleted_at IS NULL ORDER BY username"):
                print("%-20s %-28s %-12s %s" % (u["username"], u["full_name"], u["status"], u["last_login_at"] or "never"))
        elif cmd == "verify-audit":
            r = core.verify_audit(c)
            print("Audit chain intact (%d entries)." % r["checked"] if r["ok"] else "AUDIT CHAIN BROKEN at entry %s." % r["broken_at"])
        else:
            print(__doc__); return 1
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
