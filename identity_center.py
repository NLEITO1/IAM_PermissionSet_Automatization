import time
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError


class IdentityCenter:
    """
    Administra asignaciones de IAM Identity Center desde la cuenta
    donde está disponible la instancia de Identity Center.

    No hace AssumeRole hacia cada cuenta miembro: el AccountId se usa
    como TargetId de las operaciones de SSO Admin.
    """

    def __init__(self, profile_name=None, region_name=None):
        session = boto3.Session(profile_name=profile_name, region_name=region_name)
        self.sso = session.client("sso-admin")
        self._instances = self._get_instances()

        if not self._instances:
            raise RuntimeError(
                "No se encontró una instancia activa de IAM Identity Center "
                "con las credenciales/perfil actuales."
            )

        # Para este proyecto esperamos una instancia organizacional única.
        active = [x for x in self._instances if x.get("Status") == "ACTIVE"]
        if not active:
            raise RuntimeError("Se encontraron instancias de Identity Center, pero ninguna está ACTIVE.")
        if len(active) > 1:
            raise RuntimeError(
                "Se encontraron varias instancias ACTIVE. "
                "Configura explícitamente cuál usar antes de continuar."
            )

        self.instance_arn = active[0]["InstanceArn"]
        self.identity_store_id = active[0]["IdentityStoreId"]
        self.identity_store = session.client("identitystore")

        self._permission_sets_by_name = None
        self._permission_set_names_by_arn = {} 
        self._users_by_username = {}

    def _get_instances(self):
        paginator = self.sso.get_paginator("list_instances")
        instances = []
        for page in paginator.paginate():
            instances.extend(page.get("Instances", []))
        return instances

    def _load_permission_sets(self):
        if self._permission_sets_by_name is not None:
            return

        self._permission_sets_by_name = {}
        paginator = self.sso.get_paginator("list_permission_sets")

        for page in paginator.paginate(InstanceArn=self.instance_arn):
            for arn in page.get("PermissionSets", []):
                info = self.sso.describe_permission_set(
                    InstanceArn=self.instance_arn,
                    PermissionSetArn=arn,
                )["PermissionSet"]
                name = info["Name"]
                if name in self._permission_sets_by_name:
                    raise RuntimeError(f"Hay varios Permission Sets con el nombre '{name}'.")
                self._permission_sets_by_name[name] = arn
                self._permission_set_names_by_arn[arn] = name
                
    def permission_set_name(self, arn: str) -> str:
        """
        Resuelve el nombre de un Permission Set a partir de su ARN.
        Primero busca en la caché (O(1)). Si el Permission Set fue creado
        después de que se cargó la caché, hace un describe_permission_set
        directo a AWS y guarda el resultado en caché para próximas llamadas.
        """
        self._load_permission_sets()

        name = self._permission_set_names_by_arn.get(arn)
        if name is not None:
            return name

        try:
            info = self.sso.describe_permission_set(
                InstanceArn=self.instance_arn,
                PermissionSetArn=arn,
            )["PermissionSet"]
        except ClientError:
            raise ValueError(f"No se encontró un Permission Set con ARN '{arn}'.")

        name = info["Name"]
        self._permission_set_names_by_arn[arn] = name
        self._permission_sets_by_name.setdefault(name, arn)
        return name

    def obtener_usuarios(self):
        """Devuelve {UserId: UserName} para los usuarios del Identity Center."""
        usuarios = {}
        paginator = self.identity_store.get_paginator("list_users")
        for page in paginator.paginate(IdentityStoreId=self.identity_store_id):
            for user in page.get("Users", []):
                usuarios[user["UserId"]] = user["UserName"]
        #print(f"Se encontraron {len(usuarios)} usuarios en Identity Center.")
        return usuarios

    def obtener_grupos(self):
        """Devuelve {GroupId: DisplayName} para los grupos del Identity Center."""
        grupos = {}
        paginator = self.identity_store.get_paginator("list_groups")
        for page in paginator.paginate(IdentityStoreId=self.identity_store_id):
            for group in page.get("Groups", []):
                grupos[group["GroupId"]] = group["DisplayName"]
        #print(f"Se encontraron {len(grupos)} grupos en Identity Center.")
        return grupos
    
    def obtener_asignaciones(self, account_id):
        """Obtiene las asignaciones de todos los Permission Sets de una cuenta."""
        asignaciones = []
        self._load_permission_sets()
        permission_sets = list(self._permission_sets_by_name.values())
        #print(f"Se encontraron {len(permission_sets)} Permission Sets.")
        for permission_set_arn in permission_sets:
            try:
                paginator = self.sso.get_paginator("list_account_assignments")
                for page in paginator.paginate(
                    InstanceArn=self.instance_arn,
                    AccountId=account_id,
                    PermissionSetArn=permission_set_arn,
                ):
                    asignaciones.extend(page.get("AccountAssignments", []))
            except ClientError as e:
                print(f"[AVISO] No se pudo consultar {permission_set_arn}: {e}")
        return asignaciones

    def permission_set_arn(self, name: str) -> str:
        self._load_permission_sets()
        try:
            return self._permission_sets_by_name[name]
        except KeyError:
            raise ValueError(f"No existe el Permission Set '{name}'.")

    def user_id(self, username: str, user_type:str="PERSONA") -> str:
        if username in self._users_by_username:
            return self._users_by_username[username]
        if user_type.upper() =="PERSONA":
        # GetUserId permite buscar por UserName y evita depender de ListUsers.
            response = self.identity_store.get_user_id(
                IdentityStoreId=self.identity_store_id,
                AlternateIdentifier={
                    "UniqueAttribute": {
                        "AttributePath": "UserName",
                        "AttributeValue": username,
                    }
                },
            )
            user_id = response["UserId"]
        elif user_type.upper()=="GRUPO":
            response = self.identity_store.get_group_id(
                IdentityStoreId=self.identity_store_id,
                AlternateIdentifier={
                    "UniqueAttribute": {
                        "AttributePath": "DisplayName",
                        "AttributeValue": username,
                    }
                },
            )
            user_id = response["GroupId"]
        else:
            raise ValueError(f"Tipo de usuario desconocido: {user_type}, solo se permiten 'PERSONA' o 'GRUPO'")
        
        self._users_by_username[username] = user_id
        return user_id

    def assignments_for_user(self, account_id: str, user_id: str, user_type: str="PERSONA") -> List[Dict]:
        paginator = self.sso.get_paginator("list_account_assignments_for_principal")
        result = []
        user_type= "GROUP" if user_type.upper()=="GRUPO" else "USER"
        

        for page in paginator.paginate(
            InstanceArn=self.instance_arn,
            PrincipalId=user_id,
            PrincipalType=user_type,
            Filter={"AccountId": account_id},
        ):
            result.extend(page.get("AccountAssignments", []))
        return result

    def current_permission_sets(self, account_id: str, user_id: str) -> List[str]: #BORARR 
        assignments = self.assignments_for_user(account_id, user_id)
        return [x["PermissionSetArn"] for x in assignments if x["PrincipalType"] == "USER"]

    def _wait_creation(self, request_id: str, target: str):
        while True:
            response = self.sso.describe_account_assignment_creation_status(
                InstanceArn=self.instance_arn,
                AccountAssignmentCreationRequestId=request_id,
            )["AccountAssignmentCreationStatus"]

            status = response["Status"]
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                raise RuntimeError(
                    f"Falló la asignación en {target}: {response.get('FailureReason', 'sin detalle')}"
                )
            time.sleep(2)

    def _wait_deletion(self, request_id: str, target: str):
        while True:
            response = self.sso.describe_account_assignment_deletion_status(
                InstanceArn=self.instance_arn,
                AccountAssignmentDeletionRequestId=request_id,
            )["AccountAssignmentDeletionStatus"]

            status = response["Status"]
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                raise RuntimeError(
                    f"Falló la eliminación en {target}: {response.get('FailureReason', 'sin detalle')}"
                )
            time.sleep(2)

    def assign(self, account_id: str, user_id: str, permission_set_arn: str, user_type: str="PERSONA"):
        user_type= "GROUP" if user_type.upper()=="GRUPO" else "USER"
        response = self.sso.create_account_assignment(
            InstanceArn=self.instance_arn,
            TargetId=account_id,
            TargetType="AWS_ACCOUNT",
            PermissionSetArn=permission_set_arn,
            PrincipalType=user_type,
            PrincipalId=user_id,
        )
        request_id = response["AccountAssignmentCreationStatus"]["RequestId"]
        self._wait_creation(request_id, account_id)

    def remove(self, account_id: str, user_id: str, permission_set_arn: str, user_type: str="PERSONA"):
        user_type= "GROUP" if user_type.upper()=="GRUPO" else "USER"
        #print(f"Eliminando asignación: {user_type} {user_id} en cuenta {account_id} para Permission Set {permission_set_arn}")
        response = self.sso.delete_account_assignment(
            InstanceArn=self.instance_arn,
            TargetId=account_id,
            TargetType="AWS_ACCOUNT",
            PermissionSetArn=permission_set_arn,
            PrincipalType=user_type,
            PrincipalId=user_id,
        )
        request_id = response["AccountAssignmentDeletionStatus"]["RequestId"]
        self._wait_deletion(request_id, account_id)