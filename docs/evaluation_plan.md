# Plan d'évaluation v1 et matrice de coûts

**Projet :** Détection AML en flux (PFA) · **Version :** v1 (brouillon, rédigé **avant** l'entraînement des modèles ; à valider par l'équipe puis par le Pr Chergui) · **Rédaction :** 9 novembre 2026 · **Phase :** 1 (semaine 1, côté Mounir) · **Ticket :** « Plan d'évaluation v1 et matrice de coûts »

> **Avertissement : données simulées.** Toutes les mesures décrites ici porteront sur des données **générées par notre simulateur** (voir `docs/simulator_assumptions.md`). Les résultats ne diront pas ce que le système donnerait sur de vraies données bancaires. Les limites sont décrites à la section 9.

## Comment lire ce document

Ce plan fixe **à l'avance** comment on juge le système : quelles mesures, sur quelles données, avec quelle règle de découpage et quel coût attribué aux erreurs. L'intérêt est d'éviter de choisir les mesures *après* avoir vu les résultats. Une fois les modèles entraînés, ce document ne doit être modifié qu'avec une entrée datée dans `docs/journal.md` expliquant pourquoi.

Statuts, comme dans `docs/typologies.md` : **[V]** vérifié dans une source ; **[H]** hypothèse de l'équipe, avec justification ; **[À vérifier]** non confirmé.

Exigences de départ : `MASTER_PROMPT_PFA_AML.md` (section 10, lignes 186 à 197) et `Roadmap_PFA_Detection_Blanchiment.md` (lignes 51 et 69).

---

## 1. Ce qu'on évalue

| Élément | Description |
| --- | --- |
| **Système évalué** | Chaîne complète : règles, Isolation Forest, XGBoost, variables de graphe, score final (`docs/typologies.md` section 6, prompt maître). |
| **Unité d'alerte** | Un couple **(compte, jour simulé)**. Un compte est noté chaque jour s'il a eu au moins une transaction ce jour-là (comme émetteur ou destinataire). [H] |
| **Vérité terrain** | Table `labels` du simulateur : scénario, rôle, début et fin de l'activité suspecte de chaque compte impliqué. Elle sert **uniquement à évaluer et à entraîner**, jamais au scoring en direct. |
| **Couple (compte, jour) positif** | Le compte a un rôle dans un cas dont l'intervalle `[début, fin]` contient ce jour. |
| **Cas détecté** | Au moins un compte du cas apparaît dans les alertes d'un jour compris dans l'intervalle d'activité de ce compte. |
| **Contrainte métier** | Un analyste ne traite qu'un nombre limité d'alertes par jour : **k = 50 par défaut**, configurable (section 4). |

---

## 2. Découpage temporel entraînement / validation / test

### 2.1 Principe

**Le futur ne doit jamais servir à apprendre ou à régler le passé.** On découpe donc la période **dans l'ordre du temps**. Aucun mélange aléatoire de jours, de comptes ou de transactions entre les blocs, et aucune validation croisée aléatoire.

### 2.2 Blocs (période de 90 jours, jours numérotés de 1 à 90)

| Bloc | Jours | Durée | Rôle |
| --- | --- | --- | --- |
| Échauffement | 1 à 7 | 7 jours | Construire l'historique des variables sur 7 jours. **Non utilisé** pour l'entraînement ni pour la mesure. |
| **Entraînement** | 8 à 56 | 49 jours | Apprendre les modèles (XGBoost, Isolation Forest) et calculer les statistiques de référence. |
| **Validation** | 57 à 72 | 16 jours | Choisir les hyperparamètres, le seuil et le point de fonctionnement. |
| **Test** | 73 à 90 | 18 jours | Mesure finale, **utilisée une seule fois par graine** après gel des choix. |

Justification [H] : 7 + 49 + 16 + 18 = 90 jours ; entraînement ≈ 59 %, validation ≈ 19 %, test ≈ 22 % des 83 jours utilisables. Le test fait au moins 14 jours pour contenir plusieurs cycles de fenêtres de 7 jours. Ces proportions sont un choix, pas une norme.

### 2.3 Règles anti-fuite

