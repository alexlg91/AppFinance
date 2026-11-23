"""Tests d'API de bout en bout.   pip install -r requirements-dev.txt && pytest"""
import logging
import os
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, main  # noqa: E402
from app.config import Settings  # noqa: E402
from test_services import LEGACY  # noqa: E402

logging.disable(logging.WARNING)

TX = {"date": "2026-03-15", "type": "Sortie", "account": "Compte Courant",
      "target_account": None, "category": "Course", "name": "Test", "amount": 10.5}


KEY = os.environ.get("BANQUE_TEST_DB_KEY") or None   # comme test_services : toute la suite peut tourner sur une base chiffrée
UNSET = object()


def make_client(tmp_path, legacy: str | None = None, key=UNSET):
    if legacy is not None:
        (tmp_path / "banque_data.json").write_text(legacy, encoding="utf-8")
    return TestClient(main.create_app(Settings(data_dir=tmp_path, db_key=KEY if key is UNSET else key)))


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture()
def client(tmp_path):
    main.throttle = main.new_throttle()  # compteur propre à chaque test
    with make_client(tmp_path) as c:               # `with` : exécute le démarrage (création de la base)
        yield c


@pytest.fixture()
def duo(tmp_path):
    """Deux clients (deux « navigateurs ») : Admin avec mot de passe, et Alice créée par Admin."""
    main.throttle = main.new_throttle()
    with make_client(tmp_path) as admin:
        assert admin.put("/api/settings/password", json={"enabled": True, "password": "adminpw"}).status_code == 200
        r = admin.post("/api/users", json={"username": "Alice", "password": "alicepw"})
        assert r.status_code == 201
        alice = TestClient(admin.app)               # même application, cookies distincts
        assert login(alice, "alice", "alicepw").status_code == 200   # identifiant insensible à la casse
        yield admin, alice


def test_static_ui_and_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "Gestion Bancaire" in page.text
    assert client.get("/static/js/main.js").status_code == 200
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/api/bootstrap").headers["cache-control"] == "no-store"


def test_crud_and_balances(client):
    created = client.post("/api/transactions", json=TX)
    assert created.status_code == 201
    tx = created.json()["transaction"]
    assert created.json()["balances"]["Compte Courant"] == -10.5

    boot = client.get("/api/bootstrap").json()
    assert [t["id"] for t in boot["transactions"]] == [tx["id"]]
    assert boot["user"]["username"] == "Admin" and boot["user"]["is_admin"] is True
    assert "password_hash" not in boot["user"]

    assert client.put(f"/api/transactions/{tx['id']}", json={**TX, "amount": 20}).json()["total"] == -20.0
    assert client.get("/api/dashboard?year=2026&month=3").json()["month_flow"]["sorties"] == 20.0
    assert client.get("/api/export.csv").text.splitlines()[0].startswith("ID,Date,Jour,Mois")
    assert client.delete(f"/api/transactions/{tx['id']}").json()["total"] == 0.0
    assert client.delete(f"/api/transactions/{tx['id']}").status_code == 404


def test_validation_errors_are_readable(client):
    assert client.post("/api/transactions", json={**TX, "amount": 0}).status_code == 422
    r = client.post("/api/transactions", json={**TX, "type": "Transfert", "target_account": "Compte Courant"})
    assert r.status_code == 400 and "ne peuvent pas être les mêmes" in r.json()["detail"]
    assert client.get("/api/dashboard?year=2026&month=13").status_code == 422


def test_names_with_slashes_and_accents_in_urls(client):
    assert client.post("/api/accounts", json={"name": "PEL / Épargne"}).status_code == 201
    snap = client.put("/api/accounts/PEL%20%2F%20%C3%89pargne", json={"initial_balance": 250}).json()
    assert snap["balances"]["PEL / Épargne"] == 250.0
    assert client.delete("/api/accounts/PEL%20%2F%20%C3%89pargne").status_code == 200


def test_password_session_flow(client):
    assert client.get("/api/auth/status").json() == {"password_enabled": False, "authenticated": True}

    # activation : l'appelant reçoit directement une session (pas de verrouillage de sa propre fenêtre)
    r = client.put("/api/settings/password", json={"enabled": True, "password": "abc"})
    assert r.json() == {"password_enabled": True, "has_password": True}
    assert client.get("/api/bootstrap").status_code == 200

    client.cookies.clear()                                       # autre appareil / cookie perdu
    assert client.get("/api/bootstrap").status_code == 401
    assert client.get("/api/auth/status").json() == {"password_enabled": True, "authenticated": False}
    r = login(client, "Admin", "faux")
    assert r.status_code == 401 and r.json()["detail"] == "Identifiant ou mot de passe incorrect."
    assert login(client, "inconnu", "abc").json()["detail"] == r.json()["detail"]     # n'indique pas quels identifiants existent
    assert login(client, "Admin", "abc").status_code == 200
    assert client.get("/api/bootstrap").status_code == 200

    set_cookie = login(client, "admin", "abc").headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie

    client.post("/api/auth/logout")
    assert client.get("/api/bootstrap").status_code == 401


