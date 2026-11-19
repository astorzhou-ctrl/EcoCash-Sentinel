"""SQLite access: one short-lived connection per request, schema creation and time helpers."""
import datetime
import json
import os
import sqlite3

from . import config

UTC = datetime.timezone.utc
FMT = "%Y-%m-%dT%H:%M:%SZ"


def now():
    return datetime.datetime.now(UTC).strftime(FMT)


def plus(minutes=0, hours=0, days=0):
    return (datetime.datetime.now(UTC) + datetime.timedelta(minutes=minutes, hours=hours, days=days)).strftime(FMT)


def minus(minutes=0, hours=0, days=0):
    return plus(-minutes, -hours, -days)


def today():
    return (datetime.datetime.now(UTC) + datetime.timedelta(hours=config.TZ_HOURS)).date()


def parse(s):
    if not s:
        return None
    return datetime.datetime.strptime(s, FMT).replace(tzinfo=UTC)


def connect():
    os.makedirs(config.DATA, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name TEXT NOT NULL, email TEXT, phone TEXT, department TEXT, job_title TEXT,
  status TEXT NOT NULL DEFAULT 'invited',           -- invited, active, locked, deactivated, deleted
  password_hash TEXT NOT NULL, password_changed_at TEXT, must_change INTEGER NOT NULL DEFAULT 1, temp_expires_at TEXT,
  failed_attempts INTEGER NOT NULL DEFAULT 0, locked_at TEXT, last_login_at TEXT, last_login_ip TEXT,
  access_expires TEXT, data_scope TEXT NOT NULL DEFAULT 'own', timezone TEXT DEFAULT 'Africa/Harare', prefs TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, created_by INTEGER, deleted_at TEXT, deleted_by INTEGER, delete_reason TEXT);
CREATE TABLE IF NOT EXISTS roles(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT,
  is_system INTEGER NOT NULL DEFAULT 0, permissions TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_roles(
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY(user_id, role_id));
CREATE TABLE IF NOT EXISTS password_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, last_seen TEXT NOT NULL, expires_at TEXT NOT NULL, ip TEXT, user_agent TEXT, revoked_at TEXT, revoked_reason TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id INTEGER, username TEXT, event TEXT NOT NULL, module TEXT, detail TEXT, ip TEXT,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS ix_audit_event ON audit(event);
CREATE TABLE IF NOT EXISTS reset_tokens(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, first_at TEXT NOT NULL, last_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recycle(
  id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, title TEXT, module TEXT,
  deleted_by INTEGER, deleted_by_name TEXT, deleted_at TEXT NOT NULL, reason TEXT, purge_at TEXT NOT NULL, payload TEXT, restored_at TEXT);
CREATE TABLE IF NOT EXISTS risks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, title TEXT NOT NULL, description TEXT, category TEXT, function TEXT, objective TEXT,
  owner_id INTEGER, owner_name TEXT, root_cause TEXT, implication TEXT, treatment TEXT, action_date TEXT, review_date TEXT,
  inh_l INTEGER NOT NULL, inh_c INTEGER NOT NULL, res_l INTEGER NOT NULL, res_c INTEGER NOT NULL, tgt_l INTEGER, tgt_c INTEGER,
  emv_i REAL, status TEXT NOT NULL DEFAULT 'draft', needs_board INTEGER NOT NULL DEFAULT 0, is_sample INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, created_by INTEGER, updated_at TEXT, updated_by INTEGER, deleted_at TEXT, deleted_by INTEGER, delete_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_risks_cat ON risks(category);
CREATE TABLE IF NOT EXISTS risk_controls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE, ref TEXT, statement TEXT NOT NULL,
  domain TEXT, ctype TEXT, ice REAL, owner TEXT, last_test TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS risk_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE, ts TEXT NOT NULL, user_id INTEGER, username TEXT, action TEXT NOT NULL, changes TEXT);
CREATE TABLE IF NOT EXISTS risk_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, snap_date TEXT NOT NULL, label TEXT, taken_by TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, comment TEXT, assignment TEXT NOT NULL DEFAULT 'Pending', owner_text TEXT, owner_id INTEGER, deadline TEXT, revised TEXT, revised_reason TEXT,
  email_label TEXT, email_url TEXT, source TEXT NOT NULL DEFAULT 'manual', source_key TEXT, completed_at TEXT, created_at TEXT NOT NULL, created_by INTEGER, updated_at TEXT, updated_by INTEGER,
  deleted_at TEXT, deleted_by INTEGER, delete_reason TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_source ON tasks(source_key) WHERE source_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS task_history(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, ts TEXT NOT NULL, username TEXT, action TEXT NOT NULL, changes TEXT);
CREATE TABLE IF NOT EXISTS appetite_statements(
  id INTEGER PRIMARY KEY AUTOINCREMENT, dimension TEXT NOT NULL, statement TEXT NOT NULL, stance TEXT, metric TEXT, unit TEXT, direction TEXT NOT NULL DEFAULT 'max', limit_value REAL, amber REAL NOT NULL DEFAULT 0.8,
  source TEXT NOT NULL DEFAULT 'manual', actual REAL, actual_note TEXT, actual_at TEXT, owner TEXT, active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 100);
CREATE TABLE IF NOT EXISTS appetite_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT, reference TEXT, reason TEXT, snapshot TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT, scope_type TEXT NOT NULL, scope_value TEXT, due_date TEXT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, created_by INTEGER, closed_at TEXT);
CREATE TABLE IF NOT EXISTS assignments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE, risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE, assessor_id INTEGER, assessor_name TEXT,
  status TEXT NOT NULL DEFAULT 'open', p_inh_l INTEGER, p_inh_c INTEGER, p_res_l INTEGER, p_res_c INTEGER, rationale TEXT, submitted_by INTEGER, submitted_at TEXT, reviewer_id INTEGER, reviewed_at TEXT, review_comment TEXT,
  UNIQUE(campaign_id, risk_id));
