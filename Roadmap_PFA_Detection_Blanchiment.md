# Roadmap PFA – Détection du blanchiment d'argent

Mouad SALAH et Mohamed Mounir ELHAMSS · Génie IA-Data, 5ème année · Encadrant : Pr Adil CHERGUI · 6 novembre 2026

## Vue d'ensemble

Le projet livre en 7 semaines un système qui détecte le blanchiment d'argent en temps réel sur des transactions simulées. Le flux est : simulateur → Kafka → Spark Structured Streaming (variables) → scoring (règles, Isolation Forest, XGBoost, graphe) → PostgreSQL → Grafana.

Jalons :

- **Fin S3 :** les transactions simulées circulent dans Kafka.
- **Fin S4 :** pipeline complet de bout en bout avec un premier score.
- **Fin S5 :** dashboard Grafana avec alertes expliquées.
- **Fin S6 :** évaluation chiffrée et version stable.
- **Fin S7 :** rapport, déploiement et soutenance.

Principe de travail : un pipeline simple qui tourne de bout en bout dès la semaine 4, puis on l'améliore. On n'attend pas qu'un composant soit parfait avant de l'intégrer.

## Répartition des rôles

Mouad construit la chaîne de données et l'infrastructure. Mounir construit les typologies, les modèles et l'évaluation. Ils se retrouvent sur un contrat de données figé en semaine 2.

| | Mouad SALAH | Mounir ELHAMSS |
| --- | --- | --- |
| Profil | Data engineering | Data science |
| Responsable de | Simulateur de comportement normal, Kafka, Spark Streaming, stockage, Grafana, Docker, CI | Typologies de blanchiment, étiquettes, variables, modèles, graphe, SHAP, évaluation |
| Livre | Pipeline qui tourne avec `docker compose up`, dashboard, tests de charge | Modèles entraînés, rapport d'évaluation, test de dérive |
| Outils | Kafka, PySpark, PostgreSQL, Grafana, Docker, GitHub Actions | Pandas, scikit-learn, XGBoost, NetworkX, SHAP, Jupyter |
| Interface commune | Contrat de données v1 : schéma JSON de la transaction, noms des topics (`transactions`, `features`, `scores`, `alerts`), format du score | Même contrat, versionné dans `docs/` |

## Semaine 1 : cadrage et typologies

Objectif : tout le monde comprend le problème, l'environnement démarre et le prof valide le sujet.

**Mouad**

- [ ] Installer Docker (avec WSL2 sous Windows) et lancer un Kafka + Spark d'exemple en local.
- [ ] Créer le dépôt GitHub avec les dossiers `simulator/`, `streaming/`, `models/`, `dashboard/`, `docs/` et un README.
- [ ] Apprendre les bases de Kafka (topics, partitions, consumer groups) et de Structured Streaming (fenêtres, watermark).

**Mounir**

- [ ] Lire les typologies du GAFI et le cadre de la loi 43-05, et vérifier les références exactes.
- [ ] Rédiger le catalogue de 5 à 6 typologies : description, signaux observables, paramètres à simuler.
- [ ] Résumer l'état de l'art (règles, ML, graphes) avec 2 ou 3 sources et les jeux de données AML synthétiques publics.

**Ensemble**

- [ ] Faire valider la fiche et le sujet par le Pr Chergui.
- [ ] Écrire le cahier d'hypothèses v1 : nombre de clients, profils, taux de cas suspects (environ 0,1 %).
- [ ] Choisir les métriques : precision@k, recall par typologie, coût total, latence.

**Livrable :** cahier des charges validé, catalogue des typologies, hypothèses v1, environnement Docker qui démarre.

## Semaine 2 : architecture et contrat de données

Objectif : figer ce que chacun produit et consomme avant d'écrire le cœur du code.

**Mouad**

- [ ] Écrire le `docker-compose.yml` : Kafka, Spark, PostgreSQL, Grafana.
- [ ] Créer les topics `transactions`, `features`, `scores`, `alerts`.
- [ ] Tester un producteur et un consommateur minimaux de bout en bout.

**Mounir**

- [ ] Concevoir le modèle de données : clients, comptes, sociétés, transactions, étiquettes.
- [ ] Écrire le dictionnaire des variables : vitesse sur 1 h, 24 h et 7 jours, cumul glissant, nombre de contreparties distinctes, ratio montant / profil, proximité du seuil de déclaration.
- [ ] Définir la matrice de coûts (faux positif contre blanchiment raté) et le plan d'évaluation avec découpage temporel.

**Ensemble**

- [ ] Figer le contrat de données v1 dans `docs/`.
- [ ] Dessiner le schéma d'architecture pour le dossier.

**Livrable :** dossier d'architecture, contrat de données, dictionnaire des variables, plan d'évaluation.

## Semaine 3 : simulateur et flux Kafka

Objectif : des transactions réalistes, dont une part suspecte étiquetée, circulent dans Kafka.

**Mouad**

- [ ] Simuler le comportement normal par profil (salarié, étudiant, commerçant, entreprise) avec la saisonnalité : salaires en fin de mois, Ramadan, Aïd.
- [ ] Écrire le producteur Kafka avec un débit réglable.
- [ ] Stocker les transactions brutes dans PostgreSQL.

**Mounir**

- [ ] Coder l'injecteur de scénarios : fractionnement sous le seuil, enchaînement de virements, comptes relais, flux circulaires, société écran.
- [ ] Écrire les étiquettes de vérité terrain dans une table séparée du flux.
- [ ] Ajouter des paramètres d'intensité et de sophistication par scénario.

**Ensemble**

