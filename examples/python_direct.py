"""Usage direct de la lib Python sans passer par le serveur MCP.

Utile pour scripts batch, CI, pipelines de données BIM.
"""
from audit_bim.audit.engine import run_audit
from audit_bim.extraction.client import BIMDataClient
from audit_bim.extraction.model_data import extract_snapshot
from audit_bim.reporting.word_report import write_word_report
from audit_bim.reporting.xlsx_annex import write_xlsx_annex
from audit_bim.requirements.catalog import build_catalog
from audit_bim.requirements.models import BIMPhase


def main():
    # 1. Catalogue (depuis les 3 documents MOA)
    catalog = build_catalog(
        cch_pdf="/Users/stani/code/MCP/Documents maître d'ouvrage/"
                "Cahier des annexes CCH Bim I3F V3.6 - Juil 24.pdf",
        data_spec_xlsx="/Users/stani/code/MCP/Documents maître d'ouvrage/"
                       "Annexe Spécification des données I3F simplifiée - "
                       "CCH 2021 V3.7 TDB.xlsx",
        naming_spec_xlsx="/Users/stani/code/MCP/Documents maître d'ouvrage/"
                         "Annexe Nommage IFC 3F CCH 2021 V3.6 SHAB SU.xlsx",
    )

    # 2. Snapshot de la maquette BIMData
    client = BIMDataClient()  # IDs et auth depuis .env
    snapshot = extract_snapshot(client)

    # 3. Audit
    result = run_audit(snapshot, catalog, BIMPhase.AVP)
    print(f"{len(result.findings)} findings — "
          f"taux conformité : {result.conformity_rate()*100:.1f} %")

    # 4. Livrables
    write_xlsx_annex(result, "/tmp/audit_annexes.xlsx")
    write_word_report(result, "/tmp/audit_rapport.docx")
    print("Livrables prêts dans /tmp/")


if __name__ == "__main__":
    main()
