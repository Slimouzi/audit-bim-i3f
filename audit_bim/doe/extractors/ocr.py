"""Extracteur DOE PDF scanné — OCR via Tesseract.

Pré-requis système : binaire Tesseract + langues installés.

- macOS : ``brew install tesseract tesseract-lang``
- Debian/Ubuntu : ``apt-get install tesseract-ocr tesseract-ocr-fra``
- Windows : binaire depuis https://github.com/UB-Mannheim/tesseract/wiki

Dépendances Python (optional-dependency ``ocr`` du package) :

- ``pytesseract`` — wrapper Python de Tesseract.
- ``pdf2image`` — convertit chaque page PDF en image PIL.
- ``Pillow`` — manipulation d'images.

Workflow :

1. :func:`pdf2image.convert_from_path` rasterise chaque page en image PIL.
2. Pour chaque image, :func:`pytesseract.image_to_data` extrait le
   texte structuré en blocs/lignes/mots avec coordonnées.
3. On reconstitue des **lignes tabulaires** par regroupement vertical
   (groupes de mots à la même ligne, regroupés horizontalement).
4. La 1ère ligne sert d'en-tête (cf. helpers de :mod:`_common`).

Limite V1 : on n'utilise pas la détection de tableau d'OpenCV.
L'heuristique d'alignement vertical fonctionne bien pour les tableaux
simples (1 par page, avec en-tête en haut), suffisant pour la plupart
des DOE équipements. Pour les PDF complexes (multi-tableaux, mises en
page non triviales), une étape de pré-traitement OpenCV serait à
ajouter.
"""

from __future__ import annotations

from pathlib import Path

from ..models import DoeRecord
from ._common import detect_header, find_header_row, row_to_record

# Tolérance verticale pour grouper des mots dans la même « ligne » : on
# considère 2 mots comme alignés horizontalement si la différence de leur
# centre vertical est inférieure à cette valeur (en pixels après
# rasterisation à 200 DPI).
_LINE_ALIGN_TOLERANCE_PX = 12


def is_tesseract_available() -> bool:
    """Renvoie ``True`` si ``pytesseract`` ET le binaire Tesseract sont dispo.

    Permet aux callers de basculer sur un fallback ou de skipper proprement
    sans crasher si OCR n'est pas installé.
    """
    try:
        import pytesseract  # noqa: F401
        from pytesseract import get_tesseract_version

        get_tesseract_version()
    except Exception:
        return False
    return True


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    """Regroupe les mots OCR par ligne (alignement vertical).

    Args:
        words: Liste de dicts produits par ``pytesseract.image_to_data``
            (level=5 = mots) avec clés ``text``, ``left``, ``top``,
            ``width``, ``height``.

    Returns:
        Liste de lignes, chaque ligne étant la liste de ses mots triés
        par position horizontale ``left``.
    """
    if not words:
        return []
    # Trie par centre vertical croissant
    by_top = sorted(words, key=lambda w: w["top"] + w["height"] / 2)
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_center = None
    for w in by_top:
        center = w["top"] + w["height"] / 2
        if current_center is None or abs(center - current_center) <= _LINE_ALIGN_TOLERANCE_PX:
            current_line.append(w)
            # Moyenne mobile du centre courant
            current_center = sum(x["top"] + x["height"] / 2 for x in current_line) / len(
                current_line
            )
        else:
            lines.append(sorted(current_line, key=lambda x: x["left"]))
            current_line = [w]
            current_center = center
    if current_line:
        lines.append(sorted(current_line, key=lambda x: x["left"]))
    return lines


def _lines_to_table(lines: list[list[dict]], n_cols_hint: int | None = None) -> list[list[str]]:
    """Convertit des lignes OCR en cellules tabulaires.

    Détermine le nombre de colonnes via la 1ère ligne (ou ``n_cols_hint``
    si fourni) et répartit les mots de chaque ligne par proximité
    horizontale avec les centres des colonnes de la ligne d'en-tête.

    Args:
        lines: Lignes OCR (sortie de :func:`_group_words_into_lines`).
        n_cols_hint: Nombre attendu de colonnes (si connu). Sinon, déduit
            de la 1ère ligne.

    Returns:
        Table sous forme ``list[list[str]]`` (1 entrée par cellule).
    """
    if not lines:
        return []
    header_words = lines[0]
    n_cols = n_cols_hint or len(header_words)
    if n_cols == 0:
        return []
    # Centres horizontaux de chaque colonne de l'en-tête
    col_centers = [w["left"] + w["width"] / 2 for w in header_words]

    def _row_cells(words: list[dict]) -> list[str]:
        cells: list[list[str]] = [[] for _ in range(n_cols)]
        for w in words:
            center = w["left"] + w["width"] / 2
            # Colonne la plus proche
            col = min(range(n_cols), key=lambda c: abs(col_centers[c] - center))
            cells[col].append(str(w["text"]).strip())
        return [" ".join(c).strip() for c in cells]

    return [_row_cells(line) for line in lines]


def parse_doe_pdf_ocr(
    pdf_path: str | Path,
    *,
    lang: str = "fra",
    dpi: int = 200,
) -> list[DoeRecord]:
    """Extrait les DoeRecord d'un PDF scanné via OCR Tesseract.

    Args:
        pdf_path: Chemin (str ou Path) du PDF scanné.
        lang: Code de langue Tesseract (``"fra"`` par défaut pour le
            français I3F ; ``"eng"`` pour l'anglais ; ``"fra+eng"`` pour
            les documents mixtes).
        dpi: Résolution de rasterisation. Défaut 200 (compromis
            qualité/perf). 300 pour plus de précision sur petites
            polices, au prix de temps de traitement.

    Returns:
        Liste de ``DoeRecord``, toutes pages confondues.

    Raises:
        FileNotFoundError: Si le PDF n'existe pas.
        ImportError: Si ``pytesseract``, ``pdf2image`` ou ``Pillow`` ne
            sont pas installés (``pip install audit-bim-i3f[ocr]``).
        RuntimeError: Si le binaire Tesseract n'est pas trouvé sur la
            machine (cf. doc d'installation en tête de module).
    """
    import pytesseract
    from pdf2image import convert_from_path

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(path)

    pages = convert_from_path(str(path), dpi=dpi)
    records: list[DoeRecord] = []
    for page_num, image in enumerate(pages, start=1):
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
        words = [
            {
                "text": data["text"][i],
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
                "conf": data["conf"][i],
            }
            for i in range(len(data["text"]))
            if str(data["text"][i]).strip() and int(data["conf"][i]) >= 30
        ]
        if not words:
            continue
        lines = _group_words_into_lines(words)
        if len(lines) < 2:
            continue
        table = _lines_to_table(lines)
        header_idx = find_header_row(table)
        if header_idx is None:
            continue
        headers = table[header_idx]
        col_map = [detect_header(h) for h in headers]
        for row_i, row in enumerate(
            table[header_idx + 1 :],
            start=header_idx + 2,
        ):
            rec = row_to_record(
                headers,
                row,
                col_map,
                source=f"{path}#page={page_num}&ocr=tesseract:{lang}",
                row_index=row_i,
            )
            if rec is not None:
                records.append(rec)
    return records
