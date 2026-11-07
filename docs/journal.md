# Journal de bord

## 2026-11-07 — Phase 0 (bootstrap)

- Création de la structure initiale, de la CLI Python, du squelette CI, de la configuration Docker et du README.
- Décisions détaillées dans `docs/decisions.md`.
- `python3 manage.py test` : 3 tests réussis.
- `python3 manage.py up` : pile lancée; topics `transactions`, `features`, `scores`, `alerts` créés; publication/consommation Kafka réussie; datasource PostgreSQL provisionnée et connexion Grafana confirmée (`Database Connection OK`).
- `docker buildx imagetools inspect` confirme les plateformes `linux/amd64` et `linux/arm64` pour chaque tag retenu.
- Mesure `docker stats --no-stream` : dernier relevé à environ 519 Mio (Kafka 385,3 Mio, PostgreSQL 29,5 Mio, Grafana 104,5 Mio; limites cumulées configurées : 3,5 Gio). La consommation varie selon l’activité du broker.
- Premier démarrage bloqué par le port hôte 5432 déjà utilisé; PostgreSQL est donc publié en 5433 par défaut, configurable via `POSTGRES_PORT`.
- Dépôt local initialisé sur `main` et `origin` configuré vers l'URL fournie; aucun commit ni push effectué. L'accès réseau ordinaire à GitHub échouait par DNS, le contrôle distant avec accès renforcé n'a retourné aucune référence.