def test_bruteforce_lockout(client):
    client.put("/api/settings/password", json={"enabled": True, "password": "abc"})
    client.cookies.clear()
    for _ in range(8):
        assert login(client, "Admin", "x").status_code == 401
    r = login(client, "Admin", "abc")                              # même le bon mot de passe est refusé
    assert r.status_code == 429 and "Réessayez" in r.json()["detail"]


# ------------------------------------------------------------------ multi-utilisateurs
def test_users_have_isolated_data(duo):
    admin, alice = duo
    mine = admin.post("/api/transactions", json=TX).json()["transaction"]

    boot = alice.get("/api/bootstrap").json()
    assert boot["user"]["username"] == "Alice" and boot["user"]["is_admin"] is False
    assert boot["transactions"] == [] and boot["total"] == 0.0
    assert alice.get("/api/dashboard?year=2026&month=3").json()["has_data"] is False
    assert alice.get("/api/export.csv").text.count("\n") == 1

    # la transaction d'Admin est « introuvable » pour Alice (404, pas 403)
    assert alice.put(f"/api/transactions/{mine['id']}", json={**TX, "amount": 1}).status_code == 404
    assert alice.delete(f"/api/transactions/{mine['id']}").status_code == 404
    assert admin.get("/api/bootstrap").json()["transactions"][0]["amount"] == 10.5

    # … et réciproquement pour les paramètres
    alice.put("/api/accounts/Livret%20A", json={"initial_balance": 999})
    assert admin.get("/api/bootstrap").json()["balances"]["Livret A"] == 0.0


def test_only_admins_can_manage_users(duo):
    admin, alice = duo
    assert alice.get("/api/users").status_code == 403
    assert alice.post("/api/users", json={"username": "Eve", "password": "x"}).status_code == 403
    assert alice.delete("/api/users/1").status_code == 403
    assert alice.put("/api/users/1/password", json={"password": "pwned"}).status_code == 403

    users = admin.get("/api/users").json()["users"]
    assert [(u["username"], u["is_admin"]) for u in users] == [("Admin", True), ("Alice", False)]
    assert all("password_hash" not in u for u in users)
    assert admin.post("/api/users", json={"username": "alice", "password": "x"}).status_code == 409    # doublon (casse ignorée)
    assert admin.post("/api/users", json={"username": "<b>", "password": "x"}).status_code == 400
    assert admin.delete("/api/users/1").status_code == 400                                                # pas soi-même


def test_unauthenticated_requests_are_rejected_everywhere(duo):
    admin, _ = duo
    anonymous = TestClient(admin.app)
    for method, url in (("get", "/api/bootstrap"), ("get", "/api/users"), ("get", "/api/export.csv"),
                        ("delete", "/api/transactions"), ("get", "/api/dashboard?year=2026&month=1")):
        assert getattr(anonymous, method)(url).status_code == 401, url


def test_admin_reset_password_and_delete_user_cut_their_sessions(duo):
    admin, alice = duo
    assert alice.get("/api/bootstrap").status_code == 200
    assert admin.put("/api/users/2/password", json={"password": "nouveau"}).status_code == 200
    assert alice.get("/api/bootstrap").status_code == 401                   # déconnectée
    assert login(alice, "Alice", "alicepw").status_code == 401
    assert login(alice, "Alice", "nouveau").status_code == 200

    assert admin.delete("/api/users/2").status_code == 200
    assert alice.get("/api/bootstrap").status_code == 401                   # compte supprimé
    assert login(alice, "Alice", "nouveau").status_code == 401
    assert admin.get("/api/bootstrap").status_code == 200                   # Admin non affecté


def test_changing_my_password_does_not_log_out_others(duo):
    admin, alice = duo
    assert alice.put("/api/settings/password", json={"enabled": True, "password": "alice2"}).json()["has_password"] is True
    assert alice.get("/api/bootstrap").status_code == 200                   # sa propre session est renouvelée
    assert admin.get("/api/bootstrap").status_code == 200                   # celle d'Admin reste valide
    assert alice.put("/api/settings/password", json={"enabled": False}).status_code == 400   # désactivation impossible à plusieurs


def test_cannot_create_users_before_setting_own_password(client):
    r = client.post("/api/users", json={"username": "Bob", "password": "x"})
    assert r.status_code == 400 and "mot de passe" in r.json()["detail"]


def test_legacy_json_migration_and_legacy_password(tmp_path):
    main.throttle = main.new_throttle()
    with make_client(tmp_path, LEGACY) as c:
        # le JSON de test contient un mot de passe EN CLAIR : accepté puis converti en SHA-256
        assert c.get("/api/auth/status").json() == {"password_enabled": True, "authenticated": False}
        assert login(c, "Admin", "secret-en-clair").status_code == 200
        boot = c.get("/api/bootstrap").json()
        assert len(boot["transactions"]) == 5 and boot["total"] == 3040.3
        assert boot["user"]["username"] == "Admin"
    assert (tmp_path / "banque_data.json").read_text(encoding="utf-8") == LEGACY  # JSON d'origine intact

    with make_client(tmp_path, None) as c2:   # redémarrage : le hash a été migré, les données sont en base
        assert login(c2, "Admin", "secret-en-clair").status_code == 200
        conn = db.connect(tmp_path / "banque.db", KEY)
        stored = conn.execute("SELECT password_hash FROM users WHERE username = 'Admin'").fetchone()[0]
        assert stored == sha256(b"secret-en-clair").hexdigest()
        conn.close()


