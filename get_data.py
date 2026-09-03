import argparse
from pathlib import Path

import config
from botocore.exceptions import ClientError

from excel_handler import append_rows, format_sheet, open_or_create, _save
from identity_center import IdentityCenter


def obtener_filas(asignaciones, identity_center, cuenta, account_id, permission=None):
    """Convierte las asignaciones en filas para Excel."""
    filas = []
    for asignacion in asignaciones:

        tipo = "Persona" if asignacion["PrincipalType"] == "USER" else "Grupo"

        user_id = asignacion["PrincipalId"]
        permission_set_arn = asignacion["PermissionSetArn"]

        try:
            username = identity_center.usuarios.get(user_id)
            if username is None:
                print(f"No se encontró el usuario con Id {user_id}")
                continue
            permission_set = identity_center.permission_set_name(permission_set_arn)
        except ClientError as e:
            print(f"[AVISO] No se pudo obtener información para {user_id}: {e}")
            continue
        # Si se especificó --permission, ignoramos los Permission Sets diferentes.
        # Ademas de eso, ignoramos los Permission Sets que no comienzan con "BDB" (para evitar incluir permisos de AWS).
        if permission_set.upper()[:3]!="BDB" or (permission and permission_set != permission):
            continue

        print(f"{tipo}: {username} → {permission_set}")
        filas.append([cuenta, account_id, None, username, permission_set, tipo, None])

    return filas




def consultar_asignaciones(identity_center, account_id):
    """Obtiene las asignaciones de una cuenta."""
    asignaciones = identity_center.obtener_asignaciones(account_id)
    print(f"Se encontraron {len(asignaciones)} asignaciones.")
    return asignaciones


def preparar_excel(excel_path):
    """Abre el Excel existente o crea uno nuevo."""
    existe = Path(excel_path).exists()
    wb, ws, idx, nuevo = open_or_create(excel_path)
    if existe:
        print()
        print(f"El archivo '{excel_path}' ya existe.")
        print("Agregando nuevas filas...")
    else:
        print()
        print(f"Creando nuevo archivo '{excel_path}'...")
    return wb, ws, idx, nuevo


def guardar_excel(excel_path, wb, ws):
    """Aplica el formato común y guarda el archivo."""
    format_sheet(ws)
    _save(wb, excel_path)


def crear_excel(excel_path, cuenta, account_id, profile=None, region=None, permission=None):
    print(f"Consultando cuenta: {cuenta}")
    print(f"ID cuenta: {account_id}")

    identity_center = IdentityCenter(profile_name=profile, region_name=region)
    # La lógica necesita el mapa UserId -> UserName.
    identity_center.usuarios = identity_center.obtener_usuarios()
    identity_center.usuarios.update(identity_center.obtener_grupos())

    
    if permission:
        print(f"Filtro de Permission Set: {permission}")
    print()

    asignaciones = consultar_asignaciones(identity_center, account_id)
    filas = obtener_filas(asignaciones, identity_center, cuenta, account_id, permission)

    wb, ws, _, _ = preparar_excel(excel_path)
    append_rows(wb, ws, filas)
    guardar_excel(excel_path, wb, ws)

    print()
    print(f"✓ Excel actualizado: {excel_path}")
    print(f"✓ Filas agregadas: {len(filas)}")


def main():
    parser = argparse.ArgumentParser(description="Genera un Excel con los usuarios y Permission Sets de una cuenta AWS.")
    parser.add_argument("--cuenta", required=True, help="Nombre de la cuenta AWS. Ej: STG")
    parser.add_argument("--id-cuenta", required=True, help="ID de la cuenta AWS. Ej: 123456789012")
    parser.add_argument("--permission", default=None, help="Permission Set que se desea filtrar. Si no se indica, se incluyen todos.")
    args = parser.parse_args()

    crear_excel(
        excel_path=config.EXCEL_FILE,
        cuenta=args.cuenta,
        account_id=args.id_cuenta,
        profile=config.AWS_PROFILE,
        region=config.AWS_REGION,
        permission=args.permission,
    )


if __name__ == "__main__":
    main()
