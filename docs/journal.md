# Journal de bord

## 2026-11-07 — Phase 0 (bootstrap)

- Création de la structure initiale, de la CLI Python, du squelette CI, de la configuration Docker et du README.
- Décisions détaillées dans `docs/decisions.md`.
- `python3 manage.py test` : 3 tests réussis.
- `python3 manage.py up` : pile lancée; topics `transactions`, `features`, `scores`, `alerts` créés; publication/consommation Kafka réussie; datasource PostgreSQL provisionnée et connexion Grafana confirmée (`Database Connection OK`).
- `docker buildx imagetools inspect` confirme les plateformes `linux/amd64` et `linux/arm64` pour chaque tag retenu.
- Mesure `docker stats --no-stream` : dernier relevé à environ 519 Mio (Kafka 385,3 Mio, PostgreSQL 29,5 Mio, Grafana 104,5 Mio; limites cumulées configurées : 3,5 Gio). La consommation varie selon l’activité du broker.
- Premier démarrage bloqué par le port hôte 5432 déjà utilisé; PostgreSQL est donc publié en 5433 par défaut, configurable via `POSTGRES_PORT`.
- Dépôt local initialisé et `origin` configuré vers l'URL fournie. Le commit de bootstrap `e6d5b3e` a été poussé sur `main`. L'accès GitHub a d'abord échoué par DNS dans l'environnement restreint, puis le push a réussi avec l'accès réseau autorisé.

## 2026-11-08 — Phase 1 : notions Kafka et Spark (Mouad)

- Créé `docs/phase1_streaming_fundamentals.md` sur une branche de tâche dédiée `task/mouad-kafka-spark-fundamentals`, à partir du dernier `origin/main`.
- Résumé des topics, partitions, clés, offsets, consumer groups, temps événementiel, fenêtres glissantes, watermarks, micro-batches et checkpoints, avec application au pipeline AML.
- Sources consultées : documentation officielle Apache Kafka 4.3 et Apache Spark 4.3 / API PySpark.
- Relevé les questions à résoudre avant de figer le contrat : divergence de schéma et de clé entre le prompt maître et `specification_technique_aml.md`, sémantique temporelle, forme des fenêtres, retard watermark, idempotence PostgreSQL et nombre de partitions.
- Aucune modification de Docker ou de `.env`; aucun choix de contrat v1 n'a été figé. Travail documentaire seulement; aucun test de code n'était applicable.
- Mise à jour de la note avec une introduction expliquant son importance et le rôle de Mouad, puis ajout de réponses au regard du prompt maître pour le schéma, l'horodatage, les fenêtres, le watermark, les checkpoints, les doublons PostgreSQL et les partitions.
