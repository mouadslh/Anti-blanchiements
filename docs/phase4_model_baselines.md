# Phase 4 — modèles de base et scoring

## But et périmètre

Comparer trois bases de détection, puis démontrer le parcours local `simulateur → Kafka → Spark → scoring → PostgreSQL`. Les labels servent uniquement à entraîner et évaluer les modèles hors ligne; le worker de scoring ne lit aucun label. Le graphe, SHAP et le dashboard complet restent en phase 5.

## Données et résultats d’évaluation

La démonstration utilise le jeu synthétique local `light`, graine 44, en MAD. Il contient 396 803 transactions, 33 comptes de scénario (0,66 %), 255 transactions de scénario (0,0643 %) et 5 cas (un par typologie, niveau medium). Les blocs temporels sont train 155 199 lignes (105 positives), validation 51 162 lignes et test 57 505 lignes. La validation seule calibre le seuil. L’identifiant du compte, le cas, le rôle, la typologie et les labels sont exclus des variables d’entrée.

| Modèle | PR-AUC (AP) | ROC-AUC | Précision@50/j | Rappel@50/j | Cas détectés au seuil calibré | Coût test* |
|---|---:|---:|---:|---:|---:|---:|
| Règles | 0,00050 | 0,5188 | 0,00111 | 0,0714 | 1/1 | 200 |
| Isolation Forest | 0,00243 | 0,9154 | 0,00222 | 0,1429 | 1/1 | 200 |
| XGBoost | 0,00129 | 0,8888 | 0,00000 | 0,0000 | 0/1 | 200 |

\* Coût avec `c_FP=1` et `c_FN=200`; coûts relatifs hypothétiques. Chaque méthode rate/attrape des jours différents et la précision@k est faible. Un seul cas est présent au test : ces nombres servent à valider le pipeline, pas à départager les modèles de façon fiable. L’échantillon ne représente pas les transactions réelles d’une banque marocaine.

Le rôle prévu pour la dataset externe SAML-D est une référence de calibration/documentation; elle n’est pas la source principale et n’a pas été entraînée ici. Les résultats sont mesurés sur les transactions simulées par ce projet. Les labels sont produits par les mêmes règles de simulation, ce qui peut favoriser les modèles supervisés.

Rapports détaillés : `reports/model_comparison_light_seed44.md` et `.json`; statistiques de génération : `reports/dataset_light_seed44.json`. Les CSV et modèles restent locaux/ignorés par Git.

## Démonstration Docker effectuée

Sur le Docker Desktop local, 6 000 transactions ont été générées/rejouées au débit configuré de 500 événements/s dans le topic isolé `transactions_phase4`. Spark a produit 7 998 features, écrites à la fois dans `features_phase4` et PostgreSQL (`account_features_stream`). XGBoost a publié 7 998 scores dans `scores_phase4`; aucun message n’a dépassé le seuil et `alerts_phase4` contient 0 alerte. Les nombres de transactions et de features diffèrent car les sorties sont des instantanés d’activité par compte, pas un enregistrement strictement un-à-un.

Mesures observées sur cette exécution locale : débit de micro-batch Spark entre 56 et 106 lignes/s sur les lots non vides, `addBatch` entre 9,2 et 17,6 s; watermark final `2027-01-16T11:20:27Z`, 0 ligne rejetée comme tardive. Latence Kafka→score p50 80,645 s, p95 97,557 s (7 998 messages mesurés). Le retard comprend la file d’attente/reprise du lot et n’est pas une mesure de latence en régime stable; le débit réel Spark est inférieur au débit d’injection. L’exécution a confirmé le parcours et mis en évidence que les performances restent à optimiser.

## Reproduction légère

```bash
source .venv/bin/activate
python manage.py simulate --profile light --seed 44 --report --report-output reports/dataset_light_seed44.json
AML_SCORING_CONFIG=config/scoring_demo.yaml python manage.py train-scoring
AML_SCORING_CONFIG=config/scoring_demo.yaml python manage.py evaluate-scoring
```

Les topics Docker sont isolés pour ne pas réutiliser le flux normal du projet. Les services `spark` et `scorer` sont pilotés par `manage.py stream` et `manage.py score`; voir les overrides de démonstration dans le journal de phase 4. Aucun `.env` n’a été modifié.

## Défauts rencontrés et limites

- Java était configuré sous un chemin amd64 absent sur le Mac Apple Silicon; le Dockerfile laisse maintenant Java être résolu par `PATH`.
- PyArrow 12 n’est pas compatible avec NumPy 2 dans le conteneur Spark; l’extra `streaming` fixe NumPy sous 2.
- XGBoost 3 téléchargeait une dépendance NVIDIA GPU inutilisée; le projet fixe XGBoost 2.x CPU et le modèle a été réentraîné avec cette version.
- La première lecture Spark a démarré avant la création des topics et a échoué (`UnknownTopicOrPartition`); le topic a été créé, Spark relancé et le même lot retenu dans Kafka a été traité.
- Le premier score XGBoost a révélé une liste `fired` non initialisée; corrigée avant la publication des scores vérifiés.
- Au rythme mesuré, Spark met environ une minute à traiter quelques milliers d’événements; la latence p95 observée est proche de 98 s. Tester davantage de ressources, micro-batchs et comportement de rattrapage avant toute promesse de temps réel.
- Une relance complète à partir d’un topic déjà consommé peut retraiter les données si le checkpoint et les offsets changent; vérifier les clés de déduplication avant une reprise de production.

Le résultat reste une démonstration de phase 4. Il ne justifie aucune décision bancaire ou conformité réglementaire. La comparaison devra être répétée sur plusieurs graines et un jeu indépendant avant une conclusion; les visualisations avancées restent hors périmètre.
