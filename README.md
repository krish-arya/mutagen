# Mutagen

**LLM-assisted test generation, validated by mutation testing.**

Mutagen ingests a Python repository, finds under-covered functions, generates
pytest tests for them with an LLM, and keeps only the tests that actually
**kill mutants** of the target. It is built on Clean Architecture with a strict
dependency rule, two explicit state machines, full async I/O, SQLite-backed
resume, and structured logging.

```text
repo ──► ingest ──► select targets ──► generate tests ──► run ──► mutate ──► keep / discard ──► report
                                          ▲        │
                                          └── repair / strengthen loops ──┘
```

---

## What it does

For each selected target the pipeline:

1. **Generates** a pytest module from the function's source, imports, and
   surrounding context — matching your project's existing test style.
2. **Runs** it in an isolated subprocess sandbox (timeout + resource limits,
   flakiness detection via a double-run).
3. **Mutation-gates** it with [mutmut](https://github.com/boxed/mutmut): if the
   tests don't kill enough mutants, the surviving mutants become **feedback**
   for a regeneration attempt (the *strengthening loop*). If the tests fail to
   run, the failure output drives a *repair loop*.
4. **Keeps or discards** the tests based on the mutation-score threshold, and
   persists the outcome **immediately** so an interrupted run resumes cleanly.

---

## Architecture

Mutagen follows a strict **dependency rule**: dependencies point *inward*,
toward the domain. The domain (`core`) knows nothing about infrastructure; the
composition root (`config/container.py`) is the only place concrete adapters
are imported.

```text
┌─────────────────────────────────────────────────────────────────────┐
│  cli/            mutagen run <repo> · Rich progress UI · dashboard    │
├─────────────────────────────────────────────────────────────────────┤
│  services/       orchestrator · target_processor · budget · reporting │
│                  (depend only on core.interfaces — the ports)         │
├─────────────────────────────────────────────────────────────────────┤
│  core/           models (frozen dataclasses) · interfaces (ports)     │
│                  exceptions · state_machine (run + target FSMs)       │
├─────────────────────────────────────────────────────────────────────┤
│  infrastructure/ ingest · selection · generation · llm · sandbox      │
│  reporting/      gate · store (SQLite) · md/json/terminal reporters   │
│                  (implement the ports; only layer that does real I/O) │
└─────────────────────────────────────────────────────────────────────┘
        ▲                                                       │
        └──────────  config/container.py wires it all  ─────────┘
```

### Ports → adapters

Every infrastructure concern is an abstract port in `core/interfaces/`, with a
concrete adapter in `infrastructure/`:

| Port | Adapter | Role |
| --- | --- | --- |
| `RepoIngestor` | `ingest/FilesystemRepoIngestor` | Clone/copy repo → isolated workspace, venv, deps |
| `TargetSelector` | `selection/AstTargetSelector` | Coverage-guided, AST-based target ranking |
| `TestGenerator` | `generation/LLMTestGenerator` | Gather context → prompt → validate generated tests |
| `LLMClient` | `llm/AnthropicLLMClient` | Anthropic API (retries, backoff, cost tracking) |
| `SandboxRunner` | `sandbox/SubprocessSandboxRunner` | Run pytest isolated (timeout, rlimits, flakiness) |
| `MutationGate` | `gate/MutmutMutationGate` | Drive mutmut, score, survivor feedback, keep/discard |
| `Store` | `store/SqliteStore` | Persist final runs + artifacts |
| `CheckpointStore` | `store/SqliteCheckpointStore` | Per-target progress for resume |
| `Reporter` | `reporting/{Markdown,Json,Terminal,Composite}` | `report.md` + `report.json` + dashboard |

### Two state machines

```text
RUN lifecycle (RunStateMachine)
  PENDING → INITIALIZING → INGESTING → SELECTING_TARGETS
          → GENERATING_TESTS → GATING → REPORTING → COMPLETED
          (any active state → FAILED / CANCELLED)

TARGET lifecycle (TargetStateMachine), one per target
  SELECTED → GENERATED → RAN → MUTATED → KEPT
          (any active state → DISCARDED)
```

Both are data-driven tables that **reject illegal transitions** rather than
silently proceeding.

### Orchestration loop

```text
for each selected target (skipping ones already done on a prior run):
    if budget/cost exhausted: stop cleanly → PARTIAL result (resumable)
    ┌─ TargetProcessor ───────────────────────────────────────────┐
    │  generate ──► run ──► (repair loop on failure)               │
    │           └─► gate ──► (strengthen loop on surviving mutants)│
    │           └─► KEPT (score ≥ threshold) or DISCARDED          │
    └─────────────────────────────────────────────────────────────┘
    persist the target's checkpoint IMMEDIATELY  (resume-safe)
finalize RunResult → summarize → write report.md + report.json → save run
```

---

## Project layout

```text
mutagen/
├── cli/              # argparse CLI + Rich progress UI
├── config/           # RunConfig, TOML loader, logging, DI container
├── core/
│   ├── models/           # frozen domain dataclasses (RunResult, TargetOutcome, …)
│   ├── interfaces/       # abstract ports (ABCs)
│   ├── exceptions/       # MutagenError hierarchy
│   └── state_machine/    # run + target FSMs
├── services/         # orchestrator, target_processor, budget, reporting, progress
├── infrastructure/
│   ├── ingest/ selection/ generation/ llm/ sandbox/ gate/ store/
│   └── process.py        # shared subprocess-safety helper
├── reporting/        # markdown / json / terminal / composite reporters
├── tests/            # 238 tests (unit + integration, mock-driven)
└── main.py           # entrypoint
```

---

## Setup

Requires **Python 3.11+** and **git** (for ingesting remote repositories).

```bash
# Clone and install with every integration (Anthropic SDK, coverage, mutmut, …)
git clone <this-repo> && cd mutagen
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[all]"

# Provide your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...                 # Windows: $env:ANTHROPIC_API_KEY=...
```

Lighter installs are available via extras: `pip install -e .` (CLI + reporting
only), then add `[llm]`, `[sandbox]`, `[mutation]`, or `[coverage]` as needed.

---

## Usage

```bash
# Run against a local path or a git URL
mutagen run ./path/to/project
mutagen run https://github.com/org/repo

# With a config file and a score threshold
mutagen -c mutagen.toml run ./project --threshold 0.8

# Resume an interrupted run (reuse its id)
mutagen run ./project --run-id my-run-123

# Re-render the most recent run's report
mutagen report
```

`mutagen run` exits **0** on success, **1** on a handled failure, and **2**
when the achieved mutation score is below the configured threshold (useful as a
CI gate).

### Live progress & dashboard

On a TTY the CLI shows a Rich progress bar and a per-phase status line, then a
summary table. In CI / piped output it falls back to plain line logging
automatically. Use `--no-progress` to force plain output.

```text
                 Mutagen Run a1b2c3 [succeeded]
┌──────────────────────────────────┬──────────────┐
│ Mutation score (before -> after) │  n/a -> 84%  │
│ Targets kept / discarded         │       12 / 3 │
│ Tests generated                  │           15 │
│ API cost                         │      $0.4210 │
│ Execution time                   │       182.4s │
└──────────────────────────────────┴──────────────┘
```

---

## Reports

Every run writes two files under `<storage.root>/reports/` (default
`.mutagen/reports/`):

- **`report.md`** — human-readable dashboard: mutation score before/after,
  kept vs. discarded targets, API cost, execution time, and a per-target table.
- **`report.json`** — the same data, machine-readable for CI and archival.

Both include: mutation score **before/after**, **kept** / **discarded** tests,
**API cost** (USD + tokens + requests), **execution time**, and per-target
statistics.

> **Note on "before":** the *after* score is always measured. The *before*
> (baseline) score — what the repo's pre-existing tests already kill — is wired
> through the model and rendered as `n/a` until a baseline gate pass is enabled;
> it is best-effort by design.

---

## Configuration

Configuration is TOML, mirroring the config dataclass tree. See
[`mutagen.example.toml`](mutagen.example.toml) for the fully-annotated template.
CLI flags (`--threshold`) override file values. Highlights:

```toml
project_root = "."
score_threshold = 0.8

[llm]
model = "claude-opus-4-8"
effort = "high"

[orchestrator]       # budget & cost ceilings (0 = unlimited)
max_targets = 50
max_cost_usd = 5.0
max_repair_attempts = 2
max_strengthen_attempts = 2

[storage]
backend = "sqlite"
root = ".mutagen"
```

Hitting any budget/cost limit stops the run **cleanly** with a `PARTIAL`,
resumable result — the in-flight target finishes and everything completed is
already persisted.

---

## Persistence & resume

State lives in a single SQLite database at `<storage.root>/mutagen.db`:

- `runs` — final `RunResult` records (JSON payload).
- `run_checkpoints` / `target_checkpoints` — per-target progress, **upserted
  the moment each target finishes**.

Re-running with the same `--run-id` loads the checkpoint, **skips targets
already in a terminal state**, and carries their outcomes forward.

---

## Docker

```bash
docker build -t mutagen .
docker run --rm \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$PWD:/workspace" \
  mutagen run /workspace
```

The image is a slim multi-stage build with `git` for cloning targets, runs as a
non-root user, and uses `/workspace` as the working directory.

---

## Development

```bash
pip install -e ".[dev,sandbox]"

pytest                 # 238 tests, mock-driven (no network, no real LLM)
ruff check mutagen     # lint
ruff format mutagen    # format
mypy mutagen           # type-check (strict; aspirational)
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the suite on
Python 3.11 & 3.12, lints/formats with ruff, type-checks with mypy, and builds
the Docker image on every push and PR.

### Testing philosophy

The whole suite runs **without a network or a real LLM**: ports are mocked,
subprocess calls are faked, and the few genuine integration tests (the sandbox
runner) drive real pytest against tiny fixtures and skip cleanly when their
optional tools are absent.

---

## License

MIT.
