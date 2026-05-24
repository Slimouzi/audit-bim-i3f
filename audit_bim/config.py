"""Chargement de la configuration depuis l'environnement (`.env` + os.environ)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- BIMData API ----------------------------------------------------------
BIMDATA_BASE_URL = os.getenv("BIMDATA_BASE_URL", "https://api.bimdata.io")
BIMDATA_IAM_URL = os.getenv(
    "BIMDATA_IAM_URL",
    "https://iam.bimdata.io/auth/realms/bimdata/protocol/openid-connect/token",
)

API_KEY = os.getenv("BIMDATA_API_KEY") or None
CLIENT_ID = os.getenv("BIMDATA_CLIENT_ID") or None
CLIENT_SECRET = os.getenv("BIMDATA_CLIENT_SECRET") or None
ACCESS_TOKEN = os.getenv("BIMDATA_ACCESS_TOKEN") or None

CLOUD_ID = os.getenv("BIMDATA_CLOUD_ID") or None
PROJECT_ID = os.getenv("BIMDATA_PROJECT_ID") or None
MODEL_ID = os.getenv("BIMDATA_MODEL_ID") or None

# --- Documents Maître d'Ouvrage ------------------------------------------
I3F_CCH_PDF = os.getenv("I3F_CCH_PDF") or None
I3F_DATA_SPEC_XLSX = os.getenv("I3F_DATA_SPEC_XLSX") or None
I3F_NAMING_SPEC_XLSX = os.getenv("I3F_NAMING_SPEC_XLSX") or None

# --- Sortie ---------------------------------------------------------------
AUDIT_OUTPUT_DIR = Path(os.getenv("AUDIT_OUTPUT_DIR", "./out")).resolve()
