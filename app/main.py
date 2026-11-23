"""Point d'entrée FastAPI : API REST JSON + service de l'interface statique.

Aucun état n'est gardé en mémoire de processus (hors compteur anti brute-force) :
toute la vérité est dans SQLite, les sessions aussi → redémarrage ou reverse proxy sans
déconnexion, et aucune WebSocket à maintenir.
"""
import datetime as dt
import logging
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, schemas, security, services
from .config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("banque.main")

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "banque_session"
def new_throttle() -> security.LoginThrottle:
    return security.LoginThrottle(max_failures=8, window=900)       # par IP ; 8 : tolère une maison à plusieurs


throttle = new_throttle()


# ----------------------------------------------------------------------------- dépendances
def get_conn(request: Request):
    """Une connexion SQLite par requête, fermée à la fin."""
    settings: Settings = request.app.state.settings
    conn = db.connect(settings.db_path, settings.db_key)
    try:
        yield conn
    finally:
        conn.close()


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,          # illisible côté JavaScript (anti-vol par XSS)
        samesite="strict",      # jamais envoyé depuis un autre site (anti-CSRF)
        secure=settings.cookie_secure,
        path="/",
    )


def current_user(request: Request, response: Response, conn=Depends(get_conn)) -> dict:
    """Utilisateur courant. Accès libre (un seul utilisateur sans mot de passe) ou session valide, sinon 401."""
    if not services.auth_required(conn):
        user = services.open_mode_user(conn)
        if user is None:  # inatteignable : bootstrap crée toujours au moins un utilisateur
            raise HTTPException(status_code=500, detail="Aucun utilisateur configuré.")
        return user
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE, "")
    uid, renewed = security.validate_session(conn, token, settings.session_ttl_days * 86400)
    user = services.get_user(conn, uid) if uid is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Authentification requise.")
    if renewed:  # session glissante : le cookie suit la prolongation côté serveur
        _set_session_cookie(response, settings, token)
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Action réservée aux administrateurs.")
    return user


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "inconnu"


# ----------------------------------------------------------------------------- routes publiques
public = APIRouter(prefix="/api")


@public.get("/health")
def health():
    return {"status": "ok"}


@public.get("/auth/status")
def auth_status(request: Request, conn=Depends(get_conn)):
    required = services.auth_required(conn)
    authenticated = True
    if required:
        settings: Settings = request.app.state.settings
        uid, _ = security.validate_session(
            conn, request.cookies.get(SESSION_COOKIE, ""), settings.session_ttl_days * 86400)
        authenticated = uid is not None and services.get_user(conn, uid) is not None
    return {"password_enabled": required, "authenticated": authenticated}


@public.post("/auth/login")
def login(body: schemas.LoginIn, request: Request, response: Response, conn=Depends(get_conn)):
    settings: Settings = request.app.state.settings
    if not services.auth_required(conn):
        return {"authenticated": True}

    key = _client_key(request)
    wait = throttle.blocked_for(key)
    if wait:
        raise HTTPException(429, f"Trop de tentatives. Réessayez dans {math.ceil(wait / 60)} min.")

    row = services.find_user(conn, body.username)
    ok, legacy_plaintext = security.verify_password(body.password, row["password_hash"] if row else "")
    if row is None or not ok:   # même message dans les deux cas : on ne révèle pas quels identifiants existent
        throttle.record_failure(key)
        raise HTTPException(401, "Identifiant ou mot de passe incorrect.")

    throttle.reset(key)
    if legacy_plaintext:  # migration automatique clair -> SHA-256, comme l'ancienne appli
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (security.hash_password(body.password), row["id"]))
    token = security.create_session(conn, row["id"], settings.session_ttl_days * 86400)
    _set_session_cookie(response, settings, token)
    return {"authenticated": True, "username": row["username"]}


@public.post("/auth/logout")
def logout(request: Request, response: Response, conn=Depends(get_conn)):
    security.delete_session(conn, request.cookies.get(SESSION_COOKIE, ""))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