- [ ] Générer le jeu de données v1 (par exemple 10 000 clients et environ 1 million de transactions).
- [ ] Vérifier le réalisme : distributions des montants, activité par heure et par jour, taux de cas suspects.

**Livrable :** simulateur dans le dépôt, jeu de données v1 avec statistiques, flux Kafka opérationnel.

## Semaine 4 : Spark Streaming et modèles de base

Objectif : un premier pipeline complet, même imparfait, de la transaction au score.

**Mouad**

- [ ] Écrire le job Spark Structured Streaming : lecture de Kafka, watermark, variables sur fenêtres glissantes.
- [ ] Écrire les résultats dans PostgreSQL et dans le topic `features`.
- [ ] Activer les checkpoints pour la reprise après arrêt.

**Mounir**

- [ ] Coder la baseline à règles métier (seuils, fractionnement).
- [ ] Entraîner Isolation Forest et XGBoost avec un découpage temporel strict : entraînement sur le passé, test sur le futur.
- [ ] Traiter le déséquilibre des classes (poids, choix du seuil) et mesurer les premières métriques hors ligne.

**Ensemble**

- [ ] Brancher le modèle dans un consommateur de scoring qui lit `features` et écrit `scores`.
- [ ] Préparer la démo intermédiaire.

**Livrable :** démo simulateur → Kafka → Spark → score, tableau comparatif règles / Isolation Forest / XGBoost.

## Semaine 5 : dashboard, graphe et explications

Objectif : un analyste peut ouvrir le dashboard, voir les comptes les plus risqués et comprendre pourquoi.

**Mouad**

- [ ] Construire le dashboard Grafana : file d'alertes triée par risque, débit, latence, nombre d'alertes par jour.
- [ ] Provisionner Grafana par fichiers pour que le dashboard se recharge avec `docker compose up`.

**Mounir**

- [ ] Construire le graphe des transactions avec NetworkX : cycles, communautés, centralité, entrées et sorties par compte.
- [ ] Ajouter les variables de graphe au modèle.
- [ ] Calculer les valeurs SHAP et générer une phrase d'explication par alerte.

**Ensemble**

- [ ] Intégrer le score de graphe et les explications au flux et au dashboard.

**Livrable :** dashboard alimenté en temps réel, avec des alertes expliquées (variables en cause, chemin dans le graphe).

## Semaine 6 : tests, évaluation et dérive

Objectif : des résultats chiffrés et une version stable. C'est la semaine qui prouve la valeur du projet.

**Mouad**

- [ ] Écrire les tests unitaires du simulateur et des variables, et les tests d'intégration du pipeline.
- [ ] Mesurer le débit (messages par seconde) et la latence p95 sous charge.
- [ ] Tester la reprise après l'arrêt d'un service.
- [ ] Mettre en place la CI avec GitHub Actions.

**Mounir**

- [ ] Calculer les métriques finales : precision@k, recall par typologie, courbe précision-rappel, coût total selon le seuil.
- [ ] Faire l'étude d'ablation : sans variables de graphe, sans variables de vitesse.
- [ ] Faire le test adversarial : les fraudeurs changent de comportement (montants plus bas, délais plus longs), mesurer la baisse de performance puis le ré-entraînement.

**Ensemble**

- [ ] Corriger les anomalies, refactoriser et figer la version 1.0.
- [ ] Rédiger le rapport d'évaluation.

**Livrable :** cahier de tests, rapport d'évaluation, version bêta stable.

## Semaine 7 : finalisation et soutenance

Objectif : tout se lance avec une commande, le rapport est complet et vous savez défendre chaque choix.

**Mouad**

- [ ] Vérifier que `docker compose up` démarre tout le système sur une machine propre.
- [ ] Écrire le guide d'installation et d'utilisation.
- [ ] Préparer le script de démonstration.

**Mounir**

- [ ] Rédiger les chapitres modèles, évaluation et limites.
- [ ] Préparer les diapositives de résultats.

**Ensemble**

- [ ] Relire le rapport l'un chez l'autre.
- [ ] Finaliser le support de présentation.
- [ ] Répéter la soutenance deux fois, chronomètre en main.
- [ ] Préparer les questions probables : pourquoi ce modèle, ce seuil, cette simulation, quelles limites.

**Livrable :** rapport de PFA complet, application déployée et documentée, support de présentation, démo.

## Risques et plans B

| Risque | Signal d'alerte | Plan B |
| --- | --- | --- |
| Kafka et Spark trop lourds pour vos PC | Machine qui ralentit, conteneurs qui plantent | Un seul broker, débit réduit, ou remplacer Spark par un consommateur Python |
| Simulateur jugé irréaliste | Distributions trop régulières, modèle qui obtient des scores parfaits | Documenter chaque hypothèse, comparer à un jeu AML synthétique public |
| Pipeline pas prêt fin S4 | Pas de score dans `scores` | Geler les fonctionnalités, passer le graphe en traitement par lots |
| Trop peu de cas suspects | Recall instable | Augmenter le taux de cas, pondérer les classes, rapporter les intervalles |
| Fuite de données temporelle | Résultats trop bons | Découpage temporel strict, relecture croisée du code d'entraînement |
| Interfaces qui divergent | Messages rejetés, champs manquants | Contrat de données versionné dans `docs/`, modifié seulement à deux |

## Règles d'équipe et définition de terminé

- Point de 15 minutes deux fois par semaine, et une démo au Pr Chergui chaque semaine.
- Une branche Git par tâche, fusionnée après relecture par l'autre.
- Un journal de bord `docs/journal.md` : décisions, essais ratés, résultats, avec la date.
- Une tâche est terminée quand elle est versionnée, testée, documentée, relue par l'autre et qu'elle tourne avec `docker compose up`.
