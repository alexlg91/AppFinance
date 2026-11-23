# Gestion Bancaire — FastAPI + SQLite chiffrée + JS vanilla

Remplacement client/serveur de l'application Streamlit : mêmes fonctionnalités, sans WebSocket,
sans rechargement de script, sans déconnexion intempestive. **Multi-utilisateurs** : chaque utilisateur a son
identifiant, son mot de passe et ses propres données. **Base chiffrée au repos** (SQLCipher, AES-256) : rien n'est
lisible dans les fichiers du NAS.

## Démarrage rapide (Docker)

```bash
# 1. Clé de chiffrement — UNE seule fois. Puis COPIEZ-LA ailleurs que sur le NAS (voir « Chiffrement de la base »).
python scripts/generate_key.py          # ou : mkdir -p secrets && (umask 077; openssl rand -hex 32 > secrets/db_key)

# 2. (migration) déposez votre ancien fichier dans ./data — rien d'autre à faire
mkdir -p data && cp /chemin/vers/ancienne-appli/data/banque_data.json ./data/

# 3. build + lancement
PUID=$(id -u) PGID=$(id -g) docker compose up -d --build

# 4. http://localhost:8000   — puis SUPPRIMEZ ./data/banque_data.json (il est en clair, voir plus bas)
```

Au **premier** démarrage, `banque_data.json` est importé dans `data/banque.db` (comptes, soldes initiaux,
catégories + couleurs, transactions avec leurs ID, mot de passe) et rattaché à l'utilisateur administrateur **`Admin`**. Le JSON n'est jamais modifié : vous pouvez
revenir à Streamlit à tout moment. Si le JSON est illisible, l'application refuse de démarrer avec un message
explicite plutôt que de démarrer vide.

Sans fichier JSON : base neuve avec les mêmes comptes/catégories par défaut que l'ancienne appli.

## Chiffrement de la base

La base `data/banque.db` est chiffrée avec **SQLCipher 4 (AES-256)** : ouverte avec un éditeur, un client SQLite ordinaire
ou un `strings`, elle ne montre que du bruit. Le chiffrement couvre aussi le journal `-wal` et la sauvegarde de mise à niveau.
Il est **transparent** pour l'application et l'interface (seule une ligne apparaît dans Paramètres).

### Ce que ça protège — et ce que ça ne protège pas

| Menace | Protégé ? |
|---|---|
| Quelqu'un qui parcourt le dossier partagé du NAS (SMB/NFS/File Station) et ouvre `banque.db` | ✅ oui (octets illisibles) |
| Sauvegardes ou synchronisations de `data/` (Hyper Backup, rsync, cloud) | ✅ oui, **si la clé n'est pas sauvegardée avec** |
| Disque retiré, NAS revendu ou envoyé en réparation | ✅ **seulement si la clé n'est pas sur ces mêmes disques** (ex. volume chiffré à part, ou clé conservée hors du NAS et copiée au démarrage) |
| Quelqu'un qui a `root`/admin sur le NAS ou l'hôte Docker | ❌ non : il peut lire la clé, faire `docker exec`, lire la mémoire du processus |
| Un utilisateur de l'application qui voit les données d'un autre | — c'est le rôle de l'isolation par utilisateur (404) et des mots de passe, pas du chiffrement |
| **Copies faites AVANT le chiffrement** : instantanés btrfs/ZFS, versions Hyper Backup, corbeille réseau (`#recycle`), exports CSV, ancien `banque_data.json` | ❌ non : à purger vous-même (voir ci-dessous) |
| Taille et dates du fichier `banque.db` | ❌ visibles (le contenu, non) |

Choix de conception assumé : la clé est un **fichier aléatoire de 256 bits**, pas une phrase de passe. Le serveur redémarre
donc seul (coupure de courant, mise à jour du NAS) sans que personne ne saisisse rien, et l'ouverture d'une connexion
reste instantanée (une phrase de passe imposerait ~165 ms de dérivation à *chaque* requête). Contrepartie : la clé existe en
clair sur le serveur, d'où les consignes ci-dessous.

