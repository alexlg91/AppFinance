"""Authentification : mots de passe SHA-256 (compatibles avec l'ancien JSON), sessions persistantes par utilisateur."""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time


# ------------------------------------------------------------------ mots de passe
def hash_password(password: str) -> str:
    """SHA-256 hexadécimal — format IDENTIQUE à `hacher_mot_de_passe` de l'ancienne appli,
    afin que les empreintes déjà présentes dans banque_data.json restent valides."""
    if not password:
        return ""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))  # temps constant


def verify_password(candidate: str, stored: str) -> tuple[bool, bool]:
    """Retourne (ok, a_migrer).

    `a_migrer` vaut True si `stored` était un ancien mot de passe EN CLAIR : l'appelant doit alors
    le remplacer par son hash (même migration automatique que l'ancienne appli).
    """
    hashed = hash_password(candidate)   # calculé même si `stored` est vide : durée identique pour un identifiant inconnu
    if not stored:
        return False, False
    if _eq(hashed, stored):
        return True, False
    if _eq(candidate, stored):
        return True, True
    return False, False


# ------------------------------------------------------------------ sessions
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int, ttl_seconds: int) -> str:
    """Crée une session pour `user_id` et retourne le jeton brut (à poser en cookie HttpOnly)."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))  # purge opportuniste
        conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES(?, ?, ?)",
                     (_token_hash(token), user_id, now + ttl_seconds))
    return token


def validate_session(conn: sqlite3.Connection, token: str, ttl_seconds: int) -> tuple[int | None, bool]:
    """Retourne (user_id ou None, renouvelée).
    Fenêtre glissante : renouvelée quand il reste moins de 50 % de la durée."""
    if not token:
        return None, False
    now = int(time.time())
    key = _token_hash(token)
    row = conn.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (key,)).fetchone()
    if row is None or row["expires_at"] < now:
        return None, False
    if row["expires_at"] - now < ttl_seconds // 2:
        with conn:
            conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                         (now + ttl_seconds, key))
        return row["user_id"], True
    return row["user_id"], False


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def delete_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    """Déconnecte un utilisateur de tous ses appareils (changement/réinitialisation de mot de passe)."""
    with conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


# ------------------------------------------------------------------ anti brute-force
class LoginThrottle:
    """Bloque une IP après `max_failures` échecs dans une fenêtre de `window` secondes (en mémoire)."""

    def __init__(self, max_failures: int = 5, window: int = 900):
        self.max_failures, self.window = max_failures, window
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window]
        self._fails[key] = recent
        return recent

    def blocked_for(self, key: str) -> int:
        """Secondes restantes avant de pouvoir réessayer (0 = autorisé)."""
        now = time.time()
        with self._lock:
            recent = self._recent(key, now)
            if len(recent) < self.max_failures:
                return 0
            return max(1, int(self.window - (now - recent[0])))

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key, time.time()).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
