# Détection de base : règles, Isolation Forest, XGBoost (phase 4, côté Mounir)

**Statut :** implémentation locale, à relire par Mouad. Données **simulées** uniquement ; aucun résultat ne dit ce que donnerait le système sur de vraies données.

## 1. Fichiers

| Fichier | Rôle |
| --- | --- |
| `config/scoring.yaml` | Tous les seuils des règles, le découpage temporel, k, les coûts, les graines, les paramètres des modèles. Toutes les valeurs sont des **hypothèses [H]**. |
| `src/aml/models/rules.py` | Quatre règles explicables. |
| `src/aml/models/features.py` | Variables hors ligne, vectorisées, identiques à `aml.streaming.features` (test de parité). |
| `src/aml/models/splits.py`, `labels.py` | Découpage temporel strict ; labels (compte, jour), censurés à la fin de l'entraînement. |
| `src/aml/models/isolation_forest.py`, `xgboost_layer.py` | Les deux modèles. |
| `src/aml/models/metrics.py` | precision@k, recall@k, plafond, PR-AUC, ROC-AUC, coût, choix du seuil, intervalles de Wilson. |
| `src/aml/models/leakage.py` | Test d'invariance au futur. |
| `src/aml/models/pipeline.py`, `python manage.py train` | Chaîne complète et rapport JSON dans `reports/`. |

Commandes : `pip install -e ".[dev,models]"`, `python manage.py simulate --profile full --seed 1`, `python manage.py train --profile full --seed 1`, `pytest`.

## 2. Règles (R-STRUCT-01, R-RAPID-01, R-DORM-01, R-CHAN-01)

| Règle | Se déclenche si (paramètres dans `rules.*` de `scoring.yaml`) | Cas de test |
| --- | --- | --- |
| R-STRUCT-01 fractionnement | au moins `min_near_threshold_count_7d` opérations dans la bande sous le seuil de référence sur 7 j, et part d'espèces ≥ `min_cash_share_7d` | `tests/test_rules.py` : positif au seuil, saturé ; négatifs : trop peu d'opérations, pas d'espèces |
| R-RAPID-01 entrée-sortie rapide | délai moyen entrée→sortie ≤ `max_avg_delay_s_24h`, volume 24 h ≥ `min_total_amount_24h_mad`, ratio entrées/sorties dans `[min, max]` | positif plus rapide = score plus haut ; négatifs : trop lent, trop faible volume, ratio hors bande, valeurs nulles |
| R-DORM-01 dormant puis actif | au plus `max_baseline_tx_count` opérations entre J-30 et J-7, puis au moins `min_tx_count_7d` opérations et `min_total_amount_7d_mad` sur 7 j | négatifs : base d'activité non vide, pas assez d'activité, variable absente |
| R-CHAN-01 canal à risque | part espèces + virements internationaux 24 h ≥ `min_risky_share_24h`, avec nombre et volume minimaux | positifs espèces et international ; négatifs : part, nombre, volume, valeur nulle |

**Score** (identique pour toutes) : 0 si non déclenchée ; 0,5 quand la valeur clé atteint juste son seuil ; 1,0 à `saturation_multiple` × seuil. Le score de la couche `rules` est le maximum des règles déclenchées, dans [0, 1]. Sortie conforme à la proposition C-08/C-10 : `layer_scores.rules`, `model_versions.rules`, `fired_rules` (`rule_id`, `description`), `typology_hint` (renseigné seulement par R-STRUCT-01). Cette interface reste une **proposition** tant que le contrat n'est pas validé par les deux étudiants.

Aucun seuil n'est codé en dur : un test vérifie qu'aucun littéral 100 000 n'apparaît dans `src/aml/models/` et que `reporting_threshold` de `scoring.yaml` égale celui de `config/streaming.json`. Le seuil de 100 000 MAD est une hypothèse de simulation, jamais une obligation légale.