# ----------------------------------------------------------------------------- routes protégées
# Garde-fou : AUCUNE route de ce routeur n'est accessible sans utilisateur authentifié.
private = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
admin = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


@private.get("/bootstrap")
def bootstrap(request: Request, user: dict = Depends(current_user), conn=Depends(get_conn)):
    """Tout ce qu'il faut pour afficher l'application en UNE requête (filtrage/tri ensuite 100 % côté client)."""
    settings = request.app.state.settings
    encrypted = settings.db_key is not None
    payload = services.bootstrap_payload(conn, user, db_encrypted=encrypted)
    # Ancien fichier d'import resté EN CLAIR à côté de la base chiffrée : signalé aux administrateurs (Paramètres).
    payload["legacy_json_in_clear"] = encrypted and bool(user["is_admin"]) and settings.legacy_json_path.exists()
    return payload


@private.get("/dashboard")
def dashboard(year: Annotated[int, Query(ge=1900, le=2200)],
              month: Annotated[int, Query(ge=1, le=12)],
              user: dict = Depends(current_user), conn=Depends(get_conn)):
    return services.dashboard(conn, user["id"], year, month)


# --- transactions
@private.post("/transactions", status_code=201)
def create_transaction(body: schemas.TransactionIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
    tx = services.create_transaction(conn, user["id"], body.model_dump())
    return {"transaction": tx, **services.balances_payload(conn, user["id"])}


@private.put("/transactions/{tx_id}")
def update_transaction(tx_id: int, body: schemas.TransactionIn, user: dict = Depends(current_user),
                       conn=Depends(get_conn)):
    tx = services.update_transaction(conn, user["id"], tx_id, body.model_dump())
    return {"transaction": tx, **services.balances_payload(conn, user["id"])}


@private.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int, user: dict = Depends(current_user), conn=Depends(get_conn)):
    services.delete_transaction(conn, user["id"], tx_id)
    return services.balances_payload(conn, user["id"])


@private.delete("/transactions")
def clear_transactions(user: dict = Depends(current_user), conn=Depends(get_conn)):
    services.clear_transactions(conn, user["id"])
    return services.balances_payload(conn, user["id"])


