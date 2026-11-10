# Spécification technique AML — contrat v1 (proposition pour revue)

**Phase :** 2 — Contrat et schémas
**Auteur de la proposition :** Mounir ELHAMSS
**Relecteur demandé :** Mouad SALAH (aucun développement dépendant de ces choix avant sa réponse)
**Statut :** **proposition, non gelée.** Le contrat ne devient v1 qu'après les deux réponses `VALIDATED phase 2`.
**Références :** `MASTER_PROMPT_PFA_AML.md` (sections 6 à 9), `docs/data_contract.md` (proposition de Mouad), `docs/phase1_streaming_fundamentals.md` (note de cadrage de Mouad), `docs/evaluation_plan.md`, `docs/typologies.md`, `docs/simulator_assumptions.md`, `sql/schema.sql`, `src/aml/common/schemas.py`.

> **Avertissement sur la source de départ.** Le fichier `specification_technique_aml.md` d'origine (version locale de Mounir) **n'était pas dans le dépôt** au moment de ce travail. Seuls trois de ses noms de champs sont connus, de seconde main, par la note de Mouad : `transaction_id`, `event_time`, `account_id`. La comparaison ci-dessous est donc complète pour le prompt maître et pour la proposition de Mouad, et **partielle pour l'ancienne spécification**. Mounir doit reporter dans la section 2 tout autre écart présent dans sa copie locale avant l'envoi en revue.

---

## 1. Objet et périmètre

Ce document propose un contrat unique pour les quatre topics Kafka (`transactions`, `features`, `scores`, `alerts`), les labels et les écritures PostgreSQL. Il vise trois résultats :

1. un seul vocabulaire pour le simulateur, Spark, le scoring et la base ;
2. des écritures rejouables (aucun doublon après reprise) ;
3. des labels qui ne traversent jamais le flux.

Hors périmètre : toute modification de `docker-compose.yml` ou de `.env` (voir section 11), l'implémentation Spark et la valeur définitive du seuil d'alerte.

**Convention de lecture.** Les choix sont numérotés **C-01 à C-14**. Chacun est une proposition. Les points qui demandent une décision de Mouad sont rassemblés en section 10 (**Q-01 à Q-10**).

---

## 2. Comparaison des sources et divergences

### 2.1 Événement `transactions`

| Sujet | Prompt maître (sect. 6) | Ancienne spécification (partielle) | Proposition de Mouad (`data_contract.md`) | **Proposition v1 (ce document)** |
| --- | --- | --- | --- | --- |
| Identifiant de transaction | `tx_id` | `transaction_id` | `tx_id` | `tx_id` (C-01) |
| Horodatage | `timestamp`, ISO-8601 UTC | `event_time` | `timestamp` | `timestamp` (C-01), sens précisé (C-02) |
| Compte émetteur | `source_account_id` | `account_id` | `source_account_id` | `source_account_id` (C-01) |
| Compte destinataire | `target_account_id` | non connu | `target_account_id` | `target_account_id`, convention d'identifiants (C-04) |
| Montant | décimal (MAD) | non connu | nombre fini quelconque | nombre strictement positif, 2 décimales au plus (C-03) |
| Devise | `currency`, défaut `MAD` | non connu | libre, non vide | `MAD` seule valeur admise en v1 (C-03) |
| Canal | 5 valeurs dont `card` | non connu | 5 valeurs dont `card` | 5 valeurs ; **`card`**, pas `card_payment` (C-05) |
| Clé Kafka | `source_account_id` | `account_id` (sous réserve) | `source_account_id` | `source_account_id` (C-13) |
| Direction des flux par canal | non précisée | non connue | non précisée | table explicite (C-05) |

### 2.2 Sorties et labels

| Sujet | Prompt maître | Proposition de Mouad (état actuel) | **Proposition v1** |
| --- | --- | --- | --- |
| `features` : granularité | « niveau compte », fenêtres 1 h / 24 h / 7 j ; émission non fixée | un message par compte et fenêtre, clé `(account_id, window_start, window_end)` | un message par **(compte, transaction déclenchante)**, clé `(account_id, tx_id)` (C-06) |
| `scores` : clé | `account_id`, `tx_id` | clé PostgreSQL `tx_id` seul | clé `(tx_id, account_id)` (C-08) |
| `scores.ts` | non précisé | non précisé | heure simulée de la transaction déclenchante (C-08) |
| `alerts` : unité | « score au-dessus du seuil, avec `explanation` » | clé `tx_id` | unité **(compte, jour UTC)** alignée sur `evaluation_plan.md` (C-09) |
| `explanation` | JSON | « objet JSON » libre | structure fixée (C-10) |
| `labels` | 6 colonnes (`account_id`, `tx_id`, `scenario`, `role`, `start_ts`, `end_ts`) | 6 colonnes + `label_id`, valeurs libres | ajout de `case_id` et `sophistication`, énumérations (C-11) |
| Idempotence | à définir | clés « provisoires » | règle d'écriture par table (C-12) |

