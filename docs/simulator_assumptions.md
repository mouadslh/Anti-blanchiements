# Hypothèses du simulateur v1

**Projet :** Détection AML en flux (PFA) · **Version :** v1 (brouillon, à valider par l'équipe puis par le Pr Chergui) · **Rédaction :** 9 novembre 2026 · **Phase :** 1 (semaine 1, côté Mounir) · **Ticket :** « Hypothèses du simulateur v1 »

> **Avertissement : données simulées.** Toutes les données du projet (clients, comptes, transactions, étiquettes) sont **générées par notre simulateur**. Aucune donnée bancaire réelle n'est utilisée. Les valeurs de ce document décrivent des **comportements simulés**, pas des statistiques du système bancaire marocain, et pas des obligations légales. Les limites qui en découlent sont décrites à la section 9.

## Comment lire ce document

Ce document répond à une question simple : **« quel monde fictif le simulateur va-t-il fabriquer, et pourquoi ces chiffres ? »** Il sert de référence à la fois pour écrire `config/simulator.yaml` (phase 3) et pour défendre le réalisme du jeu de données devant le jury.

Chaque valeur porte un statut, repris de `docs/typologies.md` :

| Étiquette | Signification |
| --- | --- |
| **[V]** | Vérifié dans une source consultée (lien ou référence donnés). |
| **[H]** | **Hypothèse de simulation** : choix de l'équipe, non démontré par une source. Une justification est donnée. |
| **[À vérifier]** | Information plausible mais non confirmée. Elle ne doit pas être utilisée comme un fait dans le rapport. |

**Aucune valeur chiffrée de la population, des volumes, des montants ou des rythmes ci-dessous n'a de source marocaine.** Elles sont donc toutes **[H]**, sauf mention contraire. Elles sont choisies pour être plausibles, simples à expliquer et faciles à modifier, pas pour reproduire la réalité.

Les hypothèses H-01 à H-07 sont celles de `docs/typologies.md` (section 8.1) et gardent leur numéro. Les nouvelles hypothèses commencent à H-08.

---

## 1. Périmètre et lien avec le contrat de données

Le contrat de données v1 contient neuf champs : `tx_id`, `timestamp`, `source_account_id`, `target_account_id`, `amount`, `currency`, `channel`, `source_customer_type`, `city`. Le simulateur ne peut donc faire varier le comportement que sur ces axes : **qui paie qui, quand, combien, par quel canal, dans quelle ville**.

Ce que le simulateur **ne modélise pas** : solde de compte, objet d'une facture, bénéficiaire effectif, banque de la contrepartie, pays de destination, âge du compte observable dans le flux. Ces absences sont des limites (section 9).

Les étiquettes (scénario, rôle, début, fin, niveau de sophistication) vivent dans la table `labels`, **jamais dans le flux** envoyé à Kafka.

Canaux simulés (`channel`) : `transfer`, `card_payment`, `cash_deposit`, `cash_withdrawal`, `international_transfer`. [H : liste reprise du prompt maître, à confirmer au gel du contrat en phase 2.]

---

## 2. Population

### 2.1 Taille et période

| N° | Hypothèse | Valeur par défaut | Justification | Statut |
| --- | --- | --- | --- | --- |
| H-08 | Taille du profil `light` | 5 000 clients | Valeur du prompt maître ; tient sur un portable avec Kafka, PostgreSQL et Grafana (limite mémoire de 3,5 Gio configurée en phase 0). | [H] |
| H-09 | Taille du profil `full` | 20 000 clients | Plus petit effectif simple qui permet 15 cas (un par scénario × niveau) en restant sous 1 % de comptes suspects (décision D-4, `docs/typologies.md` 8.2). | [H] |
| H-10 | Un client = un compte | Oui | Le contrat n'a qu'un identifiant de compte. Le champ `source_customer_type` est donc porté par le compte. | [H] |
| H-11 | Durée simulée | 90 jours | Valeur du prompt maître ; assez longue pour des fenêtres de 7 jours et un découpage temporel en trois blocs. | [H] |
| H-12 | Date de début | 2027-01-15 (jour 1), fin le 2027-04-14 (jour 90) | Choisie pour que la période contienne un Ramadan et un Aïd el-Fitr (section 5). Ce sont des dates **fictives** de simulation. | [H] |
| H-13 | Comptes externes | Un réservoir de comptes « autres banques » égal à 20 % du nombre de clients (1 000 en `light`) | Les paiements par carte, les virements internationaux et certains virements ont besoin d'une contrepartie qui n'est pas un client. Ces comptes n'ont pas de type client (`source_customer_type` n'existe que pour les comptes émetteurs clients). | [H] |

