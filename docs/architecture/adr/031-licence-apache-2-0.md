# ADR-031: Licence Apache-2.0

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** —  
**Amended by:** —  
**Implemented in:** `LICENSE`, `license = "Apache-2.0"` in `apps/backend/pyproject.toml`; no migration  
**Affected chapters:** [02](../arc42/02-architecture-constraints.md)

## 1. Title

Under which licence the source code is published.

## 2. Context

The licence was stated in `LICENSE`, `pyproject.toml` and arc42 chapter 2 without a recorded reason.

## 3. Decision

OpenArtifact is licensed under the Apache License 2.0: it allows use, change and redistribution, and it contains
an express patent grant.

## 4. Consequences

- Dependencies must have licences compatible with Apache-2.0; no CI check enforces this.
- A contribution is accepted under the same licence.
