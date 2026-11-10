# Contrat de données v1 — proposition pour validation

**Phase :** 2 — Contrat et schémas  
**Statut :** proposition technique implémentée, en attente de validation par Mouad et Mounir.  
**Référence :** `MASTER_PROMPT_PFA_AML.md`, section 6.

Ce document fixe une base commune pour le simulateur, Kafka, Spark, le scoring et PostgreSQL. Le contrat de transaction ci-dessous suit le prompt maître. Les formes détaillées des messages `features`, `scores` et `alerts` précisent ce que le prompt laisse ouvert; elles restent des propositions tant que les deux étudiants ne les ont pas validées. Toute modification après validation devra incrémenter la version et être approuvée par les deux.

## 1. Événement `transactions`

- **Format :** objet JSON UTF-8, un événement par message.
- **Clé Kafka :** `source_account_id`.
- **Temps :** `timestamp` est l'heure simulée de l'événement en UTC, au format ISO-8601 avec suffixe `Z` ou décalage UTC `+00:00`.
- **Labels :** interdits dans ce message. La vérité terrain est conservée séparément dans PostgreSQL et dans `data/labels/`; le service de scoring ne doit jamais la lire.

| Champ | Type | Règle |
| --- | --- | --- |
| `tx_id` | chaîne | Identifiant unique de transaction, non vide. |
| `timestamp` | chaîne ISO-8601 | Date/heure avec fuseau UTC explicite. |
| `source_account_id` | chaîne | Compte émetteur, non vide; clé Kafka. |
| `target_account_id` | chaîne | Compte destinataire, non vide; peut être externe. |
| `amount` | nombre décimal JSON | Montant en MAD; le validateur accepte un entier, un nombre fini ou `Decimal`, jamais un booléen. |
| `currency` | chaîne | `MAD` par défaut selon le prompt maître. |
| `channel` | chaîne enum | `cash_deposit`, `cash_withdrawal`, `transfer`, `card`, `international_transfer`. |
| `source_customer_type` | chaîne enum | `salaried`, `student`, `merchant`, `company`. |
| `city` | chaîne | Ville, non vide. |

Tous les champs du tableau sont obligatoires dans v1; aucun champ supplémentaire n'est accepté afin d'éviter l'ajout accidentel de labels au flux. Le code de validation ne force pas une devise autre que la valeur par défaut `MAD`; la convention de conversion et l'unité du montant doivent rester cohérentes et être confirmées avant génération.

```json
{
  "tx_id": "tx-000001",
  "timestamp": "2026-01-15T10:30:00Z",
  "source_account_id": "acct-001",
  "target_account_id": "acct-927",
  "amount": 1250.50,
  "currency": "MAD",
  "channel": "transfer",
  "source_customer_type": "salaried",
  "city": "Casablanca"
}
```

## 2. Topics de sortie — formes proposées

Le prompt maître définit les éléments minimaux suivants. Les champs additionnels ci-dessous servent à rendre les messages identifiables et rejouables; leur validation conjointe est requise.

### `features`

Proposition d'un message par compte et fenêtre : `account_id` (chaîne), `window_start` et `window_end` (horodatages UTC), `features` (objet JSON de variables numériques ou catégorielles). Le prompt exige des variables au niveau compte sur 1 h, 24 h et 7 jours, mais ne précise pas si chaque message est par fenêtre, par transaction ou une mise à jour courante. Le format par compte et fenêtre est donc à valider.

### `scores`

Champs requis selon le prompt : `account_id` (chaîne), `tx_id` (chaîne), `risk_score` (nombre entre 0 et 1), `model_versions` (proposition : objet nom de modèle → version), `ts` (horodatage UTC).

### `alerts`

Proposition : mêmes champs d'identification et de score que `scores`, plus `explanation` (objet JSON). Le prompt exige une explication; le contenu détaillé (règles déclenchées, variables contributives, texte français) est à préciser avec le contrat de scoring.

**Point de cohérence à résoudre :** `docs/evaluation_plan.md` de phase 1 prend le compte par jour comme unité d'alerte, tandis que le prompt maître associe les scores à `account_id` et `tx_id` et ne fixe pas la granularité des alertes. La clé et la règle d'agrégation retenues dans le validateur et le DDL sont provisoires jusqu'à cette décision.

## 3. Labels et schéma PostgreSQL

Les labels utilisent les colonnes du prompt maître : `account_id`, `tx_id`, `scenario`, `role`, `start_ts`, `end_ts`. `tx_id` peut être nul pour un label portant sur une période ou un compte plutôt que sur une transaction unique. Les labels sont isolés dans leur table. Le DDL de cette phase ne crée pas encore de rôles ni de permissions PostgreSQL; lors de l'intégration, le service de scoring devra utiliser un rôle sans droit de lecture sur `labels`.

Le DDL de `sql/schema.sql` matérialise la proposition et peut être appliqué plusieurs fois (`CREATE ... IF NOT EXISTS`). Les clés de features, scores et alertes sont des décisions de conception proposées pour rendre les écritures rejouables; elles restent à valider avant d'être considérées comme gelées.

## 4. Divergences et décisions restant à valider

- Le prompt maître prescrit les noms transactionnels `tx_id`, `timestamp`, `source_account_id` et `target_account_id`. La spécification `docs/specification_technique_aml.md` attribuée à Mounir n'est pas présente dans `origin/main` actuel; la comparaison directe avec son contenu reste donc à faire.
- Le prompt définit la sortie `features` au niveau compte, mais ne fixe pas sa clé, ses fenêtres sérialisées ni sa cadence d'émission.
- Le plan d'évaluation de phase 1 utilise le compte par jour comme unité d'alerte. Il faut décider comment agréger les scores liés aux transactions avant de figer la clé et la granularité de `alerts`.
- `docs/typologies.md` et `docs/simulator_assumptions.md` signalent des champs potentiellement utiles absents du schéma maître (`balance`, bénéficiaire effectif, pays de destination). Ils ne sont pas ajoutés ici; leur nécessité doit être décidée ensemble, car les ajouter modifie le contrat.
- Les types exacts de `model_versions` et le contenu précis de `explanation` doivent être approuvés conjointement.
- Le prompt maître ne demande pas de sélectionner un dataset externe : le projet produit un jeu synthétique en phase 3 à partir du simulateur. Les hypothèses et taux de simulation sont réglés dans les phases prévues, et ne sont pas un choix de dataset externe en phase 2.
- Une fois les points ci-dessus décidés, inscrire la validation dans `docs/decisions.md` et mettre à jour le statut de ce document; ne déclarer le contrat gelé qu'après accord des deux étudiants.
