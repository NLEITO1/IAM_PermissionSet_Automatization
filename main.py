import argparse, sys
from datetime import  datetime
from botocore.exceptions import ClientError
import config
import excel_handler as excel
from identity_center import IdentityCenter

def validate_account_id(account_id: str):
    if len(account_id) != 12 or not account_id.isdigit():
        raise ValueError(f"ID CUENTA inválido: '{account_id}'")

# Funcion que retira y guarda los permisos orginales en el excel y asigna el permiso temporal
def iniciar(args):
    if not config.TEMP_PERMISSION_SET:
        raise RuntimeError("Define TEMP_PERMISSION_SET en el entorno.")
    #Cargamos el excel y la hoja, y creamos el objeto IdentityCenter
    wb, ws, idx, rows = excel.load_rows(args.excel, args.hoja)
    ic = IdentityCenter(profile_name=args.perfil or config.AWS_PROFILE,
                        region_name=args.region or config.AWS_REGION)
    #Traemos el ARN del permiso temporal
    temp_arn = ic.permission_set_arn(config.TEMP_PERMISSION_SET)

    processed = skipped = errors = 0

    candidates = []
    #Leemos las filas del excel para filtrar en cuales se van a usar
    for row in rows:
        if row["start_date"] not in (None, ""):
            print(f"[IGNORADO] fila {row['excel_row']}: ya tiene INICIO PRUEBA.")
            skipped += 1
            continue
        if not row["account_id"] or not row["username"]:
            print(f"[ERROR] fila {row['excel_row']}: falta ID CUENTA o USUARIO.")
            errors += 1
            continue
        try:
            validate_account_id(row["account_id"])
        except Exception as exc:
            print(f"[ERROR] fila {row['excel_row']}: {exc}")
            errors += 1
            continue
        candidates.append(row)

    groups = {}
    for row in candidates:
        groups.setdefault((row["account_id"], row["username"]), []).append(row)

    pending_writes = []   # (excel_row, name, start_date) -> filas ya existentes
    pending_inserts = []  # (anchor_row, name, start_date) -> filas a crear

    for (account_id, username), group_rows in groups.items():
        filas = ", ".join(str(r["excel_row"]) for r in group_rows)
        print(f"\n[CUENTA] {account_id} / {username} (filas {filas})")

        try:
            user_id = ic.user_id(username, group_rows[0]["user_type"])
            assignments = ic.assignments_for_user(account_id, user_id, group_rows[0]["user_type"])

            if not assignments:
                raise RuntimeError("No tiene ningún Permission Set asignado directamente.")

            original_arns = [a["PermissionSetArn"] for a in assignments]
            if temp_arn in original_arns:
                raise RuntimeError(
                    f"El usuario ya tiene el Permission Set temporal '{config.TEMP_PERMISSION_SET}'."
                )

            original_names = [ic.permission_set_name(arn) for arn in original_arns]
            print(f"  Permisos detectados en AWS: {', '.join(original_names)}")

            # --- Emparejamiento: primero las filas que YA traen PERMISO escrito ---
            remaining_names = list(original_names)  # copia, para ir "consumiendo"
            matched = []       # (row, name) -> filas existentes con permiso ya identificado
            blank_rows = []    # filas manuales sin PERMISO, a la espera de asignación

            for row in group_rows:
                if row["permission"]:
                    if row["permission"] not in remaining_names:
                        raise RuntimeError(
                            f"Fila {row['excel_row']}: el PERMISO '{row['permission']}' no coincide "
                            "con ningún permiso detectado en AWS para este usuario/cuenta."
                        )
                    remaining_names.remove(row["permission"])
                    matched.append((row, row["permission"]))
                else:
                    blank_rows.append(row)

            # Lo que sobra en remaining_names son permisos de AWS sin fila conocida:
            # se reparten primero entre las filas en blanco; si no alcanzan, se crean filas nuevas.
            if len(blank_rows) > len(remaining_names):
                raise RuntimeError(
                    f"Hay {len(blank_rows)} fila(s) en blanco pero solo {len(remaining_names)} "
                    "permiso(s) sin emparejar en AWS. Revisa el Excel manualmente."
                )

            extra_names = remaining_names[len(blank_rows):]  # los que necesitan fila nueva
            filled_blanks = list(zip(blank_rows, remaining_names[:len(blank_rows)]))

            # --- Recién aquí tocamos AWS: remover todos los originales ---
            removed = []
            try:
                for arn, name in zip(original_arns, original_names):
                    ic.remove(account_id, user_id, arn)
                    removed.append(arn)
                    print(f"  - Removido: {name}")
            except Exception:
                print("  ! Falló la remoción. Revirtiendo lo ya removido...")
                for arn in removed:
                    ic.assign(account_id, user_id, arn, group_rows[0]["user_type"])
                raise

            try:
                ic.assign(account_id, user_id, temp_arn, group_rows[0]["user_type"])
                print(f"  + Asignado temporal: {config.TEMP_PERMISSION_SET}")
            except Exception:
                print("  ! Falló la asignación temporal. Restaurando permisos originales...")
                for arn in original_arns:
                    ic.assign(account_id, user_id, arn, group_rows[0]["user_type"])
                raise

            start_date = datetime.now()
            for row, name in matched:
                pending_writes.append((row["excel_row"], name, start_date))
            for row, name in filled_blanks:
                pending_writes.append((row["excel_row"], name, start_date))

            anchor = max(r["excel_row"] for r in group_rows)
            for name in extra_names:
                pending_inserts.append((anchor, name, start_date))

            processed += len(group_rows) + len(extra_names)
            print("  ✓ Cambios aplicados en AWS.")

        except Exception as exc:
            errors += len(group_rows)
            print(f"  ✗ ERROR ( {account_id}/{username}): {exc}")

    # Escribimos de la fila más alta a la más baja para que insertar filas
    # no invalide los excel_row de escrituras/inserciones pendientes más arriba.
    for excel_row, name, start_date in sorted(pending_writes, key=lambda x: x[0], reverse=True):
        excel.write_start(args.excel, wb, ws, idx, excel_row, name, start_date)

    for anchor, name, start_date in sorted(pending_inserts, key=lambda x: x[0], reverse=True):
        excel.insert_extra_row(args.excel, wb, ws, idx, anchor, name, start_date)

    print(f"\nInicio terminado. Procesados: {processed}; ignorados: {skipped}; errores: {errors}")

