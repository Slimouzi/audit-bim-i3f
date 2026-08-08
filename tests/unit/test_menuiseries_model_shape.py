"""Le livrable Menuiseries doit avoir la FORME du gabarit client.

Écarts mesurés le 2026-08-08 entre le pack généré et
``260130 Tarare export Menuiseries.xlsx`` — le modèle de référence I3F. Aucun
n'est une question de chiffres : ce sont des écarts de **structure**, et un
livrable qui n'a pas la forme du gabarit n'est plus le gabarit, même juste.

Les quatre écarts, mesurés sur le modèle et non supposés :

1. **portes mélangées aux fenêtres** — le modèle ne contient que des lignes
   ``Fenêtre`` (A2:A16), plus une ligne d'appuis à part. Le généré ajoute six
   lignes ``Porte``, ce qui déplace le compteur de ``D2:D16`` à ``D2:D22`` et
   change le sens du livrable ;
2. **colonne en trop** — le modèle a 14 colonnes (A:N) ; le généré en a 15,
   avec une colonne ``Source quantité`` absente du gabarit ;
3. **colonnes de comparaison renommées** — le modèle attend ``Largeur``,
   ``Hauteur``, ``Surface Solibri`` (H, I, J). Le généré écrit ``Largeur IFC
   OpenShell``… : la colonne J n'est plus une comparaison Solibri ;
4. **types écrasés** — le modèle distingue ``Fenêtre 25``, ``Fenêtre châssis
   double 25``, ``Ouverture fenêtre rectangulaire 25``. Le généré regroupe sur
   ``WINDOW`` / ``DOOR`` et perd l'information qui structure les lignes.

Ce fichier est écrit AVANT le correctif et doit donc ÉCHOUER sur le
comportement actuel : une CI verte sur un livrable faux est ce qu'on cherche à
empêcher.
"""

from __future__ import annotations

import pathlib

import pytest

MODELE = pathlib.Path(
    "/Users/stani/code/MCP/Documents maître d'ouvrage/Documents I3F/Livrables/"
    "260130 Tarare export Menuiseries.xlsx"
)

#: En-têtes A:N du gabarit, relevés sur le fichier client. ``M`` est vide dans
#: le modèle — c'est une colonne de séparation, pas un oubli.
ENTETES_MODELE = [
    "Composant",
    "Type",
    "Matériau",
    "BaseQuantities.Width",
    "BaseQuantities.Height",
    "Surface Natif",
    "Nombre",
    "Largeur",
    "Hauteur",
    "Surface Solibri",
    "Ecart de largeur",
    "Ecart de heuteur",
    None,
    "Couleur",
]


def _entetes_generees() -> list[str]:
    """En-têtes que le générateur produit aujourd'hui."""
    from audit_bim.reporting import avp_snapshot

    src = avp_snapshot.build_menuiseries_from_snapshot.__doc__ or ""
    del src  # documentation seule : la liste vient du code, lue ci-dessous.
    import inspect
    import re

    corps = inspect.getsource(avp_snapshot.build_menuiseries_from_snapshot)
    bloc = re.search(r"headers = \[(.*?)\]", corps, re.S)
    assert bloc, "prémisse : le générateur doit déclarer ses en-têtes"
    return [m.group(1) for m in re.finditer(r'"([^"]*)"', bloc.group(1))]


def test_the_reference_model_is_available():
    """Sentinelle : sans le gabarit, tous les contrôles seraient vacants."""
    assert MODELE.is_file(), f"modèle client introuvable : {MODELE}"


def test_the_reference_model_holds_only_windows():
    """Le gabarit ne contient QUE des fenêtres — mesuré, pas supposé."""
    openpyxl = pytest.importorskip("openpyxl")
    ws = openpyxl.load_workbook(MODELE).active

    composants = {ws.cell(r, 1).value for r in range(2, 17)}
    assert composants == {"Fenêtre"}, composants
    assert ws.max_column == 14, ws.max_column
    assert ws.cell(17, 3).value == "=COUNTA(D2:D16)"


def test_the_generator_must_not_add_a_fifteenth_column():
    """Écart n°2 : ``Source quantité`` n'existe pas dans le gabarit."""
    entetes = _entetes_generees()
    assert "Source quantité" not in entetes, (
        "le générateur ajoute une colonne absente du gabarit client"
    )
    assert len(entetes) == 14, f"{len(entetes)} colonnes générées, 14 attendues"


def test_no_generated_column_mentions_the_third_party_tool():
    """Doctrine : aucun libellé « Solibri » dans un fichier généré.

    Ce test a d'abord été écrit **à l'envers** — il exigeait de CONSERVER les
    colonnes Solibri du gabarit historique. C'était prendre le fichier client
    pour la spécification, alors que la doctrine produit fait foi : le livrable
    n'imite pas Solibri, il assume IFC OpenShell.
    """
    entetes = _entetes_generees()
    fautifs = [h for h in entetes if "solibri" in h.lower() or "bimcollab" in h.lower()]
    assert not fautifs, fautifs


def test_the_measurement_columns_name_ifc_openshell():
    """La source unique doit être lisible dans l'en-tête, pas déduite."""
    entetes = _entetes_generees()
    for attendu in (
        "Largeur IFC OpenShell",
        "Hauteur IFC OpenShell",
        "Surface IFC OpenShell",
    ):
        assert attendu in entetes, f"colonne {attendu!r} absente du généré"


def test_the_deliverable_perimeter_excludes_doors():
    """Écart n°1 : les portes n'appartiennent pas à ce livrable.

    Le contrôle porte sur le périmètre du LIVRABLE (``_FENETRE_CLASSES``), pas
    sur la constante générale ``_MENUISERIE_CLASSES`` : celle-ci sert encore à
    compter les menuiseries pour la disponibilité, où portes et fenêtres ont
    toutes deux leur place.
    """
    from audit_bim.reporting import avp_snapshot

    portes = [c for c in avp_snapshot._FENETRE_CLASSES if "Door" in c]
    assert not portes, portes
    assert set(avp_snapshot._FENETRE_CLASSES) == {"IfcWindow", "IfcWindowStandardCase"}