### 2.3 Divergences entre documents du dépôt

| Divergence | Où | Résolution proposée |
| --- | --- | --- |
| `card` (contrat) contre `card_payment` (hypothèses du simulateur, lignes 33 et 109) | `simulator_assumptions.md` | Corriger le simulateur et le document en `card` (C-05). |
| Unité d'alerte « compte, jour » contre scores par `tx_id` | `evaluation_plan.md` contre `data_contract.md` | Deux niveaux : score par (compte, transaction), alerte par (compte, jour) (C-08, C-09). |
| Clé de `scores` et `alerts` limitée à `tx_id` | `sql/schema.sql` | Une transaction concerne deux comptes : la clé doit contenir le compte (C-08, C-09). |
| Champs candidats absents du contrat (solde, bénéficiaire effectif, pays de destination) | `typologies.md`, `simulator_assumptions.md`, `evaluation_plan.md` (limite 6) | Ne pas les ajouter en v1 (Q-04). |
| Variables « à ajouter » citées par `typologies.md` (villes distinctes, écart entrée-sortie, montants répétés, sorties de type paie) | `typologies.md` | Villes distinctes intégrée ; les autres sont reportées (C-07). |
| « Temps événementiel jusqu'à l'alerte » (prompt) contre latence publication → alerte | `evaluation_plan.md` section 3.5 | Contrat compatible : `timestamp` = temps simulé, latence mesurée avec l'horodatage Kafka (C-13). |

---

## 3. Conventions générales

**C-01 — Noms.** Les noms du prompt maître font foi : `tx_id`, `timestamp`, `source_account_id`, `target_account_id`. Correspondance avec l'ancienne spécification : `transaction_id` → `tx_id`, `event_time` → `timestamp`, `account_id` → `source_account_id` (et `target_account_id` pour la contrepartie). Les noms sont en `snake_case` anglais ; les textes pour l'analyste sont en français (champ `summary_fr`).

**C-02 — Temps.**
- `timestamp` est l'**heure d'exécution simulée** de l'opération, en UTC. Ce n'est ni l'heure d'arrivée dans Kafka ni l'heure de traitement.
- Format canonique émis : `YYYY-MM-DDTHH:MM:SSZ` (fractions de seconde permises : `…:10.250Z`). Les consommateurs acceptent aussi `+00:00` ; tout autre décalage est rejeté (comportement actuel de `schemas.py`).
- Le **jitter** d'ordre du producteur modifie l'ordre d'arrivée, **jamais** la valeur de `timestamp`.
- Ordre total des événements : `(timestamp, tx_id)`. Il sert à départager deux événements simultanés de façon déterministe.
- Le fuseau utilisé pour générer les rythmes journaliers du simulateur est à confirmer (Q-07).

