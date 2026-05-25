"""Application des classifications IFC aux éléments BIMData.

Deux modes côté MCP :

- **Sans contrôle** (``apply_suggested_classifications``) : on prend
  automatiquement la *Suggestion top 1* du classifier pour chaque élément
  ``classification_missing`` dont la confiance dépasse un seuil, et on
  applique sans intervention humaine. Idéal en première passe ou en CI.

- **Avec contrôle XLSX** (``apply_classifications_from_xlsx``) : l'auditeur
  télécharge l'annexe XLSX d'audit, édite la colonne « Suggestion 1 — code »
  de l'onglet *Classifications suggérées* (accepte / corrige / efface), puis
  re-upload. Seules les lignes avec un code non vide sont appliquées.

Workflow API en deux étapes :
    1. Créer la classification au niveau projet (cachée par (code, système)).
    2. Lier la classification à l'élément en bulk via
       ``POST /classification-element``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ..extraction.client import BIMDataClient


def list_project_classifications(client: BIMDataClient) -> list[dict]:
    """Liste les classifications déjà créées au niveau projet BIMData.

    Utilisé en pré-chargement par ``apply_classifications`` pour ne pas
    recréer une classification déjà présente (déduplication par code +
    système).

    Args:
        client: Client BIMData authentifié.

    Returns:
        Liste de dicts ``{id, name, notation, title}``.
    """
    return client._get(f"/cloud/{client.cloud_id}/project/{client.project_id}/classification")


def _normalize_system(system: str | None) -> str:
    """Normalise le nom du système de classification pour l'API BIMData.

    BIMData stocke le système dans le champ ``classification.name``
    (chaîne libre). On normalise en minuscule pour éviter les
    classifications dupliquées (``UniFormat II`` vs ``uniformat`` vs
    ``UNIFORMAT``).

    Args:
        system: Nom humain (``"UniFormat II"``, ``"Omniclass"``, ``None``).

    Returns:
        Nom normalisé : ``"uniformat"``, ``"omniclass"``, ou la valeur
        lowercase telle quelle pour les systèmes non reconnus.
    """
    if not system:
        return "uniformat"
    s = system.lower()
    if "uniformat" in s:
        return "uniformat"
    if "omniclass" in s:
        return "omniclass"
    return s


def apply_classifications(
    client: BIMDataClient,
    items: Iterable[dict],
    *,
    dry_run: bool = True,
) -> dict:
    """Applique une liste de classifications à des éléments BIMData.

    Args:
        client: client BIMData authentifié.
        items: iterable de dicts ``{uuid, code, label, system}``. ``system``
            est optionnel (défaut ``"uniformat"``). ``label`` aussi (sinon
            le code est ré-utilisé comme titre).
        dry_run: si ``True``, ne fait *aucun* appel POST. Retourne juste un
            aperçu de ce qui serait fait. Idéal pour validation utilisateur.

    Returns:
        Résumé : nombre de classifications créées, liens créés, erreurs.
    """
    items_list = [
        it for it in items if it.get("uuid") and it.get("code") and str(it["code"]).strip()
    ]
    if not items_list:
        return {
            "dry_run": dry_run,
            "n_items": 0,
            "message": "Aucune classification à appliquer.",
        }

    # Regroupement par (code, système, label) → liste d'UUIDs
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for it in items_list:
        code = str(it["code"]).strip().upper()
        system = _normalize_system(it.get("system"))
        label = str(it.get("label") or code).strip()
        grouped[(code, system, label)].append(str(it["uuid"]).strip())

    # Cache des classifications existantes (ou créées)
    cache: dict[tuple[str, str], int] = {}
    errors: list[str] = []

    if not dry_run:
        try:
            for c in list_project_classifications(client):
                cache[
                    (
                        (c.get("notation") or "").upper(),
                        _normalize_system(c.get("name")),
                    )
                ] = c["id"]
        except Exception as e:  # pragma: no cover
            errors.append(f"list_project_classifications: {e}")

    # Création des classifications manquantes
    relations: list[dict] = []
    n_created = 0
    n_reused = 0
    preview = []
    for (code, system, label), uuids in grouped.items():
        key = (code, system)
        cid: int | None = cache.get(key)
        status = "reused" if cid else ("would_create" if dry_run else "to_create")
        if cid is None and not dry_run:
            try:
                resp = client._post(
                    f"/cloud/{client.cloud_id}/project/{client.project_id}/classification",
                    {"name": system, "notation": code, "title": label},
                )
                cid = int(resp["id"])
                cache[key] = cid
                n_created += 1
                status = "created"
            except Exception as e:
                errors.append(f"create {system}/{code}: {e}")
                continue
        # En dry_run, le cid réel n'existe pas encore — on utilise un
        # placeholder négatif pour le comptage des liens à créer.
        cid_for_link = cid if cid is not None else -1
        for u in uuids:
            relations.append({"element_uuid": u, "classification_id": cid_for_link})
        if status == "reused":
            n_reused += 1
        preview.append(
            {
                "code": code,
                "system": system,
                "label": label,
                "classification_id": cid,
                "n_uuids": len(uuids),
                "status": status,
            }
        )

    if dry_run:
        return {
            "dry_run": True,
            "n_items": len(items_list),
            "n_classifications_distinct": len(grouped),
            "n_links_planned": len(relations),
            "n_reused": n_reused,
            "preview": preview,
        }

    # Liaison en bulk. Si le lien échoue, les classifications créées
    # juste avant deviennent orphelines (présentes en projet, attachées
    # à aucun élément). On les signale explicitement dans le rapport
    # pour permettre une reprise (re-run = ré-utilisation via le cache
    # par ``(code, system)``, c'est idempotent côté création).
    n_linked = 0
    link_failed = False
    if relations:
        try:
            client._post(
                f"/cloud/{client.cloud_id}/project/{client.project_id}"
                f"/model/{client.model_id}/classification-element",
                relations,
            )
            n_linked = len(relations)
        except Exception as e:
            errors.append(f"bulk link {len(relations)} relations: {e}")
            link_failed = True

    # Journal des classifications créées mais non liées (orphelines en
    # cas d'échec de l'étape 2). En re-jouant la même requête, elles
    # seront ré-utilisées (cache code+système), pas dupliquées.
    orphan_classifications: list[dict] = []
    if link_failed:
        orphan_classifications = [
            {
                "code": p["code"],
                "system": p["system"],
                "label": p["label"],
                "id": p["classification_id"],
            }
            for p in preview
            if p["status"] == "created"
        ]

    return {
        "dry_run": False,
        "n_items": len(items_list),
        "n_classifications_created": n_created,
        "n_classifications_reused": n_reused,
        "n_links_created": n_linked,
        "link_failed": link_failed,
        "orphan_classifications": orphan_classifications,
        "rerun_safe": True,
        "errors": errors,
        "preview": preview,
    }


def items_from_suggestions(suggestions: list[dict], *, min_confidence: float = 0.5) -> list[dict]:
    """Convertit la sortie de ``suggest_for_findings`` en items pour ``apply_classifications``.

    Filtre par seuil de confiance sur la suggestion top (top 1
    uniquement — la décision « auto » prend toujours la plus probable).

    Args:
        suggestions: Sortie de ``suggest_for_findings`` (liste de dicts
            avec clé ``suggestions``).
        min_confidence: Seuil 0..1 sous lequel la suggestion est
            ignorée. Défaut 0.5.

    Returns:
        Liste de dicts ``{uuid, code, label, system}`` prête pour
        ``apply_classifications``.
    """
    out: list[dict] = []
    for s in suggestions:
        sugs = s.get("suggestions") or []
        if not sugs:
            continue
        top = sugs[0]
        if (top.get("confidence") or 0) < min_confidence:
            continue
        out.append(
            {
                "uuid": s.get("element_uuid"),
                "code": top.get("code"),
                "label": top.get("label"),
                "system": top.get("system") or "UniFormat II",
            }
        )
    return out
