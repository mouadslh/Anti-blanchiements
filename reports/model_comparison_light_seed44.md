# Comparaison des modèles de base AML

Jeu : **light synthétique**, graines 44. Labels réservés à l'entraînement/évaluation; jamais consommés par le scorer.

| Modèle | PR-AUC (moy. ± écart-type) | ROC-AUC | Précision@k | Rappel@k | Rappel cas (top-k) | Coût au seuil validé |
|---|---:|---:|---:|---:|---:|---:|
| Règles | 0.0005 ± 0.0000 | 0.5188 ± 0.0000 | 0.0011 ± 0.0000 | 0.0714 ± 0.0000 | 1/1 (100.0%) | 200 |
| Isolation Forest | 0.0024 ± 0.0000 | 0.9154 ± 0.0000 | 0.0022 ± 0.0000 | 0.1429 ± 0.0000 | 1/1 (100.0%) | 200 |
| XGBoost | 0.0013 ± 0.0000 | 0.8888 ± 0.0000 | 0.0000 ± 0.0000 | 0.0000 ± 0.0000 | 0/1 (0.0%) | 200 |

## Limites et périmètre

- Transactions et labels sont simulés par le même projet; les modèles peuvent apprendre les règles du générateur.
- Les résultats n'estiment pas la performance sur les transactions réelles d'une banque marocaine.
- La qualité par scénario reste incertaine avec peu de cas par graine.
- Les seuils de règles, le coût FN/FP et k=50 sont des hypothèses de l'équipe.

## Détection des cas par typologie

| Modèle | Typologie | Cas détectés / total | Rappel |
|---|---|---:|---:|
| Règles | layering | 1/1 | 100.0% |
| Isolation Forest | layering | 1/1 | 100.0% |
| XGBoost | layering | 0/1 | 0.0% |

## Sensibilité au coût des cas manqués

| Modèle | r=10 | r=50 | r=100 | r=200 | r=500 | r=1000 |
|---|---:|---:|---:|---:|---:|---:|
| Règles | 10 | 50 | 100 | 200 | 264 | 264 |
| Isolation Forest | 10 | 50 | 100 | 200 | 523 | 523 |
| XGBoost | 10 | 50 | 100 | 200 | 500 | 1000 |
- Le seuil est choisi sur la validation uniquement; les résultats du test sont agrégés par graine.
- Le rappel de cas affiché est calculé à partir des alertes top-k par jour.
- PR-AUC est l'average precision calculée sur le bloc de test; les courbes PR/ROC échantillonnées sont dans le JSON.
- Le graphe, SHAP et le dashboard complet appartiennent à la phase 5.
