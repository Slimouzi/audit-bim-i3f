# Politique de sécurité

## Vulnérabilités

Pour signaler une vulnérabilité, ouvrir un avis sécurité privé sur
GitHub (`Security` → `Report a vulnerability`) plutôt qu'une issue
publique.

## Périmètre durci

Le serveur MCP audit-bim-i3f a été passé à plusieurs revues de
sécurité ; cf. `audit_bim/mcp/security.py` et `audit_bim/safe_paths.py`
pour les détails. Les axes couverts :

- **Auth applicative** sur les transports réseau (`AUDIT_BIM_API_KEY`,
  fail-fast au démarrage en prod).
- **Isolation d'état** par session client MCP (`ContextVar` + middleware).
- **Sandbox filesystem** sur les lectures (`AUDIT_INPUT_DIR`) et les
  écritures (`AUDIT_OUTPUT_DIR`).
- **Politique d'écriture BIMData** (`AUDIT_BIM_ALLOW_WRITES`, défaut
  read-only sur transport réseau).
- **Refus du Bearer en paramètre MCP** sur transport réseau
  (`AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM`, défaut `false` en HTTP/SSE).
  Le paramètre `access_token` des tools reste réservé au mode
  stdio local/dev — en HTTP exposé, configurer `BIMDATA_API_KEY`
  ou `BIMDATA_CLIENT_ID`+`…_SECRET` côté serveur.
- **Anti-injection** de formule sur les exports XLSX
  (`Workbook(strings_to_formulas=False)` + neutralisation `'` sur les
  valeurs externes).
- **Bornes OCR** (`AUDIT_MAX_PDF_PAGES`, `AUDIT_OCR_TIMEOUT_S`, DPI
  capé, rasterisation page-par-page).
- **Retries HTTP** bornés et limités aux méthodes idempotentes
  (GET/HEAD).

## Audit CVE — politique d'ignore

Le job CI `security-audit` exécute `pip-audit` à chaque push contre les
versions **figées dans `uv.lock`** (via `uv export --format
requirements-txt`). L'audit est donc bit-à-bit reproductible : tant
que `uv.lock` ne change pas, les résultats pip-audit ne dépendent ni
de la météo du résolveur, ni de packages installés différemment en
local. Une vuln trouvée fait sortir le job en exit code non-zéro et
bloque le build.

Un job complémentaire `security-audit-ocr` couvre les extras `[ocr]`
(pytesseract, pdf2image, Pillow), pas inclus dans la résolution
standard.

### Mettre à jour les dépendances

```bash
uv lock              # regénère uv.lock avec les dernières versions compatibles
git add uv.lock
git commit -m "chore(deps): bump via uv lock"
```

La CI bloque toute PR qui modifie `pyproject.toml` sans regénérer
`uv.lock` (via `uv lock --check`). Quand une vuln est remontée
sans correctif disponible immédiat, on peut l'ignorer **temporairement**
en suivant cette procédure :

1. **Justifier l'exception**. Ouvrir une issue GitHub avec :
   - identifiant CVE / GHSA,
   - paquet et version impactés,
   - **raison** pour laquelle l'application n'est pas exposée (ex.
     fonction non appelée, pré-requis non rempli),
   - **date d'expiration** de l'exception (par défaut 30 jours).

2. **Ajouter l'ignore dans la CI**. Éditer `.github/workflows/ci.yml`
   et `.github/workflows/release.yml` :

   ```yaml
   - run: pip-audit --skip-editable --format columns \
       --ignore-vuln GHSA-xxxx-yyyy-zzzz  # voir issue #N — expire YYYY-MM-DD
   ```

3. **Revoir avant l'expiration**. Quand la date arrive, soit :
   - le fix amont est dispo → retirer l'ignore + bumper la dépendance ;
   - la justification tient toujours → ré-ouvrir une nouvelle issue,
     reproposer une expiration, et bumper la date dans la CI.

L'objectif : aucune CVE ignorée sans trace écrite et sans date de
revue. Une exception sans date est un trou de sécurité durable.

## Variables d'environnement de sécurité

Synthèse pour le déploiement. Détail : `README.md` section
« Déploiement sécurisé ».

| Variable | Effet | Recommandé en prod |
|---|---|---|
| `AUDIT_BIM_ENV=production` | Active le mode prod (clé service obligatoire, `0.0.0.0` autorisé) | Oui |
| `AUDIT_BIM_API_KEY` | Clé service `X-API-Key` exigée à l'init MCP | Oui (32+ octets aléatoires) |
| `AUDIT_BIM_REQUIRE_API_KEY=true` | Force la clé même hors prod | Selon contexte |
| `AUDIT_BIM_ALLOW_WRITES` | Permet les push BIMData (BCF, classifications) | `false` (sauf besoin explicite) |
| `AUDIT_BIM_ALLOW_UNBOUNDED_INPUTS=true` | Opt-out de la sandbox d'inputs (déconseillé) | Non |
| `AUDIT_BIM_ALLOW_ACCESS_TOKEN_PARAM=true` | Autorise `access_token` en paramètre MCP sur réseau (stdio = toujours autorisé, déconseillé en HTTP) | Non — utiliser `BIMDATA_API_KEY` côté serveur |
| `AUDIT_INPUT_DIR` | Racine des fichiers DOE/CCH lisibles | Oui, dossier dédié |
| `AUDIT_OUTPUT_DIR` | Racine des exports xlsx/docx/json | Oui, dossier dédié |
| `AUDIT_MAX_INPUT_MB` | Taille max d'un fichier d'input | 50 par défaut |
| `AUDIT_MAX_PDF_PAGES` | Plafond pages OCRisées | 50 par défaut |
| `AUDIT_OCR_TIMEOUT_S` | Timeout Tesseract par page | 30 par défaut |
| `AUDIT_BIM_SESSION_TTL_S` | TTL inactivité session HTTP | 3600 par défaut |
| `AUDIT_BIM_MAX_SESSIONS` | Cap LRU sessions HTTP | 64 par défaut |
| `BIMDATA_HTTP_TIMEOUT` | Timeout client BIMData (s) | 30 par défaut |
