# Spécification technique — variables, scénarios et évaluation AML

**Projet :** Détection du blanchiment en flux — PFA EMSI Casablanca  
**Version :** 1.0 · **Date :** 7 novembre 2026  
**Périmètre :** données synthétiques, événements Kafka, agrégations Spark Structured Streaming, scoring et analyse de graphes.

> Ce document définit une spécification expérimentale pour le PFA. Les règles et données simulées ne constituent ni un dispositif réglementaire opérationnel ni un avis juridique. Le modèle produit des alertes à examiner par un analyste; il ne qualifie pas juridiquement une opération et ne déclenche pas seul une déclaration de soupçon.

## 1. Conventions de données et calcul en flux

Chaque événement de transaction doit au minimum porter `transaction_id`, `event_time` (UTC, instant d'acceptation ou d'exécution défini par le contrat), `account_id`, `customer_id`, `counterparty_id`, `direction` (`in`/`out`), `amount`, `currency`, `payment_channel` et un indicateur de statut. Les montants sont positifs et exprimés en unité monétaire mineure entière; les conversions se font avec un taux daté et versionné. Les transactions annulées, rejetées et dupliquées sont identifiées et exclues des agrégations pertinentes selon le statut métier.

Les variables sont calculées « as-of » à l'instant de décision `t`, uniquement avec des événements dont `event_time ≤ t` et qui étaient effectivement disponibles à cet instant. Les fenêtres sont glissantes, semi-ouvertes `(t−W, t]`; l'événement courant est inclus. Une implémentation Spark doit définir explicitement watermark, retard toléré, déduplication et politique de correction des événements tardifs. Les alertes conservent l'heure de calcul, la version des variables et les paramètres de configuration.

Soit `T_c(t)` l'ensemble des transactions admissibles du compte `c` dans la fenêtre précédant `t`; `a_i` est le montant converti en devise de référence. Calculer séparément les flux entrants et sortants, ainsi qu'un total lorsque cela a un sens. Le client et le compte ne sont pas interchangeables : les agrégations client consolident les comptes associés via une relation valide à la date de l'événement.

## 2. Dictionnaire des variables (features)

Les identifiants et valeurs démographiques brutes ne sont pas des substituts aux comportements. Les variables ci-dessous doivent être accompagnées de leurs clés de portée (compte/client, direction, canal et devise ou devise de référence) et, idéalement, de leur fraîcheur et qualité.

| Nom canonique | Définition à l'instant `t` | Type / unité | Notes d'interprétation |
|---|---|---|---|
| `txn_count_{1h,24h,7d}_{in,out}` | `N_W = Σ 1[i ∈ T_c(t), direction_i = d]`, pour `W ∈ {1 h, 24 h, 7 j}` | entier | Vitesse / fréquence des opérations. Ajouter éventuellement le total entrant + sortant. |
| `amount_sum_{1h,24h,7d}_{in,out}` | `S_W = Σ a_i` sur le même ensemble | MAD (ou devise de référence) | Cumul glissant des montants. Garder la devise d'origine disponible. |
| `amount_mean_{1h,24h,7d}_{in,out}` | `S_W / max(N_W,1)`; nul si `N_W=0` | MAD/opération | Distingue hausse du volume et hausse de la taille moyenne. |
| `amount_max_{1h,24h,7d}_{in,out}` | `max(a_i)`; nul si fenêtre vide | MAD | Signal complémentaire, sensible aux valeurs extrêmes. |
| `historical_amount_mean_{30d}` | Moyenne quotidienne ou par transaction sur la période historique antérieure à `t`, selon définition gelée | MAD | Calculée hors fenêtre de comparaison, pour éviter de comparer une transaction à elle-même. |
| `amount_sum_deviation_{W}` | `S_W − μ_{c,W}`; variante relative `(S_W−μ)/max(σ, ε)` | MAD / z-score | `μ` et `σ` sont estimés exclusivement sur des périodes antérieures; robustifier par médiane/MAD en présence de queues lourdes. |
| `txn_count_deviation_{W}` | Écart analogue entre `N_W` et la référence historique du client/compte | nombre / z-score | Référentiel saisonnier préférable (jour de semaine, heure, fin de mois) lorsque l'historique le permet. |
| `unique_counterparties_{W}_{in,out}` | `|{counterparty_id_i : i ∈ T_c(t), direction_i=d}|` | entier | Compter les identifiants résolus; traiter une contrepartie inconnue comme catégorie explicite, pas comme une nouvelle identité à chaque événement. |
| `counterparty_concentration_{W}` | `max_j(Σ_{i→j} a_i / max(S_W, ε))` ou indice de Herfindahl `Σ_j p_j²` | ratio `[0,1]` | Permet de différencier dispersion et concentration. Une forte diversité seule n'est pas une preuve de soupçon. |
| `txn_to_declared_income_ratio` | `a_t / max(income_monthly_declared, ε)` | ratio sans unité | Comparer aussi `S_24h` et `S_7d` au revenu mensuel. Revenu absent/inconnu doit produire un indicateur de disponibilité, pas un ratio artificiellement interprété. |
| `txn_to_declared_turnover_ratio` | `a_t / max(turnover_monthly_declared, ε)` | ratio sans unité | Variante adaptée aux clients professionnels; conserver la nature et la date de déclaration du profil. |
| `threshold_proximity_{τ}` | Pour seuil configurable `τ>0`: `a_t/τ`; distance normalisée `1−a_t/τ` si `a_t≤τ`, sinon `0` | ratio | Peut être calculé pour un seuil interne ou un seuil de déclaration réellement applicable. Inclure devise, canal, juridiction, type d'opération, source et période de validité de `τ`. |
| `subthreshold_count_{W,τ}` | Nombre d'opérations `a_i < τ` dans `W` | entier | À compléter par `subthreshold_sum_{W,τ}` et nombre d'opérations dans une bande `[τ(1−δ), τ)`. Mesure un motif, pas un contournement établi. |

