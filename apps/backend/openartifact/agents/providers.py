"""LLM providers and their models: OpenRouter and OpenAI-compatible endpoints.

A provider holds where requests go and the *name* of the secret with its API key, never the key. Its
models are fetched from its ``/models`` or, for an endpoint without one, defined by hand; only a model
that is enabled can be chosen for an agent.

A provider is saved only after its connection test passed (:meth:`ProviderService.test`): the address
is checked by the same guarded HTTP path every later request takes (``agents/client.py``), and the
answer must have the shape of an OpenAI-compatible API, not just a success status. For an endpoint
without ``/models`` that means one minimal chat completion with a model defined by hand.

A private or local address needs two permissions: the operator's ``OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS``
and the provider's own ``allow_private``. A refusal is an ``ArtifactError``; every change publishes
``providers.changed``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.agents import client
from openartifact.agents.client import (
    Endpoint,
    IncompatibleError,
    NoModelListError,
    ProviderError,
)
from openartifact.agents.freeze import base_url_of
from openartifact.agents.schemas import (
    MAX_MODELS_PER_PROVIDER,
    MAX_PROVIDERS,
    CheckResult,
    CheckStep,
    ModelCreate,
    ModelRead,
    ModelUpdate,
    ProviderRead,
    ProviderUpdate,
    ProviderWrite,
)
from openartifact.config import Settings
from openartifact.credentials.refs import is_name
from openartifact.credentials.store import SecretResolveError, SecretStore
from openartifact.database import SessionOpener
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models import (
    Agent,
    AgentVersion,
    GraphNode,
    LlmModel,
    LlmProvider,
    NodeKind,
    ProviderKind,
)

#: A whole connection test (all its requests) takes at most this long.
CHECK_TIMEOUT_SECONDS = 45.0
REQUEST_TIMEOUT_SECONDS = 20.0
HTTP_WARNING = (
    "The address uses http: the API key and every prompt travel unencrypted. Use it only for an "
    "endpoint on this host or in a network you trust."
)
PRIVATE_WARNING = (
    "Private addresses are switched on for this provider but not by the operator "
    "(OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS): they stay refused."
)
SOURCE_FETCHED, SOURCE_MANUAL = "fetched", "manual"


def check_base_url(url: str | None) -> str:
    """The address of a custom provider, normalised; 422 if it cannot be one."""
    text = (url or "").strip().rstrip("/")
    try:
        parts = urlsplit(text)
        host = parts.hostname
        has_credentials = parts.username is not None or parts.password is not None
    except ValueError:
        parts, host, has_credentials = None, None, False
    if parts is None or parts.scheme not in ("http", "https") or not host:
        raise ArtifactError(422, "The address must be an http or https URL with a host")
    if has_credentials:
        raise ArtifactError(422, "The address must not contain a user name or password")
    if parts.query or parts.fragment:
        raise ArtifactError(422, "The address must not have a query or a fragment")
    return text


class ProviderService:
    """Everything the APIs do with providers and models."""

    def __init__(
        self, session: SessionOpener, bus: EventBus, settings: Settings, secrets: SecretStore
    ) -> None:
        self._session = session
        self._bus = bus
        self._settings = settings
        self._secrets = secrets

    # ── reading ───────────────────────────────────────────────────────

    def _warnings(self, provider: LlmProvider) -> list[str]:
        warnings = []
        if base_url_of(provider).startswith("http://"):
            warnings.append(HTTP_WARNING)
        if provider.allow_private and not self._settings.llm_allow_private_networks:
            warnings.append(PRIVATE_WARNING)
        return warnings

    async def _read(self, session: AsyncSession, provider: LlmProvider) -> ProviderRead:
        models = await session.scalars(
            select(LlmModel)
            .where(LlmModel.provider_id == provider.id)
            .order_by(LlmModel.enabled.desc(), LlmModel.model_id)
        )
        names = {s.name for s in await self._secrets.names()}
        return ProviderRead(
            id=provider.id,
            kind=provider.kind,
            name=provider.name,
            base_url=base_url_of(provider),
            secret_name=provider.secret_name,
            secret_exists=bool(provider.secret_name) and provider.secret_name in names,
            allow_private=provider.allow_private,
            private_effective=provider.allow_private
            and self._settings.llm_allow_private_networks
            and provider.kind != ProviderKind.OPENROUTER,
            default_model=provider.default_model,
            is_default=provider.is_default,
            checked_at=provider.checked_at,
            check_ok=provider.check_ok,
            check_message=provider.check_message,
            models=[ModelRead.model_validate(m) for m in models],
            warnings=self._warnings(provider),
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )

    @staticmethod
    async def _find(session: AsyncSession, ref: str) -> LlmProvider:
        found = await session.get(LlmProvider, ref)
        if found is None:
            found = await session.scalar(select(LlmProvider).where(LlmProvider.name == ref.strip()))
        if found is None:
            raise ArtifactError(404, "Provider not found")
        return found

    async def list_all(self) -> list[ProviderRead]:
        """All providers by name, each with its models."""
        async with self._session() as session:
            rows = (await session.scalars(select(LlmProvider).order_by(LlmProvider.name))).all()
            return [await self._read(session, p) for p in rows]

    async def get(self, ref: str) -> ProviderRead:
        async with self._session() as session:
            return await self._read(session, await self._find(session, ref))

    # ── the connection test ───────────────────────────────────────────

    async def _key(self, secret_name: str | None) -> str | None:
        if not secret_name:
            return None
        return (await self._secrets.resolve([secret_name]))[secret_name]

    async def _probe(
        self,
        kind: str,
        base_url: str,
        secret_name: str | None,
        allow_private: bool,
        probe_model: str | None,
    ) -> tuple[CheckResult, list[tuple[str, str]]]:
        result = CheckResult(ok=False, steps=[])
        steps, warnings = result.steps, result.warnings  # the model's own lists, filled below
        models: list[tuple[str, str]] = []

        def step(name: str, ok: bool, message: str) -> bool:
            steps.append(CheckStep(name=name, ok=ok, message=message))
            return ok

        if base_url.startswith("http://"):
            warnings.append(HTTP_WARNING)
        custom = kind != ProviderKind.OPENROUTER
        private = custom and allow_private and self._settings.llm_allow_private_networks
        if custom and allow_private and not private:
            warnings.append(PRIVATE_WARNING)
        try:
            key = await self._key(secret_name)
        except SecretResolveError as error:
            step("secret", False, str(error))
            return result, models
        if secret_name:
            step("secret", True, f"Secret {secret_name} is stored")
        endpoint = Endpoint(base_url, key, private)
        try:
            models = await client.list_models(endpoint, timeout=REQUEST_TIMEOUT_SECONDS)
        except (NoModelListError, IncompatibleError) as error:
            if not custom:
                step("models", False, error.message)
                return result, models
            step("models", True, f"{error.message}; models are defined by hand")
        except ProviderError as error:
            step("models", False, error.message)
            return result, models
        else:
            result.lists_models = True
            result.models = [model_id for model_id, _ in models]
            step("models", True, f"/models lists {len(models)} models in the OpenAI format")
        if not custom:
            try:
                await client.check_key(endpoint, timeout=REQUEST_TIMEOUT_SECONDS)
            except ProviderError as error:
                step("key", False, error.message)
                return result, models
            step("key", True, "The API key is accepted")
        elif not result.lists_models:
            if not probe_model:
                step(
                    "completion",
                    False,
                    "The endpoint lists no models: define a model by hand, it is used for the test",
                )
                return result, models
            try:
                await client.complete(
                    endpoint,
                    probe_model,
                    [{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except ProviderError as error:
                step("completion", False, f'Model "{probe_model}": {error.message}')
                return result, models
            step(
                "completion",
                True,
                f'A minimal chat completion with model "{probe_model}" was answered in the OpenAI format',
            )
        result.ok = True
        return result, models

    async def _check(
        self,
        kind: str,
        base_url: str,
        secret_name: str | None,
        allow_private: bool,
        probe_model: str | None,
    ) -> tuple[CheckResult, list[tuple[str, str]]]:
        """The test and the ``(id, label)`` models it found (bounded in time as a whole)."""
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                return await self._probe(kind, base_url, secret_name, allow_private, probe_model)
        except TimeoutError:
            result = CheckResult(
                ok=False,
                steps=[
                    CheckStep(
                        name="time",
                        ok=False,
                        message=f"The test took longer than {CHECK_TIMEOUT_SECONDS:g} s",
                    )
                ],
            )
        return result, []

    def _checked_input(
        self, kind: str, base_url: str | None, secret_name: str | None
    ) -> tuple[str, str | None]:
        """The address and the secret name of a provider to be saved or tested; 422 if they cannot be."""
        if secret_name is not None and not is_name(secret_name):
            raise ArtifactError(
                422, "A secret name has capitals, digits and underscores and starts with a letter"
            )
        if kind == ProviderKind.OPENROUTER:
            if base_url:
                raise ArtifactError(422, "OpenRouter has a fixed address: leave base_url out")
            if not secret_name:
                raise ArtifactError(422, "OpenRouter needs the secret that holds its API key")
            return client.OPENROUTER_URL, secret_name
        return check_base_url(base_url), secret_name

    async def test(self, data: ProviderWrite) -> CheckResult:
        """Test a provider that is not saved (nothing is stored)."""
        base_url, secret_name = self._checked_input(data.kind, data.base_url, data.secret_name)
        probe = data.models[0].model_id if data.models else None
        return (await self._check(data.kind, base_url, secret_name, data.allow_private, probe))[0]

    async def check(self, ref: str) -> CheckResult:
        """Test a saved provider again and remember the outcome (it is shown with the provider)."""
        async with self._session() as session:
            provider = await self._find(session, ref)
            probe = await self._probe_model(session, provider)
            result, _ = await self._check(
                provider.kind,
                base_url_of(provider),
                provider.secret_name,
                provider.allow_private,
                probe,
            )
            self._remember(provider, result)
            await session.commit()
        self._changed()
        return result

    @staticmethod
    async def _probe_model(session: AsyncSession, provider: LlmProvider) -> str | None:
        if provider.default_model:
            return provider.default_model
        return await session.scalar(
            select(LlmModel.model_id)
            .where(LlmModel.provider_id == provider.id, LlmModel.available.is_(True))
            .order_by(LlmModel.enabled.desc(), LlmModel.model_id)
            .limit(1)
        )

    @staticmethod
    def _remember(provider: LlmProvider, result: CheckResult) -> None:
        provider.checked_at = datetime.now(UTC)
        provider.check_ok = result.ok
        failed = next((s for s in result.steps if not s.ok), None)
        provider.check_message = failed.message if failed else result.steps[-1].message

    @staticmethod
    def _refuse(result: CheckResult) -> ArtifactError:
        failed = next((s.message for s in result.steps if not s.ok), "it did not pass")
        return ArtifactError(422, f"The connection test failed: {failed}")

    # ── changing ──────────────────────────────────────────────────────

    def _changed(self) -> None:
        self._bus.publish("providers.changed", {})

    @staticmethod
    async def _free_name(session: AsyncSession, name: str, own_id: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise ArtifactError(422, "A provider needs a name")
        taken = await session.scalar(select(LlmProvider).where(LlmProvider.name == name))
        if taken is not None and taken.id != own_id:
            raise ArtifactError(409, f'A provider named "{taken.name}" exists already')
        return name

    @staticmethod
    async def _only_default(session: AsyncSession, provider: LlmProvider) -> None:
        for other in await session.scalars(
            select(LlmProvider).where(LlmProvider.is_default.is_(True))
        ):
            if other.id != provider.id:
                other.is_default = False

    @staticmethod
    async def _merge_models(
        session: AsyncSession, provider: LlmProvider, fetched: list[tuple[str, str]]
    ) -> None:
        """Bring the stored models in line with what the provider lists now.

        New ones are added switched off, listed ones become available again, a fetched one that is
        gone stays and is marked unavailable (configurations may name it). Models defined by hand are
        left alone, except that one the provider lists is available."""
        fetched = fetched[:MAX_MODELS_PER_PROVIDER]
        listed = dict(fetched)
        stored = {
            m.model_id: m
            for m in await session.scalars(
                select(LlmModel).where(LlmModel.provider_id == provider.id)
            )
        }
        for model_id, label in fetched:
            row = stored.get(model_id)
            if row is None:
                session.add(
                    LlmModel(
                        id=str(uuid.uuid4()),
                        provider_id=provider.id,
                        model_id=model_id[:200],
                        label=label[:200],
                        source=SOURCE_FETCHED,
                        enabled=False,
                        available=True,
                    )
                )
            else:
                row.available = True
                if label and row.source == SOURCE_FETCHED:
                    row.label = label[:200]
        for model_id, row in stored.items():
            if model_id not in listed and row.source == SOURCE_FETCHED:
                row.available = False

    async def create(self, data: ProviderWrite) -> ProviderRead:
        """Create a provider. It is tested first, and saved only if the test passes (422 otherwise)."""
        base_url, secret_name = self._checked_input(data.kind, data.base_url, data.secret_name)
        custom = data.kind != ProviderKind.OPENROUTER.value
        if data.models and not custom:
            raise ArtifactError(422, "OpenRouter's models come from its own list")
        async with self._session() as session:
            count = await session.scalar(select(func.count()).select_from(LlmProvider))
            if (count or 0) >= MAX_PROVIDERS:
                raise ArtifactError(409, f"At most {MAX_PROVIDERS} providers")
            if not custom and await session.scalar(
                select(LlmProvider).where(LlmProvider.kind == ProviderKind.OPENROUTER.value)
            ):
                raise ArtifactError(409, "OpenRouter is set up already")
            name = await self._free_name(session, data.name)
        probe = data.models[0].model_id if data.models else None
        result, fetched = await self._check(
            data.kind, base_url, secret_name, data.allow_private, probe
        )
        if not result.ok:
            raise self._refuse(result)
        known = {model_id for model_id, _ in fetched} | {m.model_id for m in data.models}
        if data.default_model and data.default_model not in known:
            raise ArtifactError(
                422, f'The default model "{data.default_model}" is not a model of the provider'
            )
        async with self._session() as session:
            provider = LlmProvider(
                id=str(uuid.uuid4()),
                kind=data.kind,
                name=name,
                base_url=base_url if custom else None,
                secret_name=secret_name,
                allow_private=data.allow_private and custom,
                default_model=data.default_model,
                is_default=data.is_default,
            )
            self._remember(provider, result)
            session.add(provider)
            try:
                await session.flush()
            except IntegrityError as error:
                raise ArtifactError(409, "A provider with this name exists already") from error
            await self._merge_models(session, provider, fetched)
            await session.flush()
            for manual in data.models:
                await self._put_manual(session, provider, manual)
            if data.default_model:
                await self._enable(session, provider.id, data.default_model)
            if data.is_default:
                await self._only_default(session, provider)
            await session.commit()
            read = await self._read(session, provider)
        self._changed()
        return read

    @staticmethod
    async def _model(session: AsyncSession, provider_id: str, model_id: str) -> LlmModel | None:
        return await session.scalar(
            select(LlmModel).where(
                LlmModel.provider_id == provider_id, LlmModel.model_id == model_id
            )
        )

    async def _enable(self, session: AsyncSession, provider_id: str, model_id: str) -> None:
        row = await self._model(session, provider_id, model_id)
        if row is not None:
            row.enabled = True

    async def _put_manual(
        self, session: AsyncSession, provider: LlmProvider, data: ModelCreate
    ) -> LlmModel:
        row = await self._model(session, provider.id, data.model_id)
        if row is not None:  # the provider lists it too: keep that row, apply what was asked
            row.enabled = data.enabled
            row.label = data.label or row.label
            return row
        row = LlmModel(
            id=str(uuid.uuid4()),
            provider_id=provider.id,
            model_id=data.model_id,
            label=data.label,
            source=SOURCE_MANUAL,
            enabled=data.enabled,
            available=True,
        )
        session.add(row)
        await session.flush()
        return row

    async def update(self, ref: str, data: ProviderUpdate) -> ProviderRead:
        """Change a provider. A new address, secret or private-network switch is tested first and
        saved only if the test passes (422 otherwise); the other fields are saved as they are."""
        sent = data.model_fields_set
        async with self._session() as session:
            provider = await self._find(session, ref)
            custom = provider.kind != ProviderKind.OPENROUTER
            base_url = base_url_of(provider)
            if "base_url" in sent:
                if not custom:
                    raise ArtifactError(422, "OpenRouter has a fixed address")
                base_url = check_base_url(data.base_url)
            secret_name = data.secret_name if "secret_name" in sent else provider.secret_name
            secret_name = (secret_name or "").strip() or None
            _, secret_name = self._checked_input(
                provider.kind, base_url if custom else None, secret_name
            )
            allow_private = (
                bool(data.allow_private) and custom
                if "allow_private" in sent and data.allow_private is not None
                else provider.allow_private
            )
            connection_changed = (
                base_url != base_url_of(provider)
                or secret_name != provider.secret_name
                or allow_private != provider.allow_private
            )
            fetched: list[tuple[str, str]] = []
            result = None
            if connection_changed:
                probe = await self._probe_model(session, provider)
                result, fetched = await self._check(
                    provider.kind, base_url, secret_name, allow_private, probe
                )
                if not result.ok:
                    raise self._refuse(result)
            if data.name is not None:
                provider.name = await self._free_name(session, data.name, provider.id)
            if connection_changed and result is not None:
                provider.base_url = base_url if custom else None
                provider.secret_name = secret_name
                provider.allow_private = allow_private
                self._remember(provider, result)
                if result.lists_models:
                    await self._merge_models(session, provider, fetched)
                    await session.flush()
            if "default_model" in sent:
                wanted = (data.default_model or "").strip() or None
                if wanted and await self._model(session, provider.id, wanted) is None:
                    raise ArtifactError(422, f'"{wanted}" is not a model of the provider')
                provider.default_model = wanted
                if wanted:
                    await self._enable(session, provider.id, wanted)
            if data.is_default is not None:
                provider.is_default = data.is_default
                if data.is_default:
                    await self._only_default(session, provider)
            provider.updated_at = datetime.now(UTC)
            await session.commit()
            read = await self._read(session, provider)
        self._changed()
        return read

    async def refresh_models(self, ref: str) -> ProviderRead:
        """Fetch the provider's model list again (409 if it has none, 502 if it cannot be read)."""
        async with self._session() as session:
            provider = await self._find(session, ref)
            custom = provider.kind != ProviderKind.OPENROUTER
            try:
                key = await self._key(provider.secret_name)
                endpoint = Endpoint(
                    base_url_of(provider),
                    key,
                    custom and provider.allow_private and self._settings.llm_allow_private_networks,
                )
                async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                    fetched = await client.list_models(endpoint, timeout=REQUEST_TIMEOUT_SECONDS)
            except SecretResolveError as error:
                raise ArtifactError(409, str(error)) from error
            except (NoModelListError, IncompatibleError) as error:
                raise ArtifactError(
                    409, f"{error.message}. Define the models of this provider by hand."
                ) from error
            except ProviderError as error:
                raise ArtifactError(
                    502, f"The model list could not be read: {error.message}"
                ) from error
            except TimeoutError as error:
                raise ArtifactError(502, "The model list could not be read: timeout") from error
            await self._merge_models(session, provider, fetched)
            provider.updated_at = datetime.now(UTC)
            await session.commit()
            read = await self._read(session, provider)
        self._changed()
        return read

    async def add_model(self, ref: str, data: ModelCreate) -> ProviderRead:
        """Define a model by hand (OpenAI-compatible providers only); 409 if it exists."""
        async with self._session() as session:
            provider = await self._find(session, ref)
            if provider.kind == ProviderKind.OPENROUTER:
                raise ArtifactError(409, "OpenRouter's models come from its own list")
            if await self._model(session, provider.id, data.model_id) is not None:
                raise ArtifactError(409, f'Model "{data.model_id}" exists already')
            count = await session.scalar(
                select(func.count()).where(LlmModel.provider_id == provider.id)
            )
            if (count or 0) >= MAX_MODELS_PER_PROVIDER:
                raise ArtifactError(409, f"At most {MAX_MODELS_PER_PROVIDER} models per provider")
            await self._put_manual(session, provider, data)
            await session.commit()
            read = await self._read(session, provider)
        self._changed()
        return read

    @staticmethod
    async def _model_row(session: AsyncSession, provider: LlmProvider, model_ref: str) -> LlmModel:
        row = await session.get(LlmModel, model_ref)
        if row is None or row.provider_id != provider.id:
            raise ArtifactError(404, "Model not found")
        return row

    async def update_model(self, ref: str, model_ref: str, data: ModelUpdate) -> ProviderRead:
        """Switch a model on or off, or change its label. A model that is switched off cannot be chosen
        any more; a node that still names it fails when its next execution starts."""
        async with self._session() as session:
            provider = await self._find(session, ref)
            row = await self._model_row(session, provider, model_ref)
            if data.enabled is not None:
                row.enabled = data.enabled
            if data.label is not None:
                row.label = data.label
            await session.commit()
            read = await self._read(session, provider)
        self._changed()
        return read

    async def delete_model(self, ref: str, model_ref: str) -> None:
        """Delete a model defined by hand; 409 for a fetched one (switch it off instead) and while a
        configuration names it."""
        async with self._session() as session:
            provider = await self._find(session, ref)
            row = await self._model_row(session, provider, model_ref)
            if row.source != SOURCE_MANUAL:
                raise ArtifactError(
                    409, "A model from the provider's list cannot be deleted; switch it off instead"
                )
            used = await _references(session, provider, model=row.model_id)
            if provider.default_model == row.model_id:
                used.insert(0, "it is the default model of the provider")
            if used:
                raise ArtifactError(409, "The model is in use: " + "; ".join(used[:5]))
            await session.delete(row)
            await session.commit()
        self._changed()

    async def delete(self, ref: str) -> None:
        """Delete a provider with its models; 409 while a draft, a published version (the current and
        every earlier one) or a node's override names it."""
        async with self._session() as session:
            provider = await self._find(session, ref)
            used = await _references(session, provider)
            if used:
                more = f" and {len(used) - 5} more" if len(used) > 5 else ""
                raise ArtifactError(409, "The provider is in use: " + "; ".join(used[:5]) + more)
            await session.delete(provider)
            await session.commit()
        self._changed()


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _references(
    session: AsyncSession, provider: LlmProvider, model: str | None = None
) -> list[str]:
    """Where the provider (or, with ``model``, that model of it) is named: drafts, published versions
    and the overrides of agent nodes. A configuration without a provider means the default provider."""

    def names(config: dict[str, Any]) -> bool:
        wanted = config.get("provider_id")
        mine = wanted == provider.id or (not wanted and provider.is_default)
        return mine and (model is None or config.get("model") == model)

    found: list[str] = []
    agents = {a.id: a for a in await session.scalars(select(Agent))}
    for agent in agents.values():
        if names(_loads(agent.draft)):
            found.append(f'the draft of agent "{agent.name}"')
    versions = await session.scalars(
        select(AgentVersion).order_by(AgentVersion.agent_id, AgentVersion.number)
    )
    for version in versions:
        if names(_loads(version.config)):
            found.append(f'version {version.number} of agent "{agents[version.agent_id].name}"')
    nodes = await session.scalars(select(GraphNode).where(GraphNode.kind == NodeKind.AGENT.value))
    for node in nodes:
        config = node.config or {}
        if model is None:
            if config.get("provider_id") == provider.id:
                found.append(f'agent node "{node.name}"')
        elif config.get("model") == model and config.get("provider_id") in (None, provider.id):
            found.append(f'agent node "{node.name}"')
    return found