| Code | Règle |
| --- | --- |
| L-1 | Toute variable calculée à l'instant `t` n'utilise que des transactions dont l'horodatage (temps événementiel) est **inférieur ou égal à `t`**. |
| L-2 | Les fenêtres de 7 jours du début de validation et de test **peuvent** utiliser les jours précédents (c'est du passé), mais jamais les jours suivants. |
| L-3 | Les statistiques de normalisation (moyenne historique d'un compte, médiane d'un profil) sont calculées sur le passé seulement (fenêtre croissante). |
| L-4 | **Aucune étiquette ni identifiant de compte** n'est une variable d'entrée (sinon le modèle mémorise les comptes). |
| L-5 | Les étiquettes utilisées pour l'entraînement sont celles **connues à la fin du bloc d'entraînement** : on ne s'en sert pas pour des transactions postérieures. |
| L-6 | **Chaque cas tient entièrement dans un seul bloc** (H-23 de `docs/simulator_assumptions.md`) : le simulateur place les débuts de cas pour que fin ≤ fin du bloc. La durée maximale d'un cas est donc bornée par le plus court des blocs de mesure (validation : 16 jours). Voir question ouverte 3. |
| L-7 | Les réglages (hyperparamètres, seuil, poids du score) sont choisis sur la **validation** uniquement. Le bloc de test n'est exécuté qu'après gel, et tout nouveau passage est noté dans `docs/journal.md`. |
| L-8 | Si une validation interne est nécessaire dans le bloc d'entraînement, elle est **chronologique** (fenêtre croissante, « forward chaining »), jamais aléatoire. |

### 2.4 Test automatique de fuite (exigé par le prompt maître, ligne 216)

Test d'**invariance au futur** : on calcule les variables et les scores d'un jour `t` une première fois sur le jeu complet, une seconde fois sur le jeu **tronqué à `t`** (toutes les transactions postérieures supprimées). Les résultats doivent être **identiques**. Le test échoue si une variable utilise une information postérieure. Il est à écrire en phase 4 avec les variables de fenêtre, et à exécuter par la CI.

### 2.5 Répartition des cas dans les blocs

Le profil `full` contient **15 cas** par graine : 5 scénarios × 3 niveaux (D-4). Pour que chaque bloc contienne chaque scénario, **chaque scénario place un cas dans chacun des trois blocs**, avec une permutation des niveaux tirée de la graine. [H]

| Par graine | Cas | Comptes impliqués (environ, avec H-07) |
| --- | --- | --- |
| Entraînement | 5 (1 par scénario) | environ 38 |
| Validation | 5 | environ 38 |
| Test | 5 | environ 38 |

Avec 5 graines : **25 cas de test**, soit 5 par scénario (1 à 2 par couple scénario × niveau, environ 8 par niveau sur tous les scénarios). Un recall observé de 4 sur 5 donne un intervalle de Wilson de 38 % à 96 % (`docs/typologies.md` 8.2) : les résultats par typologie sont donc **indicatifs**.

**Risque R-1 : peu de positifs pour entraîner XGBoost.** Cinq cas d'entraînement par graine, soit environ 38 comptes, c'est très peu pour un modèle supervisé. Deux options à décider (question ouverte 2) :

- **Option A (par défaut)** : un modèle par graine, entraîné sur le bloc d'entraînement de cette graine uniquement. Strictement chronologique, mais peu de positifs.
- **Option B** : entraîner sur les blocs d'entraînement de **toutes les autres graines** plus le sien (« leave-one-seed-out »), et tester sur le bloc de test de la graine. Les graines sont des mondes simulés indépendants : aucun futur de la graine testée n'est utilisé. Davantage de positifs, mais il faut justifier cette lecture auprès du jury.

Le profil `light` (1 cas par scénario) ne sert pas à l'évaluation chiffrée (D-3).

---

## 3. Métriques

### 3.1 Precision@k et recall@k, par jour

Pour chaque jour `d` du bloc évalué, on classe les comptes notés par score décroissant et on garde les **k premiers** (les alertes).

- **TP_d** : nombre d'alertes du jour qui sont des comptes positifs ce jour-là.
- **N_d** : nombre de comptes notés ce jour-là ; le nombre d'alertes vaut `min(k, N_d)`.
- **P_d** : nombre de comptes positifs notés ce jour-là.

| Métrique | Formule | Remarque |
| --- | --- | --- |
| **Precision@k du jour** | `TP_d / min(k, N_d)` | Part des alertes qui sont de vrais cas. |
| **Recall@k du jour** | `TP_d / P_d`, pour les jours où `P_d > 0` | Part des comptes positifs du jour qui sont dans les alertes. |
| **Precision@k globale (principale)** | `ΣTP_d / Σ min(k, N_d)` sur les jours du bloc | Moyenne « micro » sur tous les jours. |
| **Recall@k globale** | `ΣTP_d / ΣP_d` sur les jours où `P_d > 0` | Idem. |

On rapporte aussi la moyenne par jour et la distribution (médiane, min, max) sur le bloc de test, car les jours sans positif sont exclus du recall.

**Plafond de la precision@k (point important).** Si un jour compte `P_d` positifs et qu'on garde `k` alertes, la precision@k ne peut pas dépasser `min(1, P_d / k)`. Avec ~38 comptes positifs dans le bloc de test `full` (environ 5 cas) actifs chacun entre 5 et 15 jours dans un bloc de 18 jours, `P_d` est de l'ordre de **10 à 30** positifs par jour. Pour k = 50, la precision@k est donc plafonnée à environ **0,2 à 0,6**, même pour un détecteur parfait. [H : estimation à recalculer avec le simulateur.] **Conséquence :** une precision@50 « faible » ne prouve pas un mauvais modèle. On rapporte donc toujours, à côté de la precision@k, **le plafond `min(1, P_d / k)`** et la **precision@k normalisée** (precision@k divisée par ce plafond). Voir question ouverte 4.

### 3.2 Détection par typologie et par niveau (rappel par typologie)

| Métrique | Définition |
| --- | --- |
| **Taux de détection d'un cas (rappel par typologie)** | Pour chaque scénario : nombre de cas détectés / nombre de cas du scénario sur les blocs de test (toutes graines). Un cas est détecté selon la définition de la section 1. |
| **Rappel par niveau de sophistication** | Même mesure, agrégée **sur les scénarios**, pour faible, moyen, élevé (D-6). |
| **Rappel par compte** (secondaire) | Part des comptes étiquetés d'un scénario qui figurent au moins une fois dans les alertes pendant leur intervalle d'activité. |
| **Délai de détection** | Heures simulées entre le début du rôle du compte et la première alerte du cas. Mesure métier, distincte de la latence technique (section 3.5). |

Chaque taux par typologie est accompagné de son **intervalle de confiance de Wilson à 95 %** (D-6). Les résultats par typologie sont présentés comme **indicatifs** (section 2.5).

### 3.3 Courbes précision-rappel et ROC

Sur les couples (compte, jour) du bloc de test, pour Isolation Forest, XGBoost et le score final : **courbe précision-rappel (principale)**, aire sous cette courbe (PR-AUC) comparée à la **prévalence** (une prédiction au hasard donne une PR-AUC égale à la prévalence), et courbe ROC en complément. Justification : avec moins de 1 % de comptes positifs, la ROC paraît optimiste ; la courbe précision-rappel reste lisible.

### 3.4 Coût total

Défini à la section 5. Rapporté en fonction du seuil d'alerte, avec le point de fonctionnement retenu et sa justification (prompt maître, ligne 192).

### 3.5 Latence et débit

| Métrique | Définition |
| --- | --- |
| **Latence de bout en bout** | Durée entre la **publication** d'une transaction dans le topic `transactions` et la publication du score ou de l'alerte correspondant dans `scores` ou `alerts`. Mesurée avec les horodatages des messages Kafka (heure de création par le producteur, heure d'écriture par le broker), en secondes réelles. |
| **Percentiles** | p50, p95 (exigés) et p99 (informatif). |
| **Débit** | Événements par seconde **soutenus** sans accumulation de retard, mesurés à 100 événements/s (valeur par défaut) et 500 événements/s (maximum du prompt maître, ligne 156). |
| **Ressources** | Mémoire (`docker stats`), avec la limite configurée de 3,5 Gio. |
| **Reprise après redémarrage** | Temps pour revenir à un débit normal après arrêt et relance, avec points de reprise (checkpoints). |

Conditions de mesure : machine et version des images consignées dans le rapport ; 60 premières secondes exclues ; au moins 10 minutes en régime établi ; au moins 3 répétitions.

**Précision importante.** Le prompt maître parle de « temps événementiel jusqu'à l'alerte ». Comme le rejeu accélère le temps simulé, la latence **technique** est mesurée **de la publication à l'alerte** (secondes réelles). Le **délai de détection** métier (en heures simulées) est mesuré à part (section 3.2). Si l'alerte « top-k par jour » est calculée à la fin de la journée, le délai de détection peut atteindre 24 heures simulées par construction, sans que la latence technique en soit affectée. Voir question ouverte 5.

### 3.6 Robustesse statistique

- **Graines** : au moins **3**, **5 visées** pour l'évaluation finale (D-5).
- **Résumé** : moyenne, écart-type et minimum–maximum sur les graines, jamais une seule exécution.
- **Proportions** (rappel par typologie, par niveau) : intervalle de Wilson à 95 % calculé sur les cas cumulés de toutes les graines.
- Résultats non reproductibles à graine égale = défaut à corriger (le simulateur et l'entraînement sont déterministes, prompt maître ligne 45).

---

## 4. Valeur de k : 50 alertes par jour

| Paramètre | Valeur par défaut | Statut | Justification |
| --- | --- | --- | --- |
| `k_alerts_per_day` | **50** | [H], **configurable** | Valeur du prompt maître (ligne 190) : ordre de grandeur de ce qu'un analyste peut relire en une journée. Aucune source n'a été trouvée pour ce chiffre. |

`k` est lu dans `config/scoring.yaml` (prompt maître, ligne 96). L'analyse de sensibilité fait varier `k ∈ {10, 25, 50, 100, 200}` pour montrer comment les résultats dépendent de la capacité de l'analyste.

**Remarque d'échelle.** Le jeu `full` compte environ 20 000 comptes. Avec k = 50, on alerte sur environ **0,25 %** des comptes par jour. Avec le profil `light` (5 000 comptes), 50 alertes représentent 1 % des comptes : le même `k` n'a pas le même poids selon la taille du profil. C'est une raison de plus de ne pas interpréter les métriques sur `light`.

---

## 5. Matrice de coûts

### 5.1 Définition

| Terme | Définition |
| --- | --- |
| **Fausse alerte (FP)** | Alerte (compte, jour) sur un compte qui n'a pas de rôle actif dans un cas ce jour-là. |
| **Cas manqué (FN)** | Cas dont aucun compte n'a été alerté pendant l'activité. |
| **Alerte vraie** | Alerte sur un compte positif : coût nul dans ce modèle (la revue est le travail normal de l'analyste). [H] |
| **Coût total** | `C(τ) = c_FP × FP(τ) + c_FN × FN(τ)`, où τ est le seuil d'alerte. |

On parle ici d'une unité de coût **relative**, pas de dirhams : aucune source ne permet de chiffrer en MAD le coût d'une revue ou d'un cas manqué, et inventer ces montants donnerait une fausse précision.

### 5.2 Valeurs proposées (hypothèses)

| Paramètre | Valeur centrale | Statut | Justification |
| --- | --- | --- | --- |
| `c_FP` | **1 unité** = une revue d'alerte (supposée de l'ordre de 15 minutes d'analyste) | [H] | Unité de référence ; ce qui compte est le **rapport** `r = c_FN / c_FP`. |
| `c_FN` | **200 unités** | [H] | Un cas manqué vaut 200 revues d'alertes, soit environ 4 jours complets d'un analyste traitant 50 alertes par jour. Choix au milieu d'une échelle logarithmique de 10 à 1 000 : l'effet d'un cas non détecté (sanction réglementaire, atteinte à la réputation, perte financière) est supposé très supérieur au temps de revue. **Aucune source.** |
| `r = c_FN / c_FP` | **200** | [H] | Valeur centrale, soumise à l'analyse de sensibilité. |

### 5.3 Analyse de sensibilité

| Scénario de coût | `c_FP` | `c_FN` | `r` |
| --- | --- | --- | --- |
| Très prudent sur les erreurs coûteuses | 1 | 10 | 10 |
| Bas | 1 | 50 | 50 |
| Intermédiaire | 1 | 100 | 100 |
| **Central** | 1 | **200** | **200** |
| Haut | 1 | 500 | 500 |
| Très haut | 1 | 1 000 | 1 000 |

Ce qu'on rapporte :

1. La **courbe de coût en fonction du seuil** pour chaque `r`, sur la validation puis le test.
2. Le **seuil optimal** pour chaque `r` : s'il bouge peu, le choix du point de fonctionnement est robuste ; s'il bouge beaucoup, on le dit.
3. Le **rapport d'équilibre** entre deux systèmes A et B (par exemple « règles seules » et « ensemble complet ») : B coûte moins que A si `r > (FP_B − FP_A) / (FN_A − FN_B)`. Cela montre à partir de quel coût de cas manqué le système plus complexe devient rentable.
4. L'effet de `k` (section 4) : coût et nombre de cas manqués quand la capacité de revue passe de 10 à 200 alertes par jour.

**Exemple illustratif (ce n'est pas un résultat).** Si un seuil laisse 100 fausses alertes et 2 cas manqués, son coût central est 100 × 1 + 2 × 200 = 500. Un seuil plus bas qui laisse 400 fausses alertes et aucun cas manqué coûte 400 × 1 = 400 : il est préférable pour `r = 200`. Pour `r = 50`, les mêmes seuils coûtent 200 et 400 : le seuil plus haut est alors préférable. Ce renversement est précisément ce que l'analyse de sensibilité doit mettre en évidence.

### 5.4 Choix du point de fonctionnement

1. Sur la **validation**, on cherche le seuil τ qui minimise `C(τ)` pour `r = 200` **sous la contrainte** d'au plus `k` alertes par jour en moyenne.
2. On **gèle** ce seuil, puis on mesure sur le **test** : précision, rappel, coût.
3. On rapporte aussi les points de fonctionnement pour les autres `r`, pour montrer l'écart.

Configuration prévue (valeurs par défaut, modifiables) :

```yaml
# config/scoring.yaml (extrait proposé)
evaluation:
  k_alerts_per_day: 50
  split:
    warmup_days: 7
    train_days: [8, 56]
    validation_days: [57, 72]
    test_days: [73, 90]
  costs:
    c_fp: 1
    c_fn: 200
    sensitivity_ratios: [10, 50, 100, 200, 500, 1000]
  seeds: [1, 2, 3, 4, 5]
```

---

## 6. Comparaisons et ablations

Prévues par le prompt maître (ligne 194). Toutes avec les mêmes blocs, la même valeur de `k` et les mêmes graines.

| Variante | Question posée |
| --- | --- |
| Règles seules | Que vaut la référence simple et explicable ? |
| Isolation Forest seul | Que détecte-t-on sans étiquettes ? |
| XGBoost seul | Que gagne-t-on avec les étiquettes ? |
| Ensemble sans variables de graphe | Les cycles et les chaînes apportent-ils quelque chose ? |
| Ensemble sans variables de vitesse | La vitesse sur 1 h, 24 h, 7 j est-elle indispensable ? |
| **Ensemble complet** | Référence de comparaison. |

Les règles métier servent de **ligne de base** : un modèle complexe qui ne fait pas mieux que les règles à coût égal n'est pas justifié.

## 7. Test adversarial et dérive

Prévu en semaine 6 (prompt maître, ligne 195). On change le comportement des blanchisseurs (montants plus bas, délais plus longs, plus de bruit) **uniquement dans le bloc de test**, on mesure la baisse de rappel et de precision@k, puis on réentraîne et on mesure la récupération. La **dérive normale** vient aussi du Ramadan et de l'Aïd, présents dans le bloc d'entraînement mais pas dans le test (`docs/simulator_assumptions.md` section 4). Les paramètres exacts seront fixés avant le test, en phase 6.

---

## 8. Protocole d'exécution

1. Générer le jeu pour chaque graine avec le profil `full` ; vérifier que le taux de comptes impliqués reste **inférieur à 1 %** (contrôle automatique, D-2).
2. Calculer les variables jour par jour en respectant L-1 à L-3 ; exécuter le test d'invariance au futur (section 2.4).
3. Entraîner sur le bloc d'entraînement ; régler sur la validation ; **geler**.
4. Évaluer sur le test **une seule fois par graine**.
5. Agréger sur les graines ; produire les tableaux et courbes de la section 3 et les courbes de coût de la section 5.
6. Consigner dans `docs/journal.md` : version du code, graines, valeurs de `k` et des coûts, écarts avec ce plan.

---

## 9. Limites d'une évaluation sur données simulées

1. **Circularité.** Nous écrivons le simulateur **et** le détecteur. Un modèle peut apprendre les règles du générateur plutôt que le blanchiment. Un projet tiers rapporte des scores quasi parfaits sur SAML-D (indicatif, source tierce, `docs/typologies.md` section 7). Des résultats très élevés doivent donc éveiller la méfiance, pas la satisfaction. Parades : niveaux de sophistication, test adversarial, comparaison de réalisme avec les jeux publics.
2. **Étiquettes parfaites.** Dans la réalité, beaucoup de blanchiment n'est jamais détecté et les étiquettes sont donc incomplètes (Altman et al., NeurIPS 2023). Ici, on connaît tout. Le rappel mesuré est donc un **majorant optimiste**.
3. **Peu de cas.** 5 cas de test par scénario avec 5 graines : des intervalles de Wilson très larges (4 sur 5 donne 38 % à 96 %). Aucune comparaison fine entre deux modèles proches n'est fiable.
4. **Taux et tailles de cas choisis par nous.** La precision@k dépend directement du nombre de positifs par jour (plafond de la section 3.1). Elle n'est pas comparable à celle d'un système réel.
5. **Coûts hypothétiques.** `c_FP`, `c_FN` et `k` ne viennent d'aucune source : seule la **sensibilité** des conclusions à ces valeurs est informative, pas le coût absolu.
6. **Monde fermé et période courte.** Une banque, 90 jours, pas de solde ni de bénéficiaire effectif, pas de saisonnalité annuelle (`docs/simulator_assumptions.md` section 9).
7. **Latence mesurée sur une machine personnelle** avec un seul broker Kafka : valeurs indicatives, pas représentatives d'un déploiement bancaire.
8. **Pas d'analyste dans la boucle.** Le temps de revue d'une alerte, la qualité de l'explication (SHAP) et la fatigue de l'analyste ne sont pas mesurés.

---

## 10. Questions ouvertes

1. **Validation par l'équipe** (Mouad et Mounir) du découpage 7 / 49 / 16 / 18 jours, de la définition de l'unité d'alerte (compte, jour) et de la définition d'un « cas détecté ».
2. **Option A ou B** pour l'entraînement (section 2.5) : un modèle par graine ou entraînement sur les autres graines. L'option B est-elle acceptable pour le jury comme évaluation « temporelle » ?
3. **Durée maximale d'un cas** : la règle L-6 impose des cas d'au plus 16 jours, ce qui contredit des valeurs par défaut du catalogue (flux circulaires : 30 jours). Raccourcir les durées, ou passer le profil `full` à 120 jours (ce qui modifie le prompt maître) ?
4. **Présentation de la precision@k** avec son plafond et sa version normalisée (section 3.1) : à valider, car un lecteur pressé risque de lire une precision@50 de 0,3 comme un échec.
5. **Définition de la latence** : publication → alerte (proposée) ou temps événementiel → alerte (formulation du prompt maître, non mesurable avec un rejeu accéléré) ? Et le `top-k` est-il calculé en fin de journée (évaluation) ou en ligne (budget glissant) ?
6. **Valeurs de `c_FN` et de `k`** : à discuter avec le Pr Chergui, éventuellement avec des repères de la littérature sur le coût de revue d'une alerte.
7. **Même nombre de cas dans chaque bloc** : est-ce acceptable alors que, dans la réalité, la fréquence des cas varie dans le temps ?
8. **Test de dérive** : fixer les paramètres du changement de comportement avant l'évaluation finale.

---

## 11. Références

- `MASTER_PROMPT_PFA_AML.md` : section 10 (lignes 186 à 197), lignes 45, 96, 156, 178, 190 à 197, 216.
- `Roadmap_PFA_Detection_Blanchiment.md` : lignes 51, 69, 152, 158, 201.
- `docs/typologies.md` v1.1 : sections 5, 7 et 8 (décisions D-1 à D-6, intervalles de Wilson, profils `light` et `full`).
- `docs/simulator_assumptions.md` v1 : hypothèses H-01 à H-23, taux de comptes et de transactions.
- Altman et al., NeurIPS 2023 (AMLworld) ; Oztas et al., SAML-D, IEEE ICEBE 2023 : limites des jeux synthétiques, détaillées dans `docs/typologies.md`.