### 2.2 Répartition des profils

Les quatre profils sont ceux du cahier des charges : salariés, étudiants, commerçants, entreprises.

| Profil (`source_customer_type`) | Part des clients | Clients en `light` | Clients en `full` | Justification |
| --- | --- | --- | --- | --- |
| `salaried` | 55 % | 2 750 | 11 000 | Population majoritaire d'une banque de détail, hypothèse sans source. |
| `student` | 15 % | 750 | 3 000 | Profil peu actif, utile car les comptes relais recrutent souvent ce type de client (`docs/typologies.md` 4.3). |
| `merchant` | 18 % | 900 | 3 600 | Profil à dépôts en espèces fréquents, principale source de confusion avec le fractionnement. |
| `company` | 12 % | 600 | 2 400 | Profil à gros montants, nécessaire pour les flux circulaires et les sociétés écran. |

Statut : **[H]** pour toute la table. Les parts sont **modifiables** dans `config/simulator.yaml` (`population.mix`).

### 2.3 Villes

Le champ `city` est utilisé par le signal « dépôts dans plusieurs villes » du fractionnement. Hypothèse **[H]** : huit villes marocaines à poids décroissants (Casablanca 28 %, Rabat 15 %, Marrakech 12 %, Fès 10 %, Tanger 10 %, Agadir 8 %, Meknès 7 %, Oujda 5 %, soit 95 %, plus 5 % « autre »). Chaque client a une **ville de rattachement** fixe, et 90 % de ses opérations y sont enregistrées ; les 10 % restantes sont réparties dans les autres villes (déplacements). Justification : un client réel opère surtout près de chez lui, ce qui rend le signal « plusieurs villes » significatif. Les poids ne viennent d'aucune statistique officielle.

---

## 3. Comportement normal par profil

### 3.1 Volumes de transactions

Les volumes sont exprimés en **transactions émises par client sur 90 jours** (une transaction est comptée une fois, chez son émetteur, car le contrat ne porte que `source_customer_type`).

| Profil | Transactions émises par client sur 90 jours (moyenne) | Équivalent par jour | Justification |
| --- | --- | --- | --- |
| `salaried` | 62 | environ 0,7 | Paiements par carte réguliers, quelques virements et retraits. |
| `student` | 40 | environ 0,4 | Activité plus faible. |
| `merchant` | 140 | environ 1,6 | Dépôts de recettes et paiements fournisseurs. |
| `company` | 120 | environ 1,3 | Virements fournisseurs et salaires, moins nombreux mais plus gros. |

Moyenne pondérée par la répartition de la section 2.2 : 0,55 × 62 + 0,15 × 40 + 0,18 × 140 + 0,12 × 120 = **79,7 transactions par client**, soit environ **398 500 transactions** pour 5 000 clients (valeur visée : « environ 400 000 » du prompt maître) et environ **1,59 million** pour 20 000 clients. [H : la densité de 80 transactions par client est conservée entre `light` et `full`, comme dans la décision D-4.]

Les nombres de transactions par client suivent une **loi de Poisson** autour de la moyenne du profil, avec un facteur d'hétérogénéité par client (loi gamma, coefficient de variation 0,5) pour que certains clients soient nettement plus actifs que d'autres. [H : sans hétérogénéité, tous les clients d'un profil seraient presque identiques, ce qui rendrait la détection d'anomalies artificiellement facile.]

