"""The agent harness: reusable agent definitions, LLM providers and the runtime that calls a model.

``schemas`` holds the configuration of an agent and the bounds of its settings (the single place for
them), ``resolve`` turns a published agent plus a node's overrides into the configuration a run uses,
``render`` fills the prompts from the declared inputs, ``client`` talks to an OpenAI-compatible
endpoint through the guarded HTTP path, ``runtime`` makes the one request with its retries, and
``service`` / ``providers`` are what the APIs call. See ADR-037.
"""
