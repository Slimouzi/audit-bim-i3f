# GitHub Actions

## `ci.yml` — Intégration continue

Déclenché sur **push** vers `master` et sur **pull request**.

| Job | Détail |
|---|---|
| `lint` | `ruff check` + `ruff format --check` sur `audit_bim/` et `tests/` |
| `test` | Matrix Python 3.10 / 3.11 / 3.12 — `pytest` avec coverage, upload Codecov (3.12 seulement) |
| `build` | `python -m build` + `twine check` — produit sdist + wheel uploadés en artifact CI |

## `release.yml` — GitHub Release

Déclenché sur **tag `audit-bim-i3f-v*`** (ex: `audit-bim-i3f-v0.10.0`).

Le préfixe est celui de la **distribution**, pas du dépôt. Le workflow a
longtemps écouté `v*`, qui ne matchait plus aucun tag réel : il ne se
déclenchait pas, et ne signalait rien — un workflow qui ne part pas n'échoue
jamais.

**Distribution exclusivement via GitHub Releases** — le projet n'est pas
publié sur PyPI. Les artefacts sdist + wheel sont attachés à la release
GitHub et installables soit via téléchargement direct, soit via :

```bash
pip install https://github.com/Slimouzi/audit-bim-mcp/releases/download/audit-bim-i3f-vX.Y.Z/audit_bim_i3f-X.Y.Z-py3-none-any.whl
```

### Jobs

| Job | Détail |
|---|---|
| `lint` / `test` / `integration` / `security-audit` (×2) | Gates qualité dupliqués de `ci.yml` (besoin de garantir que le commit taggé est validé, sans dépendre du `workflow_run`) |
| `build` | `python -m build` + `twine check` — produit sdist + wheel uploadés en artifact |
| `create-release` | Crée la GitHub Release avec les artifacts + release notes auto-générées |

### Faire une release

```bash
# Bump version dans pyproject.toml et CHANGELOG.md, regen lock
vim pyproject.toml          # version = "X.Y.Z"
uv lock                     # regen uv.lock — IMPORTANT pour passer uv lock --check
vim CHANGELOG.md            # nouvelle section [X.Y.Z]
git commit -am "chore(release): X.Y.Z"
git push                    # ouvrir une PR vers master, merger
git checkout master && git pull --ff-only
git tag -a audit-bim-i3f-vX.Y.Z -m "audit-bim-i3f X.Y.Z"
git push origin audit-bim-i3f-vX.Y.Z
```

Le workflow `release.yml` se déclenche sur le push du tag, exécute les
gates de qualité, build les artefacts et crée la GitHub Release avec
les fichiers `.whl` et `.tar.gz` attachés.
