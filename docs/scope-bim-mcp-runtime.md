# Scope — extraction d'un runtime MCP réutilisable (D0-bis)

Cadrage de `bim-mcp-runtime`. **Document d'audit : aucun code modifié.**

Le verrou pour un second MCP AMO n'est pas métier. C'est de pouvoir démarrer un
serveur sans recopier 6 273 lignes de bootstrap, session, erreurs, sécurité et
wrappers. Ce document dit ce qui est réellement du moteur, ce qui est de la
colle, et ce qui est l'expérience I3F.

## Inventaire chiffré

`audit_bim/mcp` — **6 273 lignes, 20 fichiers, 46 enregistrements**
(`@mcp.tool` / `@mcp.prompt`).

« Client vif » = occurrence de `I3F` / `CCH` / `CCBIM` / `AVP` / `MOA` / `Tarare`
dans une ligne **hors docstring et hors commentaire**. Même méthode qu'en D0 :
un `grep` brut surcompte du double.

| Fichier | Lignes | Client vif | `@tool` | BIMData | Dépendances domaine |
|---|---:|---:|---:|---:|---|
| `tools_reporting.py` | 1198 | 11 | 4 | 0 | extraction, reporting |
| `tools_session.py` | 746 | 5 | 11 | 27 | classifier, extraction, requirements |
| `tools_audit.py` | 683 | 1 | 7 | 1 | 6 modules |
| `tools_actions.py` | 623 | 2 | 15 | 0 | actions, classifier, doe |
| `tools_query.py` | 540 | 0 | 8 | 1 | classifier, query |
| `security.py` | 377 | 1 | 0 | 18 | — |
| `phase.py` | 301 | 4 | 0 | 0 | enrichment, requirements |
| `prompts.py` | 278 | **32** | 0 | 6 | — |
| `session.py` | 238 | 0 | 0 | 3 | audit, classifier, extraction, requirements |
| `payloads.py` | 210 | 0 | 0 | 0 | classifier |
| `middleware.py` | 160 | 0 | 0 | 0 | — |
| `deprecation.py` | 156 | 0 | 0 | 0 | — |
| `aliases.py` | 152 | 2 | 8 | 0 | — |
| `selection.py` | 144 | 0 | 0 | 0 | audit, query |
| `model_identity.py` | 128 | 0 | 0 | 10 | — |
| `server.py` | 125 | 0 | 1 | 0 | — |
| `app.py` | 93 | 1 | 0 | 0 | — |
| `__main__.py` | 89 | 3 | 0 | 0 | — |
| `tools_profiles.py` | 26 | 0 | 1 | 0 | profiles |

`prompts.py` concentre **32 des 62 occurrences vives** sur 4 % des lignes. C'est
le profil I3F à l'état pur, et c'est net.

## Classement par responsabilité

### A. Runtime générique — 946 lignes

Aucune dépendance au domaine, aucun `@tool`, aucun vocabulaire client vif.

| Responsabilité | Fichier | L. | Ce qui est réutilisable |
|---|---|---:|---|
| Dépréciation d'outils | `deprecation.py` | 156 | `DeprecatedToolInfo`, marqueur dans la réponse, journalisation. **Zéro dépendance** — le plus propre du lot. |
| Middlewares | `middleware.py` | 160 | Masquage d'erreur, binding de session, garde par clé d'API |
| Session / état | `session.py` | 238 | `_Session`, `_SessionStore` (TTL, cap), `_StateProxy`. La **mécanique** est générique ; les **champs** ne le sont pas (voir C) |
| Bootstrap | `app.py` + `server.py` | 218 | Instance partagée, `register_all()` explicite, ré-exports de compat |
| Transport | `__main__.py` | 89 | CLI `stdio` / `http` / `streamable-http` |
| Réponses | `payloads.py` (part.) | ~85 | Seuil overflow 256 Ko, `maybe_dump_to_disk`, `plan_summary_response`, `refused_without_confirm` |

### B. Adaptateur `audit-bim-i3f` — 950 lignes

Infrastructure dans sa forme, domaine dans son contenu. Reste ici en E1 ;
certaines briques pourront remonter plus tard **si** un second consommateur
apparaît — jamais avant.

| Fichier | L. | Pourquoi ce n'est pas du runtime |
|---|---:|---|
| `security.py` | 377 | La mécanique transport/env est générique, mais `is_write_allowed`, `ensure_writes_allowed`, `warn_bimdata_auth_mode`, `assert_startup_config` encodent la **politique d'écriture BIMData** et le contrat d'authentification |
| `phase.py` | 301 | Phases BIM et validation du contexte d'audit — dépend de `requirements` et `enrichment` |
| `selection.py` | 144 | Résolution de sélection d'objets — dépend de `audit` et `query` |
| `model_identity.py` | 128 | Parse d'URL viewer et garde-fou d'identité, **spécifiques à la plateforme BIMData** |

### C. Profil I3F pur — 4 220 lignes

`prompts.py` (278), les cinq modules `tools_*` (3 790, **45 enregistrements**),
`aliases.py` (152). Le vocabulaire, les workflows, les noms d'outils.

**Répartition : 946 / 950 / 4 220**, plus 157 lignes non classées (`__init__`,
`tools_profiles`). Le moteur réutilisable pèse donc **15 % du module** — l'ordre
de grandeur du socle Word (350 l sur 1 170). Ce n'est pas décevant : c'est ce
qu'un second MCP n'aura pas à réécrire pour démarrer.

## Carte des dépendances