# ------------------------------------------------------------------ chiffrement de la base au repos
needs_cipher = pytest.mark.skipif(not db.cipher_available(), reason="sqlcipher3 n'est pas installé")


def readable_files(directory, needle: bytes):
    return [f.name for f in Path(directory).iterdir() if f.is_file() and needle in f.read_bytes()]


def test_bootstrap_reports_whether_the_database_is_encrypted(client):
    assert client.get("/api/bootstrap").json()["db_encrypted"] is (KEY is not None)


@needs_cipher
def test_encrypted_app_works_end_to_end_and_nothing_is_readable_on_disk(tmp_path):
    key = os.urandom(32).hex()
    main.throttle = main.new_throttle()
    with make_client(tmp_path, LEGACY, key) as c:
        assert login(c, "Admin", "secret-en-clair").status_code == 200
        assert c.get("/api/bootstrap").json()["db_encrypted"] is True
        r = c.post("/api/transactions", json={**TX, "name": "SECRET-API-9z"})
        assert r.status_code in (200, 201), r.text
        assert c.get("/api/dashboard?year=2026&month=3").json()["has_data"] is True
        assert c.get("/api/export.csv").text.count("SECRET-API-9z") == 1
        assert readable_files(tmp_path, b"SECRET-API-9z") == []                       # application EN COURS, WAL actif
        assert readable_files(tmp_path, b"Supermarch\xc3\xa9") == ["banque_data.json"]  # seul le JSON d'origine reste lisible
    assert readable_files(tmp_path, b"SECRET-API-9z") == []                           # après arrêt
    assert db.file_state(tmp_path / "banque.db") == "encrypted"


@needs_cipher
def test_restart_with_a_key_converts_an_existing_plain_database_without_losing_data(tmp_path):
    main.throttle = main.new_throttle()
    with make_client(tmp_path, None, None) as c:                                      # première vie : SANS clé (base en clair)
        assert c.get("/api/bootstrap").json()["db_encrypted"] is False
        c.post("/api/transactions", json={**TX, "name": "AVANT-CHIFFREMENT"})
    assert readable_files(tmp_path, b"AVANT-CHIFFREMENT") == ["banque.db"]            # preuve : bien en clair au départ

    key = os.urandom(32).hex()
    with make_client(tmp_path, None, key) as c:                                       # redémarrage AVEC clé
        boot = c.get("/api/bootstrap").json()
        assert boot["db_encrypted"] is True
        assert [t["name"] for t in boot["transactions"]] == ["AVANT-CHIFFREMENT"]
    assert readable_files(tmp_path, b"AVANT-CHIFFREMENT") == []
    assert sorted(f.name for f in tmp_path.iterdir()) == ["banque.db"]                # aucun fichier résiduel


@needs_cipher
def test_app_refuses_to_start_on_wrong_missing_or_malformed_key(tmp_path):
    key = os.urandom(32).hex()
    with make_client(tmp_path, None, key):
        pass
    before = sorted(f.name for f in tmp_path.iterdir())
    for bad in (os.urandom(32).hex(), None):                                          # mauvaise clé ; clé absente
        with pytest.raises(db.EncryptionError):
            with make_client(tmp_path, None, bad):
                pass
    assert sorted(f.name for f in tmp_path.iterdir()) == before                       # aucune base vide créée à côté
    with pytest.raises(db.EncryptionError):                                           # clé mal formée
        with make_client(tmp_path, None, "pas-une-cle"):
            pass


@needs_cipher
def test_admin_is_warned_while_the_legacy_json_stays_readable_next_to_the_encrypted_database(tmp_path):
    key = os.urandom(32).hex()
    main.throttle = main.new_throttle()
    with make_client(tmp_path, LEGACY, key) as admin:
        assert login(admin, "Admin", "secret-en-clair").status_code == 200
        assert admin.get("/api/bootstrap").json()["legacy_json_in_clear"] is True
        assert admin.post("/api/users", json={"username": "Alice", "password": "alicepw"}).status_code == 201
        alice = TestClient(admin.app)
        assert login(alice, "Alice", "alicepw").status_code == 200
        assert alice.get("/api/bootstrap").json()["legacy_json_in_clear"] is False      # information réservée aux administrateurs
        (tmp_path / "banque_data.json").unlink()                                          # l'utilisateur le supprime
        assert admin.get("/api/bootstrap").json()["legacy_json_in_clear"] is False


def test_no_legacy_warning_without_encryption(tmp_path):
    main.throttle = main.new_throttle()
    with make_client(tmp_path, LEGACY, None) as c:                                        # base en clair : le JSON n'aggrave rien
        assert login(c, "Admin", "secret-en-clair").status_code == 200
        assert c.get("/api/bootstrap").json()["legacy_json_in_clear"] is False
