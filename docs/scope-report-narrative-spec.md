# Scope — paramétrage du narratif de rapport (PR C)

Inventaire préalable à l'extraction de `word_report.py` / `xlsx_annex.py` /
`context.py` vers `bim-reporting` v0.2.0. **Document d'audit : aucun code
produit modifié.**

Reproductible : `python scripts/inventory_client_strings.py [--comparison]`.

## Ce que la mesure a changé

Un `grep` du vocabulaire client donne **45 occurrences** sur les trois fichiers.
C'est le chiffre trompeur : **25 d'entre elles (56 %) ne partiront jamais**.

| Contexte | Nb | Pourquoi |
|---|---:|---|
| docstring | 14 | Documentation développeur |
| commentaire | 8 | Idem |
| **vive mais non imprimée** | **3** | Voir ci-dessous |
| **imprimée dans le livrable** | **20** | Le vrai périmètre |

Les trois « vives non imprimées » sont le piège :

- `context.py:59` et `:91` — des `Field(description=…)` Pydantic. Documentation
  de schéma, jamais rendue dans un rapport.
- `context.py:331` — la liste de mots-clés `["uniformat", "classification ifc",
  "omniclass"]` qui sert à **reconnaître** un objectif BIM dans un descriptif de
  projet. Elle ne l'écrit pas. La paramétrer par profil serait un contresens :
  un AMO tiers doit lui aussi savoir reconnaître « uniformat » dans un texte
  client.

Un AST naïf les compte comme du narratif à extraire et les envoie vers la
mauvaise destination. Le script distingue les quatre contextes.

## Chiffres

**Périmètre PR C — 45 occurrences, dont 20 imprimées.**

| Fichier | Total | Imprimées |
|---|---:|---:|
| `word_report.py` | 22 | **13** |
| `context.py` | 16 | 5 |
| `xlsx_annex.py` | 7 | 2 |

| Nature (imprimées) | Nb |
|---|---:|
| `reference_framework` — CCH, CCBIM, chapitres, annexes | 9 |
| `classification_system` — UniFormat, Omniclass, CCI, table 3F | 4 |
| `owner` — I3F, codification I3F | 4 |
| `moa_role` — MOA, MOE | 3 |

| Destination proposée | Nb |
|---|---:|
| `ReportNarrativeSpec` | 11 |
| `ClassificationNarrativeSpec` | 4 |
| profil I3F (`owner_name`, déjà existant) | 3 |
| `ReportStructureSpec` | 2 |

**Paramétrable sans changer le livrable : 18. Change la structure du classeur : 2.**

## Le détail des 20

### `ReportNarrativeSpec` — 11

Phrases et fragments référençant le document contractuel ou les rôles MOA/MOE.

| Emplacement | Extrait |
|---|---|
| `word_report.py:390` | `"Référence du CCBIM utilisé"` (libellé de couverture) |
| `word_report.py:658` | `"• CCBIM appliqué : …"` |
| `word_report.py:1092` | `"… Étage → Espace (CCH chap. 6.1)"` |
| `word_report.py:1095` | `"… listes fermées du CCH chap. 6.3"` |
| `word_report.py:1098` | `"reprendre le nommage des pièces (listes fermées, CCH chap. 6.3)"` |
| `word_report.py:1138-1139` | `"l'écart au CCH est important"`, `"revue conjointe MOA / MOE"` |
| `context.py:434` | `rule_source="Annexe « Nommage » + programme MOA"` |
| `context.py:456` | `"extraites (BIMData + documents MOA)."` |
| `context.py:474` | `"analysés (au-delà des exigences du CCH)."` |
| `context.py:477` | `"Cahier des Charges BIM (PDF) : non fourni ou non chargé."` |

**5 des 11 sont des valeurs de `_THEME_HINTS`** (`word_report.py:1087-1099`), un
dict indexé par `Theme` — un énuméré de `bim-core`, donc générique — dont les
valeurs citent des chapitres CCH. Ce n'est pas une phrase à trouer : c'est une
**table de correspondance qui appartient au profil**. `ReportNarrativeSpec` doit
la porter entière, sinon on obtient un dict à moitié paramétré, plus difficile à
lire que l'original.

### `ClassificationNarrativeSpec` — 4

