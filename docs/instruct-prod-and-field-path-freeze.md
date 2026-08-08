# Instruction CTO — gel #82, fin de développement, mise en production (sandbox supprimé)

> **Document historique.** Rédigé quand la distribution s'appelait
> `audit-bim-i3f` ; elle se nomme **`audit-bim-mcp`** depuis la 0.11.0
> (2026-08-08). Les noms cités ci-dessous n'ont **pas** été réécrits : ce
> document est une trace de décision, pas une consigne courante.

Instruction de clôture du cycle de développement et de passage en production de
`audit-bim-i3f`. État d'entrée : jalon A1 clos, **v0.7.0 releasée** (#81), dette
overrides purgée (#83), scope `field_path` proposé en PR #82 (docs-only).

---

## 1. Gel du scope #82 — **GO, gelé tel quel**

`docs/scope-field-path.md` est **gelé** (§1 grammaire, §2 mapping, §3 exemptions) :
il applique exactement l'arbitrage CTO — `None`-exempt par `error_type` avec
justification d'une ligne, aucun token relationnel, whitelist incapable de grossir
silencieusement. **Merger #82 en l'état.**

Deux notes d'implémentation, **non bloquantes** (pas de retouche au scope) :

1. **Exclusion déterministe des findings importés** : le verrou §4 exclut
   `preliminary.py` « par provenance » — l'implémentation doit s'appuyer sur un
   marqueur structuré (source/provenance du finding), pas sur un nom de règle,
   sinon l'exclusion dérive.
2. **Premier segment = classe réelle** : le `re.fullmatch` ne suffit pas — le
   verrou doit aussi comparer le premier segment à la classe IFC effective de
   l'objet du finding (le scope §4 le dit ; ne pas l'oublier dans le test).

### Implémentation (après merge #82) — lot unique

- Émission `field_path` dans les **6 familles non-zone** (`naming.py` non-zone,
  `properties.py`, `lists.py`, `uniqueness.py`, `spatial.py`,
  `classifications.py` → `None` exempté), zones **inchangées**.
- **Verrou générique** §4 + liste blanche §3.
- **Aucun nouveau consommateur** (§5) ; `_zone_finding_kind` inchangé.
- Parité : `field_path` reste absent des payloads builders → **goldens
  inchangés** (re-vérifier `test_publication_golden_parity`, comme au lot zone).
- Suite complète verte + ruff → PR → merge → **release mineure v0.8.0**
  (investissement de contrat livré ; même pipeline que 0.7.0, smoke-install
  compris, tags immuables).

## 2. Fin de développement — reste à solder avant l'étiquette « terminé »

1. **Hygiène de branches** (instruction précédente, toujours pendante) :
   - PR docs-only « piste de décision A1 » (les docs d'audit/instruction de la
     branche `claude/perspective-sharing-cursor-follow-02xy1m`, hors prompt
     visionneuse) + récupération de l'instruction pendante
     `instruct-a1-replay-industrialisation.md` si non faite ;
   - tag `archive/codex-mcp-setup-web` puis delete de `codex/mcp-setup-web` ;
   - delete des branches mergées. Cible : master + branches vivantes seulement.
2. **#82 → implémentation → v0.8.0** (§1 ci-dessus).
3. **Dette restante** : wording « immuable » `result.py:3` au **prochain bump
   naturel** de `bim-audit-engine` — rien d'autre au registre.

Après quoi le produit est **féature-complet pour le périmètre engagé** : audit
CCH I3F, pack AVP accepté (5 annexes + Word), publication A1 industrialisée
(3 niveaux de preuve + auto-purge), contrat `field_path` généralisé.

## 3. Mise en production — décisions d'exploitation

### 3.1 Suppression du sandbox (décision d'environnement, définitive)

Le sandbox d'exécution (isolation réseau + credentials vidés) est **supprimé** :
validation **et** production tournent sur le périmètre réel exposé par les
variables d'environnement. Justification inchangée (gelée au jalon A1) : la
borne de sûreté est **le périmètre `BIMDATA_*` + les gardes du code**
(`assert_write_target`, identité par nom exact, plans scellés, `confirm`
obligatoire, secure-by-transport) — le sandbox n'ajoutait aucune sûreté et
empêchait la preuve. La suppression est un acte côté plateforme (politique
réseau de l'environnement d'exécution), hors dépôt.

### 3.2 Installation (depuis la release, jamais depuis une branche)

- Installer le **wheel tagué** (v0.7.0 puis v0.8.0) + les packages first-party
  depuis leurs **tags immuables** (procédure du corps de release, gate
  smoke-install déjà en place).
- **Sweep d'intégrité des tags** (tag ↔ rev du lock) : à rejouer **à chaque bump
  de pin** et périodiquement — réflexe post-incident moved-tag, définitif.

### 3.3 Politique d'écriture par transport (existant `mcp/security.py`, à respecter)

| Déploiement | Écritures BIMData | Règle |
|---|---|---|
| **stdio local** (AMO BIM interactif, Claude Desktop) | autorisées par défaut | périmètre = env de l'opérateur |
| **script direct** (runners replay/acceptance) | autorisées par défaut | gardes du runner = borne (cible jetable, confirm, scellés) |
| **HTTP/SSE exposé** | **refusées par défaut** | activer exige `AUDIT_BIM_ALLOW_WRITES=true` **explicite** + clé service (`REQUIRE_API_KEY`/prod) ; jamais de Bearer utilisateur en paramètre MCP sur transport réseau |

### 3.4 Boucle d'exploitation

- **Canari planifiable** : le replay A1 **dry-run** (read-only) en cron sur la
  maquette jetable — PASS déterministe 1 + 1 ; toute dérive = signal (maquette
  modifiée ou régression), à traiter, jamais à ignorer.
- **`--write` : manuel uniquement** (décision B, inchangée en prod). Le run
  standard auto-purge ; le contrôle visuel périodique **5b** se fait avec
  `--keep` puis purge manuelle (procédure README du runner).
- **Journal** : `audit_trail` est la trace d'exploitation de toute écriture —
  consultable via le tool MCP read-only, à archiver selon la politique interne.
- **Données client** : inchangé en prod — sorties/plans **hors dépôt**, stdout
  compteurs/booléens/verdict seulement, aucun livrable client versionné.

### 3.5 Critères de « mise en production effective »

1. v0.8.0 installée depuis les tags (smoke-install vert).
2. Cron dry-run actif et PASS 3 occurrences consécutives.
3. Un `--write` manuel de recette exécuté en prod (create → verify → purge, 0
   résidu au préfixe).
4. Hygiène §2.1 faite (master seul + branches vivantes).
5. Sandbox supprimé côté plateforme (§3.1).

## 4. Ordre consolidé

1. **Merge #82** (gel prononcé §1) → implémentation field_path (lot unique) →
   **v0.8.0**.
2. Hygiène de branches (§2.1) en parallèle.
3. Bascule prod : install taguée, cron dry-run, recette `--write`, suppression
   sandbox (§3).
4. Dette `result.py` au prochain bump engine. Ensuite : exploitation courante,
   nouveaux chantiers = instruction → scope gelé → code, comme toujours.
