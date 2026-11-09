# Notions de Kafka et Spark Structured Streaming

## Pourquoi cette note est importante

Cette note aide Mouad à expliquer les notions de streaming avant de construire le pipeline : comment Kafka distribue les événements et comment Spark les agrège en respectant leur heure simulée. Elle sert de repère commun pour comprendre les choix à venir, repérer les divergences entre le prompt maître et les propositions de Mounir, et préparer le contrat de données de phase 2. Elle ne remplace pas le contrat v1 et n’autorise pas à modifier Docker ou `.env`.

**Rôle de Mouad :** comprendre la chaîne de données, consigner les contraintes techniques et préparer les questions à résoudre avec Mounir. Les décisions communes — notamment le schéma des événements — seront validées par les deux étudiants en phase 2.

**Phase :** 1 — cadrage et typologies; **Responsable :** Mouad SALAH
**Statut :** note de prise en main; les choix d'implémentation restent à valider dans les phases suivantes.

## 1. Kafka : topics, partitions et groupes de consommateurs

- Un **topic** est un flux nommé d'événements. Un topic est divisé en **partitions**, chacune étant un journal ordonné avec ses propres offsets. Kafka garantit l'ordre à l'intérieur d'une partition, pas un ordre global entre toutes les partitions.
- Le producteur peut utiliser une **clé** pour diriger les événements liés vers la même partition. Pour ce projet, la clé proposée par le prompt maître est `source_account_id`; elle permet de garder ensemble les événements émis par un même compte et facilite les calculs par compte. Ce choix reste à confirmer avec le contrat v1, car le brouillon de spécification emploie un autre schéma.
- Un **consumer group** distribue les partitions d'un topic entre ses consommateurs. Dans un groupe, une partition est traitée par un membre à la fois. Si le groupe a plus de consommateurs que de partitions, certains consommateurs restent inactifs. Deux groupes différents peuvent lire le même topic indépendamment, chacun avec ses propres offsets.
- Un **offset** est la position d'un enregistrement dans une partition. Les offsets permettent à un consommateur de reprendre sa lecture après redémarrage; la rétention Kafka détermine combien de temps les événements restent disponibles.

### Application au projet

Les topics prévus sont `transactions`, `features`, `scores` et `alerts`. Spark lira `transactions` et écrira des features; le service de scoring lira `features`. Ces services doivent avoir des identifiants de groupes adaptés à leurs lectures indépendantes.

Le Compose actuel est configuré avec un broker et `KAFKA_NUM_PARTITIONS=1`. C'est simple pour le prototype, mais cela limite le parallélisme de chaque groupe à une seule partition et n'apporte aucune haute disponibilité. Le nombre de partitions devra être décidé et documenté avant les tests de charge.

## 2. Spark Structured Streaming : micro-batches et temps événementiel

