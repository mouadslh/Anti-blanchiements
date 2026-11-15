# Dataset AML v1 — résultat de génération

## Choix des jeux

Le **jeu principal** est synthétique et généré par le dépôt : comportement normal de Mouad, cinq scénarios de Mounir et labels CSV séparés. Il alimente Kafka et porte les statistiques/évaluations principales.

Le **jeu public SAML-D** est une référence externe de **benchmark et calibration**, pas une source de transactions pour le flux local. Nous comparons des ordres de grandeur et, après rapprochement de schéma, des distributions choisies. Nous ne fusionnons pas les données, ne transférons pas ses labels au dataset v1 et ne rejouons pas SAML-D dans Kafka. Sa taille publiée est de 9 504 852 transactions et sa part suspecte est de 0,1039 %; les populations, typologies et champs diffèrent du contexte marocain simulé ici.

**Clarification : aucun fichier SAML-D n'a été téléchargé ou utilisé pour construire le dataset v1.** Les montants de v1 sont générés par nos propres règles puis sérialisés avec `currency=MAD`; les villes du générateur sont Casablanca, Rabat, Marrakech, Fès, Tanger, Agadir, Meknès, Oujda et « Autre ». Les profils, réseaux de comptes, canaux et dates sont eux aussi produits localement selon `docs/simulator_assumptions.md`. SAML-D figure seulement comme comparaison bibliographique parce que l'encadrant a demandé de choisir un dataset externe et de préciser son rôle. Si la consigne exige que le dataset public soit aussi traité par le pipeline, il faudra créer un importateur et une comparaison séparés; cela ne doit pas remplacer ou contaminer la simulation marocaine.

La licence indiquée dans la documentation du projet pour SAML-D est CC BY-NC-SA 4.0. Le jeu public n'est pas stocké dans Git. Avant téléchargement/redistribution, revérifier la fiche Kaggle et attribuer la source conformément à sa licence. La validation par le Pr Chergui reste ouverte.

Sources : [fiche Kaggle SAML-D](https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring-dataset-aml), [notice des auteurs](https://github.com/BOztasUK/Anti_Money_Laundering_Transaction_Data_SAML-D), [article Oztas et al., IEEE ICEBE 2023](https://doi.org/10.1109/ICEBE59045.2023.00028).

## Génération v1

Commande reproductible (après démarrage des services Docker et installation de `.[streaming]`) :

```text
python manage.py simulate --profile light --seed 42 --report --report-output reports/dataset_v1_light_seed42.json --replay --rate 500
```

Fichiers locaux (ignorés par Git) :

- `data/transactions/dataset-light-seed42.csv` — transactions normales et événements de scénario, sans colonnes de labels.
- `data/labels/labels-light-seed42.csv` — vérité terrain séparée.
- `data/labels/labels-light-seed42.manifest.json` — graine, paramètres, placement des cas et taux mesurés.
- `reports/dataset_v1_light_seed42.json` — rapport de distributions et de contrôle, versionné avec le code.

Le rapport JSON associé est généré à partir des fichiers effectifs et doit être mis à jour lors d'une nouvelle génération. Il inclut les volumes par profil client et canal, les statistiques de montants MAD par profil (minimum, médiane, moyenne, p95, maximum), l'activité par heure UTC, jour de semaine et date, les cas/labels et les taux calculés.

Exécution locale mesurée le 15 novembre 2026 : 399 631 événements générés et 399 631 accusés comme publiés dans Kafka (topic `transactions`, 500/s). La graine `42` a produit 5 cas (un par scénario), 35 comptes étiquetés (0,70 %), 256 transactions étiquetées (0,0641 %) et 101 transactions de camouflage. Les labels sont dans un fichier distinct du flux Kafka. Rapport détaillé : `reports/dataset_v1_light_seed42.json`.

## Contrôles attendus

Le rapport distingue les transactions par type de client et canal, l'activité UTC par heure et jour de semaine, le nombre de cas par typologie/niveau, le nombre de comptes et transactions étiquetés, les opérations de camouflage, ainsi que les taux suspects de comptes et transactions. Le seuil de comptes étiquetés doit rester strictement inférieur à 1 %.

Les valeurs du profil `light` servent à vérifier le générateur et le flux; elles ne suffisent pas à interpréter la performance de détection par typologie. Les paramètres du simulateur sont des hypothèses; les données ne sont pas des données bancaires réelles et n'apportent aucune preuve de performance en production. Le MAD et les villes sont des attributs de données synthétiques; ils ne signifient pas que les transactions reproduisent des observations réelles de banques marocaines.