### 3.2 Montants

Les montants (en MAD, `currency = MAD`) suivent une **loi log-normale** par profil : la médiane donne l'ordre de grandeur, `σ` (écart-type du logarithme) donne la dispersion. Choix **[H]**, justifiés par le fait que les montants bancaires sont positifs, asymétriques et à longue traîne.

| Profil | Médiane (MAD) | `σ` | Part des montants au-dessus de `T` = 100 000 MAD | Part dans la tranche [0,9 `T`, `T`[ |
| --- | --- | --- | --- | --- |
| `salaried` | 400 | 1,0 | pratiquement nulle | pratiquement nulle |
| `student` | 150 | 0,8 | pratiquement nulle | pratiquement nulle |
| `merchant` | 1 200 | 1,1 | environ 0,003 % | environ 0,001 % |
| `company` | 15 000 | 1,3 | environ 7,2 % | environ 1,2 % |

Les deux dernières colonnes sont **calculées** à partir de la loi log-normale choisie (ce ne sont pas des observations). Elles ont une conséquence importante : avec ces paramètres, les entreprises normales font environ 7 % de transactions au-dessus du seuil et environ 1 % juste dessous. Le fractionnement doit donc se distinguer d'un **bruit normal non négligeable**, ce qui est voulu (faux positifs réalistes, voir 3.6).

Cas particuliers **[H]** :

- **Salaire** : virement mensuel d'un compte `company` vers un compte `salaried`, médiane 6 000 MAD, `σ` = 0,4.
- **Virement familial** : un étudiant reçoit en moyenne un virement par mois, médiane 1 500 MAD, `σ` = 0,5.
- **Dépôts de recettes** (commerçants) : montants issus de la loi log-normale du profil, déposés en espèces.

### 3.3 Canaux par profil

Parts des transactions émises par canal (somme de 100 % par ligne). **[H]**.

| Profil | `transfer` | `card_payment` | `cash_withdrawal` | `cash_deposit` | `international_transfer` |
| --- | --- | --- | --- | --- | --- |
| `salaried` | 35 % | 50 % | 10 % | 2 % | 3 % |
| `student` | 25 % | 60 % | 12 % | 2 % | 1 % |
| `merchant` | 20 % | 15 % | 10 % | 50 % | 5 % |
| `company` | 70 % | 10 % | 3 % | 5 % | 12 % |

Mélange global pondéré par les volumes (calcul à partir des tables ci-dessus) : environ 36 % de virements, 33 % de paiements par carte, 9 % de retraits, 18 % de dépôts en espèces et 5 % d'international. Ce sont des **sorties de contrôle** à vérifier dans le rapport de statistiques du simulateur (`python manage.py simulate --report`).

### 3.4 Contreparties

Chaque client a un **petit réseau stable de contreparties**, avec une probabilité de 10 % de nouvelle contrepartie à chaque transaction. **[H]**.

| Profil | Taille du réseau stable |
| --- | --- |
| `salaried` | 8 |
| `student` | 5 |
| `merchant` | 25 |
| `company` | 40 |

Justification : un comportement normal est répétitif (mêmes commerces, mêmes fournisseurs). Les signaux « nombre de contreparties distinctes » et « fan-in » (comptes relais, sociétés écran) n'ont de sens que si le comportement normal a un nombre de contreparties limité et stable.

### 3.5 Rythmes quotidiens et hebdomadaires

| Rythme | Valeur | Statut |
| --- | --- | --- |
| Heure (cartes, retraits, dépôts) | 0 h–6 h : 2 % ; 6 h–12 h : 28 % ; 12 h–18 h : 38 % ; 18 h–24 h : 32 % | [H] |
| Heure (virements d'entreprise) | 85 % entre 9 h et 17 h en jour ouvré | [H] |
| Week-end | Cartes des particuliers × 1,3 ; virements d'entreprise × 0,15 | [H] |
| Commerçants | Dépôts en espèces concentrés le lundi et le samedi (× 1,5 ces jours-là) | [H] |
| Paie | Salaires crédités entre le 25 et le dernier jour du mois | [H] |
| Après la paie | Cartes et retraits des salariés × 1,3 pendant les 5 jours qui suivent le crédit du salaire | [H] |

Justification commune : ces rythmes créent une **saisonnalité intra-semaine et intra-mois** visible dans les fenêtres glissantes de 1 h, 24 h et 7 j. Sans elle, un modèle pourrait confondre un week-end ou un jour de paie avec une anomalie.

### 3.6 Comportements normaux qui ressemblent à du blanchiment (confusions)

Pour mesurer les **fausses alertes**, le simulateur injecte aussi des cas normaux « piégeux » (liste issue des « confusions possibles » de `docs/typologies.md`). Ces cas ne sont **pas étiquetés** comme suspects. **[H]**.

| Confusion | Fréquence simulée | Scénario imité |
| --- | --- | --- |
| Commerçant ou entreprise qui dépose ses recettes en espèces en plusieurs fois par semaine | 100 % des commerçants (comportement de base) | Fractionnement |
| Dépôt proche d'un montant rond (loyer, scolarité) | 3 % des salariés, une fois sur la période | Fractionnement |
| Étudiant qui reçoit un virement familial ponctuel de 5 000 MAD ou plus | 2 % des étudiants | Compte relais |
| Cagnotte familiale ou association qui reçoit plusieurs virements puis redistribue | 0,2 % des clients (environ 10 en `light`) | Compte relais, layering |
| Virements rapides entre comptes personnels d'une même famille | 3 % des salariés | Layering |
| Entreprise nouvellement créée avec un premier gros contrat | 2 % des entreprises | Société écran |
| Paiements croisés légitimes entre deux entreprises partenaires | 1 % des entreprises | Flux circulaire |

Justification : un détecteur évalué sans ces cas normaux « piégeux » aurait un taux de fausses alertes sous-estimé. Les fréquences ne viennent d'aucune source et servent à créer du bruit plausible.

---

## 4. Saisonnalité de la période simulée

La période de 90 jours commence le 2027-01-15 (H-12). Les dates ci-dessous sont des **dates fictives de simulation**, alignées sur les prévisions astronomiques de presse consultées le 2026-11-09.

| Événement | Dates retenues (jour de la simulation) | Statut des dates |
| --- | --- | --- |
| Début du Ramadan | 2027-02-08 (jour 25) | **[À vérifier]** : date **prévisionnelle** donnée par des calculs astronomiques ; la date officielle est fixée par les autorités religieuses. |
| Aïd el-Fitr | 2027-03-09 (jour 54), ou le 10 mars selon la durée du mois | **[À vérifier]** : même réserve. |

Effets simulés, tous **[H]** :

| Période | Effet |
| --- | --- |
| Ramadan, en journée (avant le ftour, vers 18 h) | Volume de cartes et de retraits × 0,6 |
| Ramadan, en soirée et la nuit (18 h–2 h) | Volume × 1,4 |
| 5 jours avant l'Aïd | Cartes et virements des particuliers × 1,5 ; dépôts en espèces des commerçants × 1,3 |
| Jour de l'Aïd et lendemain | Volume × 0,5 (jours chômés) |

Justification : ces effets ajoutent une **dérive de comportement normale** dans le temps, utile pour tester que les modèles ne prennent pas un changement saisonnier pour du blanchiment.

**Conséquence sur le découpage temporel** (voir `docs/evaluation_plan.md`) : avec cette date de début, le Ramadan et l'Aïd tombent dans les jours 25 à 55, donc **dans le bloc d'entraînement** ; le bloc de test (jours 73 à 90) n'en contient pas. C'est un décalage de distribution voulu mais à documenter. Une saisonnalité annuelle (été, rentrée, fêtes de fin d'année) **n'est pas modélisable** sur 90 jours : voir la section 9.

---

## 5. Taux de comptes et de transactions suspects

### 5.1 Deux notions à ne pas confondre

| Notion | Définition | Unité | Usage |
| --- | --- | --- | --- |
| **Proportion de comptes impliqués** | Nombre de comptes ayant un rôle dans la table `labels` (source, intermédiaire, compte relais, société écran, compte collecteur) divisé par le nombre total de comptes. | Comptes | Contrainte de la question centrale : **inférieure à 1 %**. Utilisée pour le pilotage et le contrôle automatique. |
| **Proportion de transactions suspectes** | Nombre de transactions « scénario » (celles que la table `labels` rattache à un cas) divisé par le nombre total de transactions. | Transactions | Comparaison avec les jeux publics : SAML-D, 0,1039 % ; jeux IBM, environ 0,05 % à 0,12 % ([À vérifier] pour IBM, voir `docs/typologies.md` section 7). |

Les deux taux **ne se déduisent pas l'un de l'autre sans la taille d'un cas** : un compte impliqué peut avoir peu ou beaucoup de transactions suspectes. Un taux de comptes de 0,5 % correspond, avec les tailles de cas de H-07, à environ 0,04 % à 0,05 % de transactions suspectes (calcul de `docs/typologies.md` 8.2).

### 5.2 Taille moyenne d'un cas (H-07)

Avec les paramètres par défaut du catalogue, un cas moyen implique environ **7,6 comptes étiquetés** et **63 transactions « scénario »**. [H : estimation à **recalculer avec le vrai simulateur** ; elle dépend des valeurs par défaut de `docs/typologies.md` section 4.]

### 5.3 Profils retenus (décisions D-1 à D-6)

Le simulateur est **piloté par un nombre de cas**, pas par un pourcentage (H-02). Les deux taux sont des **sorties de contrôle**, avec une vérification automatique que le taux de comptes reste inférieur à 1 %.

| Profil | Clients | Transactions (environ) | Cas | Comptes impliqués | Taux de comptes | Transactions suspectes | Taux de transactions |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `light` | 5 000 | 400 000 | 5 (1 par scénario) | environ 38 | **0,76 %** | environ 315 | **0,08 %** |
| `full` | 20 000 | 1,6 million | 15 (1 par scénario × niveau) | environ 114 | **0,57 %** | environ 945 | **0,06 %** |

Le profil `light` sert au développement, aux tests et à la démonstration : **aucune métrique par typologie n'y est interprétée**. Le profil `full` sert à l'évaluation finale, avec au moins 3 graines (5 visées) et des intervalles de Wilson à 95 % (D-5 et D-6).

Les niveaux de sophistication (faible, moyen, élevé) et les paramètres de chaque scénario sont dans la section 6.

---

## 6. Paramètres des scénarios

La **source de référence** des paramètres est `docs/typologies.md`, sections 4 et 5. Cette section en donne le résumé pour que le simulateur et les hypothèses restent lisibles ensemble. Toutes les valeurs sont **[H]** (H-04 et H-05), figées dans `config/simulator.yaml`.

| Scénario | Paramètres clés (valeur par défaut) | Faible | Moyen | Élevé |
| --- | --- | --- | --- | --- |
| **Fractionnement** | 2 comptes, 10 dépôts par compte, fenêtre de 14 jours, 2 villes, regroupement après 3 jours | `amount_fraction` 0,90–0,99 ; 1 compte ; 0 % de mélange | 0,75–0,99 ; 2 à 3 comptes ; 30 % | 0,50–0,99 ; jusqu'à 5 comptes ; 60 % |
| **Layering** | 5 intermédiaires, commission de 1 % par saut, montant initial de 3 `T`, 20 % de sortie internationale | délai 5–60 min ; 1 branche | 30–360 min ; 2 branches | 60–2 880 min ; 3 branches |
| **Comptes relais** | 8 comptes relais, 12 sources entrantes, 90 % retransmis, 2 destinataires, 30 % en espèces, compte de 60 jours | retransmission en 0,5–6 h ; aucun mélange | 2–24 h ; 40 % d'activité normale | 6–72 h ; 70 % d'activité normale |
| **Flux circulaires** | cycle de 4 comptes dont 3 sociétés, perte de 2 % par tour, 2 répétitions, 30 jours | 80 % de montants ronds ; cycle de 3 | 40 % ; cycle de 4 à 5 | 10 % ; cycle de 5 à 6 |
| **Sociétés écran** | 4 sociétés, flux de 10 fois la médiane des entreprises, 4 contreparties, 30 % d'international, 30 jours dormants | 0 % de sorties de type paie | 5 % | 15 % ; activité de façade |

`T` désigne `REPORTING_THRESHOLD` = **100 000 MAD** (H-01). **Ce seuil est une hypothèse de simulation, pas une obligation légale** : la loi 43-05 consolidée ne fixe aucun montant minimal pour la déclaration de soupçon (art. 9, relu le 2026-11-08, voir `docs/typologies.md` 2.2). Les textes de Bank Al-Maghrib, illisibles automatiquement, restent à lire à la main : tant que ce n'est pas fait, le seuil reste une hypothèse.

**Placement des cas dans le temps.** Les cas sont placés dans la période de 90 jours à des dates tirées avec la graine. **Chaque cas doit tenir dans un seul bloc temporel d'évaluation** (règle détaillée dans `docs/evaluation_plan.md`), ce qui borne la durée maximale d'un cas. **[H]**. Voir la question ouverte 3.

**Limite du contrat v1 (H-06).** Il n'y a pas de champ « objet de facture » : l'effet « fausse facture » du flux circulaire n'existe que par la forme des montants et des contreparties. Il n'y a pas non plus de champ « bénéficiaire effectif » : les indicateurs de propriété du GAFI pour les sociétés écran ne sont pas simulés.

---

## 7. Différences entre la feuille de route et le prompt maître

Ces écarts ont été relevés dans `docs/typologies.md` 8.2. Ils sont repris ici avec leur résolution proposée.

| Sujet | Prompt maître (`MASTER_PROMPT_PFA_AML.md`, ligne 54) | Feuille de route (lignes 50 et 96) | Problème | Résolution proposée |
| --- | --- | --- | --- | --- |
| Nombre de clients | 5 000 (profil `light`) | 10 000 (« par exemple ») | Deux tailles pour le jeu de données v1. | 5 000 pour `light`, 20 000 pour `full` (H-08, H-09). Les 10 000 de la feuille de route ne permettent pas de couvrir les 15 couples scénario × niveau en restant sous 1 %. |
| Nombre de transactions | environ 400 000 sur 90 jours | environ 1 million | Densité différente : 80 contre 100 transactions par client. | Garder la densité de 80 transactions par client : 400 000 en `light`, 1,6 million en `full`. |
| Taux de cas suspects | environ 0,5 % de **comptes** impliqués | environ 0,1 % de « cas suspects » | Deux unités différentes (comptes, cas ou transactions), non précisées dans la feuille de route. | Distinguer explicitement taux de comptes et taux de transactions (D-1). Le « 0,1 % » se lit comme un taux de **transactions** (même ordre que SAML-D). |
| Faisabilité du taux | 0,5 % de 5 000 comptes = 25 comptes, soit environ 3 cas | 0,1 % de 10 000 comptes = 10 comptes, soit environ 1 cas | Pas un seul cas par scénario ; aucune évaluation par typologie possible. | Piloter par un **nombre de cas** (D-2), avec contrôle automatique du taux de comptes < 1 %. |
| Durée simulée | 90 jours | non précisée | Écart de précision. | 90 jours (H-11). |

**Hors volumes et taux, mais à signaler** : le prompt maître et la proposition de contrat de Mounir ne nomment pas tous les champs de la même façon (par exemple `transaction_id` contre `tx_id`), et le prompt maître écrit « UTRF » là où le texte de loi consolidé désigne l'ANRF. Ces deux points sont traités à part (phase 2 et `docs/typologies.md` section 10).

**Après accord de l'équipe**, il faudra aligner `MASTER_PROMPT_PFA_AML.md` (ligne 54) et `Roadmap_PFA_Detection_Blanchiment.md` (lignes 50 et 96) sur cette résolution.

---

## 8. Tableau récapitulatif des hypothèses

| N° | Hypothèse | Valeur | Statut |
| --- | --- | --- | --- |
| H-01 | `REPORTING_THRESHOLD` | 100 000 MAD | [H], non légal |
| H-02 | Pilotage par nombre de cas ; taux mesurés en sortie | Voir section 5 | [H], à valider par les deux membres |
| H-03 | Un scénario principal par cas | Oui | [H] |
| H-04 | Plages des paramètres des scénarios | Voir section 6 | [H] |
| H-05 | Trois niveaux de sophistication | Voir section 6 | [H] |
| H-06 | « Fausse facture » = forme des montants et contreparties | Voir section 6 | [H] |
| H-07 | Cas moyen : 7,6 comptes, 63 transactions | Estimation | [H], à recalculer |
| H-08 | Profil `light` | 5 000 clients | [H] |
| H-09 | Profil `full` | 20 000 clients | [H] |
| H-10 | Un client = un compte | Oui | [H] |
| H-11 | Durée simulée | 90 jours | [H] |
| H-12 | Date de début | 2027-01-15 | [H] |
| H-13 | Comptes externes | 20 % du nombre de clients | [H] |
| H-14 | Répartition des profils | 55 / 15 / 18 / 12 % | [H] |
| H-15 | Villes et ville de rattachement | Section 2.3 | [H] |
| H-16 | Transactions par client et par profil | 62 / 40 / 140 / 120 sur 90 jours | [H] |
| H-17 | Montants log-normaux par profil | Section 3.2 | [H] |
| H-18 | Canaux par profil | Section 3.3 | [H] |
| H-19 | Réseau stable de contreparties et 10 % de nouvelles | Section 3.4 | [H] |
| H-20 | Rythmes horaires, hebdomadaires et mensuels | Section 3.5 | [H] |
| H-21 | Cas normaux « piégeux » et leurs fréquences | Section 3.6 | [H] |
| H-22 | Effets Ramadan et Aïd | Section 4 | [H] ; dates [À vérifier] |
| H-23 | Chaque cas tient dans un bloc d'évaluation | Oui | [H] ; voir question ouverte 3 |

---

## 9. Limites liées à des données simulées

1. **Les performances mesurées valent pour le simulateur, pas pour une banque réelle.** Un modèle peut retrouver les règles du générateur ; un projet tiers rapporte des scores quasi parfaits sur SAML-D, signe que la structure simulée peut être facile à lire (indicatif, source tierce, `docs/typologies.md` section 7). Nous écrivons à la fois le simulateur et le détecteur : le risque de **circularité** (détecter ce que nous avons nous-mêmes injecté) est réel. Les parades prévues sont les niveaux de sophistication, le test adversarial et la comparaison de réalisme avec les jeux publics.
2. **Aucune calibration marocaine.** Répartition des profils, volumes, montants, canaux et villes sont des choix de l'équipe. Aucune statistique officielle n'a été utilisée.
3. **Étiquettes complètes et exactes.** Dans la simulation, on sait avec certitude quelles transactions sont suspectes. Dans la réalité, beaucoup d'opérations de blanchiment ne sont jamais détectées et les étiquettes sont donc incomplètes (Altman et al., NeurIPS 2023).
4. **Taux et tailles de cas choisis.** Les taux (environ 0,57 % à 0,76 % de comptes) sont des conséquences du nombre de cas choisi, pas une mesure du blanchiment réel.
5. **Monde fermé.** Une seule banque, un compte par client, pas de solde, pas de bénéficiaire effectif, pas de pays de destination, pas d'objet de transaction. Les indicateurs de propriété du GAFI ne sont pas observables.
6. **Nombre de cas limité.** Même en `full`, il n'y a que 15 cas par graine ; les résultats par typologie sont **indicatifs** et accompagnés d'intervalles de Wilson (D-6).
7. **Période courte.** 90 jours ne permettent pas de saisonnalité annuelle ni de dérive de long terme. La dérive est approchée par le Ramadan, l'Aïd et le test adversarial.
8. **Scénarios isolés.** Un seul scénario par cas (H-03). Les enchaînements réels (par exemple fractionnement suivi de layering) ne sont pas simulés dans cette version.
9. **Comportement normal simplifié.** Lois log-normales et Poisson indépendantes entre clients, sans événements de vie (déménagement, changement d'emploi), sans remboursements ni litiges.
10. **Dates de fêtes fictives.** Le Ramadan et l'Aïd sont placés sur des dates prévisionnelles, utilisées uniquement pour créer une saisonnalité simulée.

---

## 10. Questions ouvertes

1. **Validation par l'équipe** (Mouad et Mounir) de la résolution des volumes et des taux (section 7) avant report dans `MASTER_PROMPT_PFA_AML.md` et `Roadmap_PFA_Detection_Blanchiment.md`.
2. **Confirmation de la date de début** (2027-01-15) : elle place le Ramadan dans le bloc d'entraînement et le bloc de test sans Ramadan. Faut-il un décalage pour que le Ramadan tombe aussi dans le test, ou assume-t-on ce décalage comme un test de robustesse ?
3. **Durée maximale d'un cas** : les valeurs par défaut du catalogue (fractionnement : 14 jours, flux circulaires : 30 jours, sociétés écran : 30 jours dormants plus le pic) sont longues par rapport à un bloc de test d'environ 18 jours. Il faut soit raccourcir ces durées, soit allonger la période simulée (par exemple 120 jours pour `full`), ce qui modifie une valeur du prompt maître.
4. **Réalisme des confusions** (section 3.6) et **poids des profils** (section 2.2) : à relire avec le Pr Chergui.
5. **Dates du Ramadan et de l'Aïd** : à confirmer au moment du gel du jeu de données ; elles n'affectent que la simulation.
6. **Champs absents du contrat v1** (solde, bénéficiaire effectif, pays de destination) : à décider avant le gel du contrat (phase 2).
7. **Scénarios combinés** : à décider pour une version ultérieure du simulateur.
8. **Tailles de cas** (H-07) : à recalculer dès que le simulateur existe, puis mettre à jour les tableaux de la section 5.
9. **Contenu des textes de Bank Al-Maghrib** (PDF scannés) : lecture manuelle à faire pour confirmer l'absence ou la présence de seuils chiffrés, avant de présenter `REPORTING_THRESHOLD` autrement que comme une hypothèse.

---

## 11. Références

- `docs/typologies.md` v1.1 (sections 4, 5, 7, 8 et 10) : paramètres des scénarios, niveaux de sophistication, jeux publics, décisions D-1 à D-6.
- `MASTER_PROMPT_PFA_AML.md` : volumes par défaut (ligne 54), contrat de données, niveaux de sophistication.
- `Roadmap_PFA_Detection_Blanchiment.md` : lignes 50 et 96.
- Prévisions des dates du Ramadan 1448 et de l'Aïd el-Fitr 2027 (calculs astronomiques, presse, consultées le 2026-11-09), par exemple La Presse de Tunisie, 8 octobre 2026, et Oumma (calendrier Umm al-Qura) : **prévisions, non officielles**.
- Altman et al., « Realistic Synthetic Financial Transactions for Anti-Money Laundering Models », NeurIPS 2023 (AMLworld) ; Oztas et al., SAML-D, IEEE ICEBE 2023 : références de comparaison de taux et de limites, détaillées dans `docs/typologies.md`.
