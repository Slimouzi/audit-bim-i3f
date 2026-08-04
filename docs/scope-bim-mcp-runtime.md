# Scope — extraction d'un runtime MCP réutilisable (D0-bis)

Cadrage de l'extraction du runtime MCP. Ce document a servi de base de décision
à **E1**, qui est livré ; il reste la référence pour E2 et E3.

Le verrou pour un second MCP AMO n'est pas métier. C'est de pouvoir démarrer un
serveur sans recopier 6 273 lignes de bootstrap, session, erreurs, sécurité et
wrappers. Ce document dit ce qui est du moteur, ce qui est de la colle, et ce
qui est l'expérience I3F.

## État — E1 est livré

| | |
|---|---|
| `bim-mcp-runtime` | **v0.1.2**, adopté par `audit-bim-i3f` |
| Surface MCP | **inchangée** : 46 tools, leurs paramètres, 1 prompt |
| Mécanique de session | `SessionStore[_Session]` + `SessionBinding` du moteur |
| Défaut TTL / plafond | **corrigé dans le runtime** (v0.1.1 puis v0.1.2) |

Le défaut de configuration mérite d'être retenu, parce qu'il a fallu deux
correctifs. `RuntimeConfig` capturait l'environnement à la construction
(v0.1.1) ; une fois rendu paresseux, `SessionStore` capturait toujours son
résultat dans son ``__init__`` (v0.1.2). Un magasin déclaré au niveau module
ignorait donc toute variable posée ensuite — sans erreur, en appliquant
simplement ses défauts.

**Corriger un seul des deux niveaux ne corrigeait rien.** Une lecture paresseuse
n'est effective que si personne en aval n'en capture le résultat — et vérifier
qu'une valeur s'affiche ne prouve pas qu'elle agit. Ce gel existait déjà avant
l'extraction : le moteur était le bon endroit pour le corriger une fois pour
tous les consommateurs.

## Inventaire chiffré — la mesure qui a fondé E1

Ces chiffres ont servi à découper E1 ; ils restent la base de décision pour E2
et E3. Les catégories n'ont pas bougé : E1 n'a extrait que la mécanique de
session, soit une partie de la catégorie A.

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

**Le point dur était `session.py`, et il est résolu.** Sa mécanique — store à
TTL, plafond, proxy `_State` — est générique, mais `_Session` porte des champs
typés domaine : catalogue d'exigences, client plateforme, snapshot, résultat
d'audit. Extraire imposait donc de **paramétrer le type d'état**, pas de le
déplacer.

C'est ce que fait `SessionStore[StateT]` : il reçoit une fabrique et n'inspecte
jamais ce qu'elle produit. `_Session` est resté côté I3F.

Ce fichier illustre la limite d'un inventaire par comptage : **zéro vocabulaire
client vif, et pourtant quatre dépendances domaine**. Aucun compteur ne l'aurait
signalé.

## Neuf variables `AUDIT_BIM_*` — résolu par préfixe injecté

```
AUDIT_BIM_API_KEY · AUDIT_BIM_REQUIRE_API_KEY · AUDIT_BIM_ENV
AUDIT_BIM_ALLOW_WRITES · AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS
AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM · AUDIT_BIM_ENABLE_LEGACY_ALIASES
AUDIT_BIM_SESSION_TTL_S · AUDIT_BIM_MAX_SESSIONS
```

Deux d'entre elles (`SESSION_TTL_S`, `MAX_SESSIONS`) pilotent du runtime pur.
Les monter telles quelles aurait fait porter au socle le nom d'un MCP client —
la même erreur que `AUDIT_BIM_SOFFICE` dans `bim-reporting` v0.1.x, honorée en
compatibilité depuis.

**Règle appliquée** : le runtime lit un préfixe **injecté**
(`RuntimeConfig(env_prefix="AUDIT_BIM")`), avec repli neutre. I3F passe le sien,
ses variables n'ont pas changé, et un nouveau MCP choisira les siennes. Aucun
nom d'environnement en dur dans le socle — un test l'interdit, en visant la
**lecture** (`getenv` à clé littérale) plutôt que la forme du littéral.

## Contrat livré — `bim-mcp-runtime` v0.1.2

**Sait faire** — API réellement exposée :

| Domaine | Symboles |
|---|---|
| Sessions | `SessionStore[StateT]`, `SessionBinding`, `DEFAULT_SESSION_TTL_S`, `DEFAULT_MAX_SESSIONS` |
| Résultats | `ToolResult` (`ok` / `error` / `needs_context`), `ActiveTarget` |
| Erreurs | `ToolError`, `MissingContextError`, `ConfirmationRequiredError`, `PermissionDeniedError`, `to_tool_result`, `scrub` |
| Registre | `ToolRegistry`, `Registration`, `DuplicateRegistrationError` |
| Config | `RuntimeConfig`, `DEFAULT_ENV_PREFIX` |

