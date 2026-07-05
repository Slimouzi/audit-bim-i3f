# Validation A1 — extraction `bim-publication` v0.1.0

Preuve de **validation write réelle** de l'extraction de la couche publication
(builders BCF / Smart Views + `prepare_*`) vers le package
[`bim-publication`](https://github.com/Slimouzi/bim-publication) (tag
`bim-publication-v0.1.0`). Rejoue le protocole A1 **après** la bascule en façade
(shims), sur un **modèle de validation jetable autorisé à l'écriture** dans
l'environnement BIMData courant (même authentification qu'en production).

## Contexte

| | |
|---|---|
| Modèle | **DIEPPE-7427L-BATA-ARCHI-APD.ifc** (`model_id=1674450`) |
| Projet | I3F (`project_id=2698917`), cloud/space `33617` |
| URL viewer | `https://platform.bimdata.io/spaces/33617/projects/2698917/viewer/1674450?window=3d` |
| Commit shim (façade → package) | `be879e1` — *refactor: shim publication builders + prepare_\* over bim-publication (#51)* |
| Commit preuve golden | `e7388a9` — *golden parity vs pre-shim (af230e6) (#52)* |
| Phase auditée | AVP |
| Date du run | 2026-07-05, ~15:34 UTC |
| Préfixe des objets | `REPLAY-BIM-PUBLICATION-20260705 — ` |

## Procédure exécutée (prepare → review → apply)

1. **Cible explicite** puis **contrôle d'identité** :
   `set_active_model(cloud_id="33617", project_id="2698917", model_id="1674450", phase="AVP")`
   → `verify_active_model(expected_model_name="DIEPPE-7427L-BATA-ARCHI-APD")` →
   `ok: true`, `model_name: "DIEPPE-7427L-BATA-ARCHI-APD.ifc"`.
2. **Audit** : `parse_owner_requirements` (CCH 3.6) → `run_audit_tool`
   (19 994 findings ; `naming_invalid_format = 3`, tous thème « Nommage Pièce »,
   3 `IfcSpace` distincts).
3. **Préparation** (plans scellés, **aucune écriture**), filtre
   `error_types=["naming_invalid_format"]`, `include_overview=false` :

   | Plan | `plan_id` | `kind` | items | risks | `n_findings_in_scope` |
   |---|---|---|---|---|---|
   | BCF | `5b45c12d-28be-4337-aa98-a4eb9cce4a4a` | `bcf_topics` | **1** | `[]` | 3 |
   | Smart Views | `42d47e11-bb15-4185-8e3f-89b4afd44a37` | `smart_views` | **1** | `[]` | 3 |

   `plan.target` des deux = `{cloud_id: 33617, project_id: 2698917, model_id: 1674450,
   model_name: "DIEPPE-7427L-BATA-ARCHI-APD.ifc"}`.
4. **Revue** : `n_items = 1`, `risks = []`, cible conforme → validé.
5. **Garde-fou** : `apply_bcf_topics(confirm=False)` et
   `apply_smart_views_plan(confirm=False)` → **refusés** (`refused: true`).
6. **Application** (`confirm=True`, après revue) :

   | Action | `plan_id` | `succeeded` | `failed` | `executed_at` (UTC) |
   |---|---|---|---|---|
   | `apply_bcf_topics` | `5b45c12d…` | **1** | **0** | `2026-07-05T15:34:06Z` |
   | `apply_smart_views_plan` | `42d47e11…` | **1** | **0** | `2026-07-05T15:34:14Z` |

## Extraits du journal (`audit_trail`)

Les 2 entrées **postérieures au shim #51** (les 2 premières, à `00:01Z`, sont
antérieures et servent de baseline) :

```json
{
  "timestamp": "2026-07-05T15:34:06+00:00",
  "action": "apply_bcf_topics",
  "plan_id": "5b45c12d-28be-4337-aa98-a4eb9cce4a4a",
  "plan_kind": "bcf_topics",
  "target": {"cloud_id": "33617", "project_id": "2698917", "model_id": "1674450",
             "model_name": "DIEPPE-7427L-BATA-ARCHI-APD.ifc"},
  "succeeded": 1, "failed": 0, "skipped": 0,
  "impacted_uuids_count": 1,
  "extra": {"errors_sample": []}
}
{
  "timestamp": "2026-07-05T15:34:14+00:00",
  "action": "apply_smart_views",
  "plan_id": "42d47e11-bb15-4185-8e3f-89b4afd44a37",
  "plan_kind": "smart_views",
  "target": {"cloud_id": "33617", "project_id": "2698917", "model_id": "1674450",
             "model_name": "DIEPPE-7427L-BATA-ARCHI-APD.ifc"},
  "succeeded": 1, "failed": 0, "skipped": 0,
  "impacted_uuids_count": 1,
  "extra": {"errors_sample": []}
}
```

Aucun secret journalisé (`errors_sample` vide).

## Vérification viewer

À confirmer visuellement dans le viewer BIMData (URL ci-dessus) :

- **Panneau BCF Issues** : topic **`REPLAY-BIM-PUBLICATION-20260705 — Nommage Pièce`**
  (3 `IfcSpace` sélectionnés/colorés).
- **Panneau Smart Views** : vue **`REPLAY-BIM-PUBLICATION-20260705 — Nommage Pièce`**
  (coloring des 3 mêmes `IfcSpace`).

<!-- Captures d'écran à insérer :
  ![BCF Issues — REPLAY-BIM-PUBLICATION](images/a1-bcf.png)
  ![Smart Views — REPLAY-BIM-PUBLICATION](images/a1-smartview.png)
-->

## Conclusion

`succeeded=1 / failed=0` pour **les deux** plans, journal post-#51, cible conforme,
aucun secret. **Aucun défaut** → le tag `bim-publication-v0.1.0` est **maintenu**
(pas de v0.1.1). Combinée à la parité **golden byte-identique** vs le code pré-shim
(`#52`), la validation prouve que la chaîne extraite produit des objets réellement
valides via `apply_*` + `bimdata-write`. **Chantier Publication clôturé.**

## Workflow obligatoire (à conserver)

Toute publication write BIMData **doit** suivre `prepare → review → apply` :

1. **Cible explicite par URL** (ou IDs) via `set_active_model`.
2. **`verify_active_model`** (`ok: true`) avant tout audit/écriture.
3. **Revue du plan** avant apply : `plan.target`, `risks`, nombre d'`items`.
4. **Interdiction des chemins `legacy_execute`** (`push_bcf_topics` /
   `push_smart_views` en écriture directe) — passer par `prepare_* → apply_*`.
5. **`confirm=True` uniquement après revue** (le refus `confirm=False` est le
   garde-fou par défaut).
6. **Contrôle systématique via `audit_trail`** après chaque apply.

Clé BIMData **limitée aux projets autorisés**.
