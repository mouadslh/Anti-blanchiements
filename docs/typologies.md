# Catalogue des typologies de blanchiment

**Projet :** Détection AML en flux (PFA) · **Version :** v1.1 (brouillon, sources vérifiées le 2026-11-08, à valider par l'équipe puis par le Pr Chergui) · **Rédaction :** 8 novembre 2026 · **Phase :** 1

## Légende des statuts

Chaque information importante porte un statut, pour que le jury sache ce qui est prouvé et ce qui est supposé.

| Étiquette | Signification |
| --- | --- |
| **[V]** | Vérifié dans une source officielle ou primaire consultée le 2026-11-08 (lien dans la section « Références »). |
| **[H]** | Hypothèse de simulation : choix de l'équipe, non démontré par une source. Reprise dans `docs/simulator_assumptions.md`. |
| **[À vérifier]** | Information plausible mais non confirmée à ce jour. Elle ne doit pas être utilisée comme un fait dans le rapport. |

> **Avertissement.** Toutes les données du projet sont simulées. Aucun flux ni aucune étiquette bancaire réels ne sont utilisés. Ce document décrit des **comportements simulés**, pas des obligations légales. Les valeurs chiffrées des paramètres sont des **hypothèses [H]** destinées à être modifiées dans `config/simulator.yaml`.

---

## 1. Objet et périmètre

Ce catalogue décrit les cinq scénarios de blanchiment que le simulateur injecte dans le flux de transactions : **fractionnement (structuring/smurfing)**, **layering**, **comptes relais (mule accounts)**, **flux circulaires (round-tripping)** et **sociétés écran (shell companies)**.

Pour chaque scénario, la fiche précise :

1. le fonctionnement simulé ;
2. les signaux observables dans le flux et les variables qui les capturent ;
3. les paramètres à simuler, avec plage et valeur par défaut ;
4. les comportements légitimes qui peuvent ressembler au scénario (source de faux positifs).

Le contrat de données v1 contient : `tx_id`, `timestamp`, `source_account_id`, `target_account_id`, `amount`, `currency`, `channel`, `source_customer_type`, `city`. Les signaux décrits ci-dessous doivent pouvoir se calculer **uniquement** à partir de ces champs. Les vérités terrain (scénario, rôle, début, fin) vivent dans la table `labels`, jamais dans le flux.

---

## 2. Cadre de référence

### 2.1 Cadre juridique marocain

Source principale : **loi n° 43-05 relative à la lutte contre le blanchiment de capitaux, version consolidée après modification par la loi n° 12-18** (publiée au BO du 2 septembre 2021), disponible sur le site du ministère de la Justice (voir Références, R1). Les articles ci-dessous ont été relus dans ce texte.

| Référence | Contenu retenu pour le projet | Statut |
| --- | --- | --- |
| Art. 574-1 du Code pénal (reproduit par la loi 43-05) | Définit le blanchiment : acquérir, détenir, utiliser, convertir, transférer, transporter des biens dont on sait qu'ils proviennent d'une infraction listée ; dissimuler ou déguiser leur nature, origine, mouvement ou propriété ; faciliter la justification mensongère de l'origine ; la tentative est incluse. Les cinq scénarios correspondent à des **techniques de conversion, de transfert et de dissimulation** au sens de cet article. | [V] |
| Art. 574-2 | Liste des infractions sous-jacentes (trafic de stupéfiants, corruption, escroquerie, contrebande, etc.). Le texte adopte donc un **système de liste** et non un système de seuil pour définir les infractions. | [V] |
| Art. 574-3 | Peine pour les personnes physiques : 2 à 5 ans d'emprisonnement et 50 000 à 500 000 MAD d'amende ; amende de 500 000 à 3 000 000 MAD pour les personnes morales. | [V] |
| Chap. II, art. 2 | Liste des personnes assujetties : établissements de crédit, sociétés de change, assurances, notaires, avocats, agents immobiliers, **prestataires de services aux sociétés** (création, organisation, domiciliation), etc. | [V] |
| Art. 3 et 4 | Approche fondée sur les risques ; identification des clients et du **bénéficiaire effectif** ; vérifier que les opérations sont **cohérentes avec la connaissance du client, de son activité et de son profil de risque** ; s'assurer de l'origine et de la destination des fonds ; vigilance renforcée pour les clients à risque élevé. | [V] |
| Art. 8 | Toute opération **inhabituelle ou complexe, sans justification économique ni objet licite apparent**, fait l'objet d'un examen particulier, consigné par écrit. | [V] |
| Art. 9 | Déclaration de soupçon **immédiate** pour toutes sommes, opérations ou tentatives soupçonnées d'être liées aux infractions visées. Le texte ne fixe **aucun montant minimal** pour cette déclaration. | [V] |
| Art. 9.1 | L'autorité reçoit aussi des **déclarations systématiques** sur des opérations financières, « selon des conditions et formalités fixées par l'Unité ». Les éventuels seuils relèvent donc de textes d'application, non de la loi consolidée. | [V] pour le principe ; textes d'application **[À vérifier]** |
| Art. 13.3 | Création d'un registre public des bénéficiaires effectifs des personnes morales constituées au Maroc. | [V] |
| Art. 14 et art. 39 | L'organe national est l'**Autorité Nationale du Renseignement Financier (ANRF)**. L'art. 39 précise que cette dénomination remplace « Unité de traitement du renseignement financier » (UTRF) dans les textes. | [V] |

**Conséquence pour la documentation :** écrire « ANRF (ex-UTRF) » et non « UTRF » seul. Le `MASTER_PROMPT_PFA_AML.md` utilise encore « UTRF » ; à mettre à jour (voir section 10).

### 2.2 Ce que la loi dit, et ne dit pas, sur les seuils

Dans le texte consolidé relu :

- **Aucun seuil général de déclaration de soupçon** n'existe (art. 9). La déclaration porte sur le soupçon, quel que soit le montant.
- Des seuils chiffrés apparaissent uniquement à l'art. 5 pour des catégories précises : **30 000 MAD** pour les opérations financières des clients de casinos et **150 000 MAD** pour les opérations en espèces des négociants en pierres et métaux précieux. Ils conditionnent l'application des mesures de vigilance pour ces catégories. **Ils ne s'appliquent pas aux dépôts bancaires** et ne sont pas utilisés dans le projet.
- Les déclarations systématiques (art. 9.1) dépendent de conditions fixées par l'autorité. Leur seuil éventuel n'a **pas été vérifié**.

**Règle du projet :** le paramètre `REPORTING_THRESHOLD` (défaut **100 000 MAD**) est une **hypothèse de simulation [H]**. Il représente un déclencheur que le fraudeur simulé cherche à éviter (seuil interne de surveillance ou seuil supposé). **Il ne doit jamais être présenté comme une obligation légale marocaine.** Si une source officielle fournit un seuil réel, il sera cité avec le texte, l'article et la date, puis comparé à la valeur de simulation.

### 2.3 Sources GAFI utilisées

| Source | Ce qui a été relu | Utilité pour le catalogue | Statut |
| --- | --- | --- | --- |
| GAFI et Groupe Egmont, *Concealment of Beneficial Ownership*, 18 juillet 2018 (R4) | Page officielle de la publication et **annexe E complète** (27 groupes d'indicateurs, tirés de 106 études de cas) | Base des signaux « sociétés écran » et « flux circulaires » (voir 4.4 et 4.5). L'annexe E cite notamment : transit exclusif de fonds sans création de richesse, absence de personnel, absence de cotisations et d'impôts, solde proche de zéro malgré des flux fréquents, longue inactivité suivie d'une hausse soudaine, nombreuses opérations avec peu de destinataires, transactions « cycliques » (entrées et sorties de taille similaire avec les mêmes comptes, dites *round-robin*). | **[V]** |
| GAFI, *Professional Money Laundering*, 26 juillet 2018 (R6) | Page officielle de la publication et **résumé exécutif**. Le corps du rapport n'a pas pu être téléchargé (blocage anti-robot du site) : il n'a **pas été relu**. | Le résumé exécutif confirme que les blanchisseurs professionnels fournissent notamment la création de sociétés, des prête-noms, le recrutement et la gestion de réseaux de passeurs d'espèces ou de **money mules**, la gestion de comptes et la création de comptes financiers. Base du scénario « comptes relais ». | **[V]** pour le résumé exécutif ; détails du corps du rapport **[À vérifier]** |
| GAFI, *The Misuse of Corporate Vehicles, including Trust and Company Service Providers*, octobre 2006 (R5) | Référence bibliographique seulement (le texte n'a pas été relu) | Repère historique sur l'usage de sociétés écran. **Aucune affirmation du catalogue ne s'appuie sur ce rapport.** | Existence **[V]** ; contenu **[À vérifier]** |
| Recommandations du GAFI (adoptées le 16 février 2012, mises à jour régulièrement) | Table des recommandations de la version courante | Numérotation retenue : **R.10** vigilance à l'égard de la clientèle ; **R.20** déclaration des opérations suspectes ; **R.24** transparence et bénéficiaires effectifs des personnes morales ; **R.25** transparence et bénéficiaires effectifs des constructions juridiques. Les anciennes numérotations d'avant 2012 (par exemple R.5, R.13) ne sont **pas** utilisées. | **[V]** (page officielle fatf-gafi.org et documents concordants) |

> Les rapports du GAFI décrivent des **méthodes et des indicateurs**. Ils ne fournissent pas de valeurs chiffrées à simuler. Les plages de paramètres de ce document sont donc des hypothèses **[H]**.

### 2.4 Références marocaines complémentaires

| Source | Ce qui a été vérifié | Statut |
| --- | --- | --- |
| Bank Al-Maghrib, page « Rôle de Bank Al-Maghrib dans le cadre du dispositif LBC-FT » (R12) | BAM est l'autorité de contrôle du secteur bancaire en matière de LBC-FT (loi 43-05 et loi 103-12, art. 96 et 97). Textes de vigilance listés : **circulaire n° 5/W/2017** relative à l'obligation de vigilance (modifiée par la circulaire 3/W/2019) ; **directive n° 2/W/2019** (4 novembre 2019) sur l'identification et la connaissance des relations d'affaires, clients occasionnels et bénéficiaires effectifs ; **directive n° 3/W/2019** (4 novembre 2019) sur l'approche fondée sur les risques ; **directive n° 6/W/2021** sur l'application à l'échelle du groupe ; lettre circulaire n° 1/W/2020 (ouverture de comptes à distance). BAM indique aussi assurer, avec l'ANRF, le suivi du dénouement des opérations déclarées et de leur typologie. | **[V]** pour la liste et le rôle |
| Contenu des textes de BAM ci-dessus | Les fichiers PDF de la circulaire 3/W/2019 et de la directive 2/W/2019 sont des **scans sans texte exploitable** : leur contenu n'a **pas pu être relu**. Aucun seuil de BAM n'est donc cité. | **[À vérifier]** (lecture manuelle des PDF) |
| Amendement de la circulaire 5/W/2017 | Le Comité des établissements de crédit a émis un avis favorable le 22 octobre 2026 sur un amendement en lien avec les évolutions récentes des standards du GAFI (communiqué de BAM, R13). Le texte publié n'a pas été consulté. | Annonce **[V]** ; contenu **[À vérifier]** |
| GAFI, rapport d'évaluation mutuelle du Maroc (MENAFATF), avril 2019 (R14) | Publication officielle sur fatf-gafi.org : le rapport existe et évalue le Maroc sur les 40 Recommandations et 11 résultats immédiats. Le contenu détaillé (notes, menaces) n'a pas été relu. | Existence **[V]** ; contenu **[À vérifier]** |
| Statut du Maroc auprès du GAFI | Inscrit sur la liste des juridictions sous surveillance renforcée (« liste grise ») en **février 2021**, retiré en **février 2023** après la réunion plénière du GAFI des 20 au 24 février 2023. Plusieurs sources concordantes (fiche du Basel Institute on Governance, agence MAP, déclaration du GAFI du 24 février 2023 citée par des tiers). | **[V]** (confirmation directe sur fatf-gafi.org recommandée avant le rapport final) |
| ACAPS, *Typologies de blanchiment de capitaux et de financement du terrorisme dans le secteur des assurances*, janvier 2022 (R15) | Guide d'un superviseur marocain, enrichi de cas relevés par l'ANRF. Il porte sur l'assurance, **pas sur la banque** : cité comme exemple de format de typologies marocaines, non utilisé pour les scénarios. | Existence **[V]** |
| AMMC, *Guide LBC/FT*, novembre 2022 (R2) | Guide du superviseur du marché des capitaux. Lecture détaillée **non effectuée** ; hors périmètre bancaire. | **[À vérifier]** si utile |

> **Limite à retenir.** Je n'ai trouvé aucun texte vérifié qui impose un seuil monétaire bancaire pour la déclaration de soupçon. Ce n'est pas la preuve qu'il n'existe aucun seuil dans les circulaires de BAM, dont le contenu n'a pas pu être lu : la section 2.2 reste donc valable pour la **loi**, et `REPORTING_THRESHOLD` reste une hypothèse.

---

## 3. Lecture commune : trois étapes du blanchiment

Le modèle classique en trois étapes (placement, empilement/layering, intégration) sert de grille de lecture pour situer les scénarios.

| Étape | Idée | Scénarios du projet |
| --- | --- | --- |
| Placement | Introduire du liquide dans le système financier | Fractionnement ; comptes relais (dépôts via des tiers) |
| Layering | Multiplier les mouvements pour brouiller l'origine | Layering ; comptes relais ; sociétés écran |
| Intégration | Faire revenir l'argent sous une apparence légitime | Flux circulaires (fausses factures) ; sociétés écran |

Un même cas réel combine souvent plusieurs scénarios. Pour le projet, **chaque cas simulé suit un seul scénario principal** (champ `scenario` de la table `labels`), afin de mesurer la détection par typologie. Les scénarios combinés sont renvoyés à des extensions éventuelles (section 10).

---

## 4. Les cinq scénarios

Conventions : `T` = `REPORTING_THRESHOLD` [H, défaut 100 000 MAD]. Les valeurs de paramètres sont par défaut **[H]**.

### 4.1 Fractionnement (structuring / smurfing)

**Description.** Un client ou un groupe de clients découpe une grosse somme en espèces en nombreux dépôts de montants juste inférieurs au déclencheur `T`, pour éviter de déclencher une surveillance liée au montant. Plusieurs comptes du même groupe (« smurfs ») peuvent être utilisés.

**Fonctionnement simulé.**

1. Un groupe de `n_accounts_in_group` comptes est créé, rattaché à un compte collecteur.
2. Sur une fenêtre de `window_days` jours, chaque compte effectue des dépôts en espèces (`channel = cash_deposit`) de montant `T × u`, où `u` suit une loi uniforme entre les bornes du niveau de sophistication.
3. Les fonds sont ensuite transférés vers le compte collecteur (`transfer`) après un délai `consolidation_delay_days`.
4. En sophistication élevée, des dépôts de montants ordinaires et des opérations normales sont mélangés aux dépôts fractionnés.

**Signaux observables.**

| Signal | Variable associée (dictionnaire des variables) | Remarque |
| --- | --- | --- |
| Beaucoup de dépôts en espèces sur 24 h et 7 jours | Nombre et cumul sur 1 h, 24 h, 7 j ; part du canal espèces | Vitesse de dépôt incohérente avec le profil |
| Montants concentrés juste sous `T` | Part des montants dans les 10 % sous `T` | Signal central, exigé par le cahier des charges |
| Cumul glissant supérieur à `T` malgré des dépôts unitaires inférieurs | Cumul glissant 7 j / `T` | Distingue le fractionnement d'un dépôt isolé |
| Dépôts successifs dans plusieurs villes | Nombre de villes distinctes (champ `city`) | Variable à ajouter au dictionnaire |
| Regroupement des fonds vers un même compte | Fan-in du compte collecteur ; contreparties distinctes | Signal de graphe |
| Ratio montant / moyenne historique du compte | Ratio montant / profil | Dépôts atypiques pour un étudiant ou un salarié |

**Paramètres à simuler.**

| Paramètre | Sens | Plage | Défaut [H] |
| --- | --- | --- | --- |
| `n_accounts_in_group` | Comptes utilisés | 1 à 5 | 2 |
| `deposits_per_account` | Dépôts par compte sur la fenêtre | 4 à 30 | 10 |
| `amount_fraction_range` | Montant en fraction de `T` | faible : 0,90 à 0,99 ; moyen : 0,75 à 0,99 ; élevé : 0,50 à 0,99 | selon niveau |
| `window_days` | Durée de l'opération | 3 à 30 | 14 |
| `n_cities` | Villes de dépôt | 1 à 4 | 2 |
| `consolidation_delay_days` | Délai avant regroupement | 0 à 10 | 3 |
| `normal_mix_ratio` | Part d'opérations normales mêlées | 0 à 0,7 | selon niveau |

**Confusions possibles (faux positifs).** Un commerçant ou une entreprise qui dépose régulièrement ses recettes en espèces ; des dépôts proches d'un montant rond (loyer, scolarité). Le simulateur doit inclure ces cas normaux.

### 4.2 Layering (empilement)

**Description.** Des fonds illicites traversent une chaîne de comptes intermédiaires en des délais courts, avec des prélèvements de commission, afin de brouiller leur origine. Le scénario correspond à la dissimulation du « mouvement » des biens visée à l'art. 574-1 (voir 2.1).

**Fonctionnement simulé.**

1. Un compte source reçoit un montant initial `initial_amount`.
2. Le montant traverse une chaîne de `chain_length` comptes intermédiaires. À chaque saut, un délai `hop_delay` s'écoule et une commission `fee_rate` est prélevée.
3. Les fonds arrivent sur un compte final, souvent via un virement international.
4. En sophistication moyenne ou élevée, la chaîne se scinde en plusieurs branches parallèles qui se rejoignent.

**Signaux observables.**

| Signal | Variable associée | Remarque |
| --- | --- | --- |
| Temps très court entre une entrée et la sortie suivante | Délai moyen entrée → sortie | Variable exigée par le cahier des charges |
| Ratio sorties / entrées proche de 1 (moins la commission) | Ratio entrées/sorties sur 24 h | Compte « de passage » |
| Chaîne de comptes avec montants décroissants | Profondeur et vitesse de chaîne (graphe) | Signal de graphe |
| Montants proches d'un saut à l'autre | Écart relatif de montant entre entrée et sortie | Variable à ajouter |
| Usage de `international_transfer` en fin de chaîne | Part du canal international | |

**Paramètres à simuler.**

| Paramètre | Sens | Plage | Défaut [H] |
| --- | --- | --- | --- |
| `chain_length` | Intermédiaires | 3 à 8 (cahier des charges) | 5 |
| `hop_delay_minutes` | Délai par saut | faible : 5 à 60 ; moyen : 30 à 360 ; élevé : 60 à 2 880 (aléatoire) | selon niveau |
| `fee_rate_per_hop` | Commission prélevée par saut | 0,5 % à 3 % | 1 % |
| `initial_amount_multiple` | Montant initial, en multiples de `T` | 0,5 à 10 | 3 |
| `n_parallel_branches` | Branches parallèles | 1 à 3 | 1 (faible) ; 2 (moyen) ; 3 (élevé) |
| `international_exit_prob` | Probabilité de sortie internationale | 0 à 0,6 | 0,2 |

**Confusions possibles.** Un virement rapide entre comptes personnels d'une même famille ; un paiement de fournisseur qui transite par plusieurs entités d'un même groupe.

### 4.3 Comptes relais (mule accounts)

**Description.** Des comptes (souvent de particuliers recrutés) reçoivent de nombreux virements entrants, puis retransmettent l'essentiel en quelques heures, ou retirent les fonds en espèces. Le GAFI (R6) décrit le recrutement et la gestion de money mules comme un service fourni par les blanchisseurs professionnels.

**Fonctionnement simulé.**

1. Un réseau de `n_mules` comptes est créé, avec des clients de type `student` ou `salaried` dont l'activité normale est faible.
2. Chaque compte relais reçoit `n_inbound_sources` virements de sources différentes.
3. Après un délai `forward_delay_hours`, il retransmet `forward_ratio` du montant reçu vers 1 à 3 comptes destinataires ou le retire en espèces (`cash_withdrawal`).
4. En sophistication élevée, le compte relais garde une activité normale (achats par carte, petits virements) pour se confondre avec un client ordinaire.

**Signaux observables.**

| Signal | Variable associée |
| --- | --- |
| Nombreuses contreparties entrantes distinctes sur une courte période | Contreparties distinctes ; fan-in |
| Retransmission d'une grande part des fonds en quelques heures | Délai moyen entrée → sortie ; ratio entrées/sorties sur 24 h |
| Activité soudaine sur un compte jusque-là peu actif | Ratio montant / moyenne historique ; règle « dormant puis actif » |
| Retraits en espèces après réception de virements | Part du canal espèces |
| Plusieurs comptes relais partageant les mêmes destinataires | Communautés et centralité (graphe) |

**Paramètres à simuler.**

| Paramètre | Sens | Plage | Défaut [H] |
| --- | --- | --- | --- |
| `n_mules` | Comptes relais par réseau | 3 à 20 | 8 |
| `n_inbound_sources` | Sources entrantes par compte | 5 à 30 | 12 |
| `forward_ratio` | Part retransmise | 0,80 à 0,98 | 0,90 |
| `forward_delay_hours` | Délai de retransmission | faible : 0,5 à 6 ; moyen : 2 à 24 ; élevé : 6 à 72 | selon niveau |
| `n_destinations` | Destinataires finaux | 1 à 3 | 2 |
| `cash_out_share` | Part sortie en espèces | 0 à 0,6 | 0,3 |
| `account_age_days` | Âge du compte au début | 10 à 365 | 60 |
| `normal_mix_ratio` | Activité normale conservée | 0 à 0,8 | selon niveau |

**Confusions possibles.** Un étudiant qui reçoit des virements familiaux ponctuels ; une association ou une cagnotte familiale qui centralise des contributions puis redistribue.

### 4.4 Flux circulaires (round-tripping)

**Description.** L'argent quitte un compte d'origine, traverse des intermédiaires (souvent des sociétés, avec de fausses factures) et revient à l'origine, créant une apparence d'activité commerciale ou de revenu légitime. C'est un cas de « justification mensongère de l'origine » au sens de l'art. 574-1 (voir 2.1). L'annexe E du rapport GAFI/Egmont (R4) décrit ce comportement comme des transactions « cycliques » : entrées et sorties de taille similaire, échangées avec les mêmes comptes, les fonds sortants revenant avec peu de perte (dites *round-robin*).

**Fonctionnement simulé.**

1. Un cycle de `cycle_length` comptes est constitué, dont plusieurs sont de type `company`.
2. Un montant initial circule le long du cycle par virements (`transfer`), chaque transaction imitant le paiement d'une facture.
3. L'argent revient au compte d'origine avec une perte `loss_per_loop`.
4. Le cycle se répète `n_repeats` fois sur `period_days` jours.

**Signaux observables.**

| Signal | Variable associée |
| --- | --- |
| Cycle fermé dans le graphe de transactions | Détection de cycles (graphe) |
| Montants entrants et sortants quasi égaux sur la période | Ratio entrées/sorties cumulé sur 7 j et plus |
| Montants ronds ou répétitifs entre les mêmes contreparties | Variable à ajouter : répétition de montants par paire de comptes |
| Peu de contreparties distinctes mais gros volumes | Contreparties distinctes ; fan-in / fan-out |
| Aucun lien avec l'activité économique normale du client | Ratio montant / profil |

**Paramètres à simuler.**

| Paramètre | Sens | Plage | Défaut [H] |
| --- | --- | --- | --- |
| `cycle_length` | Comptes dans le cycle | 3 à 6 | 4 |
| `n_companies_in_loop` | Sociétés dans le cycle | 2 à 5 | 3 |
| `loss_per_loop` | Perte par tour | 0 % à 5 % | 2 % |
| `n_repeats` | Répétitions du cycle | 1 à 5 | 2 |
| `period_days` | Durée totale | 7 à 60 | 30 |
| `round_amount_share` | Part de montants ronds | 0 à 1 | faible : 0,8 ; moyen : 0,4 ; élevé : 0,1 |
| `loop_delay_days` | Délai entre étapes | 0 à 10 | selon niveau |

**Limite du contrat v1.** Le contrat ne contient pas de champ « objet de facture » : l'effet « fausse facture » n'est donc modélisé que par la forme des montants et des contreparties. À signaler dans `docs/simulator_assumptions.md`.

**Confusions possibles.** Des paiements croisés légitimes entre deux entreprises partenaires, ou des remboursements entre amis.

### 4.5 Sociétés écran (shell companies)

**Description.** Des sociétés sans activité économique réelle reçoivent et émettent de gros flux. Elles servent à faire transiter des fonds et à masquer le bénéficiaire effectif. Le rapport GAFI/Egmont (R4) décrit le recours à des prête-noms et à des montages complexes ; l'art. 4 de la loi 43-05 impose de comprendre la structure de propriété et de vérifier le bénéficiaire effectif (voir 2.1).

**Fonctionnement simulé.**

1. Un groupe de `n_shells` comptes de type `company` est créé, avec un historique court ou dormant.
2. Chaque société reçoit des flux importants (`inflow_multiple` fois la médiane d'une entreprise normale) de peu de contreparties.
3. Elle ne génère **aucune sortie de type salaire ou charges courantes** : les sorties sont des virements de gros montants vers d'autres sociétés ou à l'international.
4. En sophistication élevée, quelques sorties « de façade » (petites dépenses régulières) sont ajoutées pour imiter une activité normale.

**Signaux observables.**

| Signal | Variable associée |
| --- | --- |
| Flux très élevés par rapport aux entreprises comparables | Cumul sur 24 h et 7 j ; ratio montant / profil du type `company` |
| Très peu de contreparties distinctes | Contreparties distinctes |
| Absence de sorties régulières de type paie | Part de sorties petites et régulières ; variable « sorties de type paie » à ajouter |
| Entrées et sorties presque équivalentes | Ratio entrées/sorties sur 24 h |
| Activité qui démarre brutalement après une période dormante | Règle « dormant puis actif » |
| Plusieurs sociétés partageant les mêmes contreparties | Communautés (graphe) |

> Les signaux ci-dessus recoupent des indicateurs de l'annexe E du rapport GAFI/Egmont (R4) : exclusivement des opérations de transit sans création de richesse, absence de personnel, absence de cotisations et d'impôts, solde proche de zéro malgré des flux fréquents, longue inactivité suivie d'une hausse soudaine, nombreuses opérations avec peu de destinataires. Le contrat v1 n'ayant pas de solde, le « solde proche de zéro » est approché par l'écart cumulé entre entrées et sorties.
>
> Les indicateurs du GAFI liés à la propriété (même mandataire pour de nombreuses sociétés, prête-noms) **ne sont pas observables** avec le contrat v1, qui n'a pas de champ de bénéficiaire effectif. Le projet ne les simule pas directement ; le comportement des flux sert de substitut.

**Paramètres à simuler.**

| Paramètre | Sens | Plage | Défaut [H] |
| --- | --- | --- | --- |
| `n_shells` | Sociétés écran par groupe | 2 à 10 | 4 |
| `inflow_multiple` | Flux par rapport à la médiane des entreprises | 3 à 50 | 10 |
| `n_distinct_counterparties` | Contreparties | 2 à 10 | 4 |
| `payroll_like_outflow_share` | Part de sorties de type paie | 0 à 0,2 | faible : 0 ; moyen : 0,05 ; élevé : 0,15 |
| `international_share` | Part de virements internationaux | 0 à 0,7 | 0,3 |
| `dormancy_days` | Période dormante avant le pic | 0 à 90 | 30 |
| `facade_activity_ratio` | Opérations de façade | 0 à 0,5 | selon niveau |

**Confusions possibles.** Une société holding, une société nouvellement créée avec un premier gros contrat, une entreprise saisonnière.

---

## 5. Niveaux de sophistication

Les trois niveaux sont `low` (faible), `medium` (moyen) et `high` (élevé), selon le cahier des charges. Ils servent à mesurer la détection par niveau et à tester la robustesse (test adversarial de la semaine 6).

| Niveau | Principe | Effet sur la détectabilité attendue |
| --- | --- | --- |
| **Faible** | Comportement régulier et évident : montants proches d'un seuil, délais courts, chaînes simples, aucun mélange avec l'activité normale. | Très détectable par des règles simples. |
| **Moyen** | Variation modérée des montants et délais ; une partie de l'activité normale est mêlée ; structures un peu plus complexes. | Détectable par règles + ML ; le recall dépend des variables de vitesse. |
| **Élevé** | Montants et délais aléatoires, mélange important avec l'activité normale, structures ramifiées, imitation du profil du client. | Difficile ; met à l'épreuve les variables de graphe et le ML. |

| Scénario | Faible | Moyen | Élevé |
| --- | --- | --- | --- |
| Fractionnement | `amount_fraction` 0,90 à 0,99 ; 1 compte ; 0 % de mélange | 0,75 à 0,99 ; 2 à 3 comptes ; 30 % | 0,50 à 0,99 ; jusqu'à 5 comptes, plusieurs villes ; 60 % |
| Layering | Délai 5 à 60 min ; 1 branche | 30 à 360 min ; 2 branches | 60 à 2 880 min aléatoires ; 3 branches |
| Comptes relais | Retransmission en 0,5 à 6 h ; aucun mélange | 2 à 24 h ; 40 % d'activité normale | 6 à 72 h ; 70 % d'activité normale |
| Flux circulaires | 80 % de montants ronds ; cycle de 3 | 40 % ; cycle de 4 à 5 | 10 % ; cycle de 5 à 6, contreparties réelles mêlées |
| Sociétés écran | 0 % de sorties de type paie ; peu de contreparties | 5 % ; contreparties modérées | 15 % ; activité de façade |

Toutes les valeurs de ce tableau sont des hypothèses **[H]**. Elles seront figées dans `config/simulator.yaml` et justifiées dans `docs/simulator_assumptions.md`.

---

## 6. État de l'art : règles, apprentissage automatique, graphes

Trois sources principales, relues pour ce document.

**Règles.** La thèse de B. Oztas (Université de Bournemouth, 2025), accompagnée de travaux sur des entretiens avec des spécialistes AML, décrit les systèmes de surveillance à règles comme peu efficaces, notamment à cause d'un taux de faux positifs élevé (R10). Les règles restent néanmoins transparentes, faciles à auditer et nécessaires comme **référence** (baseline). **Choix du projet :** une couche de règles explicables (fractionnement, entrée-sortie rapide, dormant puis actif, canal à risque), servant de point de comparaison.

**Apprentissage automatique.** Weber et al. (2019, atelier KDD) comparent régression logistique, forêt aléatoire, perceptron multicouche et réseaux convolutifs de graphes sur le jeu de données Elliptic (transactions Bitcoin étiquetées). Dans leurs expériences, la **forêt aléatoire** donne les meilleurs résultats, et les auteurs invitent à combiner méthodes classiques et méthodes de graphe (R8). Altman et al. (NeurIPS 2023) comparent des arbres de gradient (GBT) et des réseaux de graphes sur des jeux synthétiques de leur générateur AMLworld, et observent que les étiquettes d'un jeu synthétique sont complètes, ce qui n'est jamais le cas dans des données réelles (R7). **Choix du projet :** Isolation Forest (non supervisé) et XGBoost (supervisé, de la même famille que les arbres de gradient), avec découpage temporel strict.

**Graphes.** Les graphes de transactions permettent de repérer des cycles, des structures de type fan-in / fan-out et des chaînes. Altman et al. rappellent que les cycles sont un indice fort de blanchiment dans la littérature et fournissent des motifs de référence que leur générateur reproduit (R7). Weber et al. montrent l'intérêt des représentations de graphe tout en soulignant que les méthodes classiques restent compétitives (R8). **Choix du projet :** variables de graphe NetworkX (cycles, communautés, centralité, profondeur de chaîne) ajoutées au modèle supervisé, évaluées par étude d'ablation.

**Synthèse pour le projet.** Aucune famille de méthodes ne suffit seule : les règles apportent l'explicabilité, le ML la capacité de combiner des signaux faibles, les graphes la détection de structures que les variables par compte ne voient pas. L'étude d'ablation (règles seules, sans graphe, sans vitesse, ensemble complet) répond à cette question avec les données simulées du projet. **Aucun chiffre de performance de ces articles n'est repris ici**, car leurs jeux de données diffèrent des nôtres.

---

## 7. Jeux de données AML synthétiques publics

Ces jeux servent à **comparer le réalisme** du simulateur et à s'inspirer de motifs (plan B du risque « simulateur irréaliste » de la feuille de route). Ils ne remplacent pas notre simulateur, car aucun ne reflète le contexte marocain. Les licences ont été relues sur les pages officielles des jeux le 2026-11-08.

| Jeu | Description vérifiée | Accès et licence | Limites |
| --- | --- | --- | --- |
| **AMLworld / IBM « Transactions for Anti-Money Laundering » (Altman et al., NeurIPS 2023)** | Données issues d'un modèle multi-agents (banques, particuliers, entreprises) où des acteurs criminels cherchent à blanchir ; chaque transaction porte une étiquette de blanchiment, y compris plusieurs sauts après l'activité illicite. Six jeux : groupes HI (taux illicite plus élevé) et LI (plus faible), en tailles Small, Medium et Large. | Kaggle : `ealtman2019/ibm-transactions-for-anti-money-laundering-aml` (R7). **Données sous licence CDLA-Sharing-1.0** ; le dépôt GitHub IBM/AML-Data est sous Apache-2.0 (R16). | Données hors Maroc ; étiquettes produites par le générateur ; motifs choisis par les auteurs ; volumes très supérieurs à notre machine (de 5 millions à environ 180 millions de transactions selon un résumé tiers). **En cas de redistribution, mêmes conditions de licence.** |
| **SAML-D (Oztas et al., IEEE ICEBE 2023)** | 9 504 852 transactions, 12 variables, 28 typologies (11 normales, 17 suspectes), 15 structures de graphe, **0,1039 % de transactions suspectes** (page Kaggle). Typologies fondées sur des jeux existants, la littérature et des entretiens avec des spécialistes. | Kaggle : `berkanoztas/synthetic-transaction-monitoring-dataset-aml` (R9). **Licence CC BY-NC-SA 4.0** (usage non commercial, attribution, partage dans les mêmes conditions). | Typologies, pays et types de paiement définis par les auteurs ; pas de solde ni de profil client. Un projet tiers rapporte des scores quasi parfaits (PR-AUC proche de 0,99) sur SAML-D, signe que la structure simulée est facile à lire (**indicatif, source tierce**). Usage non commercial : acceptable pour un PFA, à citer dans le rapport. |
| **AMLSim (IBM)** | Simulateur multi-agents qui génère des transactions bancaires synthétiques avec des motifs de blanchiment connus, destiné à tester des modèles et algorithmes de graphe. | GitHub `IBM/AMLSim` (R17). **Licence Apache-2.0.** | Chaîne technique ancienne : Java 8, MASON, Python 3.7 et `networkx==1.11` selon le README ; peu adaptée à notre pile. Ensemble de motifs limité. À utiliser comme **référence de conception**, pas comme dépendance. |
| **AMLGentex (AI Sweden, Handelsbanken, Swedbank)** | Suite open source de génération de données et de benchmark (arXiv 2025), inspirée d'AMLSim, avec jeux par pays, partiellement fondée sur le système de paiement suédois SWISH. | GitHub `aidotse/AMLGentex` (R11). **Code sous Apache-2.0.** **Licence des données non établie** : une question publique sur le dépôt (issue n° 79) demande précisément la licence des jeux générés et des jeux publiés sur Hugging Face, sans réponse trouvée ; l'article arXiv est en CC BY 4.0, ce qui ne vaut pas licence des données. | Jeux récents, calibrés sur un contexte suédois ; **ne pas redistribuer** les données tant que la licence n'est pas confirmée. Utilisation locale du générateur possible (licence du code). |
| *Elliptic (non bancaire, réel)* | Graphe de plus de 200 000 transactions Bitcoin étiquetées, utilisé par Weber et al. (R8). | Licence non vérifiée. | Cryptomonnaie, étiquettes partielles. Cité à titre de comparaison, pas comme jeu synthétique. |

**Ordres de grandeur utiles.** SAML-D contient environ 0,10 % de transactions suspectes (page Kaggle). Un résumé tiers des jeux IBM indique environ 1 transaction de blanchiment pour 800 à 1 950 transactions, soit environ 0,05 % à 0,12 % (**[À vérifier]** sur la page Kaggle). Ces valeurs servent de comparaison pour le taux de transactions suspectes de notre jeu (section 8).

**Limites communes à tous les jeux synthétiques.** Les étiquettes sont celles du modèle qui les génère : un modèle peut retrouver les règles du générateur (cas de SAML-D ci-dessus). Les performances ne se transposent pas telles quelles à des données réelles ; Altman et al. le rappellent, car dans les données réelles beaucoup d'opérations de blanchiment ne sont jamais détectées (R7). Nos résultats seront donc présentés comme **valables sur données simulées uniquement**. Aucun jeu n'est versé dans le dépôt Git (taille et licences) : le dépôt contient des scripts de téléchargement.

---

## 8. Hypothèses de simulation et décision sur les taux et volumes

### 8.1 Hypothèses

| N° | Hypothèse | Valeur par défaut | Statut |
| --- | --- | --- | --- |
| H-01 | `REPORTING_THRESHOLD` | 100 000 MAD | [H] ; non légal (voir 2.2) |
| H-02 | Injection pilotée par un **nombre de cas par scénario** ; taux de comptes et de transactions suspects **mesurés** en sortie | Voir 8.2 | [H] ; décision à valider par les deux membres de l'équipe |
| H-03 | Un scénario principal par cas simulé | Oui | [H] |
| H-04 | Plages des paramètres des fiches 4.1 à 4.5 | Voir fiches | [H] |
| H-05 | Définition des trois niveaux de sophistication | Voir section 5 | [H] |
| H-06 | Équivalence « fausse facture » = forme des montants et contreparties | Voir 4.4 | [H] ; limite du contrat v1 |
| H-07 | Taille moyenne d'un cas : environ 7,6 comptes étiquetés et 63 transactions « scénario » | Estimation avec les paramètres par défaut | [H] ; à recalculer avec le vrai simulateur |

### 8.2 Décision sur le taux de cas suspects et les volumes

**Ce que disent les documents du projet.** Le MASTER_PROMPT retient 5 000 clients, environ 400 000 transactions sur 90 jours et environ 0,5 % de comptes impliqués, avec la contrainte « moins de 1 % de comptes suspects » dans la question centrale. La feuille de route retient environ 0,1 % de « cas suspects » et propose, à titre d'exemple, 10 000 clients et environ 1 million de transactions. Elle prévoit aussi le risque « trop peu de cas suspects » avec la parade « augmenter le taux de cas, pondérer les classes, rapporter les intervalles ».

**Constat chiffré** (calcul avec les tailles de cas de l'hypothèse H-07) :

| Profil | Taux de comptes | Comptes suspects | Cas au total | Cas par scénario |
| --- | --- | --- | --- | --- |
| 5 000 clients, 0,5 % | 0,5 % | 25 | environ 3 | moins de 1 |
| 10 000 clients, 0,5 % | 0,5 % | 50 | environ 7 | environ 1,3 |
| 10 000 clients, 0,1 % | 0,1 % | 10 | environ 1 | environ 0,3 |

Avec les tailles de cas du catalogue, **0,5 % de 5 000 comptes ne permet pas d'injecter un seul cas de chacun des cinq scénarios**, et 0,1 % de 10 000 comptes donne environ un cas au total. Aucune évaluation par typologie n'est possible à ces taux, même avec trois graines.

**Les deux chiffres ne mesurent pas la même chose.** Les jeux publics comparables expriment leur taux en **transactions** (SAML-D : 0,1039 % ; jeux IBM : environ 0,05 à 0,12 %). Avec les tailles de cas du catalogue, un taux de **comptes** de 0,5 % correspond à environ **0,04 à 0,05 %** des transactions, soit le même ordre de grandeur que ces références. Le « 0,1 % » de la feuille de route se lit donc comme un taux de transactions, pas de comptes.

**Décision proposée** (à valider par les deux membres de l'équipe, car elle modifie le contrat de configuration) :

| Code | Décision |
| --- | --- |
| D-1 | **Unité** : le taux de comptes est le nombre de comptes ayant un rôle dans la table `labels` divisé par le nombre de comptes. Le **taux de transactions** (transactions « scénario » sur total) est calculé et rapporté en plus. |
| D-2 | **Pilotage** : le simulateur reçoit un nombre de cas par scénario (et par niveau), pas un pourcentage. Les deux taux deviennent des sorties de contrôle, avec une **vérification automatique que le taux de comptes reste inférieur à 1 %** (contrainte de la question centrale). |
| D-3 | **Profil `light`** (développement, tests, démonstration) : 5 000 clients, environ 400 000 transactions, 90 jours, **1 cas par scénario**, soit 5 cas, environ 38 comptes, **0,76 % des comptes** et environ 0,08 % des transactions. Usage fonctionnel seulement : aucune métrique par typologie n'est interprétée sur ce profil. |
| D-4 | **Profil `full`** (évaluation finale) : 20 000 clients, environ 1,6 million de transactions (même densité de 80 transactions par client que `light`), 90 jours, **1 cas par couple scénario × niveau**, soit 15 cas, environ 114 comptes, **0,57 % des comptes** et environ 0,06 % des transactions. L'exemple de 10 000 clients de la feuille de route ne permet pas de couvrir les 15 couples en restant sous 1 % (il en faudrait environ 11 400 pour tenir à 1 % et 14 000 pour tenir à 0,8 %). |
| D-5 | **Répétitions** : au moins 3 graines (exigence du MASTER_PROMPT), **5 graines visées** pour l'évaluation finale. |
| D-6 | **Statistiques** : rapports par typologie avec **intervalle de confiance de Wilson à 95 %** ; rapports par niveau de sophistication **agrégés sur les typologies**. |

Avec le profil `full` et 5 graines, chaque scénario cumule 15 cas (3 niveaux × 5 graines) et chaque couple scénario × niveau en cumule 5. Exemple de précision (calcul de Wilson) : un recall observé de 4 sur 5 donne un intervalle de 38 % à 96 %, 16 sur 20 donne 58 % à 92 %, 24 sur 30 donne 63 % à 90 %. L'équipe doit donc présenter les résultats par typologie comme **indicatifs**, avec leurs intervalles.

**Sensibilité** (diagnostic, pas résultat principal) : tester aussi 1 cas par couple dans un profil à 10 000 clients (environ 1,1 % des comptes, donc hors contrainte) pour mesurer l'effet du taux sur la stabilité du modèle, en l'indiquant explicitement.

**Charge de calcul** (indicatif) : rejouer 400 000 événements à 100 événements par seconde dure environ 67 minutes ; 1,6 million à 500 par seconde dure environ 53 minutes. La génération hors ligne en Parquet n'est pas le goulot ; le rejeu intégral du profil `full` est à réserver à la fenêtre de test.

**À aligner dans les documents du dépôt après accord** : `MASTER_PROMPT_PFA_AML.md` (ligne 54 : volumes et 0,5 %), `Roadmap_PFA_Detection_Blanchiment.md` (ligne 50 : « environ 0,1 % » ; ligne 96 : 10 000 clients et environ 1 million de transactions).

---

## 9. Références

Toutes consultées le 8 novembre 2026, sauf mention contraire.

**Sources juridiques et réglementaires marocaines**

- **R1.** Loi n° 43-05 relative à la lutte contre le blanchiment de capitaux, version consolidée après loi n° 12-18 (BO du 2 septembre 2021), ministère de la Justice : <https://cnclt.justice.gov.ma/wp-content/uploads/2023/06/Loi-43-05-actualisee-et-consolidee.pdf>
- **R2.** AMMC, *Guide LBC/FT*, novembre 2022 (lecture détaillée non effectuée) : <https://cnasnu.justice.gov.ma/wp-content/uploads/2023/01/AMMC_Guide-AMMC-LBC-_-Novembre-2022-1.pdf>
- **R12.** Bank Al-Maghrib, « Rôle de Bank Al-Maghrib dans le cadre du dispositif LBC-FT » : <https://www.bkam.ma/fr/Supervision-bancaire/Controle-micro-prudentiel/Integrite-financiere/Role-de-bank-al-maghrib-dans-le-cadre-du-dispositif-lbc-ft>
- **R13.** Bank Al-Maghrib, communiqué de presse de la réunion du Comité des établissements de crédit du 22 octobre 2026 : <https://www.bkam.ma/fr/content/download/852849/9198919/CdP_CEC_2210_Fr.pdf>
- **R14.** GAFI / MENAFATF, *Morocco Mutual Evaluation Report*, avril 2019 : <https://www.fatf-gafi.org/en/publications/Mutualevaluations/Mer-morocco-2019.html>
- **R15.** ACAPS, *Typologies de blanchiment de capitaux et de financement du terrorisme dans le secteur des assurances*, janvier 2022 : <https://cnasnu.justice.gov.ma/wp-content/uploads/2022/02/acaps_guide_typologies_lbcft-2022.pdf>

**Sources GAFI**

- **R3.** GAFI, *Les Recommandations du GAFI* (page officielle, adoptées le 16 février 2012, mises à jour régulièrement) : <https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations>
- **R4.** GAFI et Groupe Egmont, *Concealment of Beneficial Ownership*, 18 juillet 2018 : <https://www.fatf-gafi.org/content/fatf-gafi/en/publications/Methodsandtrends/Concealment-beneficial-ownership.html> ; annexe E (indicateurs) : <https://egmontgroup.org/wp-content/uploads/2021/10/FATF-Egmont-Concealment-beneficial-ownership-annex-E.pdf>
- **R5.** GAFI, *The Misuse of Corporate Vehicles, including Trust and Company Services Providers*, octobre 2006 (non relu) : <https://fatf-gafi.org/content/dam/fatf-gafi/reports/Misuse%20of%20Corporate%20Vehicles%20including%20Trusts%20and%20Company%20Services%20Providers.pdf.coredownload.inline.pdf>
- **R6.** GAFI, *Professional Money Laundering*, 26 juillet 2018 : page officielle <https://www.fatf-gafi.org/en/publications/methodsandtrends/documents/professional-money-laundering.html> ; résumé exécutif <https://www.fatf-gafi.org/content/dam/fatf-gafi/reports/Professional-Money-Laundering-Executive-Summary.pdf>

**État de l'art et jeux de données**

- **R7.** Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu, *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models*, NeurIPS 2023 (Datasets & Benchmarks) : <https://arxiv.org/abs/2306.16424> ; données : <https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml>
- **R8.** Weber, Domeniconi, Chen, Weidele, Bellei, Robinson, Leiserson, *Anti-Money Laundering in Bitcoin: Experimenting with Graph Convolutional Networks for Financial Forensics*, KDD 2019 Workshop on Anomaly Detection in Finance : <https://arxiv.org/abs/1908.02591>
- **R9.** Oztas, Cetinkaya, Adedoyin, Budka, Dogan, Aksu, *Enhancing Anti-Money Laundering: Development of a Synthetic Transaction Monitoring Dataset*, IEEE ICEBE 2023, pp. 47-54 : <https://eprints.bournemouth.ac.uk/40982> ; jeu SAML-D : <https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring-dataset-aml>
- **R10.** Oztas, B., *Enhancing Transaction Monitoring Controls to Detect Money Laundering Using Machine Learning*, thèse de doctorat, Université de Bournemouth : <https://eprints.bournemouth.ac.uk/41326>
- **R11.** Östman, Callisen et al., *AMLGentex: Mobilizing Data-Driven Research to Combat Money Laundering*, 2025 : <https://arxiv.org/abs/2506.13989> ; code : <https://github.com/aidotse/AMLGentex> ; question sur la licence des données : <https://github.com/aidotse/AMLGentex/issues/79>
- **R16.** IBM, dépôt `AML-Data` (données CDLA-Sharing-1.0, dépôt Apache-2.0) : <https://github.com/IBM/AML-Data>
- **R17.** IBM, dépôt `AMLSim` (Apache-2.0) : <https://github.com/IBM/AMLSim>

---

## 10. Points ouverts et à vérifier

**Résolus lors de cette version (v1.1)** : numérotation des Recommandations du GAFI (R.10, R.20, R.24, R.25) ; URL officielle du rapport *Professional Money Laundering* ; licences d'AMLworld (CDLA-Sharing-1.0), SAML-D (CC BY-NC-SA 4.0), AMLSim (Apache-2.0) et licence du code d'AMLGentex (Apache-2.0) ; statut du Maroc auprès du GAFI ; décision proposée sur les taux et volumes (section 8.2).

**Restent ouverts**

1. **Contenu des textes de Bank Al-Maghrib** (circulaire 5/W/2017 et modificatives, directives 2/W/2019 et 3/W/2019) : les PDF disponibles sont des scans sans texte. Lecture manuelle à faire pour confirmer l'absence ou la présence de seuils chiffrés. Tant que ce n'est pas fait, `REPORTING_THRESHOLD` reste une hypothèse.
2. **Textes d'application de l'art. 9.1** (déclarations systématiques) de la loi 43-05 : non trouvés.
3. **Corps du rapport GAFI *Professional Money Laundering*** : téléchargement bloqué, lecture à faire manuellement pour extraire des indicateurs précis sur les comptes relais.
4. **Rapport d'évaluation mutuelle du Maroc (2019)** et éventuels rapports de suivi : contenu non relu. Une nouvelle évaluation MENAFATF serait prévue en 2026 selon la presse : **[À vérifier]**.
5. **Licence des données AMLGentex** : aucune réponse publique trouvée ; ne pas redistribuer, ou demander aux auteurs.
6. **Décision sur les taux et volumes (section 8.2)** : à valider par les deux membres de l'équipe, puis à reporter dans `MASTER_PROMPT_PFA_AML.md` et `Roadmap_PFA_Detection_Blanchiment.md`. Les tailles de cas (H-07) seront recalculées avec le vrai simulateur.
7. **Articles de loi cités** : ils proviennent du texte officiel consolidé relu le 2026-11-08. Le MASTER_PROMPT demande de ne pas affirmer d'articles ou de seuils sans source ; dans le rapport final, chaque article cité devra rester accompagné de sa source et de sa date de consultation.
8. **Vocabulaire** : remplacer « UTRF » par « ANRF (ex-UTRF) » dans `MASTER_PROMPT_PFA_AML.md` et les documents à venir, après accord de l'équipe.
9. **Scénarios combinés** (par exemple fractionnement suivi de layering) : à décider pour une version ultérieure du simulateur.
10. **Champ « bénéficiaire effectif »** absent du contrat v1 : à discuter avant le gel du contrat (phase 2), car il permettrait de simuler les indicateurs de propriété du GAFI pour les sociétés écran.
11. **Validation** de ce catalogue par le Pr Chergui.