**Pas encore livré, et volontairement** : déversement d'une réponse trop grosse
sur disque, tolérance JSON-string sur les paramètres, adaptateurs d'erreur plus
riches. Ces primitives figuraient dans le contrat *proposé* de D0-bis ; elles
n'ont pas de second consommateur, donc elles attendent E4. Les inscrire au socle
« au cas où » reproduirait la fausse commande de profil corrigée ailleurs — un
symbole déclaré que personne ne lit.

**Ne connaît pas**

- `CCH`, `I3F`, `AVP`, `MOA` — ni en chaîne, ni en nom de symbole
- BIMData **comme client** : pas de parse d'URL viewer, pas de politique d'auth,
  pas de `set_active_model(34140, …)`
- de pack de rapport, de workflow d'audit, d'ordre d'outils
- de nom de variable d'environnement en dur

**Types neutres livrés** : `ActiveTarget`, `ToolResult`, `RuntimeConfig`. Ce sont
des formes, pas des politiques. (`SessionState` n'existe pas comme type : l'état
est un paramètre générique, ce qui est plus fort — le moteur n'en connaît même
pas la forme.)

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

## Séquence

**E1 — livré.** `bim-mcp-runtime` v0.1.2 : `SessionStore[StateT]`, `SessionBinding`,
`ToolResult`, `ActiveTarget`, `ToolError` et sa conversion, `ToolRegistry`,
`RuntimeConfig` à préfixe injecté. Adopté sans changer un nom d'outil.

**E2 — isoler le profil I3F pur.** Déplacer prompts, tools AVP/audit/reporting et
aliases sous `audit_bim/profiles/i3f/`, pour que `audit_bim/mcp` ne porte plus
que bootstrap et câblage. **Aucun nom d'outil, de prompt, d'alias ou de
paramètre ne doit changer** ; le garde-fou est le dump MCP strict avant/après,
comme en E1.

**E3 — registre de profil au runtime.** `server.py` charge un profil déclaré au
lieu d'importer I3F partout. Le profil expose prompts, tools, aliases, préfixe
d'environnement et métadonnées AMO. I3F reste le profil par défaut.

**E4 — enrichir `bim-mcp-runtime`, seulement après adoption réelle.** Aucune
primitive n'est ajoutée sur hypothèse : ce qui n'a pas de second consommateur
attend. Les interdits restent entiers.

## Le test décisif, et ce qu'il a donné

Transposé de `bim-reporting` : la pureté du moteur **installé** est vérifiée
dans un interpréteur séparé, qui échoue si un module `audit_bim` apparaît dans
`sys.modules`, si le paquet contient `AUDIT_BIM`, ou s'il déclare un outil. Sa
non-vacuité est prouvée par un second script qui importe le serveur exprès.

C'est ce qui prouve qu'un second MCP peut exister — et il passe.

## Décisions actées

Tranchées pendant E1, et opposables aux lots suivants :

1. **Aucun `@mcp.tool` dans le runtime.** Il fournit le registre, pas les outils.
   Un moteur qui livrerait un outil livrerait une expérience.
2. **`AUDIT_BIM_*` reste côté I3F.** Le runtime lit un préfixe **injecté** ; le
   serveur passe le sien, donc aucun déploiement existant ne bouge et un
   nouveau MCP choisit ses propres noms.
3. **`model_identity.py` et `security.py` restent des adaptateurs I3F.** Parse
   d'URL viewer, politique d'écriture, contrat d'authentification : ce sont des
   **politiques**, pas des mécanismes. Le runtime n'en porte aucune.
4. **`_Session` et ses champs restent côté I3F.** Catalogue d'exigences, client
   plateforme, snapshot, résultat d'audit. Le moteur fait vivre des sessions
   sans savoir ce qu'elles contiennent — c'est cette ignorance qui le rend
   réutilisable.

## Ce que cet inventaire ne dit pas

Il mesure le vocabulaire et les dépendances d'import, pas la **forme des
outils** — leurs signatures, leur granularité, leur enchaînement implicite.
Comme en D0, la section la plus piégeuse pourrait être celle qui n'affiche
aucun mot client. `session.py` en est l'exemple : zéro occurrence vive, et
pourtant quatre dépendances domaine dans ses champs.
