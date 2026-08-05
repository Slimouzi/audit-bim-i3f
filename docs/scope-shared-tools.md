# Inventaire du socle partagé — mesuré sur deux consommateurs

**Lot E6.** Aucun code runtime : ce document et un script d'inventaire
(`scripts/inventory_shared_tools.py`). Il prépare E7, dont le périmètre doit
être décidé sur des dépendances constatées, pas sur une intuition.

## Pourquoi maintenant, et pas avant

Un socle conçu sur un seul appelant n'est pas un socle : c'est une abstraction
de son unique client, qui se révèle fausse au moment où un deuxième arrive.
Depuis E5, `bim_in_motion` existe et tourne. Son inventaire d'imports est donc
la première liste de ce dossier qui ne soit pas un jugement — elle est lue sur
disque, dans un profil qui fonctionne.

**Treize modules sont ainsi prouvés neutres**, au sens fort de « du code que
deux profils déclarent les utilise » :

```
audit_bim.extraction.client               audit_bim.mcp.app
audit_bim.extraction.computed_quantities  audit_bim.mcp.model_identity
audit_bim.extraction.ifc_download         audit_bim.mcp.security
audit_bim.extraction.model_data           audit_bim.mcp.session
audit_bim.extraction.snapshot_cache       audit_bim.safe_paths
audit_bim.extraction.snapshot_health      audit_bim.security.redaction
audit_bim (config)
```

Le compte est passé de dix à treize avec E7 : le socle partagé, déclaré par les
deux profils, tire trois modules de plus. Il faut d'ailleurs compter le socle
comme du code à deux consommateurs, sinon la mutualisation *détruirait* la
preuve qu'elle établit — `bim_in_motion` n'importe plus l'extraction lui-même,
il passe par `tools_shared`.

`extraction.snapshot_health` est le seul qui ait déjà franchi le pas : il vivait
dans le profil I3F faute d'un second appelant, il en a eu un, il a été déplacé
(E5). C'est le seuil d'extraction que ce document cherche à reproduire pour les
outils.

## Méthode

La première tentative classait les outils par présence de mots — « CCH », « AVP »,
« phase ». Elle donnait un signal utile et **deux erreurs de sens contraire** :
`generate_xlsx_annex` ne porte aucun marqueur mais dépend bien du référentiel,
et `set_active_model` — l'outil par lequel on commence — en portait trois, tous
dans sa docstring. Un mot dans un texte ne dit rien de ce dont un outil dépend.

Le script lit donc ce que chaque fonction **utilise** :

1. **les symboles importés qu'elle référence réellement**, imports de module et
   imports différés dans le corps ;
2. **les champs de `_State` qu'elle lit** — les écritures sont exclues.
   `set_active_model` fait `_State.result = None` pour invalider l'audit de la
   cible précédente ; compter cette ligne en ferait un outil « qui a besoin d'un
   audit », soit l'inverse de ce qu'elle signifie ;
3. **les helpers du même module qu'elle appelle**, en fermeture transitive. Sans
   cela, un outil qui délègue à une fonction privée paraît neutre alors que la
   dépendance est une ligne plus bas — c'est exactement le cas de
   `generate_xlsx_annex`, que les deux premières passes classaient à tort.

## Résultat — 45 outils

| Catégorie | Outils | Ce que ça veut dire |
|---|---:|---|
| **Extractibles** | 33 | ne touchent que des briques neutres et des champs de session neutres |
| **Paramétrables** | 0 | — |
| **Irréductiblement I3F** | 12 | dépendent du catalogue d'exigences, des règles CCH ou du pack AVP |

La colonne « paramétrables » est vide, et c'est un résultat, pas un oubli :
aucun outil ne dépend du *narratif* de reporting sans dépendre aussi du
référentiel. Les lots C1/C2 avaient déjà sorti le narratif et la structure vers
le profil ; ce qui reste dans les outils de reporting est le référentiel
lui-même.

### La nuance qui compte : 15 outils au total exigent un amont

Parmi les 33 extractibles, **8 lisent `_State.result` ou `_State.suggestion_store`**
— des données qu'aucun outil ne produit hors d'un audit. Leur code est
générique, leur type vient de briques déjà externalisées, mais il n'y a rien à
lire tant qu'un audit n'a pas tourné, et **le seul moteur câblé aujourd'hui
applique les règles CCH**.

Les compter comme « extractibles » sans le dire promettrait à un second AMO un
socle qui ne lui rend rien. La lecture honnête est donc :

- **25 outils extractibles et autonomes** — utiles à un profil qui n'a ni audit
  ni référentiel ;
- **8 outils extractibles mais suspendus à un amont** : `query_findings`,
  `list_audit_findings`, `get_object_detail`, `list_classification_suggestions`,
  `compare_with_previous_audit`, `prepare_bcf_topics`, `prepare_smart_views_plan`,
  `apply_classification_update_plan` ;
- **12 outils I3F**.

### Les 25 extractibles autonomes