- **Structured Streaming** traite un DataFrame non borné avec les opérations de DataFrame/SQL. Le mode usuel est le traitement par petits lots (**micro-batches**); chaque déclenchement lit les nouveaux événements et met à jour les résultats.
- Le **temps événementiel** est l'heure portée par l'événement (par exemple l'heure simulée de la transaction). Il est distinct du temps de traitement, qui est l'heure à laquelle Spark reçoit l'événement. Les fenêtres AML doivent être basées sur le temps événementiel pour respecter l'ordre simulé.
- Une **fenêtre glissante** calcule un agrégat sur une durée qui avance selon un intervalle de glissement. Le projet prévoit des horizons de 1 h, 24 h et 7 jours. Des fenêtres chevauchantes peuvent compter une transaction dans plusieurs résultats; leur durée, leur pas et le niveau de sortie (par compte ou par événement) doivent être définis ensemble.
- Un **watermark** suit l'avancement maximal observé du temps événementiel, avec un retard toléré configuré. Il sert notamment à permettre le traitement d'événements reçus en retard et à borner l'état conservé pour les agrégations. Ce n'est pas la rétention du topic Kafka. Le comportement exact des événements qui arrivent au-delà du retard configuré doit être vérifié et documenté pour la requête retenue.
- Un **checkpoint** conserve la progression de la requête et son état pour reprendre après un redémarrage. Il doit être persistant et propre à la requête. La reprise sans doublons dans PostgreSQL dépend aussi de la stratégie d'écriture de la destination; le checkpoint seul ne rend pas toute écriture externe idempotente.

### Application au projet

Les événements doivent porter une heure d'événement explicite, en UTC, et le producteur pourra introduire un léger désordre temporel. Le retard de watermark devra donc être choisi à partir du jitter et des retards effectivement simulés, puis évalué. Il ne faut pas le fixer arbitrairement dans cette note.

Le pipeline prévu lit les transactions, calcule les variables par fenêtres, puis écrit les résultats dans `features` et PostgreSQL. Les sorties finales, les mises à jour de fenêtres encore ouvertes, la déduplication et l'idempotence PostgreSQL sont des décisions de conception à préciser en phase 2 et à implémenter en phase 4.

## 3. Questions et réponses selon le prompt maître

### Quel schéma de transaction et quelle clé Kafka retenir?

Le prompt maître propose un événement JSON avec `tx_id`, `timestamp` (ISO-8601 UTC), `source_account_id`, `target_account_id`, `amount`, `currency`, `channel`, `source_customer_type` et `city`. La clé du topic `transactions` y est `source_account_id`.

La spécification poussée par Mounir emploie notamment `transaction_id`, `event_time` et `account_id`. Il faut rapprocher ces propositions et approuver un schéma commun pendant la phase 2. D'ici là, le contrat du prompt maître sert de référence de travail, sans prétendre que le contrat v1 est déjà gelé.

Le prompt précise aussi que les labels restent séparés du flux et que le service de scoring ne doit jamais les lire.

### Quelle heure doit porter `timestamp`?

Le prompt maître demande une heure événementielle simulée au format ISO-8601 UTC. Spark doit utiliser cette heure pour ses fenêtres, et non l'heure à laquelle il consomme le message. Le document ne précise pas davantage si elle correspond à l'exécution ou à l'acceptation simulée de l'opération; ce détail devra être fixé dans le contrat v1. L'heure d'arrivée dans Kafka est une mesure technique distincte.

### Les features sont-elles calculées par compte ou par transaction?

Le prompt maître décrit le topic `features` comme contenant des variables au niveau compte, et demande des agrégats sur 1 h, 24 h et 7 jours. Il donne comme minimum les nombres et montants de transactions, les contreparties distinctes, les ratios au profil, les opérations proches d'un seuil configurable, le ratio entrants/sortants, les délais entre entrée et sortie, et la part d'espèces.

Le prompt ne tranche pas le format d'émission exact : une ligne par compte et fenêtre, ou une mise à jour à chaque transaction. Ce choix doit être explicité dans le contrat de phase 2 avant l'implémentation Spark de phase 4.

### Quel watermark utiliser?

Le prompt exige un watermark et indique que le producteur pourra ajouter un léger désordre temporel configurable. Il ne fixe pas de durée de retard. Il faut donc choisir une valeur à partir du jitter configuré et des retards simulés, puis mesurer les effets sur la conservation des événements tardifs, l'état Spark et la latence. Cette valeur doit rester configurable; elle ne doit pas être inventée comme un résultat mesuré.

### Comment éviter les doublons après une reprise?

Le prompt exige des checkpoints Spark et un test ultérieur de reprise sans doublons ni trous. Le checkpoint aide Spark à reprendre son traitement, mais il ne suffit pas à garantir qu'une écriture PostgreSQL rejouée ne duplique pas une ligne. Il faudra donc définir une clé stable, une contrainte d'unicité et une écriture rejouable (par exemple un upsert), puis tester le redémarrage en phase 6. Les détails de schéma relèvent de la phase 2 et l'intégration de la phase 4.

### Où garder les checkpoints?

Ils doivent survivre au redémarrage du conteneur, donc leur emplacement doit être persistant et associé à la requête Spark. Le prompt exige la reprise après arrêt, mais ne fixe pas le chemin de stockage. Ce chemin doit être choisi avec la conception Docker et testé avec le pipeline.

### Combien de partitions faut-il?

Le prompt fixe un broker Kafka unique et vise un débit de replay réglable de 100 à 500 événements par seconde; il ne fixe pas le nombre de partitions. Le Compose actuel configure une partition par défaut pour cette phase bootstrap. Dans un consumer group, ajouter des consommateurs au-delà du nombre de partitions ne donne pas plus de parallélisme. Il faut commencer avec la configuration légère, puis justifier toute augmentation par des mesures de débit et de mémoire avant de figer le réglage.

Ces réponses suivent le prompt maître. Elles ne gèlent pas le contrat, ne valident pas le schéma divergent de la spécification et n'entraînent aucune modification de Docker ou de `.env`.

## 4. Sources officielles consultées

- Apache Kafka 4.3, [Design](https://kafka.apache.org/43/design/) et [protocole et partitionnement](https://kafka.apache.org/43/design/protocol/).
- Apache Spark 4.3, [Structured Streaming : fenêtres, temps événementiel, watermark et déduplication](https://spark.apache.org/docs/4.3.0/streaming/apis-on-dataframes-and-datasets.html).
- API PySpark, [DataFrame.withWatermark](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.withWatermark.html).
