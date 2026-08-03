# Scope — inventaire structurel des sections Word (PR D0)

Cadrage de `bim-reporting` v0.2.0. **Document d'audit : aucun code modifié.**

Le vocabulaire client est sorti du contrat (PR B, C1, C2). La question n'est
plus « est-ce générique ? » mais : **quelle part de l'orchestration éditoriale
doit devenir socle sans imposer le rapport I3F à tous les AMO ?**

## La décision : primitives de section, pas squelette

Le squelette en dix sections ne monte pas. Un socle qui l'imposerait produirait
le pire cas : **un rapport I3F sans vocabulaire I3F**. Il aurait l'air générique
— tous les tests de vocabulaire passeraient — tout en gardant l'ordre des
sections, le ton AMO, les seuils de décision et la taxonomie des domaines d'un
seul maître d'ouvrage.

C'est exactement l'héritage accidentel que le registre de profils existe pour
empêcher, déplacé d'un cran : du mot vers la forme.

## Ce que sont réellement les dix sections

Chaque section suit le même motif : **un titre, un ou deux paragraphes fixes,
puis un tableau alimenté par les données**. Le tableau est du rendu ; les
paragraphes sont de l'éditorial ; le fait qu'il y ait un tableau *là*, avec
*ces* colonnes, est de l'orchestration.

| # | Section | Lignes | Appels de rendu | Texte fixe (car.) |
|---|---|---:|---:|---:|
| 1 | Page de garde | 127 | 7 | 26 |
| 2 | Synthèse exécutive | 74 | 6 | 389 |
| 3 | Périmètre | 99 | 14 | 235 |
| 4 | Méthodologie | 35 | 4 | 527 |
| 5 | Résultats globaux | 38 | 5 | 0 |
| 6 | Résultats détaillés | 97 | 11 | 537 |
| 7 | Non-conformités | 45 | 5 | 156 |
| 8 | Recommandations | 22 | 3 | 65 |
| 9 | Conclusion | 59 | 1 | 282 |
| 10 | Annexes | 44 | 3 | 474 |

La section 5 est instructive : **zéro texte fixe**, et pourtant elle est
profondément I3F — elle rend la taxonomie `DOMAINS`, six domaines de contrôle
propres au découpage I3F. Un compteur de chaînes ne l'aurait jamais signalée.
C'est la limite de l'inventaire précédent, et la raison d'être de celui-ci.

## Classement des trois natures

### A. Générique réutilisable → `bim_reporting.sections` (v0.2.0)

Motifs répétés, sans jugement éditorial :

| Composant | Occurrences aujourd'hui | Rôle |
|---|---:|---|
| `data_table(doc, headers, rows, *, style)` | 7 `add_table` / 4 `_header_row` | Tableau à en-tête peinte + lignes issues de données |
| `status_cell(cell, label, color)` | 7 `_shade_cell` | Cellule d'état ombrée, texte blanc gras |
| `findings_table(doc, findings, columns, …)` | 2 | Tableau de findings avec coloration par sévérité |
| `bullet_list(doc, items)` | 10 `_kv_or_na` + puces | Listes à puces avec repli |
| `emphasis_paragraph(doc, text, *, size, color)` | 1 | Ligne mise en valeur (« Décision finale : … ») |
| `cover_page(doc, *, title, meta_rows, logo, …)` | 1 (127 l) | Mise en page de couverture — **layout seul**, aucun libellé |
| `document_base(doc, *, margins, font)` | 1 | Marges, style Normal, `rFonts` |

Déjà dans le socle depuis v0.1.1 : `add_heading`, `section_break`, `kpi_table`,
`para_intro`, `kv_or_na`, `pie_chart`, `bar_chart`, `shade_cell`, `hex_to_rgb`.

**~350 lignes** de rendu réellement partageable, sur les 1170 du module.

### B. Orchestration éditoriale I3F → reste dans `audit-bim-i3f`

