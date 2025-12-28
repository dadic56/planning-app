# Planning App (prototype)

Démarrage rapide

1. Créer un environnement virtuel et installer les dépendances :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Initialiser la base et peupler les données de démonstration :

```bash
python scripts/seed_demo.py --reset
```

3. Lancer le serveur :

```bash
flask --app run.py run --reload
```

API minimale disponible :
- `GET /api/employees`
- `POST /api/employees`
- `GET /api/base-shifts`
- `POST /api/base-shifts`
- `GET /api/absences`
- `POST /api/absences`
- `POST /api/generate-week` (stub)
- `GET /api/snapshots` / `POST /api/snapshots`

Voir `app/` pour le code source.