```
__main__ ──> app ──> middleware ──> session ──┐
                │                             ├──> audit / classifier /
                └──> register_all ──> tools_* ┘     extraction / requirements
                                        │
                                        ├──> payloads ──> classifier
                                        ├──> phase ──> requirements, enrichment
                                        ├──> selection ──> audit, query
                                        └──> security ──> (BIMData)
prompts ─────────────────────────────────────> (aucune)
deprecation, middleware ─────────────────────> (aucune)
```

**Le point dur est `session.py`.** Sa mécanique — store à TTL, cap de sessions,
proxy `_State` — est générique. Mais `_Session` porte des champs typés domaine :
catalogue d'exigences, client BIMData, snapshot, résultat d'audit. Extraire la
mécanique impose donc de **paramétrer le type d'état**, pas de le déplacer.
C'est le vrai travail de conception d'E1-A ; le reste est mécanique.

## Le point dur suivant : neuf variables `AUDIT_BIM_*`

```
AUDIT_BIM_API_KEY · AUDIT_BIM_REQUIRE_API_KEY · AUDIT_BIM_ENV
AUDIT_BIM_ALLOW_WRITES · AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS
AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM · AUDIT_BIM_ENABLE_LEGACY_ALIASES
AUDIT_BIM_SESSION_TTL_S · AUDIT_BIM_MAX_SESSIONS
```

Deux d'entre elles (`SESSION_TTL_S`, `MAX_SESSIONS`) pilotent du runtime pur.
Les monter telles quelles ferait porter au socle le nom d'un MCP client — la
même erreur que `AUDIT_BIM_SOFFICE` dans `bim-reporting` v0.1.x, honorée en
compatibilité depuis.

**Règle proposée** : le runtime lit un préfixe **paramétrable**
(`RuntimeConfig(env_prefix="AUDIT_BIM")`), avec repli neutre `BIM_MCP`. I3F passe
son préfixe, ses variables ne changent pas, et un nouveau MCP choisit le sien.
Aucune variable en dur dans le socle.

## Contrat proposé — `bim-mcp-runtime` v0.1.0

**Doit savoir**

- enregistrer tools / prompts / resources — `ToolRegistry`, `register_all()` explicite
- fournir des erreurs structurées — `ToolError`, `refused_without_confirm`, masquage
- gérer une session générique — `SessionStore[StateT]`, TTL, cap, binding middleware
- exposer des motifs de validation de paramètres — tolérance JSON-string, bornes, `ToolResult`
- déverser une réponse trop grosse sur disque au-delà d'un seuil configurable

**Ne doit pas connaître**

- `CCH`, `I3F`, `AVP`, `MOA` — ni en chaîne, ni en nom de symbole
- BIMData **comme client** : pas de parse d'URL viewer, pas de politique d'auth,
  pas de `set_active_model(34140, …)`
- de pack de rapport, de workflow d'audit, d'ordre d'outils
- de nom de variable d'environnement en dur

**Types neutres autorisés** : `ActiveTarget`, `SessionState`, `ToolResult`,
`RuntimeConfig`. Ce sont des formes, pas des politiques.

L'accès BIMData reste dans `bimdata-read` et l'adaptateur MCP d'`audit-bim-i3f`.

## Interdits explicites

1. **Aucun workflow I3F dans le runtime.** Pas de `prepare → review → apply`
   câblé, pas d'ordre d'outils, pas de garde-fou d'écriture BIMData.
2. **Aucun `@mcp.tool` dans le runtime.** Il fournit le registre, pas les outils.
   C'est l'équivalent de la règle de D1 : des briques, pas un flux.
3. **Aucun nom de variable d'environnement en dur** — préfixe injecté.
4. **Aucun défaut éditorial.** Les messages destinés à l'utilisateur final
   appartiennent au MCP client (leçon `bim-reporting` v0.1.1, qui imprimait
   « déduit de la maquette » chez tout le monde).

## Séquence proposée

**E1-A — créer `bim-mcp-runtime` v0.1.0.** Périmètre strict de la catégorie A,
en commençant par les trois blocs sans dépendance : `deprecation`, `middleware`,
`SessionStore` paramétré. Plus `RuntimeConfig` à préfixe injecté.

**E1-B — adopter dans `audit-bim-i3f`, sans changer aucun outil visible.**
Garde-fou : `list_tools()` produit exactement le même inventaire qu'avant,
noms et signatures compris.

**E2 — bootstrap et transport** (`app`, `server`, `__main__`) une fois le
runtime éprouvé. Plus risqué : c'est le point d'entrée du serveur.

**E3 — `payloads` générique et motifs de validation**, après E2.

`security.py`, `phase.py`, `selection.py`, `model_identity.py` **restent dans
I3F** : ils encodent des politiques, pas des mécanismes.

## Test décisif d'E1

Le même que pour `bim-reporting`, transposé : **un MCP tiers démarre avec le
runtime, enregistre un outil trivial et répond**, dans un interpréteur séparé
qui échoue si un module `audit_bim` apparaît dans `sys.modules`. C'est le seul
test qui prouve qu'un second MCP peut exister.

## Ce que cet inventaire ne dit pas

Il mesure le vocabulaire et les dépendances d'import, pas la **forme des
outils** — leurs signatures, leur granularité, leur enchaînement implicite.
Comme en D0, la section la plus piégeuse pourrait être celle qui n'affiche
aucun mot client. `session.py` en est l'exemple : zéro occurrence vive, et
pourtant quatre dépendances domaine dans ses champs.
