from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit
from uuid import uuid4

from psycopg.types.json import Jsonb

from leornian.platform.credentials import CredentialVault
from leornian.platform.model_contracts import (
    CHAT_ROLES,
    ModelConfiguration,
    ModelConnection,
    ModelConnectionInput,
    ModelConnectionPatch,
    ModelConnectionUseInput,
    ModelProfile,
    ModelProfileInput,
    ModelRoleAssignmentInput,
    ModelRoleMapping,
)
from leornian.platform.model_network import validate_endpoint
from leornian.platform.model_presets import PRESETS, preset_profiles, provider_presets
from leornian.shared_kernel.errors import BusinessError

CONNECTION_COLUMNS = (
    "c.id,c.revision,c.label,c.protocol,c.base_url,c.region,c.local_endpoint,c.enabled,"
    "c.deleted,c.credential_version,c.created_at,"
    "EXISTS(SELECT 1 FROM platform.model_credentials s WHERE s.connection_id=c.id "
    "AND s.version=c.credential_version AND s.ciphertext IS NOT NULL) AS credential_present"
)


@dataclass(frozen=True)
class MaterialProbeConfiguration:
    base_url: str
    protocol: str
    operation: str
    model: str
    dimensions: int
    timeout: int
    local_endpoint: bool
    api_key: str = field(repr=False)


