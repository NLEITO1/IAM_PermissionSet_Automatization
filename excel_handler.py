from datetime import datetime
from pathlib import Path
import openpyxl

COLUMNS = [
    "CUENTA",
    "ID CUENTA",
    "INICIO PRUEBA",
    "USUARIO",
    "PERMISO",
    "TIPO",
    "FIN PRUEBA",
]

def load_rows(path: str, sheet_name: str = "Usuarios"):
    wb = openpyxl.load_workbook(path)
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        print(f"Hoja '{sheet_name}' no encontrada.")
        ws = wb.active
        print(f"Se usará la hoja activa '{ws.title}' en su lugar.")
        if input("Escriba 'si' desea continuar (o cualquier otra cosa para cancelar): ").lower() != "si":
            raise SystemExit("Cancelado por el usuario.")   

    headers = [cell.value for cell in ws[1]]
    missing = [c for c in COLUMNS if c not in headers]
    if missing:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(missing)}")

    idx = {h: headers.index(h) for h in COLUMNS}
    rows = []

    for excel_row, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not any(v is not None and str(v).strip() for v in values):
            continue

        account_name = str(values[idx["CUENTA"]] or "").strip()
        account_id = str(values[idx["ID CUENTA"]] or "").strip()
        username = str(values[idx["USUARIO"]] or "").strip()
        start_date = values[idx["INICIO PRUEBA"]]
        permission = str(values[idx["PERMISO"]] or "").strip()
        user_type = str(values[idx["TIPO"]] or "PERSONA").strip()
        end_date = values[idx["FIN PRUEBA"]]

        rows.append({
            "excel_row": excel_row,
            "account_name": account_name,
            "account_id": account_id,
            "username": username,
            "start_date": start_date,
            "permission": permission,
            "user_type": user_type,
            "end_date": end_date,
        })

    return wb, ws, idx, rows

def _save(wb, path):
    # El archivo se guarda directamente para conservar el formato general de la plantilla.
    wb.save(path)

def write_start(path, wb, ws, idx, excel_row, permission, start_date=None):
    if start_date is None:
        start_date = datetime.now()
    ws.cell(excel_row, idx["INICIO PRUEBA"] + 1).value = start_date
    ws.cell(excel_row, idx["PERMISO"] + 1).value = permission
    _save(wb, path)
    return start_date

def insert_extra_row(path, wb, ws, idx, source_row, permission, start_date):
    """
    Solo se usa cuando una fila se agregó manualmente sin PERMISO y AWS
    reporta más permisos de los que había filas en blanco para ese usuario/cuenta.
    """
    new_row = source_row + 1
    ws.insert_rows(new_row)
    for col_name in ("CUENTA", "ID CUENTA", "USUARIO"):
        ws.cell(new_row, idx[col_name] + 1).value = ws.cell(source_row, idx[col_name] + 1).value
    ws.cell(new_row, idx["INICIO PRUEBA"] + 1).value = start_date
    ws.cell(new_row, idx["PERMISO"] + 1).value = permission
    _save(wb, path)
    return new_row

def write_end(path, wb, ws, idx, excel_row):
    ws.cell(excel_row, idx["FIN PRUEBA"] + 1).value = datetime.now()
    _save(wb, path)


COLUMN_WIDTHS = {"A": 20, "B": 18, "C": 24, "D": 30, "E": 30, "F": 24}
DATE_COLUMNS = ("INICIO PRUEBA", "FIN PRUEBA")

def create_workbook(sheet_name: str = "Usuarios"):
    """Crea un libro nuevo con la estructura esperada."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(COLUMNS)
    return wb, ws

def open_or_create(path: str, sheet_name: str = "Usuarios"):
    """Abre un Excel existente o crea uno nuevo."""
    if Path(path).exists():
        wb, ws, idx, _ = load_rows(path, sheet_name)
        return wb, ws, idx, False
    wb, ws = create_workbook(sheet_name)
    idx = {column: position for position, column in enumerate(COLUMNS)}
    return wb, ws, idx, True

def append_rows(wb, ws, rows):
    """Agrega las filas al final de la hoja."""
    for row in rows:
        ws.append(row)

def format_sheet(ws):
    """Aplica los anchos y formatos de fecha del Excel."""
    for column, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[column].width = width
    for row in range(2, ws.max_row + 1):
        for column_name in DATE_COLUMNS:
            ws.cell(row=row, column=COLUMNS.index(column_name) + 1).number_format = "yyyy-mm-dd hh:mm:ss"
