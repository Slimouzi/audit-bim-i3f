# Changelog

Toutes les évolutions notables de ce projet sont consignées dans ce fichier.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versioning
[SemVer](https://semver.org/lang/fr/).

## [Unreleased]

## [0.1.0] — 2026-05-24

Première version publiable du MCP `audit-bim-i3f`.

### Ajouté

- **Architecture en 7 agents** orchestrés via FastMCP :
  - `requirements/` — parseurs des 3 documents MOA (CCH PDF + 2 annexes XLSX).
  - `extraction/` — client BIMData authentifié (OAuth2 / API Key / Bearer)
    avec dénormalisation `/element/raw`.
  - `audit/` — moteur de 6 règles : spatial, naming, classifications,
    properties (avec validateurs), uniqueness (identifiant équipement),
    lists. Hiérarchie IFC parent ↔ sous-classes (IfcWall ↔
    IfcWallStandardCase).
  - `classifier/` — suggester UniFormat II (heuristique multi-signaux),
    applier (création + liaison via API BIMData), reader XLSX modifié par
    l'auditeur. 4 référentiels (UF II / Omniclass / CCS / Table 3F).
  - `reporting/` — Word (python-docx + matplotlib) + XLSX (xlsxwriter)
    avec colonnes Suggestion + Confiance.
  - `bcf/` — BCF Topics 2.1 (workflow d'issues, panneau BCF Issues).
  - `smartview/` — Smart Views natives BIMData (panneau Smart Views) avec
    payload minimal aligné UI viewer.
  - `doe/` — agent DOE → IFC : extracteur Excel, matcher 4 stratégies
    (GUID/Tag/Nom fuzzy/localisation), enricher Psets.
- **19 tools MCP** : context_questions, set_owner_documents,
  parse_owner_requirements, get_catalog_properties,
  list_classification_systems, set_active_model, extract_model_snapshot,
  run_audit_tool, query_findings, generate_xlsx_annex,
  generate_word_report, suggest_classifications,
  apply_suggested_classifications, apply_classifications_from_xlsx,
  doe_match_only, doe_enrich_model, create_bcf_topics,
  create_smart_views, full_audit.
- **4 transports MCP** : stdio (défaut), http, sse, streamable-http
  (via flag `--transport`).
- **Persona AMO BIM** France (loi MOP, ISO 19650, NF EN 17412-1, CCH I3F)
  exposée comme prompt MCP `amo_bim_i3f`.
- **6 exemples d'intégration** : Claude Desktop, OpenAI Agents SDK,
  LangChain, CrewAI, Node.js (stdio + HTTP), Python direct.
- **167 tests pytest** sur les modules purs (validators, ifc_hierarchy,
  catalog, systems, suggester, doe/*, audit/engine, reporting/theming,
  extraction/normalizer).
- **Palette couleur sévérité** feux tricolores standard (CRITICAL rouge
  foncé / HIGH rouge / MEDIUM orange / LOW vert / INFO bleu).

### Découvertes API documentées (mémoire projet)

- Base URL BIMData : `https://api.bimdata.io` (pas `/v1`).
- OpenAPI spec : `https://api.bimdata.io/doc/schema` (auth requise).
- Smart View = BCF FullTopic avec `format: "bimdata-smartview"` dans le
  body (et non en query param).
- API Key BIMData scopée à un cloud unique.
