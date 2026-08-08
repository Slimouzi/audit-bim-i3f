"""Un pack I3F ne se livre pas avec une enveloppe calculée sans filtre.

Défaut mesuré sur `250613_MN_BAT (2)` le 2026-08-08 : le contrat d'enveloppe
avait été produit en mode ``geometric``, sans motif de calque ni de type. Le
livrable en est sorti **plausible et faux** :

- 15 lignes métier au lieu de 8 ;
- total façade 3382,21 au lieu de 2071,19 ;
- huit types en trop — cloisons, refends, béton, aluminium ;
- et le type d'enveloppe attendu ``ME 8+36+6 …`` explicitement rangé dans
  ``types_rejetes`` par le filtre géométrique.

Aucun de ces écarts ne se voit à la lecture du fichier : il faut le comparer au
modèle de référence. C'est la raison d'être de ce refus — le mode attendu pour
un pack I3F est ``layer_type_filter`` (calque + type).

Le refus ne vise que le cas **mesurable** : un contrat qui déclare lui-même
avoir été calculé sans filtre. Une enveloppe absente, ou issue d'un repli
snapshot / .xlsx, ne déclare aucun mode et reste livrable.
"""

from __future__ import annotations

import pytest

from audit_bim.reporting.avp.models import AvpQaError
from audit_bim.reporting.avp.pack import _qa_envelope_filter_mode


class _Source:
    """Forme minimale : ce que le garde-fou lit réellement."""

    def __init__(self, mode=None):
        if mode is not None:
            self.filter_mode = mode


def test_the_geometric_mode_is_reported():
    assert _qa_envelope_filter_mode(_Source("geometric")) == "geometric"


def test_the_expected_i3f_mode_is_reported_and_not_refused():
    """Contre-épreuve : le mode attendu doit passer.

    Sans elle, le contrôle prouverait seulement qu'il refuse quelque chose.
    """
    assert _qa_envelope_filter_mode(_Source("layer_type_filter")) == "layer_type_filter"


@pytest.mark.parametrize(
    ("source", "cas"),
    [
        (None, "aucune enveloppe"),
        (_Source(), "source sans attribut de mode (repli snapshot / xlsx)"),
        (_Source(None), "contrat sans diagnostics.filters"),
    ],
)
def test_an_undeclared_mode_is_not_a_refusal(source, cas):
    """Ne pas savoir n'est pas un motif de refus.

    Refuser sur l'absence bloquerait tous les packs qui n'emploient pas de
    contrat structuré — c'est-à-dire la majorité, et sans aucun défaut mesuré.
    """
    assert _qa_envelope_filter_mode(source) is None, cas


def test_the_qa_error_kind_is_declared_on_the_type():
    """Le nouveau motif doit être documenté là où les trois autres le sont."""
    doc = AvpQaError.__doc__ or ""
    assert "envelope_filter_mode" in doc
    for ancien in ("empty", "missing_quantities", "external_tool_mention"):
        assert ancien in doc, ancien


def test_the_refusal_names_the_deliverable_at_fault():
    """Un refus doit dire QUEL livrable est en cause, pas seulement échouer."""
    exc = AvpQaError(["Extraction surface enveloppe"], kind="envelope_filter_mode")
    assert exc.kind == "envelope_filter_mode"
    assert "Extraction surface enveloppe" in str(exc) or "Extraction surface enveloppe" in str(
        getattr(exc, "deliverables", exc.args[0])
    )


# ---------------------------------------------------------------------------
# Comportement : le refus se déclenche-t-il vraiment à la génération ?
# ---------------------------------------------------------------------------


def _enveloppe_source(mode: str):
    """Source d'enveloppe minimale déclarant son mode de filtrage."""
    from audit_bim.reporting.avp_sources import EnveloppeSource

    src = EnveloppeSource()
    src.filter_mode = mode
    return src


@pytest.mark.parametrize(
    ("mode", "leve"),
    [
        ("geometric", True),
        ("layer_type_filter", False),
        ("type_filter", False),
    ],
)
def test_the_pack_refuses_only_a_geometric_envelope(tmp_path, mode, leve):
    """Le pack doit REFUSER en ``geometric`` — et générer dans les autres modes.

    Le test unitaire du helper ne suffisait pas : neutraliser la condition dans
    ``write_avp_i3f_report_pack`` le laissait vert. Il prouvait le lecteur de
    mode, pas le refus.
    """
    from audit_bim.reporting.avp_i3f import write_avp_i3f_report_pack
    from audit_bim.reporting.avp_sources import AvpSources

    sources = AvpSources()
    sources.enveloppe = _enveloppe_source(mode)

    def _generer():
        return write_avp_i3f_report_pack(
            None,
            tmp_path / f"out_{mode}",
            sources=sources,
            project_name="Chantier",
            project_code="0546L",
            export_pdf=False,
        )

    if leve:
        with pytest.raises(AvpQaError) as exc:
            _generer()
        assert exc.value.kind == "envelope_filter_mode"
    else:
        pack = _generer()
        assert pack.enveloppe_xlsx.exists(), mode
