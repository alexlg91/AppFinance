"""Génère tests/fixtures/*.json avec le VRAI code backend (migration + services), pour que le test
frontend (tests/frontend_smoke.mjs) vérifie le contrat réel API <-> interface.

    python tests/make_fixtures.py
"""
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from app import db, services  # noqa: E402
from test_services import LEGACY  # noqa: E402

logging.disable(logging.WARNING)

with tempfile.TemporaryDirectory() as tmp:
    legacy = Path(tmp) / "banque_data.json"
    legacy.write_text(LEGACY, encoding="utf-8")
    conn = db.connect(Path(tmp) / "banque.db")
    db.bootstrap_database(conn, legacy)
    uid = services.find_user(conn, "Admin")["id"]

    out = ROOT / "fixtures"
    out.mkdir(exist_ok=True)
    (out / "bootstrap.json").write_text(
        json.dumps(services.bootstrap_payload(conn, services.get_user(conn, uid), db_encrypted=True), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "dashboard.json").write_text(
        json.dumps(services.dashboard(conn, uid, 2026, 1), ensure_ascii=False, indent=1), encoding="utf-8")
    conn.close()
print("Fixtures écrites dans", out)
