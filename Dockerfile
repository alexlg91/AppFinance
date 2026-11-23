FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /srv

# Dépendances d'abord : cette couche est mise en cache tant que requirements.txt ne change pas.
# Chiffrement de la base (SQLCipher) : sur x86_64 une roue précompilée suffit. Sur ARM (Raspberry Pi, NAS ARM) le
# paquet est compilé : on installe temporairement le compilateur ; les bibliothèques d'exécution (libsqlcipher0,
# tirée par libsqlcipher-dev) restent dans l'image, seuls les outils de compilation sont retirés.
COPY requirements.txt .
RUN set -eux; \
    if [ "$(uname -m)" != "x86_64" ]; then \
        apt-get update; \
        apt-get install -y --no-install-recommends build-essential libsqlcipher-dev; \
    fi; \
    pip install -r requirements.txt; \
    if [ "$(uname -m)" != "x86_64" ]; then \
        apt-get purge -y --auto-remove build-essential; \
    fi; \
    rm -rf /var/lib/apt/lists/*; \
    python -c "from sqlcipher3 import dbapi2 as s; print('SQLCipher', s.connect(':memory:').execute('PRAGMA cipher_version').fetchone()[0])"

COPY app ./app
COPY scripts ./scripts

# Chart.js est embarqué dans l'image (aucun CDN à l'exécution).
RUN python scripts/fetch_vendor.py

# COPY conserve les permissions de l'hôte (ex. fichiers en 600 si votre umask est 077) avec root comme propriétaire :
# l'utilisateur non-root du conteneur ne pourrait alors pas LIRE le code (PermissionError sur app/__init__.py).
# On force donc : lecture pour tous, traversée des dossiers.
RUN chmod -R a+rX /srv

# Utilisateur non-root. docker-compose le remplace par votre UID:GID pour écrire dans ./data.
RUN useradd --system --uid 10001 --no-create-home banque \
 && mkdir -p /data && chown banque /data
USER banque

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

# 1 seul worker : SQLite (WAL) gère très bien la charge d'un usage personnel,
# et le compteur anti brute-force reste cohérent.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
