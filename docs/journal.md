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
- La vérification CI de la pull request existante a révélé un échec Ruff préexistant sur l'ordre des imports de `manage.py`; ordre corrigé dans la branche propre pour obtenir une CI vérifiable avant fusion.
- Le contrôle CI de la PR #2 a ensuite révélé que pytest ne trouvait pas `manage` lors de la collecte des tests. Ajout de la racine du dépôt à `pythonpath` dans la configuration pytest pour rendre la collecte déterministe en CI.

## 2026-11-08 — Phase 1 (sources AML et catalogue des typologies)

**Phase :** Phase 1 (semaine 1, côté Mounir). Ticket Jira « Sources AML et catalogue des typologies ».

**Travail réalisé**

- Création de `docs/typologies.md` (v1.1) : cadre de référence, fiches des cinq scénarios (fractionnement, layering, comptes relais, flux circulaires, sociétés écran) avec fonctionnement simulé, signaux observables rattachés aux variables du projet et paramètres (plage et valeur par défaut), trois niveaux de sophistication (faible, moyen, élevé), état de l'art règles / apprentissage automatique / graphes, jeux de données synthétiques publics avec licences et limites, hypothèses, points ouverts.
- Relecture du texte consolidé de la loi 43-05 (modifiée par la loi 12-18) sur le site du ministère de la Justice. Constats utiles au projet :
  - la loi ne fixe aucun montant minimal pour la déclaration de soupçon (art. 9) ;
  - les seuils chiffrés présents (30 000 MAD casinos, 150 000 MAD négociants en pierres et métaux précieux, art. 5) ne concernent pas les dépôts bancaires ;
  - l'organe national est l'ANRF, qui remplace la dénomination UTRF (art. 14 et 39).
