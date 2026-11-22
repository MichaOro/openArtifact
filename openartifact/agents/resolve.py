"""From a published agent and a node's overrides to the configuration a run uses (pure functions).

One rule, used by the snapshot of an execution, the preview and the editor's display:

- A node's setting that is not set (``None``) is inherited from the agent; one that is set overrides
  that field only (:func:`overrides_of`).
- The provider is the node's, else the agent's, else the default provider.
- The model is the node's; else the agent's if the provider in effect is the one the agent's model was
  chosen for; else the provider's default model. It must be enabled for the provider.

There is no fallback beyond that: what cannot be resolved is a problem the node fails with.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from openartifact.agents.schemas import OVERRIDABLE, SettingState


@dataclass(frozen=True)
class ProviderInfo:
    """A provider as far as resolving needs it; ``models`` are the ids that may be used."""

    id: str
    kind: str
    name: str
    base_url: str
    secret_name: str | None
    allow_private: bool
    default_model: str | None
    is_default: bool
    models: frozenset[str]

    def frozen(self) -> dict[str, Any]:
        """What a snapshot keeps of the provider (never a key, only the name of its secret)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "base_url": self.base_url,
            "secret_name": self.secret_name,
            "allow_private": self.allow_private,
        }


def overrides_of(node_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The fields a node sets for itself."""
    config = node_config or {}
    return {key: config[key] for key in OVERRIDABLE if config.get(key) is not None}


def merged(
    agent_config: Mapping[str, Any], node_config: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The agent's overridable fields with the node's overrides on top."""
    return {
        **{key: agent_config.get(key) for key in OVERRIDABLE},
        **overrides_of(node_config),
    }


def setting_states(
    agent_config: Mapping[str, Any], node_config: Mapping[str, Any] | None
) -> list[SettingState]:
    own = overrides_of(node_config)
    return [
        SettingState(
            key=key,
            value=own.get(key, agent_config.get(key)),
            inherited=agent_config.get(key),
            overridden=key in own,
        )
        for key in OVERRIDABLE
    ]


def _default(providers: Mapping[str, ProviderInfo]) -> ProviderInfo | None:
    return next((p for p in providers.values() if p.is_default), None)


def pick_provider(
    agent_config: Mapping[str, Any],
    node_config: Mapping[str, Any] | None,
    providers: Mapping[str, ProviderInfo],
) -> tuple[ProviderInfo | None, str | None, list[str]]:
    """The provider and model in effect and what is wrong with them (see the module docstring)."""
    own = overrides_of(node_config)
    wanted = own.get("provider_id") or agent_config.get("provider_id")
    default = _default(providers)
    provider = providers.get(wanted) if wanted else default
    if provider is None:
        return (
            None,
            None,
            [
                "The provider of the agent no longer exists"
                if wanted
                else "No provider is set and there is no default provider"
            ],
        )
    model = own.get("model")
    if not model:
        chosen_for = agent_config.get("provider_id") or (default.id if default else None)
        if chosen_for == provider.id:
            model = agent_config.get("model")
        model = model or provider.default_model
    if not model:
        return (
            provider,
            None,
            [f'No model is set and provider "{provider.name}" has no default model'],
        )
    if model not in provider.models:
        return (
            provider,
            model,
            [f'Model "{model}" is not enabled for provider "{provider.name}"'],
        )
    return provider, model, []


def freeze(
    agent: Mapping[str, Any] | None,
    node_config: Mapping[str, Any] | None,
    providers: Mapping[str, ProviderInfo],
) -> dict[str, Any]:
    """What the snapshot of an execution keeps for one agent node.

    ``agent`` is ``{"id", "name", "active", "version", "config"}`` of the published version, or
    ``None`` when the node's agent does not exist. ``error`` says why the node cannot run (``None``: it
    can); the start of the execution is never refused because of it.
    """
    wanted = (node_config or {}).get("agent_id")
    if agent is None:
        reason = "No agent is chosen" if not wanted else "The agent of this node no longer exists"
        return {"agent_id": wanted or None, "error": reason}
    frozen: dict[str, Any] = {
        "agent_id": agent["id"],
        "name": agent["name"],
        "active": bool(agent["active"]),
        "version": agent.get("version"),
        "error": None,
    }
    if agent.get("config") is None:
        frozen["error"] = f'Agent "{agent["name"]}" has no published version'
        return frozen
    config = agent["config"]
    own = overrides_of(node_config)
    settings = merged(config, node_config)
    provider, model, problems = pick_provider(config, node_config, providers)
    settings["provider_id"] = provider.id if provider else settings.get("provider_id")
    settings["model"] = model
    frozen.update(
        config=config,
        overrides=own,
        settings=settings,
        inputs=config.get("inputs") or [],
        provider=provider.frozen() if provider else None,
        model=model,
    )
    if not frozen["active"]:
        frozen["error"] = f'Agent "{agent["name"]}" is inactive'
    elif problems:
        frozen["error"] = problems[0]
    return frozen
