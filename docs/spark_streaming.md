# Exécuter le job Spark Structured Streaming

Le worker Spark est un profil Compose facultatif pour ne pas démarrer un consommateur long-vivant à chaque lancement de l'environnement de base.

```bash
python manage.py up
python manage.py stream
docker compose --profile streaming logs -f spark
```

Le job lit `transactions`, écrit les variables dans `features` et PostgreSQL (`account_features_stream`). Le checkpoint durable est conservé sous `./checkpoints/features-v1` entre les redémarrages. Ne supprimez pas ce dossier si vous voulez reprendre les offsets et l'état du job. Pour arrêter le worker :

```bash
docker compose --profile streaming stop spark
```

Les paramètres de fenêtres, du watermark, du seuil, des offsets, du batch et du checkpoint sont définis dans `config/streaming.json`. Le watermark par défaut de 2 h est provisoire, à valider par l'équipe. Les événements plus tardifs que le watermark sont écartés du calcul.

Le Compose ajoute le listener interne Kafka `kafka:29092` tout en conservant `localhost:9092` pour les outils sur l'hôte. Le worker Spark a une limite de 2 Gio et utilise `local[2]`. Son image télécharge le connecteur Kafka Spark 3.5.8 au premier démarrage via Maven; cela nécessite l'accès réseau du conteneur. Le profil utilise les variables PostgreSQL déjà reconnues par Compose; `.env` n'a pas besoin d'être édité.

Les logs du job donnent par micro-batch le débit entrant/traité (lignes/s), le temps `addBatch` (ms) et la progression du watermark. Reporter ces valeurs dans `docs/journal.md` après une mesure sur l'environnement Docker réel.

## Garantie de reprise

Le checkpoint Spark restaure les offsets Kafka et l'état par compte. L'écriture PostgreSQL est rejouable grâce à la clé `(account_id, tx_id)` et à `ON CONFLICT`. Le connecteur Kafka Spark a une garantie au moins une fois : après un échec d'écriture, des messages de sortie peuvent être répétés. Les consommateurs de `features` doivent dédupliquer par `(account_id, tx_id, side)`.