| Domaine | Outils |
|---|---|
| Cible et lecture | `parse_bimdata_target`, `check_bimdata_access`, `verify_active_model`, `download_model_ifc`, `extract_model_snapshot` |
| Requêtes | `filter_bim_objects`, `show_filtered_objects_in_viewer`, `query_bim_data`, `query_bim_preset`, `list_query_presets` |
| Écritures BIMData | `apply_bcf_topics`, `apply_smart_views_plan`, `prepare_smart_view_from_filter_plan`, `prepare_classification_update_plan`, `apply_classifications_from_xlsx`, `list_write_plans`, `update_suggestion_status`, `audit_trail` |
| DOE | `extract_doe_records`, `match_doe_to_ifc`, `prepare_doe_enrichment_plan`, `apply_doe_enrichment_plan`, `doe_match_only` |
| Divers | `enrich_with_public_data`, `list_classification_systems` |

Ces outils s'appuient sur des modules internes qu'aucun second consommateur n'a
encore exercés — `audit_bim.actions`, `audit_bim.doe`, `audit_bim.mcp.payloads`,
`audit_bim.mcp.selection`, `audit_bim.query`, `audit_bim.classifier`,
`audit_bim.enrichment`. Ils sont *présumés* neutres, pas prouvés : c'est la
même situation que `snapshot_health` avant E5.

### Les 12 outils I3F, et leur point d'attache

| Outil | Attache au référentiel |
|---|---|
| `run_audit_tool`, `full_audit` | catalogue d'exigences + phase BIM |
| `import_preliminary_findings` | `audit.rules.load_preliminary_findings` |
| `generate_avp_i3f_pack`, `list_avp_i3f_xls_reports` | pack AVP |
| `generate_word_report` | `reporting.context` + phase |
| `generate_xlsx_annex` | **`_State.phase`, dans un nom de fichier** |
| `project_context_questions`, `set_owner_documents`, `parse_owner_requirements`, `get_catalog_properties` | catalogue, CCH PDF, annexes |
| `set_active_model` | `BIMPhase` |

Deux attaches sont **ténues et méritent d'être signalées** :

- `generate_xlsx_annex` ne dépend du référentiel que par `_State.phase`, lu dans
  `_default_output_paths()` pour composer `audit_<projet>_<phase>_<horodatage>.xlsx`.
  Un nom de fichier, pas une règle métier.
- `set_active_model` ne dépend que du type `BIMPhase`, qui valide un paramètre.

Ce sont des candidats à paramétrage, pas des outils du référentiel. Les traiter
ferait passer le compte de 12 à 10.

## Ce que cela dit pour E7

Le socle réaliste n'est pas « les outils génériques » : c'est **ce qu'un profil
sans référentiel peut faire seul**. Trois cercles, du plus sûr au plus coûteux :

1. **Cible, identité, lecture** — `parse_bimdata_target`, `check_bimdata_access`,
   `verify_active_model`, `extract_model_snapshot`, `download_model_ifc`. Cinq
   outils, tous appuyés sur des modules déjà prouvés par deux consommateurs, et
   dont trois avaient un équivalent réécrit dans `bim_in_motion`. **C'est le seul
   cercle où l'extraction ne repose sur aucune hypothèse.**
   **➜ Extrait en E7** vers `audit_bim/tools_shared/session.py`, déclaré par les
   deux profils. `bim_in_motion` a perdu ses deux réimplémentations ; il ne garde
   que `set_active_target`, son équivalent I3F portant une phase BIM.
2. **Requêtes sur snapshot** — 5 outils, neutres mais reposant sur
   `audit_bim.query` et `audit_bim.mcp.selection`, qu'aucun second consommateur
   n'a exercés.
3. **Écritures et DOE** — 13 outils, cercle le plus large et le moins prouvé.

Le premier cercle était le prolongement direct d'E5 : `bim_in_motion` avait
réimplémenté `verify_active_target` et `extract_model_snapshot` parce qu'aucun
socle ne les portait. C'était la seule duplication dont on ait eu la preuve
qu'elle gênait un second AMO — et E7 l'a supprimée.

L'extraction a révélé une dépendance que l'analyse statique ne pouvait pas
voir : `_State.ensure_client()` écrivait « appelez `set_active_model` » en dur.
Servi depuis le socle, ce message renvoyait les utilisateurs de BIM in Motion
vers un outil que leur serveur n'expose pas. Le nom vient désormais du profil
actif (`McpProfile.target_tool_name`). Un inventaire de dépendances mesure les
imports et les champs lus ; il ne voit pas ce qu'un texte promet.

Les cercles 2 et 3 devraient attendre qu'un profil les demande. Extraire un
outil que personne d'autre n'appelle, c'est déplacer du code en pariant sur son
usage : le pari qu'on a justement décidé de ne plus faire.

## Reproduire l'inventaire

```bash
python scripts/inventory_shared_tools.py          # tableau
python scripts/inventory_shared_tools.py --json   # données brutes
```

Les chiffres de ce document sortent de cette commande. Ils bougeront avec le
code — c'est voulu : un inventaire qu'il faut recopier à la main cesse d'être
vrai au premier commit suivant.