CREATE TABLE IF NOT EXISTS meetings(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, meeting_date TEXT, status TEXT NOT NULL DEFAULT 'planned', notes TEXT, created_by INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS board_decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE, meeting_id INTEGER, recommendation TEXT, status TEXT NOT NULL DEFAULT 'pending', rank_at_request INTEGER,
  requested_by INTEGER, requested_at TEXT NOT NULL, decided_by INTEGER, decided_at TEXT, reference TEXT, expiry_date TEXT, conditions TEXT);
CREATE TABLE IF NOT EXISTS board_packs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, meeting_id INTEGER, status TEXT NOT NULL DEFAULT 'draft', data TEXT NOT NULL, created_by INTEGER, created_at TEXT NOT NULL, issued_by INTEGER, issued_at TEXT);
CREATE TABLE IF NOT EXISTS kpis(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, grp TEXT, kind TEXT NOT NULL DEFAULT 'kpi', unit TEXT, freq TEXT NOT NULL DEFAULT 'weekly', source TEXT, source_url TEXT,
  better TEXT NOT NULL DEFAULT 'none', target REAL, amber REAL, red REAL, decimals INTEGER NOT NULL DEFAULT 1, risk_id INTEGER, owner TEXT, feed_url TEXT, feed_fmt TEXT, feed_keys TEXT, internal_key TEXT,
  active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS kpi_readings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kpi_id INTEGER NOT NULL REFERENCES kpis(id) ON DELETE CASCADE, period TEXT NOT NULL, value REAL NOT NULL, method TEXT NOT NULL DEFAULT 'manual', note TEXT, entered_by TEXT, created_at TEXT NOT NULL,
  UNIQUE(kpi_id, period));
