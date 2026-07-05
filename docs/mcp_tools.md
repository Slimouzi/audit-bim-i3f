# Tools MCP — référence

Le serveur `audit-bim-i3f` expose **40 tools MCP** répartis en 6 catégories.
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

### Pattern `prepare → apply` (écriture contrôlée)

| Tool | Statut | R/W | `confirm=True` | Risque métier |
|---|---|---|---|---|
| `prepare_bcf_topics` | actif | R+disque | — | aucun (lecture + plan scellé) |
| `apply_bcf_topics` | actif | W | **oui** | écrasement Smart Views ou doublons BCF si plan obsolète |
| `prepare_smart_views_plan` | actif | R+disque | — | aucun |
| `apply_smart_views_plan` | actif | W | **oui** | doublons Smart Views si plan obsolète |
| `prepare_classification_update_plan` | actif | R+disque | — | aucun |
| `apply_classification_update_plan` | actif | W | **oui** | écrasement classifs IFC existantes (signalé en `risks`) |

### Aliases métier (re-dispatch vers les tools ci-dessus)

| Alias | Tool sous-jacent | Pour |
|---|---|---|
| `prepare_bcf_from_findings` | `prepare_bcf_topics` | workflow lisible AMO |
| `apply_bcf_plan` | `apply_bcf_topics` | idem |
| `prepare_smartviews_from_findings` | `prepare_smart_views_plan` | idem |
| `apply_smartviews_plan` | `apply_smart_views_plan` | idem |
| `prepare_classification_corrections` | `prepare_classification_update_plan` | idem |
| `apply_classification_corrections` | `apply_classification_update_plan` | idem |

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
| `full_audit` | actif | R+disque (W si push_mode) | orchestrateur ; voir docstring |

### Reporting (écriture disque sandbox)

| Tool | Statut | R/W | Notes |
|---|---|---|---|
| `generate_xlsx_annex` | actif | R+disque | sandbox `AUDIT_OUTPUT_DIR/` |
| `generate_word_report` | actif | R+disque | sandbox `AUDIT_OUTPUT_DIR/` |

### DOE et enrichissement — pattern prepare/apply

| Tool | Statut | R/W | `confirm=True` | Notes |
|---|---|---|---|---|
| `extract_doe_records` | actif | R | — | parse Excel/PDF, pas de matching ni écriture |
| `match_doe_to_ifc` | actif | R | — | parse + matching IFC, pas d'écriture |
| `doe_match_only` | actif (historique) | R | — | équivalent à `match_doe_to_ifc` |
| `prepare_doe_enrichment_plan` | actif | R+disque | — | prépare un WritePlan scellé avec pré-calcul des conflits |
| `apply_doe_enrichment_plan` | actif | W | **oui** | écrit les Psets sur les éléments IFC matchés |
| `prepare_doe_enrichment_from_file` | actif (alias) | R+disque | — | alias métier de `prepare_doe_enrichment_plan` |
| `apply_doe_enrichment` | actif (alias) | W | **oui** | alias métier de `apply_doe_enrichment_plan` |

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

### Comportement des wrappers

Les 3 tools mutatifs dépréciés (`create_bcf_topics`, `create_smart_views`,
`apply_suggested_classifications`) ont été transformés en **wrappers
sécurisés** par défaut :

- `legacy_execute=False` (défaut) : prépare un `WritePlan` scellé,
  **aucune écriture BIMData**. L'AMO doit ensuite appeler `apply_*` avec
  `confirm=True`.
- `legacy_execute=True` : ancien comportement (push direct via les
  builders). Marqué d'un `legacy_execute_warning` fort, log INFO côté
  serveur, et appel à `ensure_writes_allowed` côté écriture.

Politique de suppression :

- **Release N** (actuelle) : wrappers fonctionnels, `legacy_execute=False`
  par défaut.
- **Release N+1** : `legacy_execute=True` lèvera un avertissement bloquant.
- **Release de rupture** (v0.5.0) : désenregistrement + suppression des 5 tools dépréciés (`suggest_classifications`, `create_bcf_topics`, `create_smart_views`, `apply_suggested_classifications`, `doe_enrich_model`) et des chemins `legacy_execute`.

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