- Décision de rédaction : `REPORTING_THRESHOLD` (100 000 MAD) est documenté comme **hypothèse de simulation, non comme obligation légale**.
- Sources GAFI relues : annexe E du rapport GAFI/Egmont de 2018 (indicateurs de sociétés écran et de transactions cycliques), résumé exécutif du rapport *Professional Money Laundering* (2018), numérotation des Recommandations (R.10, R.20, R.24, R.25).
- Références marocaines complémentaires : liste officielle des textes de vigilance de Bank Al-Maghrib, rapport d'évaluation mutuelle de 2019 (existence), statut du Maroc auprès du GAFI (liste grise de février 2021 à février 2023, à confirmer sur fatf-gafi.org).
- Licences vérifiées : AMLworld/IBM (données CDLA-Sharing-1.0), SAML-D (CC BY-NC-SA 4.0), AMLSim (Apache-2.0), AMLGentex (code Apache-2.0, licence des données non établie).
- Décision proposée sur les taux et volumes (à valider par l'équipe) : à 0,5 % de 5 000 comptes, les tailles de cas du catalogue ne permettent d'injecter qu'environ 3 cas au total, donc pas un cas par scénario. Proposition : piloter par nombre de cas, profil `light` (5 000 clients, 1 cas par scénario, environ 0,76 % des comptes) et profil `full` (20 000 clients, 15 cas, environ 0,57 % des comptes), au moins 3 graines (5 visées), intervalles de Wilson. Le « 0,1 % » de la feuille de route se lit comme un taux de transactions (même ordre que SAML-D et IBM).

**Sources consultées** (liens dans `docs/typologies.md`, section 9)

- Loi 43-05 consolidée après loi 12-18, ministère de la Justice (lue en entier).
- Bank Al-Maghrib : page « Rôle de Bank Al-Maghrib dans le cadre du dispositif LBC-FT » et communiqué du Comité des établissements de crédit du 22 octobre 2026.
- GAFI : page des Recommandations, rapport GAFI/Egmont 2018 et annexe E, *Professional Money Laundering* (résumé exécutif), page du rapport d'évaluation mutuelle du Maroc (2019).
- Altman et al. (NeurIPS 2023, AMLworld) ; Weber et al. (KDD 2019, Elliptic) ; Oztas et al. (SAML-D, IEEE ICEBE 2023, et thèse) ; AMLGentex (arXiv 2506.13989) ; dépôts GitHub IBM/AML-Data, IBM/AMLSim, aidotse/AMLGentex.

**Points à vérifier**

- Contenu des circulaires et directives de Bank Al-Maghrib (PDF scannés, illisibles automatiquement) : à lire à la main pour confirmer l'absence ou la présence de seuils chiffrés.
- Textes d'application de l'art. 9.1 (déclarations systématiques) : non trouvés.
- Corps du rapport GAFI *Professional Money Laundering* (téléchargement bloqué) et rapport d'évaluation mutuelle du Maroc de 2019 : à lire.
- Licence des données AMLGentex : aucune réponse publique trouvée.
- Décision sur les taux et volumes : à valider par les deux membres, puis à reporter dans `MASTER_PROMPT_PFA_AML.md` (ligne 54) et `Roadmap_PFA_Detection_Blanchiment.md` (lignes 50 et 96).
- Articles de loi cités : à conserver avec leur source et leur date dans le rapport final, conformément à la consigne du MASTER_PROMPT.
- Remplacer « UTRF » par « ANRF (ex-UTRF) » dans `MASTER_PROMPT_PFA_AML.md` après accord de l'équipe.
- Champ « bénéficiaire effectif » absent du contrat de données v1 : à discuter avant le gel du contrat (phase 2).
- Validation du catalogue par le Pr Chergui.

## 2026-11-09 — Phase 1 (hypothèses du simulateur v1)

**Phase :** Phase 1 (semaine 1, côté Mounir). Ticket Jira « Hypothèses du simulateur v1 ».

**Travail réalisé**

- Création de `docs/simulator_assumptions.md` (v1, brouillon) : population (profils salariés, étudiants, commerçants, entreprises), volumes, montants, canaux, contreparties, rythmes quotidiens, hebdomadaires et mensuels, saisonnalité Ramadan et Aïd, comportements normaux « piégeux » (source de fausses alertes), taux de comptes et de transactions suspects, résumé des paramètres des scénarios, limites des données simulées.
- Chaque valeur est marquée **[H]** (hypothèse) avec sa justification ; les hypothèses H-01 à H-07 de `docs/typologies.md` gardent leur numéro, les nouvelles vont de H-08 à H-23.
- Distinction explicite entre **proportion de comptes impliqués** (contrainte < 1 %) et **proportion de transactions suspectes** (comparable aux jeux publics). Profils : `light` 0,76 % de comptes et 0,08 % de transactions ; `full` 0,57 % et 0,06 %.
- Volumes calculés à partir des hypothèses : moyenne pondérée de 79,7 transactions par client sur 90 jours, soit environ 398 500 transactions pour 5 000 clients et 1,59 million pour 20 000.
- Tableau des écarts entre `MASTER_PROMPT_PFA_AML.md` (ligne 54) et `Roadmap_PFA_Detection_Blanchiment.md` (lignes 50 et 96) avec résolution proposée (reprise de D-1 à D-6).
- Dates du Ramadan 1448 (8 février 2027) et de l'Aïd el-Fitr (9 ou 10 mars 2027) issues de **prévisions astronomiques de presse**, non officielles : marquées [À vérifier] ; utilisées uniquement comme dates fictives de simulation.

**Décisions (à valider par l'équipe)**

- Période simulée du 2027-01-15 au 2027-04-14 (90 jours) pour contenir un Ramadan et un Aïd.
- Densité de 80 transactions par client conservée entre `light` et `full`.
- Les valeurs de population, de volume, de montant et de rythme sont toutes des hypothèses, aucune source marocaine n'ayant été trouvée.
- Chaque cas doit tenir dans un seul bloc d'évaluation (H-23).

**Questions ouvertes**

- Validation de la résolution des volumes et des taux, puis alignement de `MASTER_PROMPT_PFA_AML.md` et de la feuille de route.
- Avec la date de début retenue, le Ramadan tombe dans le bloc d'entraînement et pas dans le test : décalage à assumer ou à corriger.
- Les durées par défaut de certains cas (flux circulaires : 30 jours ; fractionnement : 14 jours) sont longues par rapport aux blocs d'évaluation ; raccourcir ou allonger la période (par exemple 120 jours pour `full`).
- Réalisme des cas normaux « piégeux » et poids des profils : relecture par le Pr Chergui.
- Champs absents du contrat v1 (solde, bénéficiaire effectif, pays de destination), tailles de cas H-07 à recalculer avec le vrai simulateur, textes de Bank Al-Maghrib à lire à la main.
- Travail documentaire seulement ; aucun test de code n'était applicable.

## 2026-11-09 — Phase 1 (plan d'évaluation v1 et matrice de coûts)

**Phase :** Phase 1 (semaine 1, côté Mounir). Ticket Jira « Plan d'évaluation v1 et matrice de coûts ».

**Travail réalisé**

- Création de `docs/evaluation_plan.md` (v1, brouillon), rédigé avant tout entraînement : unité d'alerte (compte, jour), définition d'un cas détecté, découpage temporel, règles anti-fuite, métriques, matrice de coûts, analyse de sensibilité, protocole d'exécution, limites.
- **Découpage temporel** (jours 1 à 90) : échauffement 1–7, entraînement 8–56, validation 57–72, test 73–90 ; aucun mélange aléatoire ; test unique par graine après gel des choix ; test d'invariance au futur prévu en phase 4.
- **Métriques** : precision@k et recall@k par jour (k = 50 par défaut, configurable dans `config/scoring.yaml`), rappel par typologie et par niveau avec intervalles de Wilson, délai de détection, courbe précision-rappel, coût total, latence p50/p95/p99 et débit.
- **Matrice de coûts** (hypothèses) : `c_FP` = 1 unité (une revue d'alerte), `c_FN` = 200 unités ; sensibilité sur `r = c_FN / c_FP` ∈ {10, 50, 100, 200, 500, 1000} et sur `k` ∈ {10, 25, 50, 100, 200}. Coûts relatifs, non chiffrés en MAD faute de source.

**Constats importants**

- **Plafond de la precision@k** : avec une dizaine à une trentaine de comptes positifs par jour dans le test `full` (estimation à recalculer), une precision@50 est plafonnée à environ 0,2 à 0,6 même pour un détecteur parfait. Proposition : rapporter aussi le plafond et la precision@k normalisée.
- **Peu de positifs d'entraînement** : environ 38 comptes par graine dans le bloc d'entraînement `full`. Deux options proposées (modèle par graine, ou entraînement sur les autres graines).

**Décisions (à valider par l'équipe)**

- Les cinq scénarios placent chacun un cas dans chaque bloc, avec une permutation des niveaux tirée de la graine : 5 cas de test par graine, 25 avec 5 graines.
- Latence technique mesurée de la publication Kafka à l'alerte ; délai de détection métier mesuré à part.

**Questions ouvertes**

- Option A ou B pour l'entraînement ; durée maximale des cas (16 jours selon la règle L-6) ; présentation de la precision@k avec son plafond.
- Formulation « temps événementiel jusqu'à l'alerte » du prompt maître non mesurable avec un rejeu accéléré ; `top-k` calculé en fin de journée ou en ligne.
- Valeurs de `c_FN` et de `k` à discuter avec le Pr Chergui ; fixer les paramètres du test de dérive avant l'évaluation finale.
- Travail documentaire seulement ; aucun test de code n'était applicable.

## 2026-11-10 — Phase 2 : contrat et schémas (Mouad)

- Rédigé `docs/data_contract.md` selon la section 6 du prompt maître; le statut reste « proposition à valider » par Mouad et Mounir.
- Implémenté les validateurs Python pour `transactions`, `features`, `scores` et `alerts` dans `src/aml/common/schemas.py`; le schéma de transaction rejette notamment les champs de label.
- Créé `sql/schema.sql` pour transactions brutes, features, scores, alertes et labels séparés, avec clés et index proposés pour faciliter les reprises idempotentes.
- Noté que le DDL n'attribue pas de rôles PostgreSQL; le compte utilisé par le scoring devra être privé de lecture sur `labels` lors de l'intégration.
- Ajouté les tests de contrat dans `tests/test_schemas.py`. Avec Python 3.11.17 : `pytest tests/test_schemas.py -q` réussit (16 tests) et la suite complète `pytest -q` réussit (19 tests); `ruff check .`, `compileall` et `git diff --check` réussissent également. Pytest et Ruff ont été installés temporairement sous `/private/tmp`, sans modification de l'environnement global.
- Le démon Docker n'était pas actif, donc le DDL n'a pas été appliqué à la base locale; `sql/schema.sql` est livré comme script de création idempotent, à appliquer et vérifier lorsque PostgreSQL sera disponible.
- La spécification `docs/specification_technique_aml.md` attribuée à Mounir n'est pas présente dans le `origin/main` actuel; sa comparaison reste ouverte. Les livrables de phase 1 présents dans `origin/main` soulèvent aussi deux points pour la revue commune : unité d'alerte compte/jour versus score transactionnel, et champs candidats (solde, bénéficiaire effectif, pays de destination) absents du prompt maître. Aucun fichier Docker ou `.env` n'a été modifié.

## 2026-11-10 — Phase 2 : spécification technique du contrat v1 (Mounir)

**Phase :** **Phase 2** (contrat et schémas, côté Mounir). Ticket Jira « Spécification technique du contrat v1 ».

**Changements effectués**

- Création de `docs/specification_technique_aml.md` : proposition de contrat v1 pour les topics `transactions`, `features`, `scores` et `alerts`, pour les labels et pour les écritures PostgreSQL. Elle contient un tableau de comparaison (prompt maître, ancienne spécification, proposition de Mouad), les décisions C-01 à C-14, les questions ouvertes Q-01 à Q-10, des exemples de messages et une liste de contrôle pour la revue de Mouad.
- Ajout de cette entrée au journal.
- **Aucun autre fichier modifié.** Ni `docker-compose.yml`, ni `.env`, ni `.env.example`, ni `schemas.py`, ni `sql/schema.sql`, ni les tests : ces fichiers dépendent des choix proposés et ne seront modifiés qu'après validation commune.

**Décisions proposées et justification**

- **Noms du prompt maître conservés** (`tx_id`, `timestamp`, `source_account_id`, `target_account_id`), avec une table de correspondance depuis `transaction_id`, `event_time`, `account_id`. Justification : le prompt est la référence commune, et Mouad a déjà implémenté ces noms.
- **`timestamp` = heure d'exécution simulée en UTC ; le jitter ne modifie que l'ordre d'arrivée.** Justification : les fenêtres Spark et les tests de fuite reposent sur le temps événementiel (note de Mouad).
- **Montant strictement positif, 2 décimales, `currency` = `MAD`.** Justification : le sens du flux est porté par le canal, et les commissions du layering se lisent dans la différence de montant.
- **Convention des comptes (`acct-`, `ext-`, `ext-cash`) et direction des flux par canal.** Justification : le prompt ne dit pas qui est la source d'un dépôt ou d'un retrait d'espèces ; une convention centrée sur le compte client garde une bonne clé de partition et donne un sens aux ratios entrées/sorties.
- **`features` émis par (compte, transaction déclenchante), clé `(account_id, tx_id)`, fenêtres arrière arrêtées à `as_of`.** Justification : cela relie directement `features` à `scores` (clé du prompt), exclut toute fuite par construction et borne l'état Spark. Remplace `window_start` / `window_end` de la proposition actuelle.
- **`scores` : clé `(tx_id, account_id)`, `ts` simulé.** Justification : une transaction concerne deux comptes, donc la clé `tx_id` seule de `sql/schema.sql` provoquerait des collisions ; un `ts` simulé rend le message rejouable à l'identique.
- **`alerts` : unité (compte, jour UTC), seuil en ligne, top-k calculé en évaluation, upsert qui garde le score maximal.** Justification : alignement avec `evaluation_plan.md` ; le maximum est commutatif, donc l'ordre de rejeu n'a pas d'effet.
- **Labels : ajout de `case_id` et `sophistication`, énumérations `scenario` et `role`.** Justification : nécessaires pour définir un « cas détecté » et le rappel par niveau (`evaluation_plan.md`). Labels toujours hors des topics.
- **Idempotence : une règle d'écriture par table, tx_id déterministe, une graine par base.**
- **1 partition Kafka conservée**, clés définies pour passer plus tard à plusieurs partitions sans changer le contrat.

**Divergences résolues dans la proposition**

- `card` contre `card_payment` : `card` retenu (à corriger dans `simulator_assumptions.md`).
- Unité d'alerte compte/jour contre score par transaction : deux niveaux (score par compte et transaction, alerte par compte et jour).
- Clés `tx_id` seules dans le DDL : remplacées par des clés contenant le compte.

**Divergences et questions signalées pour décision commune** (détail en section 10 du document)

- Format d'émission des `features` (Q-01) : faisabilité Spark à confirmer par Mouad ; alternative décrite (instantané horaire).
- Valeur du watermark et jitter (Q-02) ; extension `layer_scores` (Q-03) ; champs solde, bénéficiaire effectif, pays absents en v1 (Q-04, recommandation : ne pas les ajouter) ; fuseau du rythme journalier (Q-07) ; énumération `role` (Q-08) ; graines multiples hors ligne (Q-09) ; rôle PostgreSQL du scoring, qui exigera une modification de Docker donc un accord commun (Q-10).

**Limites et points non vérifiés**

- **La spécification d'origine `specification_technique_aml.md` n'était pas dans le dépôt.** La comparaison avec elle se limite aux trois noms de champs connus par la note de Mouad (`transaction_id`, `event_time`, `account_id`). Autres écarts à reporter depuis la copie locale (Q-05) avant l'envoi en revue.
- Travail documentaire : aucun code ni DDL modifié. Vérifications faites : les 4 exemples de transactions du document passent `validate_transaction`, les 7 blocs JSON sont syntaxiquement valides, `pytest -q` (19 tests) et `ruff check .` réussissent sur le dépôt inchangé. Les exemples `features`, `scores` et `alerts` **ne passent pas** le validateur actuel : c'est voulu, leur forme diffère de la proposition de Mouad (section 11 du document).
- Les valeurs des exemples de `features`, de scores et de l'explication sont illustratives, pas issues d'une exécution.
- Docker non testé : aucune modification de la pile.

**Prochaine étape :** revue de Mouad (réponses Q-01 à Q-10, puis `VALIDATED phase 2` ou corrections). Mise à jour de `schemas.py`, de `sql/schema.sql`, des tests et de `docs/decisions.md` seulement après cet accord.

## 2026-11-12 — Phase 3 : simulateur normal et rejeu (Mouad)

**Périmètre :** uniquement les tâches individuelles de Mouad. Les scénarios de blanchiment, leurs labels, la sélection éventuelle d'un jeu public et la génération finale commune ne sont pas inclus.

- Ajout de `src/aml/simulator/normal.py` : génération reproductible des profils clients, comptes, transactions normales, contreparties, montants, canaux, villes, heures et dates de simulation; ordre global chronologique et identifiants stables par graine. Les événements passent par le validateur existant et n'embarquent aucun label.
- Extension de `manage.py simulate` : profils `light`/`full`, `--seed`, `--output`, `--report`, `--replay`, `--store-raw` et `--rate` (100 par défaut, plafond 500).
- Ajout de l'extra optionnel `.[streaming]` (Confluent Kafka et psycopg) ; publication idempotente vers `transactions` et insertion PostgreSQL avec `ON CONFLICT (tx_id) DO NOTHING`.
- Ajout de `docs/simulator_usage.md` avec commandes, hypothèses et limites. Les statistiques scénario/taux suspect ne sont pas inventées avant intégration de la tâche Mounir.
- Aucun changement de Docker Compose, `.env`, schéma SQL, contrat partagé, fichier de roadmap, scénario ou label. La roadmap locale de l'utilisateur demeure hors de ce commit.

**Validation d'intégration :** services Docker non démarrés ici; Kafka/PostgreSQL ne sont donc pas contactés. Les opérations `--replay` et `--store-raw` nécessitent les dépendances optionnelles et les services déjà prêts. (À compléter après revue/validation de l'équipe.)

## 2026-11-13 — Phase 3 : injection des scénarios AML et labels (Mounir)

**Phase :** Phase 3 (simulateur, côté Mounir). Ticket Jira « Injecter les scénarios AML et produire les labels ».

**Travail réalisé**

- Ajout de `src/aml/simulator/scenario_config.py` (défauts, plages du catalogue, validation, tirage des paires `[min, max]`), `scenarios.py` (les cinq constructeurs : fractionnement, layering, comptes relais, flux circulaires, sociétés écran), `dataset.py` (plan des cas, placement, fusion avec le flux normal, `tx_id`, labels, manifeste) et `labels.py` (schéma, validation, CSV, rapport). Ajout de `config/simulator.yaml` (copie exacte des défauts, vérifiée par test).
- `python manage.py simulate` injecte maintenant les scénarios par défaut et écrit les labels à part (`data/labels/`) ; `--normal-only` conserve l'ancien comportement ; `--scenario-config` charge des surcharges YAML ; `--labels-output` choisit la sortie des labels. Le rapport `--report` remplace les trois champs « non générés » par des valeurs mesurées.
- Labels : `account_id, tx_id, scenario, role, start_ts, end_ts, case_id, sophistication` (contrat C-11 de `specification_technique_aml.md`). Lignes compte-rôle (`tx_id` vide) et lignes transaction. Aucun label dans le CSV de transactions ni dans Kafka : `validate_transaction` rejette tout champ inconnu et un test rejoue des transactions de scénario via `publish_kafka` (producteur simulé) pour vérifier les messages.
- Pilotage par nombre de cas (D-2), niveaux `low`/`medium`/`high` (section 5 de `typologies.md`), déterminisme par graine, un compte au plus par cas. `light` : 1 cas par scénario au niveau `medium` ; `full` : 15 cas, un cas par bloc et par scénario avec permutation des niveaux tirée de la graine (`evaluation_plan.md` 2.5). La génération échoue si le taux de comptes étiquetés atteint 1 %.
- Fenêtres de silence du comportement normal : comptes relais (`account_age_days`) et sociétés écran (`dormancy_days`) n'ont plus de transactions normales avant leur activité.
- Hypothèses ajoutées (H-24 à H-29, `docs/simulator_assumptions.md`, section 9 bis) : montant et fenêtre de réception des comptes relais, montant initial et mélange des flux circulaires, durée du pic et façade des sociétés écran, sources entrantes = vrais clients dédiés au cas, camouflage non étiqueté au niveau transaction, virements d'entreprise en jours ouvrés.

**Corrections du simulateur normal (nécessaires, hors périmètre initial)**

- `generate_transactions` plantait dès la première transaction : `TypeError` sur le tirage de l'heure (`hour, hour_range = ...` dépaquetait un tuple) puis `IndexError` pour les clients sans contrepartie externe (canal `card`, environ 40 % des étudiants). Corrigé dans `normal.py` (deux modifications minimales) et couvert par un test. Le journal du 2026-11-12 ne signalait pas ce plantage : à relire avec Mouad. Les flux générés avant ce correctif n'existent donc pas.

**Résultats mesurés (graine 42)**

| Profil | Transactions | Comptes étiquetés | Taux de comptes | Transactions de scénario | Taux de transactions | Camouflage |
| --- | --- | --- | --- | --- | --- | --- |
| `light` (5 cas) | 399 631 | 35 | 0,70 % | 256 | 0,064 % | 101 |
| `full` (15 cas) | 1 592 647 | 103 | 0,52 % | 741 | 0,047 % | 471 |

Les estimations de H-07 (7,6 comptes et 63 transactions par cas) deviennent : environ 7 comptes et 50 transactions de scénario par cas. Les deux taux restent sous 1 % de comptes et dans l'ordre de grandeur des jeux publics (0,05 à 0,12 %). Sans cas configuré, le flux est identique à `generate_transactions` (vérifié sur `light`). Temps : `light` environ 12 s, `full` environ 66 s.

**Tests :** `pytest -q` : 78 tests réussis (19 existants + 59 nouveaux dans `tests/test_scenarios.py` et `tests/test_labels.py`), `ruff check .` réussit. Les tests couvrent la signature de chaque scénario (seuil, commission, retransmission, cycle fermé, flux des sociétés écran), les niveaux, les surcharges de paramètres et la validation, le placement par bloc, la séparation des labels et l'absence de label dans les messages `transactions`. `docker-compose.yml` et `.env` n'ont pas été modifiés (`.env.example` non plus).

**Décisions à valider / questions ouvertes**

- **Durée des cas (question ouverte 3, maintenant chiffrée).** Avec les durées du catalogue, 2 des 15 cas `full` sortent de leur bloc prévu et sont placés dans l'entraînement : fractionnement `medium` (17 jours, bloc validation de 16) et flux circulaires `high` (jusqu'à 30 jours, bloc test de 18). Aucune valeur n'a été modifiée en silence : le manifeste le signale (`placement_summary.cases_outside_assigned_block`). Avec `window_days: 10` (fractionnement) et `period_days: 10` (flux circulaires), les 15 cas tiennent dans leur bloc (testé). À trancher : raccourcir ces durées ou passer à 120 jours.
- La marge de report aux jours ouvrés (3,5 jours) rend le placement prudent : un cas peut être jugé trop long alors que sa durée réelle tient.
- Les labels ne sont **pas** chargés dans PostgreSQL : `sql/schema.sql` n'a pas les colonnes `case_id` et `sophistication` (C-11), et le contrat attend la validation de l'équipe. À faire à l'intégration : ajouter les colonnes, charger par `TRUNCATE` puis insertion, créer le rôle de scoring sans `SELECT` sur `labels`.
- Les niveaux par défaut de `light` (tous `medium`) et les valeurs H-24 à H-29 sont mes choix ; à relire avec Mouad puis le Pr Chergui.
- Non testé : Kafka, PostgreSQL et Docker réels (le producteur est simulé dans les tests). `psycopg`/`confluent-kafka` non installés ici.
