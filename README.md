# AWS IAM Identity Center Permission Manager

Automatiza una prueba temporal sobre usuarios de IAM Identity Center:

1. Lee usuarios desde Excel.
2. Detecta el Permission Set asignado directamente al usuario en cada cuenta.
3. Guarda su nombre en `PERMISO`.
4. Quita el Permission Set original.
5. Asigna un Permission Set temporal común.
6. Registra `INICIO PRUEBA`.
7. Más adelante, `finalizar` quita el temporal, restaura `PERMISO` y registra `FIN PRUEBA`.

## Excel

La hoja `Usuarios` debe tener exactamente estas columnas:

| CUENTA | ID CUENTA | INICIO PRUEBA | USUARIO | PERMISO | TIPO | FIN PRUEBA |
| :----- | :----------: | :-----------: | :---------- | :-----: | :-----: | :--------: |
| STG | 123456789012 | | juan.perez | | PERSONA | |
| DEV | 987654321098 | | dev_group | | GRUPO | |

Las filas con `INICIO PRUEBA` ya llena se ignoran al ejecutar `iniciar`.

Las filas con `FIN PRUEBA` ya llena se ignoran al ejecutar `finalizar`.

`finalizar` solo procesa filas que tengan inicio, pero no fin.

`PERMISO` lo verifica y escribe el programa al iniciar. No es necesario llenarlo manualmente.

**Importante:** el programa va a tomar TODOS los permisos asignados a ese usuario/grupo y se los va a quitar 

## Modelo AWS

Este proyecto administra IAM Identity Center mediante `sso-admin`. El `ID CUENTA` se usa como `TargetId`; no hace falta entrar con `AssumeRole` a cada cuenta miembro para crear/eliminar estas asignaciones cuando administras la instancia organizacional desde la cuenta autorizada.

Necesitas ejecutar el script con credenciales que tengan permisos sobre la instancia de IAM Identity Center y el Identity Store.

## Preparación

### 1. Instalar

```bash
python -m venv .venv
```
Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

### 2. AWS CLI / SSO

Para iniciar sesión la primera vez (se necita tener instalado AWS CLI):

```bash
aws configure sso
```
Una vez tengas creado el perfil puedes hacer:
```
aws sso login --profile nombre_perfil
```

Comprueba:

```bash
aws sts get-caller-identity --profile  nombre_perfil
```

### 3. Configuración

Copia `.env.example` a `.env` y define:

```text
AWS_PROFILE = nombre_perfil
AWS_REGION = us-east-1
TEMP_PERMISSION_SET = PRUEBA_TEMP
EXCEL_FILE = usuarios.xlsx
SHEET_NAME = Usuarios
```

## Primera prueba: solo lectura

Antes de modificar cualquier permiso:

```bash
python main.py verificar
```

Este comando **no modifica AWS ni el Excel**.

## Traer usuarios de una cuenta
Para crear (o agregar filas si el archivo ya existe) el archivo excel trayendo todos los usuarios de una cuenta específica (con posibilidad de filtrar por su permiso):

```bash
python get_data.py --cuenta Nombre --id-cuenta 1111111111 --permission Permiso_opcional
```
No modifica los datos existentes, y por ejemplo si se ejecuta dos veces van quedar dos filas repetidas por cada usuario
## Iniciar prueba

```bash
python main.py iniciar
```

Para cada fila nueva:

```text
Lee excel
  ↓
buscar usuario
  ↓
buscar Permission Set original del usuario en ID CUENTA
  ↓
quitar permisos originales
  ↓
asignar TEMP_PERMISSION_SET
  ↓
guardar PERMISO + (datetime.now) en INICIO PRUEBA
```

Si falla la asignación temporal después de quitar el original, el programa intenta devolver el original automáticamente.

## Finalizar prueba

```bash
python main.py finalizar 
```

Flujo:

```text
Leer excel
  ↓
buscar usuario
  ↓
comprobar Permission Set temporal
  ↓
quitar temporal
  ↓
buscar PERMISO originale(s)
  ↓
restaurarlo(s)
  ↓
guardar (datetime.now) en FIN PRUEBA
```

Si falla la restauración después de quitar el temporal, el programa intenta devolver el temporal como rollback.

## Decisiones de seguridad

- `verificar` es solo lectura.
- `iniciar` no procesa filas con fecha de inicio.
- `finalizar` no procesa filas con fecha de fin.
- `iniciar` retira todos los permisos asignados.
- No se permite iniciar si el usuario ya tiene el Permission Set temporal.
- No se permite finalizar si no está presente el Permission Set temporal.
- Las fechas se escriben solo después de completar correctamente la operación AWS.
- **Si el excel está abierto el programa no lo podrá actualizar**
- **Las operaciones `iniciar` y `finalizar` modifican TODO lo que este en el archivo y hoja indicados, sin importar la cuenta o fecha**.
