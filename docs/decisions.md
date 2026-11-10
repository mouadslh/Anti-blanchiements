# Décisions techniques

## Phase 0 — bootstrap

- Kafka utilise l'image officielle `apache/kafka` en mode KRaft à un seul nœud. Un seul broker réduit la mémoire et évite Zookeeper; ce choix convient au prototype local, pas à une haute disponibilité.
- PostgreSQL utilise l'image officielle `postgres`; Grafana utilise `grafana/grafana-oss`. Les versions épinglées sont Kafka 4.3.2, PostgreSQL 17.11-bookworm et Grafana OSS 12.3.1; elles exposent des images linux/amd64 et linux/arm64 vérifiées sur leurs pages officielles Docker Hub le 7 novembre 2026.
- La vérification directe `docker buildx imagetools inspect` a confirmé `linux/amd64` et `linux/arm64` pour chacun des trois tags sélectionnés.
- Les limites Docker locales sont respectivement 2 Gio, 1 Gio et 512 Mio, soit 3,5 Gio au total. Le dernier relevé `docker stats --no-stream` indiquait environ 519 Mio utilisés au total sur cette machine (Kafka 385,3 Mio, PostgreSQL 29,5 Mio, Grafana 104,5 Mio).
- PostgreSQL est exposé au port hôte 5433 par défaut pour éviter un conflit avec un serveur PostgreSQL local déjà présent; le port est configurable dans `.env`.
- `manage.py` n'a que des dépendances de la bibliothèque standard en phase 0 afin de pouvoir orchestrer la préparation avant l'installation des dépendances de modélisation.

## Phase 2 — proposition de contrat (à valider)

- Le schéma des transactions suit les noms, enums et champs du prompt maître; les messages transactionnels n'acceptent pas de champs supplémentaires, ce qui empêche notamment l'injection de vérité terrain dans Kafka.
- Le code de validation utilise la bibliothèque standard afin de ne pas ajouter de dépendance pour valider JSON, timestamps UTC et nombres décimaux.
- La forme des messages `features` est proposée par compte et fenêtre, avec une clé PostgreSQL `(account_id, window_start, window_end)`. Les sorties de score et d'alerte sont provisoirement uniques par `tx_id`. Ces clés rendent possibles des écritures rejouables, mais doivent être confirmées par les deux étudiants avant gel.
- `sql/schema.sql` garde la table `labels` isolée des tables lues par le scoring. Les contraintes portent la même validation enum que les schémas Python.
- Le DDL de phase 2 ne crée pas de rôle applicatif; l'intégration devra fournir au service de scoring un rôle sans privilège `SELECT` sur `labels`.
- La spécification attribuée à Mounir n'est pas présente dans `origin/main` actuel; aucune affirmation de réconciliation avec ce document n'est faite ici. Le contrat reste une proposition tant qu'une revue croisée n'a pas eu lieu.
- Le plan d'évaluation de phase 1 fixe une unité d'alerte compte/jour, alors que le message de score du prompt est transactionnel (`tx_id`). La granularité et l'agrégation des alertes restent une décision commune; la clé provisoire du DDL ne doit pas être interprétée comme un choix final.
- Les documents de phase 1 signalent aussi des champs candidats absents du contrat maître (solde, bénéficiaire effectif, pays de destination). Aucun n'a été ajouté sans décision des deux étudiants.