**Extensions hors contrat v1** (à décider avec Mouad) : `tx_count_7d_to_30d` (R-DORM-01) et `international_share_24h` (R-CHAN-01) ne figurent pas dans C-07. Sans elles, ces deux règles restent silencieuses (valeur absente = jamais déclenchée). Le job Spark devrait les produire (l'état de 30 jours le permet).

## 3. Modèles et protocole temporel

- **Unité de calcul** : un événement (compte, transaction, côté). L'alerte est le couple (compte, jour), au score maximal du jour (C-09).
- **Découpage** (plan d'évaluation 2.2) : échauffement jours 1–7 (historique seulement), entraînement 8–56, validation 57–72, test 73–90. Aucun mélange aléatoire ; `assert_chronological` et les tests de `tests/test_splits.py` le vérifient.
- **Isolation Forest** : ajusté sur tout le bloc d'entraînement, **sans aucun label** ; score brut ramené à [0, 1] par la distribution empirique des scores d'entraînement ; valeurs nulles remplacées par -1.
- **XGBoost** : ajusté sur le bloc d'entraînement ; labels (compte, jour) **censurés au dernier jour d'entraînement** (L-5) ; nombre d'arbres choisi par arrêt précoce sur la **validation** (L-7).
- **Déséquilibre** : `scale_pos_weight = négatifs / positifs` de l'entraînement (≈ 1 100 à 1 300 selon la graine). Conséquence : la sortie n'est pas une probabilité calibrée ; seul le classement et le seuil choisi sur la validation comptent. Alternatives non essayées : sous-échantillonnage des négatifs, pondération plus faible.
- **Seuil** : sur la validation, seuil de coût minimal (`c_FP = 1`, `c_FN = 200`) sous la contrainte de **k = 50 alertes par jour en moyenne** (plan 5.4) ; il est ensuite gelé et appliqué au test. Un cas est « détecté » si un de ses comptes est alerté un jour de son intervalle. Les cas d'un bloc sont ceux qui **commencent** dans ce bloc.
- **Graines** : `models.random_seed + graine du jeu`, XGBoost mono-thread. Deux exécutions de la graine 1 ont donné des rapports identiques (hors durées).

## 4. Test de fuite

`tests/test_leakage.py` calcule les variables sur le jeu complet puis sur le jeu tronqué à un instant `t` : les événements antérieurs doivent avoir des valeurs identiques (`aml.models.leakage`). Il passe pour les variables du projet et **échoue bien** sur deux témoins volontairement fautifs (moyenne sur toute la période ; valeur du prochain événement). `test_models_features.py` vérifie en plus l'égalité avec les variables du job Spark (≈ 3 000 événements comparés sur des données synthétiques, 0 écart ; contrôle préalable de 1 659 événements du jeu `light`).

Limite : le test ne détecte une fuite qu'aux instants de coupure testés ; il ne voit pas une fuite d'étiquettes (traitée par la censure et par l'absence d'identifiant parmi les entrées, vérifiée par un test).

## 5. Résultats préliminaires (exécutés)

Profil `full`, graines 1 à 3, un seul passage du test par graine, aucun réglage après lecture du test. **Indicatif** : 4 à 5 cas de test par graine, intervalles très larges. Valeurs du bloc de test ; seuil choisi sur la validation. Prévalence (compte, jour) ≈ 0,05 %. Plafond de la precision@50 ≈ 0,15 (voir plan 3.1).

| Couche | PR-AUC (moy. ± écart) | ROC-AUC | precision@50 | recall@50 | Cas détectés (graines 1, 2, 3) | Alertes/jour au seuil |
| --- | --- | --- | --- | --- | --- | --- |
| Règles | 0,0066 ± 0,0022 | 0,61 | 0,025 | 0,19 | 4/4, 5/5, 4/4 | 34, 34, 42 |
| Isolation Forest | 0,0123 ± 0,0013 | 0,94 | 0,021 | 0,15 | 3/4, 2/5, 0/4 | 23, 9, 0 |
| XGBoost | 0,104 ± 0,014 | 0,96 | 0,055 | 0,40 | 2/4, 3/5, 0/4 | 4,2 ; 2,9 ; 0 |

Lecture prudente : XGBoost classe nettement mieux (PR-AUC 0,10 contre 0,007 à 0,012), mais son seuil choisi sur la validation est trop strict pour la graine 3 (aucune alerte) et il manque des cas. Les règles détectent presque tous les cas mais au prix de 34 à 42 alertes par jour dont plus de 95 % sont fausses. Rien ici ne justifie de conclure sur l'ensemble final. Le XGBoost s'arrête tôt (5 à 26 arbres retenus) : peu de positifs d'entraînement (≈ 40 comptes) et risque de sur-apprentissage sur le simulateur.

Les seuils des règles ont été fixés a priori (non ajustés sur le test) ; ils n'ont pas non plus été optimisés sur la validation : c'est un point à améliorer.

## 6. Limites et points ouverts

1. Données simulées, étiquettes parfaites, circularité simulateur/détecteur (plan d'évaluation, section 9).
2. Le profil `light` ne sert pas à l'évaluation : le pipeline émet un avertissement si la validation ne contient aucun cas.
3. Deux cas `full` sortent de leur bloc prévu (journal du 13 novembre) ; ils sont comptés dans le bloc où ils commencent.
4. Option A (un modèle par graine) retenue ; l'option B (entraîner sur les autres graines) n'est pas implémentée.
5. Le test unitaire d'intégration Spark → scoring n'est pas couvert ici (service de scoring hors de ce ticket) ; les règles ne sont pas branchées au flux Kafka.
6. Python 3.12 utilisé pour l'exécution ici ; le projet exige 3.11 : relancer la CI et les commandes sur 3.11.
