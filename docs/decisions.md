# Décisions techniques

## Phase 0 — bootstrap

- Kafka utilise l'image officielle `apache/kafka` en mode KRaft à un seul nœud. Un seul broker réduit la mémoire et évite Zookeeper; ce choix convient au prototype local, pas à une haute disponibilité.
- PostgreSQL utilise l'image officielle `postgres`; Grafana utilise `grafana/grafana-oss`. Les versions épinglées sont Kafka 4.3.2, PostgreSQL 17.11-bookworm et Grafana OSS 12.3.1; elles exposent des images linux/amd64 et linux/arm64 vérifiées sur leurs pages officielles Docker Hub le 7 novembre 2026.
- La vérification directe `docker buildx imagetools inspect` a confirmé `linux/amd64` et `linux/arm64` pour chacun des trois tags sélectionnés.
- Les limites Docker locales sont respectivement 2 Gio, 1 Gio et 512 Mio, soit 3,5 Gio au total. Le dernier relevé `docker stats --no-stream` indiquait environ 519 Mio utilisés au total sur cette machine (Kafka 385,3 Mio, PostgreSQL 29,5 Mio, Grafana 104,5 Mio).
- PostgreSQL est exposé au port hôte 5433 par défaut pour éviter un conflit avec un serveur PostgreSQL local déjà présent; le port est configurable dans `.env`.
- `manage.py` n'a que des dépendances de la bibliothèque standard en phase 0 afin de pouvoir orchestrer la préparation avant l'installation des dépendances de modélisation.