Ce qui constitue *le rapport d'audit I3F* et non *un rapport d'audit* :

- **`write_word_report`** et **l'ordre des dix sections**. C'est la signature du
  livrable.
- **`DOMAINS`** — la taxonomie en six domaines de contrôle. Un autre AMO peut
  regrouper autrement.
- **`_decision`** et ses **seuils** : `≥ 90 %` sans critique ni majeure →
  « Acceptée » ; `≥ 70 %` sans critique → « Acceptée sous réserve ». **Ce sont
  des seuils contractuels**, pas des constantes techniques. Les monter dans le
  socle imposerait la doctrine d'acceptation d'I3F à tout le monde.
- **`GRAVITY_FR`** (5 niveaux techniques → 4 niveaux métier) et
  **`_STATUS_LABEL`** (`✔ Conforme` / `⚠ Avertissement` / `✖ Non conforme`).
- **Les caps** `MAX_FINDINGS_PER_THEME = 25`, `MAX_NONCONFORMITIES = 80` :
  arbitrages de lisibilité propres au format I3F.
- **Le découpage 6.1 → 6.7** de la section Résultats détaillés.

### C. Contenu de profil → specs existantes (déjà fait, B/C1/C2)

`ReferenceFrameworkSpec`, `ReportNarrativeSpec`, `ClassificationNarrativeSpec`,
`ReportStructureSpec`. Les paragraphes fixes restants des sections 4, 9 et 10
(méthodologie, conclusion, annexes — ~1280 caractères) rejoindront
`ReportNarrativeSpec` **au moment de l'extraction**, pas avant : les déplacer
maintenant sans consommateur recréerait la fausse commande de profil corrigée
en C1.

## Contrat proposé

```python
# bim_reporting.sections — rend des BLOCS, n'assemble rien
data_table(doc, headers, rows, *, style="Light Grid Accent 1") -> Table
status_cell(cell, label, *, color, bold=True) -> None
findings_table(doc, findings, *, columns, severity_colors, max_rows=None) -> Table
bullet_list(doc, items, *, style="List Bullet") -> None
emphasis_paragraph(doc, text, *, size_pt, color_hex) -> Paragraph
cover_page(doc, *, title, subtitle, meta_rows, logo_path=None, wordmark) -> None
document_base(doc, *, margins_cm, font_name, font_size_pt, color_hex) -> None
```

**Le MCP client assemble.** Aucune fonction du socle n'appelle une autre section,
n'impose d'ordre, ni ne connaît de seuil métier. Un socle qui exposerait
`write_report(sections=[...])` serait déjà un squelette : la liste des sections
et leur ordre appartiennent au client.

## Tests exigés à l'extraction (PR D1)

1. **I3F produit le même Word qu'avant** — comparaison paragraphe par paragraphe
   contre un `git worktree` sur `master`, comme en C1 (87 paragraphes, diff vide).
2. **Un profil tiers assemble un Word de trois sections sans importer
   l'orchestrateur I3F** — le test doit échouer si `audit_bim.reporting.word_report`
   apparaît dans ses imports. C'est le seul test qui prouve que le socle n'impose
   pas de squelette.
3. Purity `bim-reporting` inchangée : aucun import MCP, aucun vocabulaire client.

## Ce qu'il ne faut pas faire

- **Ne pas déplacer `word_report.py` entier.** L'orchestrateur reste I3F.
- **Ne pas exposer une fonction « rapport complet » dans le socle**, même
  paramétrable : c'est le squelette sous un autre nom.
- **Ne pas monter `DOMAINS` ni les seuils de `_decision`.** Ils n'ont pas de
  vocabulaire client et passeraient tous les garde-fous existants — c'est
  précisément ce qui les rend dangereux.

## Séquence

**D0** (ce document) → **D1** extraction des composants listés en A, périmètre
strict → **D2** éventuel passage des paragraphes fixes restants dans
`ReportNarrativeSpec`, seulement s'ils ont alors un consommateur.