CREATE INDEX IF NOT EXISTS ix_kpi_readings ON kpi_readings(kpi_id, period);
CREATE TABLE IF NOT EXISTS kpi_imports(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT, kind TEXT, filename TEXT, rows_new INTEGER NOT NULL DEFAULT 0, rows_replaced INTEGER NOT NULL DEFAULT 0, undo TEXT NOT NULL DEFAULT '[]', deleted_at TEXT);
CREATE TABLE IF NOT EXISTS kriq_risks(no INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT, rating REAL);
CREATE TABLE IF NOT EXISTS kriq_kris(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, risk_no INTEGER, name TEXT NOT NULL, target_raw TEXT, op TEXT, target REAL, unit TEXT, lower_better INTEGER NOT NULL DEFAULT 0, sort INTEGER NOT NULL DEFAULT 0, last_fq TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS kriq_values(id INTEGER PRIMARY KEY AUTOINCREMENT, kri_id INTEGER NOT NULL, fq TEXT NOT NULL, raw TEXT, value REAL, target_raw TEXT, source TEXT, prev_raw TEXT, prev_source TEXT, import_id INTEGER, entered_by TEXT, created_at TEXT, UNIQUE(kri_id, fq));
CREATE TABLE IF NOT EXISTS kriq_risk_q(risk_no INTEGER NOT NULL, fq TEXT NOT NULL, residual REAL, note TEXT, source TEXT, import_id INTEGER, PRIMARY KEY(risk_no, fq));
CREATE TABLE IF NOT EXISTS kpi_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, as_of TEXT NOT NULL, grp TEXT NOT NULL, text TEXT NOT NULL, author TEXT, updated_at TEXT NOT NULL, UNIQUE(as_of, grp));
CREATE TABLE IF NOT EXISTS kpi_feed_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kpi_id INTEGER, ok INTEGER NOT NULL, message TEXT);
CREATE TABLE IF NOT EXISTS kri_alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kpi_id INTEGER NOT NULL, level TEXT NOT NULL, period TEXT, value REAL, status TEXT NOT NULL DEFAULT 'open', opened_at TEXT NOT NULL, ack_by TEXT, ack_at TEXT, ack_note TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS incidents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'incident', category TEXT, severity TEXT NOT NULL DEFAULT 'Medium', occurred_on TEXT, detected_at TEXT, description TEXT,
  risk_id INTEGER, control_text TEXT, gross_loss REAL NOT NULL DEFAULT 0, recovered REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open', owner TEXT, root_cause TEXT, pdb INTEGER NOT NULL DEFAULT 0, notified_at TEXT, notified_note TEXT,
  closed_at TEXT, closed_by TEXT, created_at TEXT NOT NULL, created_by INTEGER, updated_at TEXT, deleted_at TEXT, deleted_by INTEGER, delete_reason TEXT);
CREATE TABLE IF NOT EXISTS kpi_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL, host TEXT NOT NULL, provider TEXT, tier TEXT NOT NULL DEFAULT 'unverified', freq TEXT, note TEXT, status TEXT NOT NULL DEFAULT 'proposed', manual_only INTEGER NOT NULL DEFAULT 0,
  auto_accept INTEGER NOT NULL DEFAULT 0, proposed_by TEXT, proposed_at TEXT NOT NULL, verified_by TEXT, verified_at TEXT, verify_note TEXT, cert_fp TEXT, cert_changed INTEGER NOT NULL DEFAULT 0, content_hash TEXT, last_checked TEXT, last_status TEXT, last_bytes INTEGER,
  fail_count INTEGER NOT NULL DEFAULT 0, changed_at TEXT, reviewed_at TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS kpi_source_links(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL REFERENCES kpi_sources(id) ON DELETE CASCADE, kpi_id INTEGER NOT NULL REFERENCES kpis(id) ON DELETE CASCADE, rule_type TEXT NOT NULL DEFAULT 'watch', rule TEXT, UNIQUE(source_id, kpi_id));
CREATE TABLE IF NOT EXISTS kpi_proposals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kpi_id INTEGER NOT NULL, source_id INTEGER NOT NULL, period TEXT NOT NULL, value REAL NOT NULL, snippet TEXT, checks TEXT, status TEXT NOT NULL DEFAULT 'pending', decided_by TEXT, decided_at TEXT, note TEXT, created_at TEXT NOT NULL,
  UNIQUE(kpi_id, source_id, period, value));
