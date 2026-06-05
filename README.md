# Mutagen

Production-grade mutation testing for Python, built on Clean Architecture.

> **Status:** project skeleton. Interfaces, domain models, configuration, the
> dependency container, logging scaffolding, and the run state machine are in
> place. Business logic is intentionally not yet implemented (methods raise
> `NotImplementedError`).

## Architecture

Mutagen follows a strict dependency rule: dependencies point *inward*, toward
the domain. Outer layers know about inner layers; never the reverse.

```
cli ─┐
     ├─► services ─► core (models, interfaces, exceptions, state_machine)
infra┘        ▲              ▲
              └── depend only on core.interfaces (ports)
config / container ── compose infra adapters into services
```

| Layer | Package | Responsibility |
|-------|---------|----------------|
| Domain | `mutagen.core` | Models, ports, exceptions, run state machine. No I/O. |
| Application | `mutagen.services` | Use-case orchestration over ports. |
| Infrastructure | `mutagen.infrastructure` | Concrete adapters (LLM, coverage, mutation, sandbox, storage, repository). |
| Reporting | `mutagen.reporting` | `Reporter` implementations (JSON, terminal). |
| Interface | `mutagen.cli` | Command-line surface. |
| Composition | `mutagen.config` | `RunConfig`, logging setup, DI `Container`. |

### Key design choices

- **Interface-first.** Every infrastructure concern is defined as an abstract
  port in `mutagen.core.interfaces` before any adapter exists.
- **Dependency injection.** `mutagen.config.container.Container` is the single
  composition root; nothing else constructs adapters.
- **Fully typed.** `from __future__ import annotations`, `slots=True`
  dataclasses, and `mypy --strict`.
- **Immutable domain.** Domain models are frozen dataclasses.
- **Explicit lifecycle.** `RunStateMachine` makes illegal run transitions
  raise rather than silently proceed.

## Layout

```
mutagen/
├── cli/            # argument parsing + dispatch
├── config/         # RunConfig, logging, DI container, loader
├── core/
│   ├── models/         # frozen domain dataclasses
│   ├── interfaces/     # abstract ports (ABCs)
│   ├── exceptions/     # MutagenError hierarchy
│   └── state_machine/  # RunState enum + guarded transitions
├── services/       # application orchestration
├── infrastructure/
│   ├── llm/ coverage/ mutation/ sandbox/ storage/ repository/
├── reporting/      # JSON + terminal reporters
├── tests/          # pytest suite (+ conftest fixtures)
└── main.py         # entrypoint
```

## Development

```bash
pip install -e ".[dev]"
pytest
mypy mutagen
ruff check mutagen
```

## Usage (planned)

```bash
mutagen --config mutagen.toml run --threshold 0.8
```
