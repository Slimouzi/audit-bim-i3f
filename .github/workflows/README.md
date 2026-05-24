# GitHub Actions

## `ci.yml` — Intégration continue

Déclenché sur **push** vers `master` et sur **pull request**.

| Job | Détail |
|---|---|
| `lint` | `ruff check` + `ruff format --check` sur `audit_bim/` et `tests/` |
| `test` | Matrix Python 3.10 / 3.11 / 3.12 — `pytest` avec coverage, upload Codecov (3.12 seulement) |
| `build` | `python -m build` + `twine check` — produit sdist + wheel uploadés en artifact CI |

## `release.yml` — Publication PyPI

Déclenché sur **tag `v*`** (ex: `v0.1.0`, `v0.2.0`).

| Job | Détail |
|---|---|
| `build` | Idem CI |
| `publish-pypi` | Upload PyPI via [Trusted Publisher OIDC](https://docs.pypi.org/trusted-publishers/) — pas de token à stocker |
| `create-release` | Crée la GitHub Release avec les artifacts + release notes auto |

### Configuration PyPI Trusted Publisher

À faire **une fois** sur [pypi.org](https://pypi.org/manage/account/publishing/) :

1. Créer le projet `audit-bim-i3f` (ou laisser la 1ère release le créer).
2. Ajouter un *pending publisher* :
   - Owner : `Slimouzi`
   - Repository name : `audit-bim-i3f`
   - Workflow filename : `release.yml`
   - Environment name : `pypi`

Côté GitHub, créer une **environment** `pypi` dans Settings → Environments (sans secrets,
l'OIDC suffit). Optionnel : exiger une review pour la promotion.

### Faire une release

```bash
# Bump version dans pyproject.toml et CHANGELOG.md
git commit -am "chore: release v0.2.0"
git tag v0.2.0
git push origin v0.2.0
```

Le workflow `release.yml` se déclenche, build, publie sur PyPI, crée la GitHub Release.