CREATE TABLE IF NOT EXISTS source_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, source_id INTEGER, ok INTEGER NOT NULL, status_code INTEGER, bytes INTEGER, ms INTEGER, outcome TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS txn_daily(product TEXT NOT NULL, day TEXT NOT NULL, ts INTEGER NOT NULL, tf INTEGER NOT NULL, ta INTEGER NOT NULL DEFAULT 0, uploaded_by TEXT, uploaded_at TEXT, PRIMARY KEY(product, day));
CREATE TABLE IF NOT EXISTS kpi_charts(id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT NOT NULL, title TEXT NOT NULL, ctype TEXT NOT NULL DEFAULT 'column', mode TEXT NOT NULL DEFAULT 'series', codes TEXT NOT NULL, periods INTEGER NOT NULL DEFAULT 12, sort INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS kpi_layout(grp TEXT PRIMARY KEY, per_slide INTEGER NOT NULL DEFAULT 4);
CREATE TABLE IF NOT EXISTS kpi_deck(as_of TEXT NOT NULL, grp TEXT NOT NULL, page INTEGER NOT NULL DEFAULT 1, subtitle TEXT, source TEXT, tiles TEXT NOT NULL DEFAULT '[]', bullets TEXT NOT NULL DEFAULT '[]', updated_by TEXT, updated_at TEXT, PRIMARY KEY(as_of, grp, page));
CREATE TABLE IF NOT EXISTS txn_hourly(product TEXT NOT NULL, day TEXT NOT NULL, hour INTEGER NOT NULL, failed INTEGER NOT NULL, uploaded_by TEXT, uploaded_at TEXT, PRIMARY KEY(product, day, hour));
CREATE TABLE IF NOT EXISTS control_tests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, control_id INTEGER NOT NULL REFERENCES risk_controls(id) ON DELETE CASCADE, ttype TEXT NOT NULL, tested_on TEXT NOT NULL, tester TEXT, tester_id INTEGER, score INTEGER NOT NULL, result TEXT NOT NULL, evidence TEXT NOT NULL, prev_ice REAL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS control_attest(control_id INTEGER NOT NULL REFERENCES risk_controls(id) ON DELETE CASCADE, period TEXT NOT NULL, attested_by TEXT, ok INTEGER NOT NULL, note TEXT, ts TEXT NOT NULL, PRIMARY KEY(control_id, period));
CREATE TABLE IF NOT EXISTS actions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, title TEXT NOT NULL, description TEXT, source TEXT NOT NULL DEFAULT 'manual', risk_id INTEGER, control_id INTEGER, incident_id INTEGER, owner_name TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Medium',
  due_date TEXT NOT NULL, revised_due TEXT, revision_reason TEXT, revision_status TEXT, revision_by TEXT, status TEXT NOT NULL DEFAULT 'open', evidence TEXT, esc_level INTEGER NOT NULL DEFAULT 0,
  created_by INTEGER, created_by_name TEXT, created_at TEXT NOT NULL, closed_at TEXT, closed_by TEXT, updated_at TEXT, deleted_at TEXT, deleted_by INTEGER, delete_reason TEXT);
