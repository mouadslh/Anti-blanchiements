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