def finalizar(args):
    if not config.TEMP_PERMISSION_SET:
        raise RuntimeError("Define TEMP_PERMISSION_SET en el entorno.")

    wb, ws, idx, rows = excel.load_rows(args.excel, args.hoja)
    ic = IdentityCenter(profile_name=args.perfil or config.AWS_PROFILE,
                        region_name=args.region or config.AWS_REGION)

    temp_arn = ic.permission_set_arn(config.TEMP_PERMISSION_SET)

    processed = skipped = errors = 0
    candidates = []

    for row in rows:
        if row["end_date"] not in (None, ""):
            print(f"[IGNORADO] fila {row['excel_row']}: ya tiene FIN PRUEBA.")
            skipped += 1
            continue

        if row["start_date"] in (None, ""):
            print(f"[IGNORADO] fila {row['excel_row']}: no tiene INICIO PRUEBA.")
            skipped += 1
            continue

        if not row["account_id"] or not row["username"] or not row["permission"]:
            print(f"[ERROR] fila {row['excel_row']}: falta ID CUENTA, USUARIO o PERMISO.")
            errors += 1
            continue

        try:
            validate_account_id(row["account_id"])
        except Exception as exc:
            print(f"[ERROR] fila {row['excel_row']}: {exc}")
            errors += 1
            continue

        candidates.append(row)

    # Agrupamos por cuenta+usuario porque comparten UNA sola asignación temporal:
    # no se puede remover el temporal fila por fila, hay que hacerlo una vez por grupo.
    groups = {}
    for row in candidates:
        key = (row["account_id"], row["username"])
        groups.setdefault(key, []).append(row)

    for (account_id, username), group_rows in groups.items():
        filas = ", ".join(str(r["excel_row"]) for r in group_rows)
        print(f"\n[CUENTA] {account_id} / {username} (filas {filas}) -> "
              f"{len(group_rows)} permiso(s) a restaurar")

        try:
            user_id = ic.user_id(username, group_rows[0]["user_type"])
            assignments = ic.assignments_for_user(account_id, user_id, group_rows[0]["user_type"])

            has_temp = any(a["PermissionSetArn"] == temp_arn for a in assignments)
            if not has_temp:
                raise RuntimeError(
                    f"El usuario no tiene asignado el Permission Set temporal "
                    f"'{config.TEMP_PERMISSION_SET}'. No se modifica nada."
                )

            # Resolvemos ARNs originales y validamos ANTES de tocar nada.
            targets = []  # (row, original_arn)
            for row in group_rows:
                original_arn = ic.permission_set_arn(row["permission"])
                has_original = any(a["PermissionSetArn"] == original_arn for a in assignments)
                if has_original:
                    raise RuntimeError(
                        f"El usuario ya tiene asignado '{row['permission']}' "
                        f"(fila {row['excel_row']}). No se modifica nada en el grupo."
                    )
                targets.append((row, original_arn))

            # Asignamos todos los originales del grupo, con rollback si alguno falla.
            assigned = []
            try:
                for row, original_arn in targets:
                    ic.assign(account_id, user_id, original_arn, group_rows[0]["user_type"])
                    assigned.append(original_arn)
                    print(f"  + Restaurado: {row['permission']} (fila {row['excel_row']})")
            except Exception:
                print("  ! Falló la restauración de un permiso. Revirtiendo lo ya asignado...")
                for arn in assigned:
                    ic.remove(account_id, user_id, arn, group_rows[0]["user_type"])
                raise

            # Solo removemos el temporal una vez, después de que TODOS los originales
            # del grupo quedaron asignados correctamente.
            try:
                ic.remove(account_id, user_id, temp_arn, group_rows[0]["user_type"])
                print(f"  - Removido temporal: {config.TEMP_PERMISSION_SET}")
            except Exception:
                print("  ! Falló la remoción del temporal. Los permisos originales ya quedaron "
                      "asignados junto con el temporal: requiere revisión manual.")
                raise

            for row in group_rows:
                excel.write_end(args.excel, wb, ws, idx, row["excel_row"])
                processed += 1
            print("  ✓ Fin registrado en Excel para el grupo.")

        except Exception as exc:
            errors += len(group_rows)
            print(f"  ✗ ERROR ( {account_id}/{username}): {exc}")

    print(f"\nFinalización terminada. Procesados: {processed}; ignorados: {skipped}; errores: {errors}")

