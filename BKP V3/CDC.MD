# Cahier des charges – Planning des vendeuses

## 1. Contexte
Le magasin dispose de **6 vendeuses** avec un planning de base fixe et des horaires d'ouverture du lundi au samedi (dimanche fermé sauf exception). L'application web doit présenter ce planning de référence, gérer les absences et produire un planning ajusté conforme aux contraintes légales et organisationnelles.

## 2. Objectifs fonctionnels
- Afficher simultanément le planning de base (en haut) et le planning ajusté (en dessous) pour une semaine donnée.
- Déclarer des absences (multi-sélection) avec motif, période, indication de dimanche ouvert/fermé et marquage des jours fériés.
- Redistribuer automatiquement les créneaux des personnes absentes en respectant toutes les contraintes.
- Mettre en évidence les modifications : remplacements, créneaux supprimés ou non couverts, absences actives.
- Fournir un résumé clair : remplacements effectués, contraintes non respectées, alertes de couverture.
- Expliquer les blocages restants (heures sup atteintes, règles individuelles, chevauchements) et suggérer les ajustements possibles.
- Gérer le référentiel des vendeuses : création d'un profil, renommage, mise à jour du contrat, statut de mi-temps thérapeutique et pourcentage associé.
- Définir si les heures supplémentaires sont autorisées pour chaque vendeuse (case à cocher) afin d'ajuster automatiquement le planning.
- Permettre la modification manuelle du planning de base via une page dédiée.

## 3. Règles de gestion et contraintes
### 3.1 Couverture magasin
- Minimum **3 personnes** à l’ouverture (09:30).
- Minimum **3 personnes** à la fermeture (19:15).
- Minimum **2 vendeuses** en permanence sur la plage d'ouverture (sur toute la durée d'ouverture).
- Tolérance : la durée cumulée avec seulement 2 vendeuses ne doit pas dépasser **1h par jour**.
- Les alertes `COVER_OPEN` et `COVER_CLOSE` sont générées si la couverture est insuffisante.

### 3.2 Durées et pauses
- Maximum **10h** travaillées par jour.
- Maximum **6h consécutives** sans pause.
- Pause déjeuner comprise entre **1h** et **2h**, devant commencer à partir de **12:00** et se terminer au plus tard à **15:00**.
- Chaque vendeuse doit bénéficier de **2 jours de repos** par semaine (consécutifs ou non).

### 3.3 Contrats
- `24h` : plafond strict pour Clara et Nathalie, avec un maximum absolu de **32h** (jusqu’à 8h supplémentaires de manière exceptionnelle).
- `35h` : plafond recommandé pour Alexandra, Aurélia et Noémie, avec un maximum absolu de **41h** (jusqu’à 6h supplémentaires exceptionnelles).
- La colonne « Total (h) » affiche `+xh` lorsque des heures sup sont consommées et met en surbrillance les dépassements du plafond majoré (32h / 41h).
- Les vendeuses en mi-temps thérapeutique définissent un pourcentage (ex : 60 %) qui ajuste automatiquement leur plafond hebdomadaire dans l’algorithme.
- Une option « Heures sup autorisées » permet de bloquer immédiatement toute attribution dépassant le contrat + marge.

### 3.4 Contraintes individuelles
- **Clara** : contrat 24h.
- **Nathalie** : contrat 24h + lundi après-midi impérativement libre (pas de shift après 12:00, reprise éventuelle à partir de 15:30).
- **Stéphanie** : ne travaille jamais le vendredi.
- Les vendeuses en mi-temps thérapeutique doivent respecter le pourcentage paramétré (disponibilité limitée sur la semaine).
- Les règles individuelles sont stockées dans `Employee.special_rules` et contrôlées dans l’algorithme de génération.

### 3.5 Absences et redistribution
1. Ajouter l’absence via `/api/absences` (ou le formulaire UI).
2. Le générateur (
   `generate_adjusted_week`) supprime les créneaux de la période absente.
3. Recherche d’une remplaçante :
   - Disponible ce jour-là (pas déjà absente).
   - Ne dépasse pas son plafond horaire (hebdo + restes du planning de base).
   - Ne chevauche pas un shift existant et respecte la pause d’1h.
   - N’enchaîne pas plus de 6h effectives.
   - Respecte les règles individuelles ci-dessus.
4. Si une remplaçante est trouvée : création d’un `AdjustedShift` avec `source="reassigned"`.
5. Sinon, aucun shift n’est posé et un `SHIFT_UNASSIGNED` est enregistré dans `RuleViolation`.

