# Détection AML en flux — PFA

Projet de simulation et de détection de typologies de blanchiment sur un flux de transactions synthétiques. Les données sont simulées; aucun flux ni label bancaire réel n'est utilisé.

## Phase 0 — démarrage local

Prérequis : Docker avec Docker Compose, et Python 3.11. Sur Windows, Docker Desktop avec WSL2.

Copier `.env.example` vers `.env`, puis lancer :

```text
python manage.py up
```

La commande démarre Kafka (KRaft), PostgreSQL et Grafana, crée les topics de base et réalise un contrôle de publication/consommation Kafka ainsi que de la datasource PostgreSQL de Grafana. Interface : http://localhost:3000 (identifiants locaux par défaut `admin` / `admin_local_dev`). Changez-les avant tout usage partagé. PostgreSQL est exposé sur le port hôte 5433 par défaut (`POSTGRES_PORT`), afin d'éviter le conflit courant avec une installation locale.

Commandes : `python manage.py down`, `python manage.py reset` (supprime aussi les volumes), `python manage.py test`. Les commandes `simulate`, `train` et `evaluate` seront ajoutées dans leurs phases respectives.

Les limites mémoire Compose de cette phase totalisent 3,5 Gio (Kafka 2 Gio, PostgreSQL 1 Gio, Grafana 512 Mio), sous le plafond visé de 6 Gio pour la pile. Le dernier relevé local (`docker stats`) était d’environ 519 Mio au total.
