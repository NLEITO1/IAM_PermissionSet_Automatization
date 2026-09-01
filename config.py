import os
from dotenv import load_dotenv

load_dotenv()

def required(name):
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"No se encontró la variable '{name}' en el archivo .env"
        )
    
    return value

AWS_PROFILE = required("AWS_PROFILE")
AWS_REGION = required("AWS_REGION")
TEMP_PERMISSION_SET = required("TEMP_PERMISSION_SET")

EXCEL_FILE = os.getenv(
    "EXCEL_FILE",
    "usuarios.xlsx"
)
SHEET_NAME = os.getenv(
    "SHEET_NAME",
    "Usuarios"
)