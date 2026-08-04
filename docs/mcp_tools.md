# Tools MCP — référence

Le serveur `audit-bim-i3f` expose par défaut **46 tools MCP canoniques** répartis
en 6 catégories. Les **8 aliases métier** sont désormais **LEGACY opt-in** (cf.
[Aliases métier](#aliases-métier--compat-legacy-opt-in)) : absents par défaut, ils
portent le total à **54** quand ils sont activés.
La table ci-dessous est la **source de vérité** pour la documentation
utilisateur et les contrôles de migration.

## Légende

| Colonne | Signification |
|---|---|
| **Statut** | `actif` = à utiliser ; `legacy_wrapper` = déprécié, mode par défaut sûr (prepare/apply) ; `deprecated` = à remplacer ; `alias` = re-dispatch vers un tool actif |
| **R/W** | `R` = lecture ; `W` = écriture BIMData ; `R+disque` = écrit en sandbox `AUDIT_OUTPUT_DIR/` |
| **`confirm=True`** | Le tool exige `confirm=True` pour exécuter (sinon refus explicite) |
| **Risque métier** | Conséquence si mal employé |

## Tools actifs — workflow recommandé

### Filtrage / consultation (lecture seule)

| Tool | Statut | R/W | `confirm=True` | Risque métier |
|---|---|---|---|---|
| `filter_bim_objects` | actif | R | — | aucun |
| `list_audit_findings` | actif | R | — | aucun |
| `get_object_detail` | actif | R | — | aucun |
| `list_classification_suggestions` | actif | R | — | aucun |
| `query_findings` | actif (historique) | R | — | aucun |
| `show_filtered_objects_in_viewer` | actif | R | — | aucun (instruction viewer, aucune écriture) |

### Requête tabulaire sémantique sur la maquette (lecture seule)

| Tool | Statut | R/W | `confirm=True` | Risque métier |
|---|---|---|---|---|
| `query_bim_data` | actif | R | — | aucun |
| `query_bim_preset` | actif | R | — | aucun |
| `list_query_presets` | actif | R | — | aucun |

Permet à un agent IA / AMO de poser des questions sémantiques type
*« Liste les portes avec matériaux, performance acoustique et
dimensions »*. Voir [docs/workflow_amo_bim.md](workflow_amo_bim.md)
section *Interroger la maquette*.

### Profils MCP multi-AMO (lecture seule, déclaratif)

| Tool | Statut | R/W | `confirm=True` | Risque métier |
|---|---|---|---|---|
| `list_mcp_profiles` | actif | R | — | aucun |

Expose la carte des briques génériques et des profils client/AMO connus
(`i3f` par défaut, `bim_in_motion` préparatoire). **Purement déclaratif** : ne
change pas le profil actif, ne touche pas à la session, ne déclenche aucun
calcul. Voir [docs/scope-multi-amo-mcp.md](scope-multi-amo-mcp.md).

### Pattern `prepare → apply` (écriture contrôlée)

| Tool | Statut | R/W | `confirm=True` | Risque métier |
|---|---|---|---|---|
| `prepare_bcf_topics` | actif | R+disque | — | aucun (lecture + plan scellé) |
| `apply_bcf_topics` | actif | W | **oui** | écrasement Smart Views ou doublons BCF si plan obsolète |
| `prepare_smart_views_plan` | actif | R+disque | — | aucun |
| `apply_smart_views_plan` | actif | W | **oui** | doublons Smart Views si plan obsolète |
| `prepare_smart_view_from_filter_plan` | actif | R+disque | — | aucun (plan scellé depuis un filtre) |
| `prepare_classification_update_plan` | actif | R+disque | — | aucun |
| `apply_classification_update_plan` | actif | W | **oui** | écrasement classifs IFC existantes (signalé en `risks`) |

> **Aliases métier** : les variantes `*_from_findings` / `*_corrections` /
> `*_plan` re-dispatchent vers ces tools mais sont **LEGACY opt-in** (absentes par
> défaut). Voir [Aliases métier — compat LEGACY opt-in](#aliases-métier--compat-legacy-opt-in).

### Workflow / revue

| Tool | Statut | R/W | `confirm=True` | Risque métier |
|---|---|---|---|---|
| `update_suggestion_status` | actif | R (memory) | — | aucun (modifie session, pas BIMData) |
| `list_write_plans` | actif | R | — | aucun |
| `audit_trail` | actif | R | — | aucun |

### Contexte / configuration

| Tool | Statut | R/W | Notes |
|---|---|---|---|
| `project_context_questions` | actif | R | inspecte l'état de session |
| `set_owner_documents` | actif | R | charge les 3 documents MOA |
| `parse_owner_requirements` | actif | R | construit le catalogue d'exigences |
| `get_catalog_properties` | actif | R | filtre les PropertySpec du catalogue |
| `set_active_model` | actif | R | cible toute maquette par IDs ou URL viewer BIMData |
| `list_classification_systems` | actif | R | référentiels disponibles |
| `extract_model_snapshot` | actif | R | récupère depuis BIMData |
| `run_audit_tool` | actif | R | exécute les règles d'audit |
| `compare_with_previous_audit` | actif | R | audit comparatif |
| `verify_active_model` | actif | R | garde-fou d'identité |
| `full_audit` | actif | R+disque | orchestrateur ; défaut `push_mode="none"` = audit complet + livrables, sans publication BIMData |

### Reporting (écriture disque sandbox)

| Tool | Statut | R/W | Notes |
|---|---|---|---|
| `generate_xlsx_annex` | actif | R+disque | sandbox `AUDIT_OUTPUT_DIR/` |
| `generate_word_report` | actif | R+disque | sandbox `AUDIT_OUTPUT_DIR/` |
| `generate_avp_i3f_pack` | actif | R+disque | pack AVP (5 annexes + Word), sandbox `AUDIT_OUTPUT_DIR/` |
| `import_preliminary_findings` | actif | R (entrées sandbox) | importe des findings externes (clash/surfaces) dans la session |

### DOE et enrichissement — pattern prepare/apply

| Tool | Statut | R/W | `confirm=True` | Notes |
|---|---|---|---|---|
| `extract_doe_records` | actif | R | — | parse Excel/PDF, pas de matching ni écriture |
| `match_doe_to_ifc` | actif | R | — | parse + matching IFC, pas d'écriture |
| `doe_match_only` | actif (historique) | R | — | équivalent à `match_doe_to_ifc` |
| `prepare_doe_enrichment_plan` | actif | R+disque | — | prépare un WritePlan scellé avec pré-calcul des conflits |
| `apply_doe_enrichment_plan` | actif | W | **oui** | écrit les Psets sur les éléments IFC matchés |

> Les aliases DOE `prepare_doe_enrichment_from_file` / `apply_doe_enrichment` sont
> **LEGACY opt-in** (cf. section dédiée), pas dans le workflow recommandé.

### Autres écritures (à migrer vers prepare/apply dans une release ultérieure)

| Tool | Statut | R/W | Notes |
|---|---|---|---|
| `enrich_with_public_data` | actif | W | open data BAN/DPE/PLU/Géorisques (`dry_run` par défaut) |
| `apply_classifications_from_xlsx` | actif | W | révision XLSX → push BIMData (`dry_run` par défaut) |

## Tools dépréciés

**Supprimés en v0.5.0.** Les 5 tools hérités et leurs chemins `legacy_execute`
ont été retirés. Utiliser les workflows `list → (accept/reject) → prepare →
apply` :

| Tool retiré (v0.5.0) | Remplaçant |
|---|---|
| `suggest_classifications` | `list_classification_suggestions` |
| `create_bcf_topics` | `prepare_bcf_topics` → `apply_bcf_topics(confirm=True)` |
| `create_smart_views` | `prepare_smart_views_plan` → `apply_smart_views_plan(confirm=True)` |
| `apply_suggested_classifications` | `list_classification_suggestions` → `update_suggestion_status` → `prepare_classification_update_plan` → `apply_classification_update_plan(confirm=True)` |
| `doe_enrich_model` | `match_doe_to_ifc` → `prepare_doe_enrichment_plan` → `apply_doe_enrichment_plan(confirm=True)` |

### Suppression des wrappers (v0.5.0)

**Effective en v0.5.0** : les 5 tools hérités (`suggest_classifications`,
`create_bcf_topics`, `create_smart_views`, `apply_suggested_classifications`,
`doe_enrich_model`) **et** le paramètre/chemin `legacy_execute` ont été
**supprimés** (module `tools_legacy.py` retiré). Le seul workflow d'écriture est
désormais `prepare → review → apply(confirm=True)` (cf. table ci-dessus). Un test
d'inventaire (`test_mcp_inventory.py`) atteste leur absence du registre MCP.

La publication via `full_audit(push_mode=…)` **ne pousse plus** : elle **prépare**
des plans BCF/Smart Views et renvoie leur chemin ; l'écriture passe ensuite par
`apply_*`.

## Profil actif — `AUDIT_BIM_PROFILE`

Le serveur enregistre les outils du **profil** déclaré au démarrage. Par défaut,
et sans aucune variable, c'est **`i3f`** : la surface MCP est exactement celle
décrite dans ce document.

- `AUDIT_BIM_PROFILE=i3f` (défaut) — les 45 outils I3F, plus `list_mcp_profiles`,
  plus le prompt `amo_bim_i3f`.
- `AUDIT_BIM_PROFILE=bim_in_motion` — profil préparatoire : **aucun outil client**
  n'est enregistré, et les modules du profil I3F ne sont même pas importés. Le
  serveur n'expose que ses outils transverses. C'est l'état attendu tant que ce
  profil n'a pas les siens.
- Casse, tirets et espaces sont normalisés (`BIM-IN-MOTION` fonctionne).

Un identifiant inconnu **empêche le démarrage**, en nommant la valeur fautive et
les profils connus. C'est délibéré : un repli silencieux sur `i3f` donnerait un
serveur qui répond normalement tout en imprimant « CCH BIM I3F » dans le rapport
d'un autre AMO — une erreur invisible en exploitation.

Le profil ne se change **pas** en cours de session : il n'existe aucun outil MCP
pour le basculer. Changer de profil, c'est relancer le serveur.

## Aliases métier — compat LEGACY opt-in

Les **8 aliases** ci-dessous donnent un vocabulaire AMO plus parlant mais
**re-dispatchent à 100 %** vers un tool canonique (même signature, même
comportement). Depuis la réduction de surface MCP, ils sont **opt-in** :

- **Par défaut, ils ne sont pas enregistrés** — `audit_bim/profiles/i3f/aliases.py` n'est
  même pas importé (moins de bruit côté Claude/harness).
- Pour les réexposer : lancer le serveur avec
  **`AUDIT_BIM_ENABLE_LEGACY_ALIASES=true`** (valeurs acceptées : `1`/`true`/`yes`/`on`).
- Les tools **canoniques ne changent pas** selon le flag.

| Alias LEGACY | Tool canonique équivalent |
|---|---|
| `prepare_bcf_from_findings` | `prepare_bcf_topics` |
| `apply_bcf_plan` | `apply_bcf_topics` |
| `prepare_smartviews_from_findings` | `prepare_smart_views_plan` |
| `apply_smartviews_plan` | `apply_smart_views_plan` |
| `prepare_classification_corrections` | `prepare_classification_update_plan` |
| `apply_classification_corrections` | `apply_classification_update_plan` |
| `prepare_doe_enrichment_from_file` | `prepare_doe_enrichment_plan` |
| `apply_doe_enrichment` | `apply_doe_enrichment_plan` |

> Migration recommandée : appeler directement les tools canoniques. Les aliases
> seront retirés une fois les appelants migrés.

## Garanties transverses

Tous les tools `apply_*` (incl. aliases) :

1. **Refusent `confirm=False`** : retour `{"refused": True, "reason": "..."}` sans toucher BIMData ;
2. Appellent `ensure_writes_allowed(action)` après confirm — gate par transport (stdio autorisé, HTTP refusé sauf `AUDIT_BIM_ALLOW_WRITES=true`) ;
3. Validation d'intégrité du plan (SHA-256) — refus si altéré ;
4. Validation de cible BIMData (cloud/project/model) — refus si mismatch ;
5. Journalisation `audit_bim/security/write_journal.py` (append-only JSONL sous `AUDIT_OUTPUT_DIR/write_log/`).

Tous les retours MCP :

- restent **sous 1 MB** (overflow disque automatique à 256 KB) ;
- les erreurs sont scrubées (`audit_bim.security.redaction.redact_secrets`) avant journal et retour.

Voir aussi : [docs/migration_prepare_apply.md](migration_prepare_apply.md).
