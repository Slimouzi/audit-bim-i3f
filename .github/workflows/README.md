# GitHub Actions

## `ci.yml` — Intégration continue

Déclenché sur **push** vers `master` et sur **pull request**.

| Job | Détail |
|---|---|
| `lint` | `ruff check` + `ruff format --check` sur `audit_bim/` et `tests/` |
| `test` | Matrix Python 3.10 / 3.11 / 3.12 — `pytest` avec coverage, upload Codecov (3.12 seulement) |
| `build` | `python -m build` + `twine check` — produit sdist + wheel uploadés en artifact CI |

## `release.yml` — GitHub Release

Déclenché sur **tag `audit-bim-mcp-v*`** (ex: `audit-bim-mcp-v0.11.0`), et
manuellement via **`workflow_dispatch`** pour un dry-run.

Le préfixe est celui de la **distribution**, pas du dépôt. Le workflow a
longtemps écouté `v*`, qui ne matchait plus aucun tag réel : il ne se
déclenchait pas, et ne signalait rien — un workflow qui ne part pas n'échoue
jamais.

**Distribution exclusivement via GitHub Releases** — le projet n'est pas
publié sur PyPI. Les artefacts sdist + wheel sont attachés à la release
GitHub et installables soit via téléchargement direct, soit via :

```bash
pip install https://github.com/Slimouzi/audit-bim-mcp/releases/download/audit-bim-mcp-vX.Y.Z/audit_bim_mcp-X.Y.Z-py3-none-any.whl
```

### Jobs

| Job | Détail |
|---|---|
| `lint` / `test` / `integration` / `security-audit` (×2) | Gates qualité dupliqués de `ci.yml` (besoin de garantir que le commit taggé est validé, sans dépendre du `workflow_run`) |
| `build` | `python -m build` + `twine check` — produit sdist + wheel uploadés en artifact |
| `create-release` | Crée la GitHub Release avec les artifacts + release notes auto-générées. **Conditionné à `github.event_name == 'push' && startsWith(github.ref, 'refs/tags/audit-bim-mcp-v')`** |

### Dry-run — et sa limite, qui n'est pas un détail

`workflow_dispatch` exécute **toute la recette sauf la publication** : les
gates, les pins first-party, le build, `twine check`, l'installation du wheel
en venv vierge, `pip check` et le smoke CLI.

`create-release` est **exclu par construction**, pas par prudence de
l'opérateur. La condition teste **l'événement autant que la ref** :

```yaml
if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/audit-bim-mcp-v')
```

Tester la seule ref ne suffisait pas, et c'est un piège qui s'est refermé une
fois : `gh workflow run --ref` accepte **une branche ou un tag**. Un dispatch
lancé sur un tag de release aurait satisfait un
`startsWith(github.ref, 'refs/tags/')` — le chemin censé ne jamais publier
aurait publié. Une garde peut être présente, lisible, et fausse.

Sur un dispatch, le job est donc `skipped`, ce qui est vérifiable sur le run.

**Ce que le dry-run ne prouvera jamais.** Un `create-release` qui tourne n'est
plus un dry-run, c'est une publication. Trois énoncés à tenir ensemble :

1. `workflow_dispatch` exécute toute la recette **sauf** la publication ;
2. un push de tag `audit-bim-mcp-v*` reste **le seul chemin** vers
   `create-release` ;
3. **le prochain vrai tag sera encore le premier test réel de la création de
   GitHub Release.**

Le dry-run réduit le risque au dernier job ; il ne le supprime pas. Le prétendre
serait exactement la panne que ce workflow a déjà connue — croire publié ce qui
ne l'est pas.

### Faire une release

**Avant tout bump : lancer le dry-run** (onglet Actions → Release → *Run
workflow*, sur `master`) et vérifier que `smoke-install` passe et que
`create-release` est bien `skipped`.

```bash
# Bump version dans pyproject.toml et CHANGELOG.md, regen lock
vim pyproject.toml          # version = "X.Y.Z"
uv lock                     # regen uv.lock — IMPORTANT pour passer uv lock --check
vim CHANGELOG.md            # nouvelle section [X.Y.Z]
git commit -am "chore(release): X.Y.Z"
git push                    # ouvrir une PR vers master, merger
git checkout master && git pull --ff-only
git tag -a audit-bim-mcp-vX.Y.Z -m "audit-bim-mcp X.Y.Z"
git push origin audit-bim-mcp-vX.Y.Z
```

Le workflow `release.yml` se déclenche sur le push du tag, exécute les
gates de qualité, build les artefacts et crée la GitHub Release avec
les fichiers `.whl` et `.tar.gz` attachés.