CREATE TABLE IF NOT EXISTS action_log(id INTEGER PRIMARY KEY AUTOINCREMENT, action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE, ts TEXT NOT NULL, username TEXT, event TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS purge_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, recycle_id INTEGER NOT NULL, title TEXT, entity_type TEXT, requested_by INTEGER, requested_name TEXT, reason TEXT NOT NULL, requested_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', decided_by TEXT, decided_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS departments(code TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT, grp TEXT, sort INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS control_catalog(kind TEXT NOT NULL, category TEXT, ref TEXT NOT NULL, statement TEXT, ice REAL, theme TEXT, PRIMARY KEY(kind, ref));
CREATE TABLE IF NOT EXISTS wb_store(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT, sha256 TEXT, size INTEGER, uploaded_by TEXT, uploaded_at TEXT NOT NULL, summary TEXT, data BLOB, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS wb_sheets(store_id INTEGER NOT NULL REFERENCES wb_store(id) ON DELETE CASCADE, name TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0, grid TEXT NOT NULL, PRIMARY KEY(store_id, name));
CREATE TABLE IF NOT EXISTS dq_fixes(id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, ts TEXT NOT NULL, username TEXT, kind TEXT NOT NULL, tbl TEXT NOT NULL, row_id INTEGER, field TEXT NOT NULL, old TEXT, new TEXT, reverted_at TEXT);
CREATE TABLE IF NOT EXISTS ai_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id INTEGER, username TEXT, feature TEXT NOT NULL, model TEXT, system_version TEXT, prompt_hash TEXT, input TEXT, output TEXT, tools TEXT, sources TEXT, tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, searches INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ok', error TEXT, flags TEXT, conv_id INTEGER, redactions TEXT);
CREATE INDEX IF NOT EXISTS ix_ai_log_ts ON ai_log(ts);
CREATE TABLE IF NOT EXISTS ai_convs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS ai_msgs(id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER NOT NULL REFERENCES ai_convs(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT, log_id INTEGER, ts TEXT NOT NULL, feedback TEXT, feedback_note TEXT);
CREATE TABLE IF NOT EXISTS ai_docs(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'other', filename TEXT, version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending', confidentiality TEXT NOT NULL DEFAULT 'internal', text TEXT, chars INTEGER, quality TEXT, sha256 TEXT, data BLOB, uploaded_by INTEGER, uploaded_by_name TEXT, uploaded_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT, supersedes_id INTEGER, change_summary TEXT, summary TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS ai_proposals(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL, rationale TEXT, confidence REAL, evidence TEXT, requested_by INTEGER, requested_by_name TEXT, model TEXT, log_id INTEGER, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, decided_by TEXT, decided_at TEXT, decision_note TEXT, applied_ref TEXT, source_doc INTEGER, risk_ref TEXT, ai_values TEXT, final_values TEXT);
CREATE TABLE IF NOT EXISTS ai_watch(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'topic', name TEXT NOT NULL, query TEXT, url TEXT, domains TEXT, freq_hours INTEGER NOT NULL DEFAULT 24, active INTEGER NOT NULL DEFAULT 1, last_run TEXT, last_hash TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_briefs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, watch_id INTEGER, topic TEXT, title TEXT NOT NULL, url TEXT, source TEXT, published TEXT, severity INTEGER NOT NULL DEFAULT 3, summary TEXT, impact TEXT, sources TEXT, status TEXT NOT NULL DEFAULT 'new', reviewed_by TEXT, reviewed_at TEXT, note TEXT, dedupe TEXT UNIQUE, log_id INTEGER, origin TEXT);
CREATE TABLE IF NOT EXISTS ai_incidents(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, reported_by TEXT, kind TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'Medium', description TEXT NOT NULL, log_id INTEGER, status TEXT NOT NULL DEFAULT 'open', resolution TEXT);
CREATE TABLE IF NOT EXISTS ai_fairness(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, run_by TEXT, model TEXT, scenarios INTEGER, max_gap REAL, result TEXT, passed INTEGER);
CREATE TABLE IF NOT EXISTS kit_items(id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT NOT NULL, entity TEXT NOT NULL, ref TEXT, status TEXT, data TEXT NOT NULL, wf_version INTEGER, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT, deleted_at TEXT);
CREATE INDEX IF NOT EXISTS kit_idx ON kit_items(module, entity, deleted_at);
CREATE TABLE IF NOT EXISTS kit_history(id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, ts TEXT NOT NULL, username TEXT, action TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS workflow_defs(id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft', states TEXT NOT NULL, transitions TEXT NOT NULL, note TEXT, created_by TEXT, created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT);
CREATE TABLE IF NOT EXISTS integ_connectors(key TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, handler TEXT, enabled INTEGER NOT NULL DEFAULT 0, expected_hours INTEGER NOT NULL DEFAULT 24, rotate_days INTEGER NOT NULL DEFAULT 90, key_hash TEXT, key_tail TEXT, key_created TEXT, scopes TEXT, last_sync TEXT, last_error TEXT, note TEXT, endpoint TEXT);
CREATE TABLE IF NOT EXISTS integ_events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, connector TEXT NOT NULL, status TEXT NOT NULL, rows_in INTEGER NOT NULL DEFAULT 0, rows_bad INTEGER NOT NULL DEFAULT 0, detail TEXT);
CREATE TABLE IF NOT EXISTS report_defs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, dataset TEXT NOT NULL, spec TEXT NOT NULL, owner_id INTEGER, owner_name TEXT, share TEXT NOT NULL DEFAULT 'private', system INTEGER NOT NULL DEFAULT 0, freq TEXT, run_time TEXT, recipients TEXT, fmt TEXT NOT NULL DEFAULT 'xlsx', last_run TEXT, created_at TEXT NOT NULL, deleted_at TEXT, deleted_by TEXT);
CREATE TABLE IF NOT EXISTS report_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, report_id INTEGER, username TEXT, action TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS ai_web_cache(key TEXT PRIMARY KEY, ts TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS owner_aliases(alias TEXT PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS objectives(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, perspective TEXT NOT NULL, owner TEXT, description TEXT, target_text TEXT, sort INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS objective_kpis(objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE, kpi_id INTEGER NOT NULL, PRIMARY KEY(objective_id, kpi_id));
CREATE TABLE IF NOT EXISTS scenarios(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, template TEXT NOT NULL, risk_id INTEGER, narrative TEXT, appetite_usd REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS scenario_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE, version INTEGER NOT NULL, params TEXT NOT NULL, assumptions TEXT, results TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scenario_scores(scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE, username TEXT NOT NULL, score INTEGER NOT NULL, ts TEXT NOT NULL, PRIMARY KEY(scenario_id, username));
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, url TEXT, source TEXT, theme TEXT, confidence REAL NOT NULL DEFAULT 0.5, impact INTEGER NOT NULL DEFAULT 3, velocity INTEGER NOT NULL DEFAULT 3, proximity INTEGER NOT NULL DEFAULT 3, status TEXT NOT NULL DEFAULT 'new', origin TEXT NOT NULL DEFAULT 'manual', risk_id INTEGER, decided_by TEXT, decided_at TEXT, note TEXT, dedupe TEXT UNIQUE, created_by TEXT);
CREATE TABLE IF NOT EXISTS radar_watch(id INTEGER PRIMARY KEY AUTOINCREMENT, theme TEXT NOT NULL, owner TEXT, review_date TEXT, notes TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS radar_feeds(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 0, last_run TEXT);
CREATE TABLE IF NOT EXISTS audit_plan(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, year INTEGER NOT NULL, title TEXT NOT NULL, area TEXT, risk_id INTEGER, scope TEXT, month_start INTEGER NOT NULL, month_end INTEGER NOT NULL, lead TEXT, status TEXT NOT NULL DEFAULT 'planned', grade TEXT, report_date TEXT, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS audit_findings(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, engagement_id INTEGER REFERENCES audit_plan(id), title TEXT NOT NULL, condition_text TEXT, criteria TEXT, cause TEXT, effect TEXT, recommendation TEXT, priority TEXT NOT NULL DEFAULT 'Medium', risk_id INTEGER, control_id INTEGER, owner_name TEXT, owner_id INTEGER, due_date TEXT, status TEXT NOT NULL DEFAULT 'open', response TEXT, response_by TEXT, response_at TEXT, closed_by TEXT, closed_at TEXT, close_note TEXT, action_ref TEXT, created_by TEXT, created_by_id INTEGER, created_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS fraud_alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, detected_at TEXT NOT NULL, typology TEXT NOT NULL, channel TEXT, agent_cluster TEXT, region TEXT, amount REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'detected', assigned_to TEXT, contained_at TEXT, loss REAL NOT NULL DEFAULT 0, recovered REAL NOT NULL DEFAULT 0, risk_id INTEGER, control_id INTEGER, incident_id INTEGER, outcome TEXT, notes TEXT, source TEXT NOT NULL DEFAULT 'manual', created_by TEXT, created_at TEXT NOT NULL, closed_at TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS fraud_base(period TEXT PRIMARY KEY, txn_value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS fraud_sim_daily(day TEXT PRIMARY KEY, attempts INTEGER NOT NULL, blocked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS speakup_cases(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, received_at TEXT NOT NULL, channel TEXT NOT NULL, theme TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Normal', summary TEXT NOT NULL, detail TEXT, anonymous INTEGER NOT NULL DEFAULT 1, reporter_sealed TEXT, status TEXT NOT NULL DEFAULT 'received', officer_id INTEGER, ack_due TEXT, close_due TEXT, acknowledged_at TEXT, closed_at TEXT, outcome TEXT, created_by TEXT, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS speakup_access(user_id INTEGER PRIMARY KEY, granted_by TEXT, granted_at TEXT NOT NULL, last_review TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS speakup_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, case_id INTEGER, username TEXT, action TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, to_addr TEXT, subject TEXT, body TEXT, kind TEXT);
"""


MIGRATE = {"kpi_imports": [("snapshot", "TEXT")], "outbox": [("status", "TEXT NOT NULL DEFAULT 'queued'"), ("sent_at", "TEXT"), ("error", "TEXT"), ("attempts", "INTEGER NOT NULL DEFAULT 0")], "control_catalog": [("origin", "TEXT")], "users": [("mfa_admin", "INTEGER NOT NULL DEFAULT 0"), ("mfa_secret", "TEXT"), ("mfa_enabled", "INTEGER NOT NULL DEFAULT 0"), ("mfa_last_step", "INTEGER"), ("mfa_recovery", "TEXT"), ("avatar", "TEXT")], "sessions": [("mfa_state", "TEXT NOT NULL DEFAULT 'ok'")], "risk_controls": [("ice_prev", "REAL"), ("next_due", "TEXT"), ("ice_source", "TEXT"), ("score", "INTEGER"), ("attested_on", "TEXT")], "kpi_readings": [("import_id", "INTEGER")], "risks": [("lor", "REAL"), ("rrr", "REAL"), ("emv_r", "REAL"), ("rr_target", "REAL"), ("rr_appetite", "REAL"), ("rr_tolerance", "REAL"), ("assessed_on", "TEXT"), ("wb_detail", "TEXT"), ("assess_source", "TEXT"), ("system", "TEXT"), ("source_ref", "TEXT"), ("strategic_objective", "TEXT"), ("needs_assessment", "INTEGER NOT NULL DEFAULT 0"), ("emv_a", "REAL"), ("subcategory", "TEXT"), ("delegate_name", "TEXT")]}


def init_schema():
    """Create missing tables and add missing columns, so an upgrade never loses or breaks existing data."""
    c = connect()
    try:
        c.executescript(SCHEMA)
        for table, cols in MIGRATE.items():
            have = {r["name"] for r in c.execute("PRAGMA table_info(%s)" % table)}
            for name, ddl in cols:
                if name not in have:
                    c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))
        c.execute("UPDATE users SET mfa_admin=1 WHERE mfa_enabled=1 AND mfa_admin=0")  # two-step sign-in that people turned on themselves is now kept on by the administrator's switch
        for table, col in (("risks", "owner_name"), ("tasks", "owner_text"), ("actions", "owner_name"), ("kpis", "owner"), ("risk_controls", "owner"), ("incidents", "owner")):  # there is no Head of Fraud at EcoCash: fraud sits under Compliance and ML/CTF
            try:
                c.execute("UPDATE %s SET %s='Head of Compliance and ML/CTF' WHERE %s='Head of Fraud'" % (table, col, col))
            except Exception:
                pass
        c.commit()
    finally:
        c.close()


def get_policy(db):
    pol = dict(config.DEFAULT_POLICY)
    r = db.execute("SELECT value FROM settings WHERE key='policy'").fetchone()
    if r:
        try:
            pol.update(json.loads(r["value"]))
        except ValueError:
            pass
    return pol
