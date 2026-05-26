# Migration vers le pattern `prepare → apply`

Ce document détaille la transition des tools mutatifs historiques vers le
workflow `prepare → review → apply` introduit par la PR #8 et finalisé
par la PR refactor des tools dépréciés.

## Pourquoi les anciens tools sont dépréciés

Les tools `create_bcf_topics`, `create_smart_views` et
`apply_suggested_classifications` exécutaient directement des écritures
BIMData en un seul appel. Cela posait trois problèmes :

1. **Pas de revue intermédiaire** : un agent LLM pouvait pousser des
   centaines de classifications sans validation humaine.
2. **Pas de scellé** : si la cible BIMData changeait entre la décision et
   l'exécution, on écrivait dans le mauvais modèle sans s'en apercevoir.
3. **Pas de journal d'audit** : impossible de rejouer ou expliquer une
   opération a posteriori.

Le pattern `prepare → apply` répond à ces trois points :

- **`prepare_*`** calcule un `WritePlan` complet et le **scelle SHA-256**
  sous `AUDIT_OUTPUT_DIR/plans/<plan_id>.json`. Aucune écriture BIMData.
- L'humain ou l'agent **revoit le plan** (chemin retourné dans
  `plan_path`).
- **`apply_*`** recharge le plan, vérifie son intégrité + la cible
  BIMData courante, exige `confirm=True`, exécute, puis journalise.

## Mapping ancien → nouveau

### BCF Topics

**Avant** :

```python
create_bcf_topics(prefix="I3F Audit — ", dry_run=False)
```

**Après** :

```python
# 1. Optionnel : filtrer le périmètre.
list_audit_findings(filter={"severity_min": "HIGH"})

# 2. Préparer le plan (aucune écriture BIMData).
prepare_bcf_topics(
    finding_filter={"severity_min": "HIGH"},
    prefix="I3F Audit — ",
)
# → {"plan_id": "...", "plan_path": "/tmp/.../plans/<uuid>.json", ...}

# 3. Vérifier le plan (humain ou agent).
list_write_plans(limit=5)

# 4. Exécuter avec confirmation explicite.
apply_bcf_topics(plan_path="/tmp/.../plans/<uuid>.json", confirm=True)
# → ActionResult{succeeded, failed, impacted_uuids, errors}
```

Alias plus parlant côté AMO :

```python
prepare_bcf_from_findings(finding_filter={"severity_min": "HIGH"})
apply_bcf_plan(plan_path="...", confirm=True)
```

### Smart Views

**Avant** :

```python
create_smart_views(prefix="I3F Audit — ", dry_run=False)
```

**Après** :

```python
prepare_smart_views_plan(finding_filter=None)
apply_smart_views_plan(plan_path="...", confirm=True)
```

Alias :

```python
prepare_smartviews_from_findings()
apply_smartviews_plan(plan_path="...", confirm=True)
```

### Classifications IFC

**Avant** :

```python
apply_suggested_classifications(min_confidence=0.5, dry_run=False)
```

**Après** :

```python
# 1. Voir les suggestions filtrables.
list_classification_suggestions(filter={"min_confidence": 0.85})

# 2. Accepter / rejeter par UUID.
update_suggestion_status(element_uuid="W1", status="accepted")
update_suggestion_status(element_uuid="W2", status="rejected")

# 3. Préparer le plan (ne traite que les ACCEPTED par défaut).
prepare_classification_update_plan()

# 4. Exécuter avec confirmation.
apply_classification_update_plan(plan_path="...", confirm=True)
```

Alias :

```python
prepare_classification_corrections()
apply_classification_corrections(plan_path="...", confirm=True)
```

## Période de transition — `legacy_execute`

Pour ne pas casser les scripts existants, les 3 wrappers acceptent un
paramètre `legacy_execute: bool = False` :

- `legacy_execute=False` (défaut) : pattern prepare/apply.
- `legacy_execute=True` : ancien comportement (push direct), avec :
  - log INFO côté serveur,
  - `legacy_execute_warning` fort dans le retour,
  - appel à `ensure_writes_allowed`.

Exemple migration progressive :

```python
# Étape 1 (release N) — code actuel, fonctionne mais marqué deprecated.
create_bcf_topics(legacy_execute=True, dry_run=False)
# → {"deprecated": True, "use_instead": "prepare_bcf_topics + apply_bcf_topics", ...}

# Étape 2 (avant release N+1) — migration côté script.
prep = prepare_bcf_topics()
apply_bcf_topics(plan_path=prep["plan_path"], confirm=True)
```

## Politique de suppression

| Release | Comportement |
|---|---|
| **N** (actuelle) | Wrappers dépréciés conservés. `legacy_execute=False` par défaut. |
| **N+1** | `legacy_execute=True` lève un warning bloquant si exécuté sur HTTP transport. |
| **N+2** (v0.3.0) | Suppression complète des 4 tools dépréciés. |

## Lecture seule : `suggest_classifications`

Le tool `suggest_classifications` est purement de lecture (analyse). Il
n'a pas de mode `legacy_execute` — c'est un **alias historique** qui
duplique fonctionnellement `list_classification_suggestions` avec un
format de sortie différent.

**Avant** :

```python
suggest_classifications(min_confidence=0.4, top_n=3, limit=200)
# → list[dict] (legacy, statut interne non géré)
```

**Après** :

```python
list_classification_suggestions(filter={"min_confidence": 0.4, "limit": 200})
# → {items, total, next_offset, store_counts}
# Bonus : statut accepted/rejected/applied persisté en session,
# filtres avancés (proposed_level_3, only_mismatches, etc.)
```

## Garanties de sécurité ajoutées par le pattern

| Garantie | Implémentation |
|---|---|
| Aucune écriture sans plan validé + `confirm=True` | Tous les `apply_*` retournent `{"refused": True}` sans `confirm=True` |
| Plan altéré rejeté | SHA-256 du payload canonique (sorted keys, hors `plan_id`/`created_at`) |
| Cible changée entre prepare et apply rejetée | `validate_target` compare `cloud_id`/`project_id`/`model_id` (str-cast) |
| Journal append-only | `WriteJournal` JSONL sous `AUDIT_OUTPUT_DIR/write_log/journal.jsonl` |
| Erreurs scrubées | `redact_secrets` appliqué automatiquement dans `ActionResult.errors` et `WriteJournal.extra` |
| Sandbox `load_plan` | refus chemins absolus hors `AUDIT_OUTPUT_DIR`, refus `..` |
| Tools MCP < 1 MB | overflow disque automatique à 256 KB |

## Références

- [docs/mcp_tools.md](mcp_tools.md) — référence complète des 40 tools
- [audit_bim/mcp/deprecation.py](../audit_bim/mcp/deprecation.py) —
  registre central `DEPRECATIONS`
- [audit_bim/actions/plans.py](../audit_bim/actions/plans.py) — scellé +
  validation de cible
- [audit_bim/security/write_journal.py](../audit_bim/security/write_journal.py)
  — journal append-only
- [audit_bim/security/redaction.py](../audit_bim/security/redaction.py)
  — redaction des secrets