class UserModels:
    def __init__(self, connection, settings):
        self.connection = connection
        self.settings = settings
        self.vault = CredentialVault(settings.credential_master_file)

    def connection_view(self, actor, connection_id, *, lock=False):
        row = self.connection.execute(
            "SELECT " + CONNECTION_COLUMNS + " FROM platform.model_connections c "
            "WHERE c.id=%s AND c.actor_id=%s" + (" FOR UPDATE OF c" if lock else ""),
            (connection_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Model connection not found.")
        return ModelConnection(**row)

    def configuration(self, actor):
        connections = self.connection.execute(
            "SELECT " + CONNECTION_COLUMNS + " FROM platform.model_connections c "
            "WHERE c.actor_id=%s ORDER BY c.created_at,c.id",
            (actor.id,),
        ).fetchall()
        profiles = self.connection.execute(
            "SELECT id FROM platform.model_profiles WHERE actor_id=%s ORDER BY created_at,id",
            (actor.id,),
        ).fetchall()
        mappings = self.connection.execute(
            "SELECT role,profile_id,revision FROM platform.model_role_mappings WHERE actor_id=%s",
            (actor.id,),
        ).fetchall()
        return ModelConfiguration(
            connections=[ModelConnection(**row) for row in connections],
            profiles=[self.profile(actor, row["id"]) for row in profiles],
            mappings=[ModelRoleMapping(**row) for row in mappings],
            credential_storage="available" if self.vault.available() else "waiting_config",
            configuration_scope=self.settings.model_configuration_mode,
            capabilities=[
                "explicit-role-assignment.v1", "provider-presets.v1",
                "provider-presets.v2", "provider-presets.v3",
                "material-web-search.v1",
            ],
            presets=provider_presets(),
        )

    def apply_preset(self, actor, key, preset_id, data):
        request = {
            "kind": "provider-preset.apply",
            "preset_id": preset_id,
            **data.model_dump(mode="json"),
            "credential_identity": hashlib.sha256(
                data.api_key.get_secret_value().encode()
            ).hexdigest(),
        }
        previous = self._replay(actor, key, request)
        if previous:
            return self.connection_view(actor, previous)
        preset = PRESETS[preset_id]
        available = [
            profile for profile in preset["profiles"]
            if data.group is None or
            (profile["operation"] == "chat") == (data.group == "teaching")
        ]
        models = data.models if data.models is not None else [
            profile["model"] for profile in available
        ]
        if (
            not models or len(models) != len(set(models))
            or not set(models) <= {profile["model"] for profile in available}
        ):
            raise BusinessError("precondition_failed", "Choose models from this provider preset.")
        command = "preset:" + hashlib.sha256(key.encode()).hexdigest()
        if data.connection_id:
            current = self.connection_view(actor, data.connection_id, lock=True)
            if current.deleted or current.local_endpoint or any(
                getattr(current, field) != preset[field]
                for field in ("protocol", "base_url", "region")
            ):
                raise BusinessError(
                    "precondition_failed", "Choose this preset's existing provider connection."
                )
            result = self.patch_connection(
                actor,
                current.id,
                ModelConnectionPatch(
                    expected_revision=data.expected_connection_revision,
                    enabled=True,
                    api_key=data.api_key,
                ),
            )
        else:
            result = self.create_connection(
                actor,
                command + ":connection",
                ModelConnectionInput(
                    label=preset["label"],
                    protocol=preset["protocol"],
                    base_url=preset["base_url"],
                    region=preset["region"],
                    enabled=True,
                    api_key=data.api_key,
                ),
            )
        configuration = self.configuration(actor)
        mappings = {item.role: item for item in configuration.mappings}
        for fields in preset_profiles(preset_id, result.id, models):
            profile = next(
                (
                    item for item in configuration.profiles
                    if item.model_dump(exclude={"id", "revision", "created_at"})
                    == fields.model_dump()
                ),
                None,
            ) or self.save_profile(
                actor, command + ":" + fields.operation, fields, assign_roles=False
            )
            for role in profile.roles:
                # Qwen fills missing chat roles without replacing an existing teaching model.
                if (preset_id == "qwen" and data.group is None
                        and role in CHAT_ROLES and role in mappings):
                    continue
                self.assign_role(
                    actor,
                    role,
                    ModelRoleAssignmentInput(
                        profile_id=profile.id,
                        expected_profile_revision=profile.revision,
                        expected_mapping_revision=data.expected_mapping_revisions.get(role, 0),
                    ),
                )
        self._remember(actor, key, request, result.id)
        return result

    def create_custom_provider(self, actor, key, data):
        request = {
            "kind": "provider.custom",
            **data.model_dump(mode="json"),
            "credential_identity": hashlib.sha256(
                data.connection.api_key.get_secret_value().encode()
            ).hexdigest(),
        }
        previous = self._replay(actor, key, request)
        if previous:
            return self.connection_view(actor, previous)
        command = "custom:" + hashlib.sha256(key.encode()).hexdigest()
        connection = self.create_connection(actor, command + ":connection", data.connection)
        profile = self.save_profile(
            actor, command + ":profile",
            ModelProfileInput(
                **data.profile.model_dump(), connection_id=connection.id,
                roles=list(CHAT_ROLES) if data.group == "teaching" else [data.profile.operation],
                enabled=True, allow_private_material=True,
            ),
            assign_roles=False,
        )
        self.use_connection(actor, command + ":use", connection.id, ModelConnectionUseInput(
            expected_connection_revision=connection.revision, group=data.group,
            profiles=[{"profile_id": profile.id, "expected_revision": profile.revision}],
            expected_mapping_revisions=data.expected_mapping_revisions,
        ))
        self._remember(actor, key, request, connection.id)
        return connection

    def use_connection(self, actor, key, connection_id, data):
        request = {
            "kind": "connection.use", "connection_id": str(connection_id),
            **data.model_dump(mode="json"),
        }
        if self._replay(actor, key, request):
            return self.configuration(actor)
        connection = self.connection_view(actor, connection_id, lock=True)
        if connection.revision != data.expected_connection_revision:
            raise BusinessError("stale_version", "Model connection changed.")
        desired = {}
        allowed = (
            set(CHAT_ROLES) if data.group == "teaching" else {"ocr", "embedding", "rerank"}
        )
        for item in data.profiles:
            profile = self.profile(actor, item.profile_id, lock=True)
            if profile.revision != item.expected_revision:
                raise BusinessError("stale_version", "Model profile changed.")
            if profile.connection_id != connection_id:
                raise BusinessError("precondition_failed", "Choose this connection's profiles.")
            if not profile.allow_private_material:
                raise BusinessError("precondition_failed", "Authorize this profile's material use.")
            roles = set(profile.roles)
            if not roles or not roles <= allowed or roles & desired.keys():
                raise BusinessError("precondition_failed", "Choose distinct compatible profiles.")
            desired.update(dict.fromkeys(roles, profile))
        if data.group == "teaching" and set(desired) != set(CHAT_ROLES):
            raise BusinessError("precondition_failed", "Choose a complete teaching profile.")
        for role, profile in desired.items():
            self.assign_role(actor, role, ModelRoleAssignmentInput(
                profile_id=profile.id,
                expected_profile_revision=profile.revision,
                expected_mapping_revision=data.expected_mapping_revisions.get(role, 0),
            ))
        self._remember(actor, key, request, connection_id)
        return self.configuration(actor)

    def _remember(self, actor, key, request, result_ref):
        self.connection.execute(
            "INSERT INTO platform.model_configuration_commands"
            "(actor_id,command_key,request,result_ref) VALUES (%s,%s,%s,%s)",
            (actor.id, key, Jsonb(request), result_ref),
        )

    def _replay(self, actor, key, request):
        row = self.connection.execute(
            "SELECT request,result_ref FROM platform.model_configuration_commands "
            "WHERE actor_id=%s AND command_key=%s",
            (actor.id, key),
        ).fetchone()
        if row and row["request"] != request:
            raise BusinessError(
                "idempotency_conflict", "Model configuration key has different input."
            )
        return row["result_ref"] if row else None

    def create_connection(self, actor, key, data):
        secret = data.api_key.get_secret_value()
        request = {
            "kind": "connection.create",
            **data.model_dump(mode="json"),
            # Used only for command idempotency; never returned as a credential descriptor.
            "credential_identity": hashlib.sha256(secret.encode()).hexdigest(),
        }
        previous = self._replay(actor, key, request)
        if previous:
            return self.connection_view(actor, previous)
        validate_endpoint(data.base_url, data.local_endpoint)
        if data.protocol == "dashscope":
            self._dashscope_region(data.base_url, data.region, data.local_endpoint)
        connection_id = uuid4()
        scheme, ciphertext = self.vault.seal(actor.id, connection_id, 1, secret)
        self.connection.execute(
            "INSERT INTO platform.model_connections"
            "(id,actor_id,revision,label,protocol,base_url,region,local_endpoint,enabled,"
            "credential_version) VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,1)",
            (
                connection_id,
                actor.id,
                data.label,
                data.protocol,
                data.base_url,
                data.region,
                data.local_endpoint,
                data.enabled,
            ),
        )
        self.connection.execute(
            "INSERT INTO platform.model_credentials(connection_id,version,scheme,ciphertext) "
            "VALUES (%s,1,%s,%s)",
            (connection_id, scheme, ciphertext),
        )
        view = self.connection_view(actor, connection_id)
        self._connection_version(view)
        self._remember(actor, key, request, connection_id)
        return view

    @staticmethod
    def _dashscope_region(base_url, region, local):
        regions = {
            "cn-beijing": "cn-beijing",
            "singapore": "ap-southeast-1",
            "ap-southeast-1": "ap-southeast-1",
            "us-virginia": "us-east-1",
            "us-east-1": "us-east-1",
            "cn-hongkong": "cn-hongkong",
        }
        legacy_hosts = {
            "cn-beijing": "dashscope.aliyuncs.com",
            "ap-southeast-1": "dashscope-intl.aliyuncs.com",
            "us-east-1": "dashscope-us.aliyuncs.com",
        }
        url, canonical = urlsplit(base_url), regions.get(region)
        host = url.hostname or ""
        suffix = "." + canonical + ".maas.aliyuncs.com" if canonical else ""
        workspace = host.removesuffix(suffix) if suffix and host.endswith(suffix) else ""
        known_root = canonical is not None and (
            host == legacy_hosts.get(canonical)
            or bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", workspace))
        )
        if local or url.scheme != "https" or url.path or not known_root:
            raise BusinessError(
                "precondition_failed",
                "DashScope requires a matching regional or workspace API root.",
            )

    def _connection_version(self, view):
        self.connection.execute(
            "INSERT INTO platform.model_connection_versions"
            "(connection_id,revision,configuration) VALUES (%s,%s,%s)",
            (view.id, view.revision, Jsonb(view.model_dump(mode="json"))),
        )

    def patch_connection(self, actor, connection_id, data):
        view = self.connection_view(actor, connection_id, lock=True)
        if view.deleted:
            raise BusinessError("precondition_failed", "Deleted credentials cannot be re-enabled.")
        if view.revision != data.expected_revision:
            raise BusinessError("stale_version", "Model connection changed.")
        credential_version = view.credential_version
        if data.api_key is not None:
            credential_version += 1
            scheme, ciphertext = self.vault.seal(
                actor.id, connection_id, credential_version, data.api_key.get_secret_value()
            )
            self.connection.execute(
                "INSERT INTO platform.model_credentials(connection_id,version,scheme,ciphertext) "
                "VALUES (%s,%s,%s,%s)",
                (connection_id, credential_version, scheme, ciphertext),
            )
        self.connection.execute(
            "UPDATE platform.model_connections SET revision=revision+1,label=%s,enabled=%s,"
            "credential_version=%s WHERE id=%s",
            (
                data.label if data.label is not None else view.label,
                data.enabled if data.enabled is not None else view.enabled,
                credential_version,
                connection_id,
            ),
        )
        result = self.connection_view(actor, connection_id)
        self._connection_version(result)
        return result

    def delete_connection(self, actor, connection_id, revision):
        view = self.connection_view(actor, connection_id, lock=True)
        if view.deleted and revision == view.revision - 1:
            return view
        if view.revision != revision:
            raise BusinessError("stale_version", "Model connection changed.")
        self.connection.execute(
            "UPDATE platform.model_connections SET enabled=false,deleted=true,revision=revision+1 "
            "WHERE id=%s",
            (connection_id,),
        )
        self.connection.execute(
            "UPDATE platform.model_credentials SET ciphertext=NULL,deleted_at=now() "
            "WHERE connection_id=%s AND ciphertext IS NOT NULL",
            (connection_id,),
        )
        result = self.connection_view(actor, connection_id)
        self._connection_version(result)
        return result

    def profile(self, actor, profile_id, *, lock=False):
        row = self.connection.execute(
            "SELECT p.id,p.revision,p.created_at,v.configuration "
            "FROM platform.model_profiles p JOIN platform.model_profile_versions v "
            "ON v.profile_id=p.id AND v.revision=p.revision WHERE p.id=%s AND p.actor_id=%s "
            + ("FOR UPDATE OF p" if lock else ""),
            (profile_id, actor.id),
        ).fetchone()
        if not row:
            raise BusinessError("not_found", "Model profile not found.")
        return ModelProfile(
            id=row["id"],
            revision=row["revision"],
            created_at=row["created_at"],
            **row["configuration"],
        )

    def save_profile(self, actor, key, data, profile_id=None, *, assign_roles=True):
        fields = data.model_dump(mode="json", exclude={"expected_revision"})
        request = {"kind": "profile.create", **fields}
        if not assign_roles:
            request["assign_roles"] = False
        if profile_id is None:
            previous = self._replay(actor, key, request)
            if previous:
                return self.profile(actor, previous)
        connection = self.connection_view(actor, data.connection_id, lock=True)
        if connection.deleted:
            raise BusinessError("precondition_failed", "Choose a non-deleted model connection.")
        if connection.protocol == "chat_completions" and data.operation not in {
            "chat",
            "embedding",
            "ocr",
        }:
            raise BusinessError(
                "precondition_failed", "Dedicated operation needs its real protocol."
            )
        if profile_id is not None:
            original = self.profile(actor, profile_id, lock=True)
            if original.revision != data.expected_revision:
                raise BusinessError("stale_version", "Model profile changed.")
            revision = original.revision + 1
            self.connection.execute(
                "UPDATE platform.model_profiles SET revision=%s WHERE id=%s",
                (revision, profile_id),
            )
        else:
            profile_id, revision = uuid4(), 1
            self.connection.execute(
                "INSERT INTO platform.model_profiles(id,actor_id,revision) VALUES (%s,%s,1)",
                (profile_id, actor.id),
            )
        self.connection.execute(
            "INSERT INTO platform.model_profile_versions(profile_id,revision,configuration) "
            "VALUES (%s,%s,%s)",
            (profile_id, revision, Jsonb(fields)),
        )
        if assign_roles:
            # Keep role revisions monotonic when a profile loses a role qualification.
            for role in data.roles:
                self.connection.execute(
                    "INSERT INTO platform.model_role_mappings(actor_id,role,profile_id,revision) "
                    "VALUES (%s,%s,%s,1) ON CONFLICT (actor_id,role) DO UPDATE "
                    "SET profile_id=EXCLUDED.profile_id,revision=model_role_mappings.revision+1 "
                    + (
                        "WHERE model_role_mappings.profile_id=EXCLUDED.profile_id"
                        if revision > 1
                        else ""
                    ),
                    (actor.id, role, profile_id),
                )
        if revision == 1:
            self._remember(actor, key, request, profile_id)
        return self.profile(actor, profile_id)

    def assign_role(self, actor, role, data):
        original = self.profile(actor, data.profile_id)
        connection = self.connection_view(actor, original.connection_id, lock=True)
        profile = self.profile(actor, data.profile_id, lock=True)
        if profile.revision != data.expected_profile_revision:
            raise BusinessError("stale_version", "Model profile changed.")
        operation = "chat" if role in CHAT_ROLES else role
        if role not in profile.roles or profile.operation != operation:
            raise BusinessError(
                "precondition_failed", "Choose a model profile that allows this role."
            )
        if (
            not profile.enabled
            or not connection.enabled
            or connection.deleted
            or not connection.credential_present
        ):
            raise BusinessError(
                "precondition_failed", "Enable the model profile and its credential connection."
            )
        current = self.connection.execute(
            "SELECT role,profile_id,revision FROM platform.model_role_mappings "
            "WHERE actor_id=%s AND role=%s FOR UPDATE",
            (actor.id, role),
        ).fetchone()
        if (current["revision"] if current else 0) != data.expected_mapping_revision:
            raise BusinessError("stale_version", "Model role assignment changed.")
        row = self.connection.execute(
            "INSERT INTO platform.model_role_mappings(actor_id,role,profile_id,revision) "
            "VALUES (%s,%s,%s,1) ON CONFLICT (actor_id,role) DO UPDATE "
            "SET profile_id=EXCLUDED.profile_id,revision=model_role_mappings.revision+1 "
            "RETURNING role,profile_id,revision",
            (actor.id, role, profile.id),
        ).fetchone()
        return ModelRoleMapping(**row)

    def binding(self, actor, role, *, require_private=True):
        row = self.connection.execute(
            "SELECT profile_id,revision FROM platform.model_role_mappings "
            "WHERE actor_id=%s AND role=%s",
            (actor.id, role),
        ).fetchone()
        if not row:
            raise BusinessError("model_unavailable", "Configure and enable this model role.")
        profile = self.profile(actor, row["profile_id"])
        connection = self.connection_view(actor, profile.connection_id)
        if (
            not profile.enabled
            or role not in profile.roles
            or profile.operation != ("chat" if role in CHAT_ROLES else role)
            or not connection.enabled
            or connection.deleted
            or not connection.credential_present
            or (require_private and not profile.allow_private_material)
        ):
            raise BusinessError(
                "model_unavailable", "Model role or material sharing is not enabled."
            )
        return {
            "scope": "user",
            "owner_id": str(actor.id),
            "profile_id": str(profile.id),
            "profile_revision": profile.revision,
            "connection_id": str(connection.id),
            "connection_revision": connection.revision,
            "credential_version": connection.credential_version,
            "role": role,
            "mapping_revision": row["revision"],
            "model": profile.model,
            "operation": profile.operation,
            "region": connection.region,
            "protocol": connection.protocol,
            "base_url": connection.base_url,
        }

    def validate_binding(self, actor, binding, *, require_private=True):
        current = self.binding(actor, binding["role"], require_private=require_private)
        if current != binding:
            raise BusinessError(
                "model_unavailable", "Frozen model configuration changed; no request was sent."
            )
        # Lock the owners through the dispatch transaction, serializing credential revocation.
        self.connection.execute(
            "SELECT id FROM platform.model_connections WHERE id=%s AND actor_id=%s FOR SHARE",
            (binding["connection_id"], actor.id),
        )
        self.connection.execute(
            "SELECT id FROM platform.model_profiles WHERE id=%s AND actor_id=%s FOR SHARE",
            (binding["profile_id"], actor.id),
        )
        self.connection.execute(
            "SELECT role FROM platform.model_role_mappings WHERE actor_id=%s AND role=%s FOR SHARE",
            (actor.id, binding["role"]),
        )
        # The profile may have changed while waiting for the share lock.
        if self.binding(actor, binding["role"], require_private=require_private) != binding:
            raise BusinessError("model_unavailable", "Model configuration changed before dispatch.")

    def probe_binding(self, actor, profile_id):
        profile = self.profile(actor, profile_id)
        connection = self.connection_view(actor, profile.connection_id)
        if (
            not profile.enabled
            or not connection.enabled
            or connection.deleted
            or not connection.credential_present
        ):
            raise BusinessError(
                "model_unavailable", "Enable this model and its connection to test."
            )
        return {
            "scope": "user",
            "purpose": "connection-probe.v1",
            "owner_id": str(actor.id),
            "profile_id": str(profile.id),
            "profile_revision": profile.revision,
            "connection_id": str(connection.id),
            "connection_revision": connection.revision,
            "credential_version": connection.credential_version,
            "model": profile.model,
            "operation": profile.operation,
            "region": connection.region,
            "protocol": connection.protocol,
            "base_url": connection.base_url,
        }

    def validate_probe_binding(self, actor, binding):
        if (
            binding.get("purpose") != "connection-probe.v1"
            or self.probe_binding(actor, binding["profile_id"]) != binding
        ):
            raise BusinessError("model_unavailable", "Frozen model test configuration changed.")
        self.connection.execute(
            "SELECT id FROM platform.model_connections WHERE id=%s AND actor_id=%s FOR SHARE",
            (binding["connection_id"], actor.id),
        )
        self.connection.execute(
            "SELECT id FROM platform.model_profiles WHERE id=%s AND actor_id=%s FOR SHARE",
            (binding["profile_id"], actor.id),
        )
        if self.probe_binding(actor, binding["profile_id"]) != binding:
            raise BusinessError("model_unavailable", "Model test configuration changed.")

    def resolve_chat(self, actor, binding, *, require_private=True):
        self.validate_binding(actor, binding, require_private=require_private)
        profile = self.profile(actor, binding["profile_id"])
        if profile.operation != "chat":
            raise BusinessError("model_unavailable", "This role needs a chat model profile.")
        return self._chat_configuration(actor, binding, profile)

    def _chat_configuration(self, actor, binding, profile):
        secret = self._secret(actor, binding)
        endpoint = binding["base_url"]
        if binding["protocol"] == "dashscope":
            endpoint += "/compatible-mode/v1"
        return replace(
            self.settings,
            model_enabled=True,
            model_base_url=endpoint,
            model_name=profile.model,
            model_api_key=secret,
            model_thinking=profile.thinking or "enabled",
            model_stage_thinking="{}",
            model_context_tokens=profile.context_tokens,
            model_max_output_tokens=profile.max_output_tokens,
            model_timeout=profile.timeout_seconds,
            model_network_guard=True,
            model_local_endpoint=self.connection_view(
                actor, binding["connection_id"]
            ).local_endpoint,
            model_profile_timeout=profile.timeout_seconds,
        )

    def resolve_material_probe(self, actor, binding):
        return self.resolve_material(actor, binding, require_private=False)

    def resolve_material(self, actor, binding, *, require_private=True):
        self.validate_binding(actor, binding, require_private=require_private)
        profile = self.profile(actor, binding["profile_id"])
        if profile.operation == "chat":
            raise BusinessError("model_unavailable", "Choose a dedicated material operation.")
        return self._material_configuration(actor, binding, profile)

    def _material_configuration(self, actor, binding, profile):
        return MaterialProbeConfiguration(
            base_url=binding["base_url"],
            protocol=binding["protocol"],
            operation=profile.operation,
            model=profile.model,
            dimensions=profile.embedding_dimensions,
            timeout=profile.timeout_seconds,
            local_endpoint=self.connection_view(actor, binding["connection_id"]).local_endpoint,
            api_key=self._secret(actor, binding),
        )

    def resolve_probe(self, actor, binding):
        self.validate_probe_binding(actor, binding)
        profile = self.profile(actor, binding["profile_id"])
        if profile.operation == "chat":
            return self._chat_configuration(actor, binding, profile)
        return self._material_configuration(actor, binding, profile)

    def _secret(self, actor, binding):
        credential = self.connection.execute(
            "SELECT scheme,ciphertext FROM platform.model_credentials "
            "WHERE connection_id=%s AND version=%s",
            (binding["connection_id"], binding["credential_version"]),
        ).fetchone()
        if not credential or credential["ciphertext"] is None:
            raise BusinessError("model_unavailable", "The model credential was deleted.")
        return self.vault.open(
            actor.id,
            binding["connection_id"],
            binding["credential_version"],
            credential["scheme"],
            credential["ciphertext"],
        )
