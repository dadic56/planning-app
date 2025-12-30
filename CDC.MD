# Cahier des charges – Application web de planning des vendeuses

## 1. Contexte & objectif
Le magasin emploie six vendeuses avec un planning hebdomadaire de référence. L'application web doit :
- gérer ce planning de base ;
- déclarer les absences et événements exceptionnels (dimanches ouverts, jours fériés) ;
- générer automatiquement un planning ajusté en respectant les contraintes légales et internes ;
- archiver et restaurer des semaines validées.
L'outil vise une responsable de boutique qui l’utilise depuis un navigateur desktop moderne (Chrome/Edge/Safari). Aucun multi-magasin n’est prévu.

## 2. Vision fonctionnelle
### 2.1 Gestion du référentiel
- CRUD des vendeuses
  - champs : prénom, type de contrat (24h, 35h, autre), heures contrat, heures sup autorisées, mi-temps thérapeutique (bool + %), règles particulières (texte libre), disponibilité le dimanche.
  - validation : prénom unique, heures > 0, pourcentage thérapeutique 1–100% si activé.
- Gestion du planning de base (BaseShift)
  - création/modification/suppression des créneaux hebdomadaires (jour, horaire, pause, note).
  - liste regroupée par vendeuse + total hebdo affiché (badge).

### 2.2 Déclaration d’absences
- formulaire principal : sélection multi-vendeuses, date de début/fin, motif.
- liste des absences actives affichée sous le planning (avec bouton de suppression).

### 2.3 Génération du planning ajusté
- Champ « semaine (lundi) » + case « dimanche ouvert ».
- Sélecteur de durée (1 ou 2 semaines). Pour deux semaines, les deux plannings sont affichés côte à côte, les absences couvrent automatiquement les créneaux et ne sont plus comptabilisées dans les totaux.
- Bouton « Générer planning ajusté » appelle `/api/generate-week` pour chaque semaine demandée.
- Résultat : tableau principal avec planning de base (bleu) et ajusté (vert/orange), tags de pause, total journalier, total hebdo (hors absences), colonnes OUV./FERM. indiquant les jours couverts pour chaque vendeuse, ligne de couverture agrégée.
- Résumé des changements et alertes avec badges de sévérité. Les alertes incluent des propositions d’action (renfort, réorganisation…).

### 2.4 Archives (snapshots)
- Bouton « Archiver cette semaine » : enregistre planning ajusté, absences, violations, ouvertures spéciales, label personnalisé, statut (brouillon, prévisionnel, validé).
- Option « 2 semaines » : l’archive capture les deux semaines et leur contenu.
- Page `/snapshots` :
  - liste latérale des archives (date, statut, contraintes, timestamp, nb de créneaux) avec changement de statut et restauration.
  - panneau principal affichant le planning archivé (1 ou 2 semaines) sous forme de tableaux identiques à ceux de la page principale, rappel des absences et alertes, bouton de téléchargement JSON.
  - restauration : remplace les `AdjustedShift`/`RuleViolation` sur la période couverte par l’archive.

## 3. Règles métiers & contraintes
### 3.1 Couverture magasin
- Au moins 3 personnes présentes à l’ouverture et à la fermeture (heures normales : 09:30 et 19:15 ; horaires issus des ouvertures spéciales sinon).
- Tous les créneaux générés doivent respecter les disponibilités (absences, règles individuelles, acceptation dimanche).
- Les violations `COVER_OPEN`/`COVER_CLOSE` sont enregistrées avec suggestions (renfort, heures sup…).
- Les vendeuses en absence ne doivent afficher aucun créneau ni heures décomptées sur la semaine ; les jours concernés sont remplacés par une pastille « Absence ».

### 3.2 Horaires / pauses
- Durée max d’un shift : 10h.
- Pas plus de 6h consécutives sans pause.
- Pause déjeuner obligatoire entre 12:00 et 15:00 si le shift dépasse 6h (1h à 2h).
- Deux jours de repos hebdomadaires minimum par vendeuse (hérité du planning de base ; pas de calcul automatique d’équilibre pour cette V1).
- À la création/modification d’un créneau de base, les horaires doivent être au format HH:MM, la fin après le début, la pause optionnelle valide et aucun chevauchement n’est toléré pour une même vendeuse.

