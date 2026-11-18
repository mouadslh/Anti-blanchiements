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

## Phase 3 — rôle du jeu externe demandé par l'encadrant

- **Jeu principal :** transactions synthétiques générées localement par notre simulateur (comportement normal + cinq scénarios + labels séparés). C'est ce jeu qui alimente le flux Kafka et l'évaluation principale.
- **Jeu externe retenu :** SAML-D, uniquement comme **benchmark et référence de calibration** pour comparer des ordres de grandeur et vérifier que les taux/statistiques du simulateur ne sont pas aberrants. Les schémas et données restent séparés; aucune ligne SAML-D n'est mélangée, rejouée dans Kafka ou utilisée comme label du jeu v1.
- **Motif :** SAML-D documente 9 504 852 transactions et environ 0,1039 % de transactions suspectes; il apporte un point de comparaison public. Son échelle, ses typologies et ses conventions ne sont pas identiques à notre jeu et ne représentent pas spécifiquement des opérations bancaires marocaines.
- **Licence rapportée dans `docs/typologies.md` :** CC BY-NC-SA 4.0. Citer les auteurs et respecter l'usage non commercial/partage à l'identique; ne pas versionner le fichier externe dans le dépôt. Confirmer les conditions depuis la fiche du jeu avant de télécharger ou redistribuer.
- **Statut :** décision de travail pour le PFA, à faire confirmer explicitement par le Pr Chergui.

## Phase 4 — job Spark Structured Streaming (proposition à valider)

- Le job `aml.streaming.feature_job` consomme le contrat de transactions v1, interprète `timestamp` en UTC, applique un watermark configurable (2 h provisoires), déduplique `tx_id` dans cette durée, développe les opérations internes en événements source/cible et calcule une sortie par `(account_id, tx_id, side)`.
- Les fenêtres glissantes sont les intervalles exacts `(as_of - H, as_of]` pour 1 h, 24 h et 7 jours. Le ratio au montant historique utilise les 30 derniers jours par défaut et exclut l'événement déclencheur; le seuil 100 000 MAD est un paramètre de simulation, pas une obligation réglementaire.
- La sortie suit la proposition C-06/C-07 de `specification_technique_aml.md`. Elle coexiste avec l'ancien DDL partagé `account_features` compte/fenêtre : le job crée `account_features_stream` avec une clé `(account_id, tx_id)` pour une écriture PostgreSQL idempotente. Cette évolution de contrat doit être revue par Mouad et Mounir avant gel.
- Le checkpoint est monté dans `./checkpoints` et le service Spark est derrière le profil Compose `streaming`; lancement via `python manage.py stream`. Le broker garde le listener hôte `localhost:9092` et ajoute `kafka:29092` pour les conteneurs. La limite mémoire Spark est 2 Gio et le master `local[2]`. Aucun changement `.env` n'est requis; le mot de passe PostgreSQL existant est transmis par Compose.
- Kafka Structured Streaming garantit au mieux une écriture « au moins une fois » vers Kafka : un rejeu peut dupliquer des messages après panne. PostgreSQL est protégé par upsert sur la clé logique; les consommateurs Kafka doivent dédupliquer par `(account_id, tx_id, side)`. Ne pas présenter le pipeline complet comme « exactly once ».
- Le délai watermark de 2 h reste provisoire (Q-02 non tranchée). Les événements expirés au-delà du watermark sont exclus des variables et doivent être surveillés via le journal de progression/les métriques de données tardives.

## Phase 4 — règles et modèles de base (proposition, Mounir)

- Score de règle : 0 ou 0,5 à 1,0 selon le dépassement du seuil, maximum sur les règles ; alternative écartée : score binaire (trop d'égalités pour le classement top-k).
- Unité de calcul par événement, alerte par (compte, jour) au maximum du jour ; entraînement XGBoost sur tous les événements de l'entraînement avec `scale_pos_weight` automatique ; alternative non essayée : sous-échantillonnage des négatifs.
- Labels d'entraînement censurés au dernier jour d'entraînement (L-5) ; seuil choisi sur la validation seulement (L-7).
- Deux variables d'extension hors contrat v1 pour les règles ; à valider avec Mouad.

- Pour rendre les quatre règles du prompt exécutables, trois signaux supplémentaires sont proposés : `days_since_previous_tx`, `current_channel_cash`, `current_channel_international`. Ils sont émis par Spark dans la carte `features`; approbation et incrément éventuel de `feature_version` restent à faire avant gel du contrat.

## Phase 4 — modèles de base et évaluation (implémentation à valider)

- Un exemple d'apprentissage/évaluation est le dernier événement observé de chaque compte et jour UTC; ses features sont les mêmes calculs arrière que Spark, calculés à `as_of`. Les labels d'intervalle marquent la cible après extraction; identifiants de compte, cas, typologie et niveau sont exclus de la matrice.
- Découpage conservé comme dans `docs/evaluation_plan.md`: jours 8–56 train, 57–72 validation, 73–90 test, sans permutation. Un modèle IF et XGBoost est entraîné séparément par graine (Option A); les seuils d'alerte sont calibrés sur validation par coût et capacité k/jour. Les hyperparamètres XGBoost restent fixés dans le YAML pour cette comparaison de base; aucune recherche sur le test.
- Comparatif effectivement produit pour la démonstration: profil `light`, graine 44; un seul cas de test, donc métriques exploratoires uniquement. Les rapports sont `reports/model_comparison_light_seed44.md/.json`. SAML-D reste une référence de calibration envisagée, sans entraînement ni mélange externe. Le rôle de la dataset externe demeure à confirmer par le professeur; les résultats sur le simulateur ne sont pas transposables à une banque réelle.
- Le worker scorer consomme `features` et produit `scores`/`alerts` via Kafka pour le modèle sélectionné dans la configuration. Le modèle par défaut est XGBoost; aucun label n'est monté dans le conteneur.
- Aucun modèle « gagnant » n'est retenu : un seul cas de test ne permet pas une sélection fiable. L'ensemble pondéré/stacking, graphe, SHAP et dashboard complet sont hors de ce gate (phase 5).