| Emplacement | Extrait |
|---|---|
| `word_report.py:859-860` | `"UniFormat II par défaut ; Omniclass / CCI / table interne 3F selon le référentiel"` |
| `word_report.py:1099` | `"compléter la classification IFC (UniFormat / Omniclass / table 3F)"` |
| `context.py:408` | `"Présence d'une classification (UniFormat II par défaut)"` |

**« table interne 3F » n'est ni le document ni le maître d'ouvrage** : c'est un
**système de classification propriétaire**, au même rang qu'UniFormat et
Omniclass. Il ne se dérive d'aucun champ existant. Le profil déclare
`default_classification_system="UniFormat II"` — un scalaire, insuffisant : il
faut la liste des systèmes cités, avec celui qui fait défaut.

### Profil I3F (`owner_name`) — 3

| Emplacement | Extrait |
|---|---|
| `word_report.py:868` | `"les listes fermées et la codification I3F (CCH chap. 6.3)."` |
| `word_report.py:1060` | `"• Référentiel CCH I3F : documents transmis par la maîtrise …"` |
| `word_report.py:1097` | `Theme.NAMING_ZONE: "… (codification I3F, CCH chap. 6.3)"` |

Le champ existe déjà (`McpProfile.owner_name = "I3F"`) et a servi en PR B. Deux
de ces trois lignes **mélangent deux axes** (`CCH` + `I3F`) : elles relèvent à la
fois de `ReportNarrativeSpec` et du profil. C'est le motif qui a produit la
régression de PR B — substituer `short_name` là où la phrase cite le maître
d'ouvrage. Les traiter ligne par ligne, pas par recherche-remplacement.

### `ReportStructureSpec` — 2

| Emplacement | Extrait | Effet |
|---|---|---|
| `xlsx_annex.py:42` | `("Référence CCH", 14)` | En-tête de colonne |
| `xlsx_annex.py:193` | `wb.add_worksheet("Référentiel I3F")` | Nom d'onglet |

Ces deux-là ne changent pas une phrase : ils changent **le gabarit que la MOA
ouvre**, compare d'un audit à l'autre, et sur lequel des macros ou des tableaux
croisés peuvent s'appuyer côté client. Un nom d'onglet est une clé, pas du texte.

## Comparaison — pack AVP (hors périmètre)

**119 occurrences, dont 31 imprimées.** À traiter *plus tard*, et différemment :
c'est un pack client légitime, 22 des 31 imprimées sont des `owner` qui ont
vocation à y rester.

Un point mérite d'être remonté : **6 occurrences `project_sample`** —
`example_filename="260211 Tarare 0546L Contrôle Maquettes AVP.xlsx"` et
équivalents dans `avp_report_catalog.py`. C'est la dette « vocabulaire Tarare »
déjà identifiée : ces noms d'exemple sont lus par les agents, qui les recopient.
**Deux contiennent une coquille — « Tatare »** (`avp_report_catalog.py:179`
et `:323`), recopiée telle quelle depuis un fichier réel. Correction triviale,
hors périmètre PR C, mais à ne pas perdre.

## Décision proposée : Word d'abord, Excel ensuite

**PR C1 — narratif Word uniquement (18 occurrences).**
`ReportNarrativeSpec` + `ClassificationNarrativeSpec` + usage de `owner_name`.
Aucun changement de structure de livrable ; se recette par comparaison de texte,
exactement comme PR B — et l'instantané figé des chaînes I3F existe déjà.

**PR C2 — structure Excel (2 occurrences).**
`ReportStructureSpec` pour l'en-tête de colonne et le nom d'onglet. Deux lignes
de code, mais une recette différente : il faut ouvrir le classeur produit et
vérifier qu'aucun usage aval côté MOA ne casse.

La donnée soutient l'instinct : **2 occurrences seulement touchent la structure**,
donc les séparer ne coûte presque rien en découpage, alors que les mélanger
ferait passer toute la PR sous le régime de recette du livrable MOA — le plus
lent et le plus risqué.

Ordre : **C1 → recette texte → C2 → recette classeur → extraction v0.2.0.**

## Ce que l'inventaire ne dit pas

Il compte le **vocabulaire client**, pas la **structure narrative**. Les sections
du rapport Word (`_write_section_methodology`, `_write_section_conclusion`, …)
restent I3F par leur enchaînement et leur ton, même sans citer « CCH ». Le
mesurer demande une lecture, pas un script — c'est le sujet de l'extraction
elle-même, pas de ce cadrage.
