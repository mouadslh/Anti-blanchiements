# Simulateur de comportement normal — Phase 3 (Mouad)

Ce composant génère la base de transactions normales nécessaire au pipeline AML. Il respecte la forme `transactions` du contrat v1 proposé et n'émet aucun label. Les scénarios de blanchiment, leurs labels et la génération finale commune restent à intégrer séparément par Mounir/l'équipe.

Les paramètres par défaut viennent de `docs/simulator_assumptions.md` : profils `light` (5 000 clients) et `full` (20 000), 90 jours à partir du 15 janvier 2027, répartition des profils, canaux, montants log-normaux, réseau stable de contreparties, villes, horaires, semaine et saisonnalité. Ce sont des hypothèses de simulation, pas des statistiques observées. Le contrat v1 et ces hypothèses restent à valider ensemble.

## Générer le CSV et le rapport

Depuis la racine du dépôt :

```text
python manage.py simulate --profile light --seed 42 --report
```

Le fichier est écrit dans `data/transactions/normal-light-seed42.csv` (dossier ignoré par Git). Pour choisir une autre sortie ou utiliser le profil complet :

```text
python manage.py simulate --profile full --seed 7 --output data/transactions/full-seed7.csv --report
```

Le rapport présente les volumes par profil, canal, heure UTC et jour de semaine. Les nombres de scénarios et le taux suspect sont indiqués comme indisponibles tant que l'injecteur de Mounir et les labels séparés ne sont pas intégrés; le simulateur ne fabrique pas de métriques AML.

Une graine donnée produit les mêmes clients, comptes et événements ordonnés dans le même fichier. Les identifiants de transactions sont attribués après tri chronologique (`tx-` et huit chiffres); les comptes utilisent `acct-`/`ext-`. Une nouvelle graine peut réutiliser les mêmes `tx_id`, donc les générations de graines différentes doivent être isolées dans la base, comme prévu par la spécification.

## Rejeu Kafka et stockage PostgreSQL facultatifs

Installer les dépendances dédiées une seule fois :

```text
python -m pip install -e ".[streaming]"
```

Puis ajouter `--replay` pour publier vers le topic `transactions` dans l'ordre événementiel, avec débit configurable de 1 à 500 événements/s (défaut 100) :

```text
python manage.py simulate --profile light --seed 42 --replay --rate 100
```

Le producteur Kafka active l'idempotence et utilise `source_account_id` comme clé. Le serveur par défaut est `localhost:9092`; `KAFKA_BOOTSTRAP_SERVERS` permet de le remplacer. `--duration 30` limite un rejeu à 30 secondes (utile pour une démonstration). Ajouter `--store-raw` pour insérer dans `raw_transactions` avec `ON CONFLICT (tx_id) DO NOTHING`. La connexion utilise `DATABASE_URL`, ou les variables existantes `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (valeurs locales par défaut du Compose du projet). Le schéma `sql/schema.sql` doit déjà être appliqué.

```text
python manage.py simulate --profile light --seed 42 --replay --store-raw
```

Ces options utilisent les services déjà démarrés par l'équipe; elles ne modifient ni Docker Compose ni `.env`. Il n'y a pas de jitter d'arrivée configurable dans cette première version; les événements sont publiés dans l'ordre du temps événementiel.