def verificar(args):
    """Modo solo lectura: no modifica AWS ni Excel."""
    wb, ws, idx, rows = excel.load_rows(args.excel, args.hoja)
    ic = IdentityCenter(profile_name=args.perfil or config.AWS_PROFILE,
                        region_name=args.region or config.AWS_REGION)
    processed = skipped = errors = 0
    for row in rows:
        if row["end_date"] not in (None, ""):
            print(f"[IGNORADO] fila {row['excel_row']}: ya tiene FIN PRUEBA.")
            skipped+=1
            continue

        if not row["account_id"] or not row["username"]:
            print(f"[ERROR] fila {row['excel_row']}: falta ID CUENTA o USUARIO.")
            errors += 1
            continue

        try:
            validate_account_id(row["account_id"])
            user_id = ic.user_id(row["username"], row["user_type"])
            assignments = ic.assignments_for_user(row["account_id"], user_id, row["user_type"])

            print(f"\n{row['account_name']} ({row['account_id']}) / {row['username']}")
            if not assignments:
                print("  ! No tiene Permission Sets asignados directamente.")
                errors += 1
            else:
                for assignment in assignments:
                    name = ic.permission_set_name(assignment["PermissionSetArn"])
                    print(f"  ✓ {name}")
                processed += 1

        except Exception as exc:
            print(f"  ✗ ERROR: {exc}")
            errors += 1
    print(f"\nVerificación terminada. Procesados: {processed}; ignorados: {skipped}; errores: {errors}")


def main():
    parser = argparse.ArgumentParser(
        description="Gestión temporal de asignaciones de IAM Identity Center."
    )
    parser.add_argument("--perfil", help="Perfil AWS CLI/Boto3.")
    parser.add_argument("--region", help="Región de IAM Identity Center.")
    parser.add_argument("--hoja", default=config.SHEET_NAME)
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("verificar", help="Solo lectura: verifica usuarios y permisos.")
    p.add_argument("--excel", default=config.EXCEL_FILE)
    p.set_defaults(func=verificar)

    p = sub.add_parser("iniciar", help="Quita el permiso actual y asigna el temporal.")
    p.add_argument("--excel", default=config.EXCEL_FILE)
    p.set_defaults(func=iniciar)

    p = sub.add_parser("finalizar", help="Quita el temporal y restaura PERMISO.")
    p.add_argument("--excel", default=config.EXCEL_FILE)
    p.set_defaults(func=finalizar)

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