### 3.3 Contrats & heures
- 24h (ex : Clara, Nathalie) – plafond strict ; tolérance max 32h si heures sup autorisées.
- 35h (ex : Alexandra…) – plafond recommandé 41h.
- Mi-temps thérapeutique : plafond = heures contrat * pourcentage.
- `allow_overtime` bloque l’affectation au-delà du plafond élargi.
- Dimanche ouvert : seules les vendeuses qui ont coché « Disponible le dimanche » peuvent être affectées.
- Dimanche ouvert nécessite au moins 3 vendeuses disponibles et affectées via l’ouverture spéciale.

### 3.4 Règles individuelles (exemples)
- Nathalie : lundi après-midi libre (pas de shift après 12:00 avant 15:30).
- Stéphanie : jamais le vendredi.
- Ces règles sont stockées dans `Employee.special_rules` et appliquées lors de la génération.

### 3.5 Absences et redistribution automatique
1. **Déclaration** : Ajouter l'absence via `/api/absences` (ou le formulaire UI) avec date début/fin et motif.
2. **Suppression des créneaux** : Le générateur (`generate_adjusted_week`) retire automatiquement tous les créneaux de la personne absente sur la période.
3. **Recherche de remplaçante** pour chaque créneau supprimé :
   - **Priorité aux contrats 24h** (Clara, Nathalie) pour répartir la charge en premier
   - Si aucune 24h disponible, recherche parmi les **35h**
   - Critères de disponibilité :
     - Pas déjà absente ce jour-là
     - Ne dépasse pas son plafond horaire hebdo (heures déjà planifiées + nouveau créneau ≤ plafond)
     - Pas de chevauchement avec un shift existant
     - Respect de la pause obligatoire (1h minimum entre deux shifts)
     - Pas plus de 6h consécutives sans pause déjeuner
     - Respect des règles individuelles (ex: Stéphanie jamais le vendredi)
     - Disponible le dimanche si c'est un dimanche
4. **Création du remplacement** : Si une remplaçante est trouvée, création d'un `AdjustedShift` avec `source="reassigned"` (tag orange dans l'UI)
5. **Échec de remplacement** : Si aucune remplaçante n'est trouvée, enregistrement d'une `RuleViolation` avec code `SHIFT_UNASSIGNED` et détail des raisons (toutes en heures sup, indisponibles, règles bloquantes...)
6. **Résumé détaillé** : Le générateur retourne les métadonnées de tous les remplacements effectués (qui → qui, créneau, impact heures) et les échecs avec suggestions d'actions.

### 3.6 Ouvertures spéciales (roadmap)
Le modèle existe déjà dans la base, mais aucune interface n’est fournie dans la version courante. L’intégration (saisie, affectation, injection dans la génération) est repoussée à une itération ultérieure.

## 4. API (v1)
### 4.1 Référentiel
- `GET /api/employees` → liste complète (tri alphabétique).
- `POST /api/employees` / `PUT /api/employees/<id>` → payload : `name`, `contract_type`, `max_week_hours`, `therapeutic_part_time`, `therapeutic_percent`, `allow_overtime`, `sunday_available`, `special_rules`.
- `GET /api/base-shifts` (option `?weekday=`) / `POST` / `PUT` / `DELETE` pour les créneaux de base.

### 4.2 Absences
- `GET /api/absences?from=&to=`
- `POST /api/absences`
- `DELETE /api/absences/<id>`

### 4.3 Génération & consultation
- `POST /api/generate-week?monday=YYYY-MM-DD&sunday_open=0|1` (appelé pour chaque semaine demandée côté front).
- `GET /api/base-week?monday=`
- `GET /api/adjusted?from=&to=`
- `GET /api/violations?from=&to=`

### 4.4 Archives
- `GET /api/snapshots`
- `POST /api/snapshots` (payload : `monday`, `label?`, `status?`, `sunday_open?`, `weeks?` où `weeks ∈ {1,2}`)
- `GET /api/snapshots/<id>`
- `PUT /api/snapshots/<id>` (changer label/statut)
- `DELETE /api/snapshots/<id>`
- `POST /api/snapshots/<id>/restore`