## 4. Interface utilisateur
### 4.1 Tableau principal
- Colonnes : lundi → dimanche + couverture ouverture/fermeture + total hebdo.
- Lignes : vendeuses (ordre alphabétique). Les personnes absentes sont signalées par un badge « Absente ».
- Tags par créneau :
  - Bleu (`base`) = planning de base.
  - Vert (`adjust`) = créneau ajusté.
  - Orange (`replacement`) = remplaçante ; contour jaune si dérivé d’un ajustement.
  - Tag barré (`ghost`) = créneau supprimé à cause d’une absence.
- Chaque tag affiche la tranche horaire et la durée correspondante ; le total journalier est indiqué en bas de la cellule.
- Colonne « Total (h) » enrichie : total hebdo + badge d’heures sup (`+xh`) et avertissement si le plafond majoré est dépassé.

### 4.2 Résumés
- **Absences déclarées** : liste hebdomadaire affichée sous le tableau (`#absSummary`), issue de `/api/absences`.
- **Résumé des changements** : liste les créneaux ajustés / remplacements et les violations détectées (`/api/violations`).
- Ligne de couverture en bas du tableau : nombre de personnes présentes à 09:30 et 19:15, avec code couleur OK/KO.
- Alertes enrichies : badges de sévérité (Critique, Grave, À surveiller, Info…) et détail textuel des blocages (heures sup dépassées, règles individuelles, incompatibilités horaires).
- Panneau « Gestion des vendeuses » : formulaire pour ajouter ou éditer une vendeuse (prénom, contrat, heures hebdo, mi-temps thérapeutique + pourcentage, règles spécifiques) et tableau de synthèse.

### 4.3 Page « Planning de base »
- CRUD complet sur `BaseShift` (filtre par jour, édition, suppression) accessible via `/base`.
- Les modifications respectent l’unicité des créneaux (index unique en base sur `employee_id + weekday + start_time + end_time + lunch`).

## 5. Données & persistance
### 5.1 Tables principales
- `Employee(id, name, contract_type, max_week_hours, special_rules)`.
- `BaseShift(id, employee_id, weekday, start_time, end_time, lunch_start, lunch_end)`.
- `AdjustedShift(id, employee_id, date, start_time, end_time, lunch_start, lunch_end, source, note)`.
- `Absence(id, employee_id, start_date, end_date, reason)`.
- `RuleViolation(id, date, employee_id, code, details, severity, created_at)`.

### 5.2 Intégrité
- Index unique `idx_base_shift_unique` garantit l’absence de doublon sur `BaseShift`.
- `generate_adjusted_week` nettoie les `AdjustedShift` et `RuleViolation` de la période avant chaque génération.

## 6. API
| Méthode & route | Description |
|-----------------|-------------|
| `GET /api/employees` | Liste des vendeuses (id, nom, contrat, heures max). |
| `POST /api/employees` | Ajoute une vendeuse (nom, contrat, mi-temps…). |
| `PUT /api/employees/<id>` | Met à jour une vendeuse existante. |
| `GET /api/base-week?monday=` | Planning de base projeté sur la semaine. |
| `POST /api/generate-week?monday=&sunday_open=` | Lance la génération ajustée. |
| `GET /api/adjusted?from=&to=` | Liste les `AdjustedShift` de la période. |
| `GET /api/violations?from=&to=` | Violations enregistrées sur la période. |
| `POST /api/absences` | Déclare une absence. |
| `GET /api/absences?from=&to=` | Absences actives chevauchant la période. |
| `GET/POST/PUT/DELETE /api/base-shifts` | Gestion du planning de base. |

## 7. Processus de génération (récapitulatif)
1. Charger les employés, absences, shifts de base, horaires d’ouverture.
2. Calculer l’effort hebdomadaire restant par employée (minutes restantes du planning de base).
3. Pour chaque `BaseShift` de la semaine :
   - Si l’employée n’est pas absente, recopier le shift avec `source="base"`.
   - Sinon, tenter une réaffectation (filtrage + scoring par contrat, heures déjà posées, réserve restante).
   - En cas d’échec, consigner `SHIFT_UNASSIGNED`.
4. Calculer la couverture ouverture/fermeture et consigner les alertes associées.
5. Sauvegarder les `AdjustedShift` et `RuleViolation` générés.

## 8. Contrôles & validations
- Compilation Python (`python3 -m compileall backend`) lors des modifications.
- Vérification BDD : `SELECT * FROM base_shift` doit rester sans doublons.
- Tests manuels :
  - Déclarer une absence d’Alexandra → vérifier que ses créneaux disparaissent / remplacements orange / violations listées.
  - Vérifier la ligne de couverture (≥3) après génération.
  - Observer la section « Absences déclarées » correspondante.
