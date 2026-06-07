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

### Context enrichment (optional)

Generation step 1 can fold in two extra signals — both **off by default**, both
configured under `[generation]`:

- **Semantic code understanding (call graph).** An AST-based
  `CallGraphAnalyzer` builds a repo-wide call graph and extracts each target's
  *execution path* — its transitive callees — so the model writes tests that
  exercise the whole tree end-to-end rather than just the entry function:

  ```text
  process_order
   ├── validate_order
   ├── calculate_tax
   └── save_order
  ```

  The rendered tree **and** the callee sources are added to the prompt. The
  analyzer resolves only unambiguous in-repo calls (plain, `self`/`cls` methods,
  imported names) and omits anything it can't pin down — no misleading edges.

- **Retrieval-augmented generation (RAG).** Instead of seeding the prompt with
  the first couple of test files, an `EmbeddingTestRetriever` indexes the
  project's existing tests (one chunk per `test_*` function) and retrieves the
  ones most *similar* to the target by embedding similarity:

  ```text
  target function ─► vector search ─► relevant existing tests ─► prompt
  ```

  The default `HashingEmbeddingProvider` is dependency-free and deterministic
  (no model download, no API key); a real embedding model can drop in behind the
  same port. Retrieved examples make generated tests far more consistent with
  the conventions of genuinely related code.

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
| `CallGraphAnalyzer` | `selection/AstCallGraphAnalyzer` | Build a repo call graph → a target's execution path |
| `TestGenerator` | `generation/LLMTestGenerator` | Gather context → prompt → validate generated tests |
| `EmbeddingProvider` | `retrieval/HashingEmbeddingProvider` | Embed text into vectors (dependency-free default) |
| `TestRetriever` | `retrieval/EmbeddingTestRetriever` | Index existing tests → retrieve the most similar ones |
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
# Install with every integration (Anthropic + OpenAI SDKs, coverage, mutmut, …)
pip install "mutagen[all]"        # or: pipx install "mutagen[all]"
```

Then provide an API key for whichever provider you use — via your shell or a
`.env` file in your project (loaded automatically):

```bash
export ANTHROPIC_API_KEY=sk-ant-...    # Anthropic   (Windows: $env:ANTHROPIC_API_KEY=...)
export OPENAI_API_KEY=sk-...           # OpenAI
export GEMINI_API_KEY=...              # Google Gemini
export OPENROUTER_API_KEY=sk-or-...    # OpenRouter
```

```ini
# .env (kept out of source control; never committed)
OPENAI_API_KEY=sk-...
```

Verify everything at once:

```bash
mutagen doctor    # checks Python, git, optional deps, and which provider key is set
```

Lighter installs are available via extras: `pip install mutagen` (CLI +
reporting only), then add `[llm]` (Anthropic), `[openai]` (OpenAI / Gemini /
OpenRouter), `[sandbox]`, `[mutation]`, or `[coverage]` as needed. `mutagen
doctor` tells you exactly which extra to install for anything missing.

---

## Usage

```bash
# Run against a local path or a git URL
mutagen run ./path/to/project
mutagen run https://github.com/org/repo

# Pick a provider and model straight from the CLI — no config file needed.
# Per-provider API-key env var and base URL are filled in automatically;
# just set the matching key (e.g. OPENAI_API_KEY).
mutagen run ./project --provider openai --model gpt-4o

# With a config file and a score threshold
mutagen -c mutagen.toml run ./project --threshold 0.8

# Resume an interrupted run (reuse its id)
mutagen run ./project --run-id my-run-123

# Re-render the most recent run's report
mutagen report

# Diagnose the environment (Python, git, optional deps, provider key)
mutagen doctor
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
CLI flags (`--threshold`, `--provider`, `--model`) override file values, so you
can switch provider without touching — or even having — a config file. Highlights:

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
max_parallel_targets = 4   # process this many targets at once (1 = sequential)

[storage]
backend = "sqlite"
root = ".mutagen"
```

Hitting any budget/cost limit stops the run **cleanly** with a `PARTIAL`,
resumable result — the in-flight target finishes and everything completed is
already persisted.

### Parallelism

Targets are independent — each runs in its own isolated sandbox and mutation
workspace — so the orchestrator processes up to `max_parallel_targets` of them
at once via a bounded worker pool (default `1`, i.e. sequential). Budget and
cost limits are enforced with an **atomic reservation** before each target is
scheduled, so concurrency never overshoots `max_targets`; once a limit trips,
no new targets start but those already in flight finish cleanly. Per-target
checkpoints are still written immediately, so resume works identically whether
the run was sequential or parallel.

Because the dominant cost is CPU-bound (`pytest` + `mutmut`), the practical
sweet spot for `max_parallel_targets` is roughly the host's core count — higher
values mostly cause subprocess thrashing rather than further speedup.

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

## Contributing

Contributions are welcome — bug fixes, features, docs, tests. The `main` branch
is protected: **all changes land through a reviewed pull request**, and direct
pushes are not accepted.

1. **Fork** the repo and clone your fork.
2. **Create a branch** off `main`:
   ```bash
   git checkout -b fix/short-description
   ```
3. **Set up the dev environment** and make your change:
   ```bash
   pip install -e ".[dev,sandbox]"
   ```
4. **Run the checks locally** — your PR can't merge until CI is green:
   ```bash
   pytest                 # full test suite
   ruff check mutagen     # lint
   ruff format mutagen    # format
   mypy mutagen           # type-check (strict; aspirational)
   ```
5. **Commit, push to your fork, and open a pull request** against `main`.
   Describe what changed and why; link any related issue.
6. A maintainer reviews it. **At least one approval and passing CI are required
   before merge** — please be patient and address review feedback by pushing
   more commits to the same branch.

Not sure where to start, or want to propose something larger first? **Open an
issue** to discuss before investing in a big change.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guidelines.

---

## License

MIT.