### Consignes pour la clé (à lire une fois)

1. **Sauvegardez-la ailleurs que sur le NAS** (gestionnaire de mots de passe, clé USB rangée). **Clé perdue = données
   définitivement irrécupérables**, il n'existe aucune procédure de secours.
2. Gardez `secrets/` **hors du dossier partagé** en SMB/NFS et **hors des sauvegardes de `data/`**. Sinon la clé voyage avec la base et le chiffrement ne sert plus à rien.
3. Droits : fichier en `600`, dossier en `700`, propriétaire = l'utilisateur du conteneur (`PUID`). `generate_key.py` s'en charge et refuse d'écraser une clé existante.
4. Pas de rotation de clé intégrée (changer de clé = ré-exporter la base ; non fourni).
5. `DB_KEY_FILE` (fichier, utilisé par `docker-compose.yml` via un *secret* Docker) est préférable à `DB_KEY` (variable d'environnement, visible avec `docker inspect`). Si les deux sont définies, le fichier l'emporte.

### Activation sur une base existante (conversion automatique)

Il suffit de démarrer avec la clé configurée. Au démarrage, **avant** toute ouverture :

1. copie chiffrée de la base (journal WAL inclus) dans un fichier temporaire ;
2. **vérification** : intégrité + empreinte de chaque table (nombre de lignes et SHA-256) identiques à l'original ; au moindre écart, conversion annulée et base d'origine **intacte** ;
3. remplacement atomique, puis écrasement (zéros) et suppression de l'ancien fichier en clair.

Un arrêt brutal à n'importe quelle étape est repris proprement au démarrage suivant (jamais de perte de la seule copie).
La sauvegarde `banque.v1.bak.db` d'une mise à niveau antérieure est convertie de la même façon.

**À faire après la conversion** (l'écrasement est « au mieux » : sans effet garanti sur SSD, systèmes de fichiers copy-on-write et instantanés) :

* supprimer `data/banque_data.json` — il contient toutes vos données **et l'empreinte de votre mot de passe, en clair**. Paramètres affiche un avertissement aux administrateurs tant qu'il est présent ; gardez-en une copie hors du NAS si vous voulez pouvoir revenir à Streamlit ;
* purger les anciens instantanés / versions de sauvegarde / corbeille qui contiennent l'ancienne `banque.db` en clair ;
* les exports CSV (Paramètres) sont, eux, en clair par nature : ne les laissez pas traîner sur le NAS.

### Vérifier par vous-même

```bash
head -c 16 data/banque.db | od -c | head -1   # ne doit PAS commencer par « SQLite format 3 »
strings data/banque.db | head                 # du bruit, aucun nom de compte ni de catégorie
sqlite3 data/banque.db .tables                # « file is not a database »
```

### Sauvegarde

Ne copiez pas `banque.db` à chaud (mode WAL : copie possiblement incohérente) et le client `sqlite3` ne lit pas SQLCipher. Utilisez :

```bash
docker compose exec banque python scripts/backup.py            # → data/backups/banque-AAAAMMJJ-HHMMSS.db
docker compose exec banque python scripts/backup.py /data/backups/avant-mise-a-jour.db
```

Copie cohérente prise pendant que l'application tourne, **vérifiée** (empreintes), en `600`, **chiffrée avec la même clé** ; elle n'écrase jamais un fichier.
Pour restaurer : arrêter l'application, remplacer `data/banque.db` par la copie (et supprimer `banque.db-wal` / `-shm`), redémarrer avec la **même clé**.
À froid (conteneur arrêté), copier `data/banque.db` suffit. Les sauvegardes restent illisibles sans la clé : **sauvegardez la clé séparément**.

### Comportement en cas de problème (l'application ne se rabat jamais sur du clair)

| Situation | Résultat |
|---|---|
| Clé configurée, base en clair | conversion automatique (ci-dessus) |
| Base chiffrée, **aucune clé** configurée | refus de démarrer (plutôt que créer une base vide à côté) |
| Mauvaise clé | refus de démarrer : « clé de chiffrement incorrecte… » ; aucun fichier modifié |
| Clé mal formée / fichier de clé absent ou illisible | refus de démarrer, avec la commande pour corriger |
| Aucune clé, base en clair | fonctionne comme avant, sans chiffrement (avertissement dans Paramètres) |

### Machine ARM (Raspberry Pi, NAS Synology/QNAP ARM)

Des roues précompilées de `sqlcipher3-binary` n'existent que pour Linux **x86_64**. Sur ARM, le `Dockerfile` compile le paquet
(il installe puis retire `build-essential`, et garde `libsqlcipher-dev`). **Ce chemin de compilation n'a pas pu être testé** dans l'environnement où le projet a été écrit ;
si le build échoue, le message d'erreur de l'étape `pip install` indique la dépendance manquante. Le build affiche `SQLCipher 4.x` quand tout est en place.

## Dépannage Docker

| Message | Cause et solution |
|---|---|
| `PermissionError: [Errno 13] Permission denied: '/srv/app/__init__.py'` | Fichiers du projet illisibles pour l'utilisateur du conteneur (umask 077 à l'extraction). Corrigé dans le `Dockerfile` (`chmod -R a+rX /srv`) ; pour une ancienne version : `chmod -R a+rX app scripts` puis `docker compose build --no-cache`. |
| `Le dossier de données « /data » n'est pas accessible en écriture…` | `./data` n'appartient pas à l'utilisateur du conteneur. Lancer avec `PUID=$(id -u) PGID=$(id -g) docker compose up -d`, ou `sudo chown -R $(id -u):$(id -g) ./data`. Créez `./data` **avant** le premier lancement (sinon Docker le crée en root). |
| Docker Compose se plaint du secret `banque_db_key` / du fichier `./secrets/db_key` introuvable au `docker compose up` | La clé n'existe pas encore : étape 1 du démarrage rapide. Pour **ne pas** chiffrer : retirer les blocs `secrets` et la ligne `DB_KEY_FILE` de `docker-compose.yml`. |
| `DB_KEY_FILE=… : lecture impossible pour l'utilisateur …` | `./secrets/db_key` n'appartient pas à `PUID` : `sudo chown $(id -u):$(id -g) ./secrets/db_key && chmod 600 ./secrets/db_key`. |
| `…est chiffrée mais aucune clé n'est configurée` | `DB_KEY_FILE`/`DB_KEY` absents alors que la base est chiffrée : restaurez la configuration d'origine. |
| `clé de chiffrement incorrecte (ou base non chiffrée)` | Ce n'est pas la clé qui a chiffré cette base. Retrouvez la bonne (sauvegarde de la clé). |
| `ERREUR : contenu inattendu pour …chart.umd.js` au build | Le téléchargement de Chart.js a échoué (pas d'accès Internet pendant le build) : vérifier le réseau/proxy du build, ou déposer `chart.umd.js` (Chart.js 4.4.7) dans `app/static/vendor/` avant le build. |

## Sans Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/fetch_vendor.py          # Chart.js : déjà fourni dans app/static/vendor/ (ne télécharge que s'il manque)
python scripts/generate_key.py          # clé de chiffrement (une fois)
DB_KEY_FILE=secrets/db_key uvicorn app.main:app --port 8000
```

## Utilisateurs

| | |
|---|---|
| **Données** | Chaque utilisateur a ses propres comptes, soldes initiaux, catégories, transactions et brouillon du simulateur. Rien n'est partagé ; un utilisateur ne peut ni lire ni modifier les données d'un autre (API : `404`). |
| **Administrateur** | `Admin` (créé à l'installation / migration) crée et supprime des utilisateurs, et réinitialise leurs mots de passe : **Paramètres → 👥 Utilisateurs**. Un administrateur peut en nommer d'autres à la création. |
| **Prérequis** | L'administrateur doit d'abord définir **son propre mot de passe** (sinon n'importe qui pourrait se connecter en son nom). Tant qu'il est seul et sans mot de passe, l'application reste en accès libre comme avant. |
| **Connexion** | Identifiant (insensible à la casse) + mot de passe. Dès qu'il y a 2 utilisateurs, la connexion est obligatoire et la protection ne peut plus être désactivée. |
| **Sessions** | Une session par appareil, indépendantes. Changer **son** mot de passe ne déconnecte pas les autres utilisateurs ; la réinitialisation par un admin ou la suppression d'un utilisateur coupent immédiatement ses sessions. |
| **Suppression** | Supprimer un utilisateur supprime **toutes** ses données (irréversible). On ne peut pas supprimer son propre profil. |

### Mise à niveau depuis la v1 (base sans utilisateurs)

Si vous utilisiez déjà la v1 (`data/banque.db` existant), la mise à niveau est **automatique au démarrage** :
copie de sauvegarde `data/banque.v1.bak.db` (chiffrée si une clé est configurée), puis migration atomique (rollback complet en cas d'erreur, l'application
refuse alors de démarrer). Toutes vos données et votre mot de passe passent à l'utilisateur `Admin` ; IDs de
transactions et soldes sont conservés. Seules les sessions ouvertes sont abandonnées (reconnexion unique).

## Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATA_DIR` | `data` (`/data` en Docker) | Dossier de `banque.db` et de l'éventuel `banque_data.json` |
| `DB_KEY_FILE` | *(vide)* | Chemin du fichier contenant la clé de chiffrement (64 caractères hexadécimaux). **Recommandé.** |
| `DB_KEY` | *(vide)* | Même clé, directement en variable (moins sûr : visible avec `docker inspect`). Ignorée si `DB_KEY_FILE` est défini. Sans clé : base non chiffrée. |
| `COOKIE_SECURE` | `false` | `true` dès que l'appli est servie en HTTPS |
| `SESSION_TTL_DAYS` | `30` | Durée de session **glissante** (prolongée à l'usage) |
| `ENABLE_DOCS` | `false` | `true` expose Swagger sur `/api/docs` |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | IP autorisées à fournir `X-Forwarded-For` (vraie IP pour l'anti brute-force : 8 échecs → blocage 15 min) |

## Reverse proxy

Aucune WebSocket : aucun en-tête `Upgrade` ni timeout spécial à configurer. Mettre `COOKIE_SECURE=true`.

```caddy
banque.example.com {
    reverse_proxy banque:8000
}
```

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Architecture

```
Navigateur ── JSON/HTTP ──► FastAPI (routes minces) ──► services.py (logique métier) ──► SQLite WAL + SQLCipher (AES-256)
   │                          └─ sert aussi l'UI statique         ▲                         └─ fichier chiffré sur le NAS
   └─ filtre / tri / résumé / simulateur : 100 % local            └─ sessions, mot de passe, données
```

* **Sans état serveur** : sessions en base (hash du jeton), cookie `HttpOnly` + `SameSite=Strict`, durée glissante.
  Redémarrer le conteneur ou passer par un proxy ne déconnecte personne.
* **Un seul appel au chargement** (`/api/bootstrap`), puis uniquement de petites requêtes ciblées.
* **Argent en centimes entiers** en base : aucune dérive d'arrondi dans les soldes.
* **Chiffrement** : clé brute 256 bits (`PRAGMA key = "x'…'"`, sans dérivation), vérifiée à chaque ouverture ; conversion clair → chiffré vérifiée par empreintes ; aucun repli silencieux vers le clair.

```
banque/
├── Dockerfile · docker-compose.yml · requirements*.txt · pytest.ini
├── secrets/db_key                 Clé de chiffrement (créée par vous, jamais versionnée ni copiée dans l'image)
├── scripts/                       fetch_vendor.py (Chart.js) · generate_key.py (clé) · backup.py (sauvegarde à chaud chiffrée)
├── app/
│   ├── main.py                    Routes REST, auth, en-têtes de sécurité, statique
│   ├── services.py                Utilisateurs, soldes, transactions, dashboard (SQL), paramètres, export CSV (tout filtré par user_id)
│   ├── security.py                SHA-256 compatible, sessions par utilisateur, anti brute-force
│   ├── migration.py               Import de banque_data.json
│   ├── db.py                      Connexion (SQLCipher), schéma v2, mise à niveau v1, conversion clair → chiffré
│   ├── schemas.py · config.py · constants.py · money.py
│   └── static/
│       ├── index.html · css/app.css
│       └── js/  main · api · store · ui · logic · dashboard · transactions · simulator · settings · theme
├── tests/                         unittest (logique + chiffrement), node:test (frontend), pytest (API)
└── data/                          banque.db chiffrée (volume Docker)
```

## API (JSON)

`GET /api/bootstrap` (inclut `db_encrypted`) · `GET /api/dashboard?year=&month=` · `POST|PUT|DELETE /api/transactions[/{id}]` ·
`POST|PUT|DELETE /api/accounts[/{nom}]` · `POST|PUT|DELETE /api/categories[/{nom}]` ·
`PUT /api/settings/password` (mon mot de passe) · `GET /api/export.csv` · `POST /api/auth/login` (`{username, password}`) · `POST /api/auth/logout` · `GET /api/auth/status` · `GET /api/health`

Administrateurs uniquement (`403` sinon) : `GET|POST /api/users` · `DELETE /api/users/{id}` · `PUT /api/users/{id}/password`

## Tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_services.py"     # logique métier, isolation entre utilisateurs, migrations
python -m unittest discover -s tests -p "test_encryption.py"   # chiffrement : aucun octet lisible, clé, conversion, reprise après crash, sauvegarde
python tests/make_fixtures.py                     # régénère les payloads réels du backend…
node --test tests/frontend_smoke.mjs              # …et rejoue le frontend dessus (mini-DOM, sans navigateur)
node --test tests/logic.test.mjs                  # filtres, tris, résumé, simulateur
pytest                                            # tout, y compris l'API de bout en bout (FastAPI TestClient)

# Toute la suite sur une base CHIFFRÉE :
BANQUE_TEST_DB_KEY=$(openssl rand -hex 32) pytest
```

## Écarts volontaires par rapport à Streamlit

1. **Courbe d'évolution des soldes corrigée.** L'ancienne version repartait des *soldes initiaux* chaque année,
   en ignorant les années précédentes : dès la 2ᵉ année la courbe ne correspondait plus aux soldes affichés.
   Elle part désormais du solde réel au 1ᵉʳ janvier (`services._evolution`).
2. **Liste triée par montant/catégorie** : liste continue au lieu de répéter un titre de mois à chaque changement de mois.
3. **Recherche** insensible aux accents et à la casse. Années proposées : 2020 → année courante + 4, étendu si des données plus anciennes existent.
4. Ajouts : **multi-utilisateurs** (voir plus haut), **base chiffrée au repos**, annulation de suppression (« Annuler » 7 s), confirmation avant
   suppression de compte/catégorie/réinitialisation, blocage après 8 échecs de connexion (15 min), révocation des sessions
   au changement de mot de passe.
5. Montants affichés au format français (`1 234,56 €`).

## Note de sécurité

Le mot de passe est stocké en **SHA-256 non salé**, volontairement, pour rester compatible avec les empreintes de
`banque_data.json`. Cette empreinte est désormais **à l'intérieur de la base chiffrée** (elle n'est plus lisible dans un fichier du NAS),
mais elle reste faible face à un attaquant qui aurait déjà accès à la base ouverte. C'est suffisant pour un usage personnel derrière HTTPS avec anti brute-force ; si l'appli est
exposée sur Internet, préférez un mot de passe long et/ou un contrôle d'accès au niveau du reverse proxy.