# --- comptes (le nom fait office d'identifiant, comme dans l'ancien JSON ; `:path` tolère les « / »)
@private.post("/accounts", status_code=201)
def add_account(body: schemas.AccountIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
    return services.add_account(conn, user["id"], body.name)


@private.put("/accounts/{name:path}")
def set_initial_balance(name: str, body: schemas.InitialBalanceIn, user: dict = Depends(current_user),
                        conn=Depends(get_conn)):
    return services.set_initial_balance(conn, user["id"], name, body.initial_balance)


@private.delete("/accounts/{name:path}")
def delete_account(name: str, user: dict = Depends(current_user), conn=Depends(get_conn)):
    return services.delete_account(conn, user["id"], name)


# --- catégories
@private.post("/categories", status_code=201)
def add_category(body: schemas.CategoryIn, user: dict = Depends(current_user), conn=Depends(get_conn)):
    return services.add_category(conn, user["id"], body.name, body.color)


@private.put("/categories/{name:path}")
def set_category_color(name: str, body: schemas.CategoryColorIn, user: dict = Depends(current_user),
                       conn=Depends(get_conn)):
    return services.set_category_color(conn, user["id"], name, body.color)


@private.delete("/categories/{name:path}")
def delete_category(name: str, user: dict = Depends(current_user), conn=Depends(get_conn)):
    return services.delete_category(conn, user["id"], name)


# --- mot de passe de l'utilisateur courant & export
@private.put("/settings/password")
def update_password(body: schemas.PasswordIn, request: Request, response: Response,
                    user: dict = Depends(current_user), conn=Depends(get_conn)):
    """Active / modifie / désactive MON mot de passe.
    Mes sessions existantes sont révoquées ; je reçois une session neuve (les autres utilisateurs ne sont pas touchés)."""
    settings: Settings = request.app.state.settings
    required = services.set_password(conn, user["id"], body.enabled, body.password)
    security.delete_user_sessions(conn, user["id"])
    has_password = bool((services.get_user(conn, user["id"]) or {}).get("has_password"))
    if has_password:
        _set_session_cookie(response, settings,
                            security.create_session(conn, user["id"], settings.session_ttl_days * 86400))
    else:
        response.delete_cookie(SESSION_COOKIE, path="/")
    return {"password_enabled": required, "has_password": has_password}


@private.get("/export.csv")
def export_csv(user: dict = Depends(current_user), conn=Depends(get_conn)):
    filename = f"transactions_bancaires_{dt.date.today()}.csv"
    return Response(
        content=services.export_csv(conn, user["id"]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- administration des utilisateurs (réservée aux administrateurs : 403 sinon)
@admin.get("/users")
def list_users(conn=Depends(get_conn)):
    return {"users": services.list_users(conn)}


@admin.post("/users", status_code=201)
def create_user(body: schemas.UserIn, actor: dict = Depends(require_admin), conn=Depends(get_conn)):
    return {"users": services.create_user(conn, actor["id"], body.username, body.password, body.is_admin)}


@admin.delete("/users/{user_id}")
def delete_user(user_id: int, actor: dict = Depends(require_admin), conn=Depends(get_conn)):
    return {"users": services.delete_user(conn, actor["id"], user_id)}


@admin.put("/users/{user_id}/password")
def reset_user_password(user_id: int, body: schemas.UserPasswordIn, actor: dict = Depends(require_admin),
                        conn=Depends(get_conn)):
    return {"users": services.reset_user_password(conn, actor["id"], user_id, body.password)}


# ----------------------------------------------------------------------------- application
def _check_data_dir(path: Path) -> None:
    """Échoue tout de suite, avec une explication, si le dossier de données n'est pas inscriptible
    (cas typique Docker : ./data appartient à un autre utilisateur que celui du conteneur)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        uid = os.getuid() if hasattr(os, "getuid") else "?"
        raise RuntimeError(
            f"Le dossier de données « {path} » n'est pas accessible en écriture pour l'utilisateur {uid} ({exc}). "
            f"Docker : lancez `PUID=$(id -u) PGID=$(id -g) docker compose up -d`, ou donnez la main sur ./data : "
            f"`sudo chown -R {uid}:{os.getgid() if hasattr(os, 'getgid') else uid} ./data`."
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    os.umask(0o077)   # fichiers créés (base, journaux) lisibles par le seul utilisateur du service
    _check_data_dir(settings.data_dir)
    # Garantit l'état voulu AVANT d'ouvrir la base : chiffre automatiquement une base (et sa sauvegarde v1) encore en clair,
    # ou refuse de démarrer si la base est chiffrée sans clé configurée.
    db.prepare_storage(settings.db_path, settings.db_key, extra=[settings.v1_backup_path])
    conn = db.connect(settings.db_path, settings.db_key)
    try:
        # schéma (mise à niveau v1 -> v2 si besoin, avec sauvegarde) + migration JSON au 1er lancement
        db.bootstrap_database(conn, settings.legacy_json_path, backup_dir=settings.data_dir, key=settings.db_key)
    finally:
        conn.close()
    if settings.db_key:
        log.info("Base de données chiffrée au repos (SQLCipher, AES-256).")
        if settings.legacy_json_path.is_file():
            log.warning("⚠ %s (EN CLAIR : toutes vos données + empreinte du mot de passe) est toujours présent. "
                        "Il n'est plus utilisé : conservez-en une copie hors du NAS si besoin, puis supprimez-le d'ici.",
                        settings.legacy_json_path)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    docs = settings.enable_docs
    app = FastAPI(
        title="Gestion Bancaire", lifespan=lifespan,
        docs_url="/api/docs" if docs else None, redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.settings = settings

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        # API : jamais mise en cache (données financières). Statique : revalider (ETag) à chaque visite.
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache")
        return response

    @app.exception_handler(services.ServiceError)
    async def service_error(_: Request, exc: services.ServiceError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    app.include_router(public)
    app.include_router(private)
    app.include_router(admin)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