`ε` est une constante de stabilité numérique documentée (par exemple la plus petite unité significative du montant), jamais un moyen de transformer une valeur absente en observation valide. Pour les références historiques, stocker `history_count`, `history_days`, `profile_version` et `is_cold_start`. En cas d'historique insuffisant, utiliser une référence de population comparable et un indicateur explicite de repli; ne pas mélanger silencieusement client et population.

### Seuils et interprétation réglementaire

Le « seuil légal de déclaration » ne doit pas être codé comme un seuil universel de déclaration de soupçon. Au Maroc, l'article 9 de la loi 43-05 consolidée prévoit une déclaration pour les sommes, opérations ou tentatives soupçonnées d'être liées aux infractions visées et pour une identité douteuse; le texte cité ne pose pas un montant général en dessous duquel le soupçon ne serait pas déclarable. Les opérations inhabituelles ou complexes sans justification apparente relèvent également d'un examen particulier selon l'article 8. En conséquence, `τ` dans le simulateur désigne par défaut un **seuil expérimental de scénario** ou une **règle interne fictive**, clairement étiqueté; il ne doit jamais être présenté comme une obligation marocaine réelle. Si des obligations quantitatives sectorielles sont étudiées, elles devront être sourcées dans le texte et la circulaire applicables au secteur et à la date considérés, puis validées par l'encadrant. Référence primaire : [loi 43-05 telle que modifiée et complétée (ACAPS, PDF)](https://www.acaps.ma/sites/default/files/publication_documents/la_loi_ndeg_43-05_relative_a_la_lutte_contre_le_blanchiment_de_capitaux_telle_que_modifiee_et_completee_0.pdf); page de [cadre légal et réglementaire de l'ACAPS](https://www.acaps.ma/fr/professionels/lutte-contre-le-blanchiment-des-capitaux/cadre-legal-reglementaire-et-normatif).

## 3. Catalogue des typologies synthétiques

Les paramètres ci-dessous définissent des motifs de données synthétiques pour évaluer le pipeline; ils ne décrivent pas de procédure permettant de contourner les contrôles d'un établissement réel. Pour éviter une règle simpliste apprise par le modèle, varier les montants, horaires, délais et tailles de réseau et injecter des cas normaux comparables (paie, collecte légitime, paiements commerçants, remboursements). Chaque épisode reçoit un `scenario_id` et des labels conservés séparément du flux observable. Au niveau événement, distinguer `scenario_member` de `alertable_event`; au niveau compte/épisode, évaluer aussi la détection du cas.

Paramètres communs : montant de référence `B`, période de scénario `H`, intensité `q`, bruit comportemental `η`, et graine aléatoire `seed`. Paramétrer tous les montants en MAD synthétiques ou devise de référence, sans donnée personnelle réelle. Les intervalles proposés sont des **valeurs initiales de simulation**, à ajuster au générateur normal et à documenter dans la configuration versionnée.

| Typologie | Construction de l'épisode | Paramètres/initiaux | Signaux attendus |
|---|---|---|---|
| Fractionnement (smurfing) | Un initiateur répartit un montant agrégé `A` en `n` dépôts/transferts `x_i`, généralement vers un ou quelques comptes collecteurs, avec `Σx_i ≈ A`. | `n ∈ [5,20]`; `H ∈ [1 h, 7 j]`; `x_i = A/n × (1+ε_i)`, `ε_i ~ U(-0,10,0,10)`; paramètre expérimental `τ_sim`, et proportion choisie sous `τ_sim` configurable. Autoriser une marge de bruit et plusieurs initiateurs. | Compte cumulé élevé malgré montants unitaires modestes; répétition rapprochée; concentration des bénéficiaires; proximité de `τ_sim`. |
| Enchaînement de virements (layering) | Chemin orienté `v_0→v_1→…→v_L`; transfert d'une fraction du montant à chaque étape, avec délais courts et éventuelle bifurcation/recombinaison. | `L ∈ [3,8]`; délais inter-étapes `Δt ∈ [1 min, 6 h]`; conservation `r_i ∈ [0,90,0,995]` du flux (reste modélisé en frais/bruit); `H ≤ 48 h`; branchement facultatif `b ∈ [1,3]`. | Profondeur de chemin courte dans le temps; forte proximité entre montant entrant et sortant; multiplicité de comptes intermédiaires; activité inhabituelle du réseau. |
| Comptes relais / mules | Un compte reçoit de une à plusieurs sources puis expédie tout ou partie des fonds à un ou plusieurs bénéficiaires dans un délai court. | `k_in ∈ [2,10]`, `k_out ∈ [1,5]`; délai réception→sortie `Δt ∈ [1 min, 24 h]`; ratio de retransmission `ρ = montant_sortant / max(montant_entrant,ε) ∈ [0,75,1,00]` sur l'épisode; activité de fond faible ou moyenne tirée du profil. | Temps de séjour faible; ratios entrée/sortie élevés; sources/bénéficiaires multiples; activité transactionnelle dépassant le profil historique. |
| Flux circulaires | Cycle simple ou presque simple `v_1→v_2→…→v_m→v_1`, éventuellement avec fractionnement des arêtes ou bruit de montants. | `m ∈ [3,8]`; durée de cycle `H ∈ [1 h, 7 j]`; chaque arête transmet `r_i ∈ [0,85,1,00]`; bruit multiplicatif `η_i ∈ [-0,05,0,05]`; limiter les cycles répétés par compte selon `q`. | Cycle dans le graphe temporel; retour de fonds vers une entité d'origine; pertes cumulées plausibles; relations récurrentes ou faibles justifications économiques simulées. |

`A`, `τ_sim`, distributions et intervalles doivent être séparés des variables d'entrée du modèle. Les scénarios peuvent se chevaucher; enregistrer un label multi-étiquette par épisode plutôt que forcer une classe exclusive. Produire des niveaux de difficulté (signaux forts, bruités, partiellement observés) et des variations de sophistication où une fraction des étapes est absente du jeu observé. L'injecteur ne doit jamais écrire le label ou `scenario_id` dans le topic consommé par le modèle.

## 4. Matrice de coûts et plan d'évaluation

### 4.1 Déséquilibre et protocole de référence

Le taux suspect cible du projet est inférieur ou voisin de `0,1 %` selon la configuration, cohérent avec un problème à très forte rareté. Le taux réel synthétique doit être rapporté précisément au niveau transaction **et** épisode/client; ces unités ne sont pas comparables. Une précision élevée sur un échantillon équilibré ne représente pas la file opérationnelle.

- Construire le jeu d'évaluation avec la prévalence naturelle du simulateur et ne pas sous-échantillonner les négatifs dans le test final. Si l'entraînement utilise sous-échantillonnage, pondération de classe ou sur-échantillonnage, le faire uniquement dans les partitions d'entraînement; tracer la prévalence d'origine et recalibrer les probabilités sur validation représentative.
- Rapporter la performance par période, typologie, profil, canal et niveau de couverture. Les métriques doivent inclure intervalles de confiance, idéalement bootstrap par client/épisode ou par blocs temporels, afin de ne pas traiter des événements corrélés comme observations indépendantes.
- Fixer une capacité de revue `K` par jour/semaine avec les parties prenantes ou, à défaut, présenter plusieurs budgets explicites. Aucun `K` universel ne doit être inféré des seules données synthétiques.

### 4.2 Coûts métier illustratifs

Un faux positif mobilise du temps d'analyse et peut créer des délais, demandes de justificatifs ou frictions client; un faux négatif laisse passer un risque potentiellement grave, mais son coût réel dépend du dossier, du cadre réglementaire et des conséquences. Faute de données de coûts bancaires réels, utiliser une **unité de coût relative** et tester la sensibilité plutôt que prétendre à une estimation monétaire.

| Réalité / décision | Pas d'alerte | Alerte (revue humaine) |
|---|---:|---:|
| Cas normal | `0` | `C_FP = 1` unité (coût indicatif de revue; décomposer en minutes × coût horaire + coût de friction si estimable) |
| Cas suspect simulé | `C_FN = 100` unités (coût critique illustratif) | `C_TP = C_review = 1` unité (l'alerte requiert encore analyse et décision humaine) |

La matrice de base `C_FN/C_FP = 100` est une hypothèse de travail, pas une donnée sectorielle. Présenter une analyse de sensibilité au minimum aux ratios `10`, `100` et `1000`; faire varier le coût de revue et la prévalence. Pour score `s` et capacité limitée, décider sur un seuil choisi sur validation afin de minimiser `C = C_FP·FP + C_FN·FN + C_review·TP`, ou maximiser le rappel sous contrainte `K`. Ne pas assimiler un vrai positif de simulation à un blanchiment juridiquement établi.

### 4.3 Métriques à publier

| Mesure | Définition / usage |
|---|---|
| Precision@K | Parmi les `K` alertes au score le plus élevé sur une période, fraction de cas positifs; mesurer aussi les épisodes suspects touchés par ces `K` alertes. Rapporter `K` et l'unité de classement. |
| Rappel par typologie | `TP_type/(TP_type+FN_type)` par smurfing, layering, mule et cycle; préciser évaluation événementielle ou détection d'épisode et la règle d'attribution multi-étiquette. |
| Courbe précision-rappel et AUPRC | Montrer la courbe sur la prévalence naturelle; fournir la prévalence comme baseline de précision. AUPRC synthétise la courbe mais ne remplace pas le point de fonctionnement métier. |
| Taux d'alertes / charge analyste | Alertes par jour et part de la capacité consommée; compléter la précision@K pour quantifier l'exploitabilité. |
| Coût attendu | Valeur de la matrice par période et typologie, accompagnée de l'analyse de sensibilité des coûts. |
| Latence | Temps événement→score et événement→alerte (p50, p95, p99), en séparant retard d'arrivée, calcul Spark et scoring. |

Précision, rappel, F-score et matrice de confusion restent utiles à des seuils documentés. ROC-AUC peut être rapportée à titre secondaire, mais ne doit pas masquer la faible valeur prédictive positive possible sous forte rareté. Pour les cas synthétiques, donner aussi le rappel au niveau de l'épisode et le délai jusqu'à la première alerte.

### 4.4 Découpage temporel sans fuite

Ordonner les données selon `event_time`. Exemple de protocole initial : entraînement sur les 60 % les plus anciens, validation sur les 20 % suivants, test final sur les 20 % les plus récents. Si le volume ou la saisonnalité l'exige, employer plusieurs fenêtres walk-forward, mais ne jamais mélanger aléatoirement le test futur dans les partitions antérieures. Insérer une période de purge/embargo au moins égale à la plus longue fenêtre d'agrégation (`7 j`) autour des frontières; pour des labels d'épisodes qui durent plus longtemps, purger l'intégralité des épisodes qui chevauchent une frontière.

- Ajuster imputations, normalisation, encodage, sélection de variables, seuil de décision, calibration de probabilité et hyperparamètres uniquement sur entraînement/validation; le test final n'est consulté qu'une fois le protocole gelé.
- Calculer les historiques et variables de graphe « as-of » dans chaque partition avec les seuls événements antérieurs disponibles. Ne pas utiliser le futur d'un compte, les agrégats complets d'un épisode, ni une centralité calculée sur le graphe global.
- Garder les labels et métadonnées d'injection dans une table séparée inaccessible au pipeline de features/scoring. Exclure les champs révélateurs (`scenario_id`, `scenario_type`, graine, indicateurs du générateur, ordre d'injection) et vérifier les dérivés qui pourraient les encoder directement.
- Éviter la contamination d'entités entre partitions lorsque l'objectif est de mesurer la généralisation à de nouveaux comptes : ajouter une évaluation complémentaire groupée par client. Cette mesure ne remplace pas le test temporel principal, car le contexte de production contient généralement des clients déjà connus.
- Documenter les frontières, versions du code et données, règles de purge, prévalences, paramètres du simulateur et empreinte des jeux de test pour rendre les résultats reproductibles.

Le résultat attendu est un tableau comparatif règles / modèle tabulaire / modèle enrichi par graphe, selon un même découpage temporel et une même capacité `K`, plus une étude d'ablation des familles de variables et une analyse des faux positifs par cause apparente.