## 5. Données & persistance
### 5.1 Modèle relationnel
- `Employee(id, name, contract_type, max_week_hours, special_rules, therapeutic_part_time, therapeutic_percent, allow_overtime, sunday_available)`
- `BaseShift(id, employee_id, weekday, start_time, end_time, lunch_start, lunch_end, note)`
- `Absence(id, employee_id, start_date, end_date, reason)`
- `AdjustedShift(id, employee_id, date, start_time, end_time, lunch_start, lunch_end, source, note)`
- `RuleViolation(id, date, employee_id, code, details, severity, created_at)`
- `PlanningSnapshot(id, monday, sunday, label, status, data, created_at)`

> `SpecialOpening` et `SpecialOpeningShift` sont conservées dans le schéma, mais non exploitées dans l’interface actuelle (cf. §3.5).

Indices & intégrité :
- Unicité `(employee_id, weekday, start_time, end_time, lunch_start)` sur BaseShift.
- `SpecialOpening.date` unique.
- `SpecialOpeningShift.opening_id` cascade delete.

## 6. UX & UI
- Pages : `/` (planning ajusté multi-semaine), `/base` (planning de base + total heures), `/snapshots` (archives).
- `base.js` : formulaire inline pour les créneaux, bouton « Fermer » si pas de modification, durée affichée.
- `app.js` : colonnes OUV./FERM. par vendeuse avec jours couverts, suggestions dans les alertes, badge total heures avec surlignage si dépassement.
- Responsive : barre d’outils reflow < 960px, archives en layout colonne sur mobiles.

## 7. Algorithme (détails)
- Étapes principales déjà décrites au §2.4/2.5.
- Gestion des ouvertures spéciales :
  1. Validation des règles (au moins 3 vendeuses dimanche, disponibilité).
  2. Injection des `SpecialOpeningShift` comme `AdjustedShift` source `special`.
  3. Couverture recalculée avec horaires spécifiques (selon `open_time/close_time`).
- Les shifts de base ne sont pas générés les jours couverts par une ouverture spéciale (on s’y substitue totalement).

## 8. Tests & validation
- Tests automatisés :
  - `pytest` couvre la validation des créneaux de base (formats, chevauchement) et la création d’archives (1 ou 2 semaines).
  - Marqueur `e2e` pour les scénarios Playwright (chargement de la page principale). Nécessite `playwright install`.
- Tests manuels conseillés :
  1. Génération sur 2 semaines avec absences → vérifier que les créneaux barrés disparaissent et que les totaux hebdos n’intègrent pas l’absence.
  2. Déclaration d’absence multi-vendeuses sur la semaine courante → la pastille Absence doit remplacer les créneaux.
  3. Archivage + restauration multi-semaine → l’affichage et la couverture redeviennent identiques après restauration.

## 9. Observabilité & exploitation
- `/health` → `{ "ok": true }`.
- Logs : `INFO generate_adjusted_week`, `WARN` pour violations, `ERROR` pour exceptions.
- Migrations Alembic obligatoires (cf. tables supplémentaires).

## 10. Roadmap détaillée
- **Mise en production** : finaliser migrations, renseigner env `.flaskenv` (URI BDD, SECRET_KEY).
- **Phase 2** (suggestions) :
  - Saisie d’un « modèle dimanche » pour générer automatiquement les shifts.
  - Gestion des jours de repos garantis / équilibre heures.
  - Authentification simple (mot de passe).
  - Exports PDF/CSV des plannings.

## 11. Exploitation & scripts
- `python scripts/seed_demo.py --reset` : réinitialise la base avec les données de démo (employées, horaires d’ouverture, planning de base).
- `python tools/build_assets.py` : génère les fichiers JavaScript hashés et le manifest consommé par Flask.
- `pytest` / `pytest -m e2e` : lance la suite de tests (les scénarios E2E nécessitent Playwright installé).

Ce cahier des charges est auto-suffisant pour reconstruire l’application via une IA : il décrit l’objectif, les règles, les modèles, les API, les écrans et le comportement attendu.
