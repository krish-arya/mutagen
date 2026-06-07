# Contributing to Mutagen

Thanks for your interest in improving Mutagen! This guide covers how to propose
changes. By contributing you agree your work is licensed under the project's
[MIT License](LICENSE).

## Ground rules

- The **`main` branch is protected.** Nobody pushes to it directly — every
  change, including a maintainer's, goes through a pull request.
- A PR can merge only when **CI is green** (tests on Python 3.11 & 3.12, ruff
  lint + format, build) **and it has at least one approving review.**
- Be respectful and constructive in issues and reviews.

## Workflow

1. **Open an issue first** for anything non-trivial (a new feature, a behavior
   change, a refactor). Small fixes and typos can go straight to a PR.

2. **Fork** the repository and clone your fork:
   ```bash
   git clone https://github.com/<your-username>/mutagen.git
   cd mutagen
   ```

3. **Create a topic branch** off `main`:
   ```bash
   git checkout -b fix/short-description
   ```
   Use a short, descriptive name (`fix/...`, `feat/...`, `docs/...`).

4. **Install the dev dependencies:**
   ```bash
   pip install -e ".[dev,sandbox]"
   ```

5. **Make your change.** Keep it focused — one logical change per PR. Match the
   surrounding code style and the project's Clean Architecture dependency rule
   (dependencies point inward; only `config/container.py` wires concrete
   adapters).

6. **Run the full check suite locally** — these are exactly what CI runs, so
   running them first saves a round-trip:
   ```bash
   pytest                 # full test suite (no network, no real LLM)
   ruff check mutagen     # lint
   ruff format mutagen    # format (use --check to verify only)
   mypy mutagen           # type-check (strict; aspirational, non-blocking)
   ```
   Add or update tests for any behavior you change.

7. **Commit** with a clear message (imperative mood, e.g. `fix: handle empty
   target list`), then **push to your fork:**
   ```bash
   git push origin fix/short-description
   ```

8. **Open a pull request** against `main`. In the description:
   - explain *what* changed and *why*,
   - link the related issue (`Closes #123`),
   - note anything reviewers should look at closely.

9. **Address review feedback** by pushing additional commits to the same
   branch. Once approved and CI is green, a maintainer merges it.

## Reporting bugs

Open an issue with:
- what you did (command, config, repo characteristics),
- what you expected,
- what actually happened (include the error output / `mutagen doctor` output).

## Questions

Not sure about something? Open an issue and ask — that's always fine.