**C-03 — Montant et devise.**
- `amount` : nombre JSON, **strictement positif**, 2 décimales au plus, en MAD. Pas de montant négatif : le sens du flux est porté par le canal (C-05).
- Le producteur sérialise sans bruit flottant (par exemple `98500.00` à partir d'un `Decimal`, pas `98499.99999999`).
- `currency` : seule la valeur `"MAD"` est admise en v1. Les virements internationaux sont exprimés en équivalent MAD ; la conversion est une hypothèse du simulateur, non une donnée du flux.
- Les commissions du layering sont modélisées par la différence de montant entre deux sauts, pas par un champ `fee`.
- PostgreSQL : `NUMERIC(18,2)`.

**C-04 — Identifiants de compte.**
- Format `^(acct|ext)-[0-9]{6}$`. `acct-` désigne un compte client de la banque simulée, `ext-` un compte d'une autre banque (réservoir H-13 de `simulator_assumptions.md`).
- Valeur réservée `ext-cash` : contrepartie fictive des opérations en espèces (voir C-05).
- Un client possède un seul compte en v1 (hypothèse).
- `source_account_id` ≠ `target_account_id` (règle de validation à ajouter).
- Seuls les comptes `acct-` ont des variables et des scores : un compte `ext-` n'est observé que par ses échanges avec la banque. Ses propres transactions n'apparaissent pas.
- `tx_id` : `tx-` suivi de 8 chiffres, attribué après tri par `(timestamp, tx_id)` et déterminé par la graine ; un rejeu produit donc les mêmes identifiants.

**C-05 — Canaux et direction des flux.** Le prompt maître ne dit pas qui est `source` pour un dépôt ou un retrait d'espèces. On propose une convention **centrée sur le compte client**, qui garde `source_account_id` = client (bonne clé de partition, pas de clé « chaude » `ext-cash`) et donne un sens à `source_customer_type` :

| `channel` | `source_account_id` | `target_account_id` | Effet sur le compte source | Effet sur le compte cible |
| --- | --- | --- | --- | --- |
| `transfer` | client `acct-` | `acct-` ou `ext-` | sortie | entrée (si `acct-`) |
| `card` | client `acct-` | commerçant `acct-` ou `ext-` | sortie | entrée (si `acct-`) |
| `international_transfer` | client `acct-` | `ext-` | sortie | aucun (compte externe) |
| `cash_withdrawal` | client `acct-` | `ext-cash` | sortie | aucun |
| `cash_deposit` | client `acct-` | `ext-cash` | **entrée** | aucun |

Le nom du canal reste `card` (valeur du prompt maître). Les contreparties « distinctes » (variables) excluent `ext-cash`.

**C-06 à C-14** sont décrits dans les sections suivantes.

**Règles communes JSON.** UTF-8, un objet par message, aucun champ supplémentaire (rejet), pas de `NaN` ni `Infinity`, `null` admis seulement là où le tableau l'indique.

**Versionnage.** Le contrat porte un numéro (`v1`). Tout ajout, retrait ou changement de sens d'un champ incrémente la version et exige l'accord des **deux** étudiants. La version n'est pas dans chaque message ; elle est dans `docs/data_contract.md` et dans `feature_version` pour les variables (section 5).

---

## 4. Topic `transactions`

Clé Kafka : `source_account_id`. Valeur : objet JSON ci-dessous. **Aucun label, aucun indicateur de scénario, aucun champ de vérité terrain.**

| Champ | Type | Règle |
| --- | --- | --- |
| `tx_id` | chaîne | `^tx-[0-9]{8}$`, unique |
| `timestamp` | chaîne ISO-8601 | UTC, voir C-02 |
| `source_account_id` | chaîne | C-04, toujours `acct-` |
| `target_account_id` | chaîne | C-04, différent de la source |
| `amount` | nombre | > 0, 2 décimales au plus |
| `currency` | chaîne | `"MAD"` |
| `channel` | énumération | `cash_deposit`, `cash_withdrawal`, `transfer`, `card`, `international_transfer` |
| `source_customer_type` | énumération | `salaried`, `student`, `merchant`, `company` |
| `city` | chaîne | non vide ; ville de l'opération |

Exemples (dates fictives de la période simulée, voir `simulator_assumptions.md`) :

```json
{"tx_id":"tx-00004711","timestamp":"2027-02-03T08:15:42Z","source_account_id":"acct-000042","target_account_id":"acct-000873","amount":1250.50,"currency":"MAD","channel":"transfer","source_customer_type":"salaried","city":"Casablanca"}
```

```json
{"tx_id":"tx-00012345","timestamp":"2027-02-03T09:42:10Z","source_account_id":"acct-000123","target_account_id":"ext-cash","amount":98500.00,"currency":"MAD","channel":"cash_deposit","source_customer_type":"merchant","city":"Rabat"}
```

```json
{"tx_id":"tx-00012990","timestamp":"2027-02-03T11:03:55Z","source_account_id":"acct-000042","target_account_id":"acct-004801","amount":329.90,"currency":"MAD","channel":"card","source_customer_type":"salaried","city":"Casablanca"}
```

```json
{"tx_id":"tx-00013102","timestamp":"2027-02-03T13:20:00Z","source_account_id":"acct-002210","target_account_id":"ext-000512","amount":47000.00,"currency":"MAD","channel":"international_transfer","source_customer_type":"company","city":"Tanger"}
```

---

## 5. Topic `features`

**C-06 — Granularité et émission.** Un message est émis **pour chaque transaction et pour chaque compte `acct-` qu'elle concerne** (donc un ou deux messages). Les variables sont calculées sur des **fenêtres glissantes arrière** terminées à l'instant `as_of` = `timestamp` de la transaction déclenchante. Cette lecture répond à la question laissée ouverte par le prompt (« une ligne par fenêtre ou une mise à jour à chaque transaction ») et à la note de Mouad. Elle a trois avantages :

- elle donne exactement la clé `(account_id, tx_id)` du topic `scores` demandé par le prompt ;
- elle est sans fuite par construction : aucune variable n'utilise d'événement postérieur à la transaction déclenchante dans l'ordre `(timestamp, tx_id)` ;
- elle borne la mémoire Spark (pas de 168 fenêtres chevauchantes par événement avec un pas d'une heure).

Son coût est une implémentation à état par compte (par exemple `applyInPandasWithState` / `flatMapGroupsWithState`) plutôt que `window()` seul : **c'est une décision de faisabilité qui appartient à Mouad (Q-01).** L'alternative (instantané toutes les heures simulées, clé `(account_id, window_end)`) est décrite en Q-01.

Clé Kafka : `account_id`. Les messages d'une même transaction pour la source et la cible portent donc des clés différentes.

| Champ | Type | Règle |
| --- | --- | --- |
| `account_id` | chaîne | compte `acct-` concerné |
| `tx_id` | chaîne | transaction déclenchante |
| `side` | énumération | `source` ou `target` : rôle du compte dans la transaction |
| `as_of` | chaîne ISO-8601 UTC | `timestamp` de la transaction déclenchante |
| `feature_version` | chaîne | version du dictionnaire, `"1"` en v1 |
| `features` | objet | variables du dictionnaire ci-dessous ; valeur numérique ou `null` |

Remarque : ce format remplace `window_start` / `window_end` de la proposition actuelle. Chaque variable porte sa durée dans son nom (`_1h`, `_24h`, `_7d`) ; une seule paire de bornes ne décrit pas trois horizons.

**Fenêtre.** Pour un horizon `H`, l'intervalle est `(as_of − H, as_of]`, transaction déclenchante incluse. Un compte est concerné par une transaction comme émetteur (selon C-05) ou comme destinataire (s'il est `acct-`).

**C-07 — Dictionnaire des variables (minimum du prompt maître + une variable proposée).**

| Variable | Définition | Horizons | `null` si |
| --- | --- | --- | --- |
| `tx_count_{H}` | nombre d'événements du compte (entrées et sorties) | 1h, 24h, 7d | jamais |
| `total_amount_{H}_mad` | somme des montants | 1h, 24h, 7d | jamais |
| `distinct_counterparties_{H}` | contreparties distinctes, hors `ext-cash` | 1h, 24h, 7d | jamais |
| `amount_to_avg_ratio` | montant de la transaction déclenchante divisé par la moyenne des montants du compte sur les `history_days` jours précédents (transaction déclenchante exclue) | historique | moins de `min_history_events` événements |
| `near_threshold_share_{H}` | part des montants dans `[0,9 × REPORTING_THRESHOLD ; REPORTING_THRESHOLD[` | 24h, 7d | aucun événement |
| `inflow_outflow_ratio_24h` | entrées / sorties (convention C-05) | 24h | sorties nulles |
| `avg_in_to_out_delay_s_24h` | délai moyen, en secondes, entre une entrée et la sortie suivante | 24h | aucune paire |
| `cash_share_{H}` | part des événements en canal espèces | 24h, 7d | aucun événement |
| `distinct_cities_24h` *(proposée)* | villes distinctes | 24h | jamais |

Règles de nommage : `snake_case`, horizon en suffixe, unité dans le nom quand elle n'est pas évidente (`_mad`, `_s`). Les paramètres (`REPORTING_THRESHOLD`, `history_days`, `min_history_events`, tailles de fenêtre) sont lus dans `config/scoring.yaml` ; ils ne sont pas dans le message. Les variables « à ajouter » de `typologies.md` autres que les villes distinctes (écart relatif entrée-sortie, répétition de montants, sorties de type paie) sont **reportées** à une v2 pour ne pas élargir le contrat avant la phase 4.

Exemple (compte du dépôt `tx-00012345`, troisième dépôt de la journée) :

```json
{
  "account_id": "acct-000123",
  "tx_id": "tx-00012345",
  "side": "source",
  "as_of": "2027-02-03T09:42:10Z",
  "feature_version": "1",
  "features": {
    "tx_count_1h": 1,
    "tx_count_24h": 3,
    "tx_count_7d": 9,
    "total_amount_1h_mad": 98500.00,
    "total_amount_24h_mad": 291800.00,
    "total_amount_7d_mad": 880400.00,
    "distinct_counterparties_1h": 0,
    "distinct_counterparties_24h": 0,
    "distinct_counterparties_7d": 1,
    "amount_to_avg_ratio": 14.2,
    "near_threshold_share_24h": 1.0,
    "near_threshold_share_7d": 0.78,
    "inflow_outflow_ratio_24h": null,
    "avg_in_to_out_delay_s_24h": null,
    "cash_share_24h": 1.0,
    "cash_share_7d": 0.89,
    "distinct_cities_24h": 2
  }
}
```

(Valeurs illustratives, non issues d'une exécution.)

**Événements tardifs.** Le retard de watermark est un paramètre (`watermark_delay`) qui doit dépasser le jitter maximal du producteur (Q-02). Un événement plus tardif que le watermark est conservé dans `raw_transactions` mais exclu des variables et compté dans une métrique de suivi.

---

## 6. Topic `scores`

**C-08 — Score et clé.** Un message par couple (compte, transaction), donc un ou deux par transaction. Clé Kafka : `account_id`.

| Champ | Type | Règle |
| --- | --- | --- |
| `account_id` | chaîne | compte noté |
| `tx_id` | chaîne | transaction déclenchante |
| `risk_score` | nombre | dans [0, 1] |
| `model_versions` | objet | nom de couche → version (chaîne) |
| `ts` | chaîne ISO-8601 UTC | **`as_of` de la transaction** (heure simulée), pas l'heure de calcul |
| `layer_scores` | objet *(extension proposée, Q-03)* | nom de couche → nombre dans [0, 1] ou `null` |

Pourquoi `ts` simulé : le message devient une fonction déterministe de ses entrées, donc un rejeu produit un message identique (clé d'idempotence stable). L'heure réelle de calcul est portée par l'horodatage Kafka (C-13).

Pourquoi `layer_scores` : l'étude d'ablation et le tableau de bord (règles, Isolation Forest, XGBoost, graphe) ont besoin des scores par couche. Sans ce champ, il faut les recalculer hors ligne. Si Mouad refuse l'extension, le champ est retiré sans autre impact.

Les couches sont nommées `rules`, `isolation_forest`, `xgboost`, `graph`, `ensemble`. Une couche non disponible vaut `null` dans `layer_scores` et est absente de `model_versions`.

```json
{
  "account_id": "acct-000123",
  "tx_id": "tx-00012345",
  "risk_score": 0.91,
  "layer_scores": {"rules": 1.0, "isolation_forest": 0.74, "xgboost": 0.93, "graph": null},
  "model_versions": {"rules": "1.0.0", "isolation_forest": "0.1.0", "xgboost": "0.1.0", "ensemble": "0.1.0"},
  "ts": "2027-02-03T09:42:10Z"
}
```

---

## 7. Topic `alerts`

**C-09 — Unité d'alerte.** L'unité est le couple **(compte, jour UTC simulé)**, comme dans `evaluation_plan.md`. Deux niveaux coexistent :

- **en ligne** : une alerte est émise quand `risk_score` d'un compte atteint le seuil `alert_threshold` (`config/scoring.yaml`) ; si, le même jour, un score plus élevé survient, l'alerte du jour est **mise à jour** (même clé, score plus haut) ;
- **en évaluation** : la précision@k est calculée hors ligne en classant, chaque jour, les alertes par `risk_score` et en gardant les `k` premières (k = 50 par défaut). Le top-k n'est donc pas calculé dans le flux (réponse proposée à la question 5 de `evaluation_plan.md`).

Le seuil n'a pas de valeur par défaut dans ce document : elle sera fixée par l'analyse de coût de la phase 6, pas par préférence.

Clé Kafka : `account_id`.

| Champ | Type | Règle |
| --- | --- | --- |
| `account_id` | chaîne | compte alerté |
| `alert_date` | chaîne `YYYY-MM-DD` | jour UTC du `ts` |
| `tx_id` | chaîne | transaction qui porte le score le plus élevé du jour |
| `risk_score` | nombre | score le plus élevé du jour pour ce compte |
| `model_versions` | objet | comme `scores` |
| `ts` | chaîne ISO-8601 UTC | `as_of` de cette transaction |
| `explanation` | objet | voir C-10 |

**C-10 — Structure de `explanation`.**

| Clé | Type | Contenu |
| --- | --- | --- |
| `summary_fr` | chaîne | phrase courte en français pour l'analyste |
| `typology_hint` | énumération ou `null` | `structuring`, `layering`, `mule`, `round_tripping`, `shell_company` ; **déduit des règles, des variables ou du graphe, jamais lu dans `labels`** |
| `fired_rules` | liste | objets `{"rule_id": chaîne, "description": chaîne}`, vide si aucune |
| `top_features` | liste | objets `{"feature": chaîne, "value": nombre ou null, "shap_value": nombre ou null}`, triés par contribution décroissante ; `shap_value` est `null` pour une règle seule |
| `graph` | objet ou `null` | `{"pattern": "cycle" \| "community" \| "chain", "accounts": [chaînes ordonnées], "tx_ids": [chaînes]}` |

```json
{
  "account_id": "acct-000123",
  "alert_date": "2027-02-03",
  "tx_id": "tx-00012345",
  "risk_score": 0.91,
  "model_versions": {"rules": "1.0.0", "isolation_forest": "0.1.0", "xgboost": "0.1.0", "ensemble": "0.1.0"},
  "ts": "2027-02-03T09:42:10Z",
  "explanation": {
    "summary_fr": "Trois dépôts en espèces de 96 100 à 98 500 MAD en 24 heures, juste sous le seuil configuré de 100 000 MAD.",
    "typology_hint": "structuring",
    "fired_rules": [
      {"rule_id": "R-STRUCT-01", "description": "Dépôts en espèces répétés juste sous le seuil de référence"}
    ],
    "top_features": [
      {"feature": "near_threshold_share_24h", "value": 1.0, "shap_value": 0.31},
      {"feature": "cash_share_24h", "value": 1.0, "shap_value": 0.12},
      {"feature": "amount_to_avg_ratio", "value": 14.2, "shap_value": 0.09}
    ],
    "graph": null
  }
}
```

(Valeurs illustratives. `R-STRUCT-01` est un identifiant d'exemple : les règles réelles seront nommées en phase 4. Le seuil de 100 000 MAD est l'hypothèse `REPORTING_THRESHOLD`, pas une obligation légale.)

---

## 8. Labels : séparation et forme

**C-11.** Les labels ne figurent **dans aucun topic**. Ils sont écrits par le simulateur dans la table PostgreSQL `labels` et dans `data/labels/` (Parquet ou CSV). Le service de scoring ne les lit jamais ; la validation du topic `transactions` rejette tout champ inconnu, ce qui empêche leur injection.

Deux extensions de la table sont proposées, car l'évaluation en a besoin :

| Colonne | Statut | Raison |
| --- | --- | --- |
| `account_id`, `tx_id`, `scenario`, `role`, `start_ts`, `end_ts` | prompt maître | inchangées ; `tx_id` nul pour un label de compte, renseigné pour un label de transaction |
| `case_id` *(ajout)* | chaîne non nulle | définir un « cas détecté » et le délai de détection (`evaluation_plan.md`) |
| `sophistication` *(ajout)* | `low`, `medium`, `high` | rappel par niveau de sophistication (`evaluation_plan.md`, D-6) |

Énumérations proposées :
- `scenario` : `structuring`, `layering`, `mule`, `round_tripping`, `shell_company` ;
- `role` (à valider, Q-08) : `originator`, `depositor`, `intermediary`, `mule`, `beneficiary`, `shell_company`.

Deux sortes de lignes : des lignes **compte-rôle** (`tx_id` nul, avec `start_ts` / `end_ts` de l'activité) et des lignes **transaction** (`tx_id` renseigné), nécessaires au taux de transactions suspectes que `simulator_assumptions.md` demande de rapporter.

Isolation d'accès : le compte PostgreSQL utilisé par le scoring ne doit avoir **aucun droit `SELECT` sur `labels`**. Le script de création de ce rôle est décrit en section 11 ; il n'est pas appliqué ici.

---

## 9. Idempotence et rejeu

**C-12 — Une règle par destination.** Les écritures Kafka sont *au moins une fois* (Spark ou le scoring peuvent republier après un redémarrage). L'exactitude vient des **écritures PostgreSQL rejouables**, qui reposent sur une clé stable et une opération d'upsert. Le checkpoint Spark ne suffit pas à lui seul (note de Mouad, section 3).

| Table | Clé primaire | Écriture | Pourquoi c'est rejouable |
| --- | --- | --- | --- |
| `raw_transactions` | `tx_id` | `INSERT … ON CONFLICT (tx_id) DO NOTHING` | une transaction est immuable ; un doublon identique est ignoré |
| `account_features` | `(account_id, tx_id)` | `INSERT … ON CONFLICT (account_id, tx_id) DO UPDATE` | le contenu est une fonction déterministe des événements ≤ `as_of` ; un recalcul remplace par la même valeur |
| `scores` | `(tx_id, account_id)` | `INSERT … ON CONFLICT (tx_id, account_id) DO UPDATE` | une nouvelle version de modèle remplace l'ancienne ; un rejeu identique ne change rien |
| `alerts` | `(account_id, alert_date)` | `INSERT … ON CONFLICT DO UPDATE … WHERE` le nouveau score est plus élevé (égalité : plus petit `tx_id`) | le maximum est commutatif : l'ordre des rejeux n'a pas d'effet |
| `labels` | `label_id` + index d'unicité `(case_id, account_id, role, COALESCE(tx_id, ''))` | rechargement complet par graine (`TRUNCATE` puis chargement) | écrit une seule fois par génération du jeu |

Autres règles :

- **Doublons dans le flux** : un second message avec le même `tx_id` est ignoré (déduplication par `tx_id` côté Spark, bornée par le watermark). Un `tx_id` répété avec un contenu **différent** est une erreur de contrat : il est compté et journalisé, il n'écrase rien.
- **Déterminisme des identifiants** : `tx_id` dépend de la graine (C-04) ; sans cela le rejeu créerait de nouvelles lignes.
- **Producteur** : idempotence Kafka activée (`enable.idempotence=true`) pour éviter les doublons dus aux réessais réseau.
- **Une graine par base** : les identifiants `tx-…` se répètent d'une graine à l'autre. Une base ne contient qu'une graine à la fois (`python manage.py reset` entre deux). Les évaluations à plusieurs graines (au moins 3) se font **hors ligne** sur les fichiers Parquet (Q-09).
- **Test attendu (phase 6)** : arrêter puis relancer le job Spark, puis vérifier l'absence de doublons et de trous sur `raw_transactions`, `account_features`, `scores`, `alerts`.

Extrait de DDL **proposé** (non appliqué ; `sql/schema.sql` n'est pas modifié par ce travail) :

```sql
-- scores : la clé doit contenir le compte (une transaction concerne deux comptes)
CREATE TABLE IF NOT EXISTS scores (
    tx_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    risk_score NUMERIC NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    layer_scores JSONB,
    model_versions JSONB NOT NULL,
    scored_at TIMESTAMPTZ NOT NULL,          -- valeur du champ ts (heure simulée)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tx_id, account_id)
);

-- alerts : unité (compte, jour)
CREATE TABLE IF NOT EXISTS alerts (
    account_id TEXT NOT NULL,
    alert_date DATE NOT NULL,
    tx_id TEXT NOT NULL,
    risk_score NUMERIC NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    model_versions JSONB NOT NULL,
    explanation JSONB NOT NULL,
    alerted_at TIMESTAMPTZ NOT NULL,         -- valeur du champ ts (heure simulée)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, alert_date)
);

-- upsert d'une alerte : on garde le score le plus élevé, départage par tx_id
-- INSERT INTO alerts (...) VALUES (...)
-- ON CONFLICT (account_id, alert_date) DO UPDATE SET
--   tx_id = EXCLUDED.tx_id, risk_score = EXCLUDED.risk_score, ...
-- WHERE EXCLUDED.risk_score > alerts.risk_score
--    OR (EXCLUDED.risk_score = alerts.risk_score AND EXCLUDED.tx_id < alerts.tx_id);
```

---

## 10. Topics Kafka : réglages et questions ouvertes

**C-13 — Clés, partitions, horodatage Kafka.**

| Topic | Clé | Partitions (v1) |
| --- | --- | --- |
| `transactions` | `source_account_id` | 1 |
| `features` | `account_id` | 1 |
| `scores` | `account_id` | 1 |
| `alerts` | `account_id` | 1 |

- On garde **1 partition** (réglage actuel du Compose) : l'ordre est global et le débit visé (100 à 500 évènements par seconde) reste faible. Le nombre sera revu après le test de charge, avec des mesures (note de Mouad). Les clés sont déjà définies, le passage à plusieurs partitions ne change donc pas le contrat.
- L'horodatage de l'enregistrement Kafka (`CreateTime`) est l'heure **réelle** de création par le producteur. Il sert à la latence technique de `evaluation_plan.md` (publication → score ou alerte). Il est distinct de `timestamp`, qui est l'heure simulée.
- Les paramètres sont lus dans `config/scoring.yaml` : `reporting_threshold`, `alert_threshold`, `k_alerts_per_day`, `watermark_delay`, `history_days`, `min_history_events`, tailles de fenêtre. Ce fichier n'existe pas encore ; sa création relève de l'implémentation, après validation.

**C-14 — Compatibilité du validateur.** Le contrat est défini pour que `schemas.py` n'ait besoin que d'ajustements limités (section 11).

### Questions ouvertes pour décision commune

| N° | Question | Proposition de Mounir | Décideur |
| --- | --- | --- | --- |
| **Q-01** | Format d'émission de `features` : par transaction (C-06) ou instantané horaire par compte ? | Par transaction. **Alternative :** instantané toutes les heures simulées avec clé `(account_id, window_end)` ; cela s'écrit avec `window()` Spark seul, mais ne donne plus de lien direct avec `tx_id`, donc il faudrait attribuer un score à un compte-heure et non à une transaction. | Mouad (faisabilité Spark) |
| **Q-02** | Valeur de `watermark_delay` et jitter maximal du producteur | À fixer à partir du jitter simulé, puis à mesurer ; le watermark doit dépasser le jitter. Aucune valeur proposée ici. | Mouad |
| **Q-03** | Accepter `layer_scores` dans `scores` ? | Oui, pour l'ablation et le tableau de bord. | Les deux |
| **Q-04** | Ajouter `balance`, bénéficiaire effectif, pays de destination ? | **Non en v1.** Le simulateur ne les produit pas et `evaluation_plan.md` assume ce monde fermé. À rouvrir en v2 avec incrément de version. | Les deux |
| **Q-05** | Autres écarts avec l'ancienne spécification | À compléter depuis la copie locale de Mounir avant l'envoi en revue. | Mounir |
| **Q-06** | Alerte en ligne par seuil + top-k en évaluation (C-09) | Oui. | Les deux |
| **Q-07** | Fuseau du rythme journalier du simulateur : UTC direct, ou heure locale du Maroc convertie en UTC ? | UTC direct, documenté comme simplification. L'effet sur `alert_date` doit être vérifié avant d'adopter une conversion locale (le décalage du Maroc autour du Ramadan est à confirmer). | Les deux |
| **Q-08** | Valeurs de l'énumération `role` | Liste de C-11, à valider avec les cinq fiches de `typologies.md`. | Mounir puis Mouad |
| **Q-09** | Une graine par base, évaluation multi-graines hors ligne (C-12) | Oui. | Mouad |
| **Q-10** | Rôle PostgreSQL du scoring sans accès à `labels` | À créer lors de l'intégration (voir section 11). | Les deux |

---

## 11. Conséquences après validation et périmètre de ce travail

**Docker et `.env` : aucune modification.** `docker-compose.yml`, `.env.example`, `.env` et le nombre de partitions Kafka ne sont pas touchés. Le rôle PostgreSQL du scoring (Q-10) nécessite un script d'initialisation monté dans le conteneur, c'est-à-dire une modification de Docker : elle est donc **conditionnée à un accord commun explicite**. Contenu prévu, à titre d'information :

```sql
-- à exécuter à l'intégration, après accord commun (rôle sans mot de passe en clair dans le dépôt)
REVOKE ALL ON labels FROM PUBLIC;
-- le rôle du scoring reçoit SELECT sur account_features, INSERT/UPDATE sur scores et alerts,
-- et aucun droit sur labels
```

**Travaux dépendants de ce contrat, à ne commencer qu'après `VALIDATED phase 2` :**

| Fichier | Changement prévu |
| --- | --- |
| `src/aml/common/schemas.py` | `amount` > 0 et 2 décimales ; `currency` = `MAD` ; regex des identifiants ; `source` ≠ `target` ; `features` : champs `tx_id`, `side`, `as_of`, `feature_version` (remplacent `window_start` / `window_end`) ; `alerts` : champ `alert_date`, structure de `explanation` ; `scores` : `layer_scores` optionnel |
| `tests/test_schemas.py` | cas d'erreur pour chaque règle ci-dessus et validation des exemples de ce document |
| `sql/schema.sql` | clés de `scores` et `alerts`, `NUMERIC(18,2)`, colonnes et contraintes de `labels` |
| `docs/data_contract.md` | statut, version, renvoi vers ce document |
| `docs/simulator_assumptions.md` | `card_payment` → `card` ; convention des opérations en espèces (C-05) |
| `docs/decisions.md` | décisions C-01 à C-14 après accord |

---

## 12. Liste de contrôle pour la revue de Mouad

- [ ] Les exemples de la section 4 respectent le contrat `transactions` actuel de `schemas.py` (vérifiés hors validateur durci, voir `docs/journal.md`).
- [ ] C-05 (direction des flux et `ext-cash`) convient à la conception du simulateur.
- [ ] C-06 (une ligne de variables par compte et transaction) est faisable avec Spark en 2 Gio (Q-01).
- [ ] C-09 (alerte par compte et jour, seuil en ligne) convient au tableau de bord.
- [ ] Les règles d'idempotence C-12 sont implémentables avec `foreachBatch`.
- [ ] Réponses aux questions Q-01 à Q-10.
- [ ] Réponse `VALIDATED phase 2` ou liste de corrections.
