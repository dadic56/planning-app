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

### 2.2 Ouvertures spéciales
- Page dédiée `/special` permettant de déclarer des journées exceptionnelles :
  - date, label, notes, mode dimanche, journée fermée ou non, horaires ouvrants.
  - association de créneaux à des vendeuses (respect de leur disponibilité dimanche si mode dimanche).
  - contraintes : au moins 3 vendeuses affectées si dimanche ouvert ; au moins un créneau si journée ouverte.
- Les ouvertures spéciales peuvent être mises à jour ou supprimées. Elles sont prises en compte lors des générations.

### 2.3 Déclaration d’absences
- formulaire principal : sélection multi-vendeuses, date de début/fin, motif.
- liste des absences actives affichée sous le planning (avec bouton de suppression).

### 2.4 Génération du planning ajusté
- Champ « semaine (lundi) » + case « dimanche ouvert ».
- Bouton « Générer planning ajusté » appelle `/api/generate-week` avec `sunday_open`.
- Résultat : tableau principal avec planning de base (bleu) et ajusté (vert/orange), tags de pause, total journalier, total hebdo, colonnes OUV./FERM. indiquant les jours couverts pour chaque vendeuse, ligne de couverture agrégée.
- Résumé des changements et alertes avec badges de sévérité. Les alertes incluent des propositions d’action (renfort, réorganisation…).

### 2.5 Archives (snapshots)
- Bouton « Archiver cette semaine » : enregistre planning ajusté, absences, violations, ouvertures spéciales, label personnalisé, statut (brouillon, prévisionnel, validé).
- Page `/snapshots` :
  - liste latérale des archives (date, statut, contraintes, timestamp, nb de créneaux) avec changement de statut et restauration.
  - panneau principal affichant la semaine archivée sous forme de planning complet (identique à l’ajusté), rappel des absences, alertes, ouvertures spéciales et bouton de téléchargement JSON.
  - restauration : remplace les `AdjustedShift`/`RuleViolation` de la semaine.

## 3. Règles métiers & contraintes
### 3.1 Couverture magasin
- Au moins 3 personnes présentes à l’ouverture et à la fermeture (heures normales : 09:30 et 19:15 ; horaires issus des ouvertures spéciales sinon).
- Tous les créneaux générés doivent respecter les disponibilités (absences, règles individuelles, acceptation dimanche).
- Les violations `COVER_OPEN`/`COVER_CLOSE` sont enregistrées avec suggestions (renfort, heures sup…).

### 3.2 Horaires / pauses
- Durée max d’un shift : 10h.
- Pas plus de 6h consécutives sans pause.
- Pause déjeuner obligatoire entre 12:00 et 15:00 si le shift dépasse 6h (1h à 2h).
- Deux jours de repos hebdomadaires minimum par vendeuse (hérité du planning de base ; pas de calcul automatique d’équilibre pour cette V1).

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

### 3.5 Ouvertures spéciales
- Remplacent les horaires standards pour la date ciblée.
- Peuvent être « fermées » (aucun shift généré) ou ouvertes avec horaires spécifiques.
- Les créneaux saisis via `SpecialOpeningShift` sont injectés comme `AdjustedShift` source `special` lors de la génération.

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
- `POST /api/generate-week?monday=YYYY-MM-DD&sunday_open=0|1`
- `GET /api/base-week?monday=`
- `GET /api/adjusted?from=&to=`
- `GET /api/violations?from=&to=`

### 4.4 Archives
- `GET /api/snapshots`
- `POST /api/snapshots` (payload : `monday`, `label?`, `status?`, `sunday_open?`)
- `GET /api/snapshots/<id>`
- `PUT /api/snapshots/<id>` (changer label/statut)
- `DELETE /api/snapshots/<id>`
- `POST /api/snapshots/<id>/restore`

### 4.5 Ouvertures spéciales
- `GET /api/special-openings?from=&to=`
- `POST /api/special-openings`
  ```json
  {
    "date": "2025-07-14",
    "label": "Fête nationale",
    "sunday_mode": false,
    "is_closed": false,
    "open_time": "10:00",
    "close_time": "18:00",
    "notes": "Horaires réduits",
    "shifts": [
      {"employee_id": 4, "start_time": "10:00", "end_time": "14:00"},
      {"employee_id": 5, "start_time": "14:00", "end_time": "18:00"}
    ]
  }
  ```
- `GET /api/special-openings/<id>`
- `PUT /api/special-openings/<id>`
- `DELETE /api/special-openings/<id>`

## 5. Données & persistance
### 5.1 Modèle relationnel
- `Employee(id, name, contract_type, max_week_hours, special_rules, therapeutic_part_time, therapeutic_percent, allow_overtime, sunday_available)`
- `BaseShift(id, employee_id, weekday, start_time, end_time, lunch_start, lunch_end, note)`
- `SpecialOpening(id, date, label, open_time, close_time, is_closed, sunday_mode, notes, created_at)`
- `SpecialOpeningShift(id, opening_id, employee_id, start_time, end_time, lunch_start, lunch_end)`
- `Absence(id, employee_id, start_date, end_date, reason)`
- `AdjustedShift(id, employee_id, date, start_time, end_time, lunch_start, lunch_end, source, note)`
- `RuleViolation(id, date, employee_id, code, details, severity, created_at)`
- `PlanningSnapshot(id, monday, sunday, label, status, data, created_at)`

Indices & intégrité :
- Unicité `(employee_id, weekday, start_time, end_time, lunch_start)` sur BaseShift.
- `SpecialOpening.date` unique.
- `SpecialOpeningShift.opening_id` cascade delete.

## 6. UX & UI
- Pages : `/` (planning ajusté), `/base` (planning de base + total heures), `/special` (ouvertures spéciales), `/snapshots` (archives).
- `base.js` : formulaire inline pour les créneaux, bouton « Fermer » si pas de modification, durée affichée.
- `app.js` : colonnes OUV./FERM. par vendeuse avec jours couverts, suggestions dans les alertes, badge total heures avec surlignage si dépassement.
- `special.js` : interface type kanban (liste à gauche, formulaire à droite), créneaux dynamiques, validation du dimanche.
- Responsive : barre d’outils reflow < 960px, archives en layout colonne sur mobiles.

## 7. Algorithme (détails)
- Étapes principales déjà décrites au §2.4/2.5.
- Gestion des ouvertures spéciales :
  1. Validation des règles (au moins 3 vendeuses dimanche, disponibilité).
  2. Injection des `SpecialOpeningShift` comme `AdjustedShift` source `special`.
  3. Couverture recalculée avec horaires spécifiques (selon `open_time/close_time`).
- Les shifts de base ne sont pas générés les jours couverts par une ouverture spéciale (on s’y substitue totalement).

## 8. Tests & validation
- Tests unitaires recommandés : `minutesBetween`, `fits_daily_rules`, `respects_special_rules`, `generate_adjusted_week` (cas normal, absence multiple, ouverture spéciale dimanche, journée fermée).
- Tests manuels :
  1. Dimanche ouvert avec 3 vendeuses disponibles → vérifier la génération.
  2. Dimanche ouvert sans ouverture spéciale → erreur explicite.
  3. Ouverture « fermé » (jour férié) → aucun shift ce jour-là, pas de violation (jour ignoré).
  4. Archive > restauration → planning adapté et colonnes OUV./FERM. cohérentes.

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

Ce cahier des charges est auto-suffisant pour reconstruire l’application via une IA : il décrit l’objectif, les règles, les modèles, les API, les écrans et le comportement attendu.
