# Repository Guidelines

## Project Structure & Module Organization

This repository is currently an empty project scaffold: no application source, tests, assets, dependency manifest, or build configuration are checked in. Keep the root uncluttered as the project is initialized. Place implementation code in a clearly named package or `src/` directory, tests in `tests/`, and static resources in `assets/`. Mirror source paths in the test tree—for example, `src/api/client.py` should be covered by `tests/api/test_client.py`. Document any new top-level directory in this file or the project README.

## Build, Test, and Development Commands

No build or development commands are defined yet. When adding the first toolchain, commit its lockfile and expose a small, stable command set through a `Makefile`, `pyproject.toml`, or package scripts. Contributors should then be able to discover routine tasks without relying on local shell aliases. Suggested targets are:

- `make setup` — install pinned development dependencies.
- `make test` — run the complete automated test suite.
- `make lint` — run formatting and static checks.
- `make run` — start the application locally.

Replace these examples with the actual commands once tooling is introduced.

## Coding Style & Naming Conventions

Follow the formatter and linter configured with the chosen language; do not hand-format around those tools. Use descriptive names, small modules, and consistent language conventions. Prefer `snake_case` for Python files and functions, `PascalCase` for classes, and kebab-case for documentation or asset names. Keep configuration explicit and checked in.

## Testing Guidelines

Add tests with every behavior change and regression fix. Name tests after observable behavior, not implementation details. Keep unit tests fast and deterministic; isolate network, filesystem, and model dependencies behind fixtures or mocks. Until a coverage threshold is adopted, prioritize meaningful coverage of changed paths and failure cases.

## Commit & Pull Request Guidelines

No Git history is available to establish an existing commit convention. Use short, imperative subjects such as `Add workflow validation`, with focused commits and explanatory bodies when needed. Pull requests should explain the problem and solution, list verification performed, link relevant issues, and include screenshots or sample output for user-visible changes. Never commit credentials, generated caches, large model files, or machine-specific configuration.

## Model Routing & Token Discipline

Use one agent by default; delegation must save meaningful reading or mechanical work. Route tasks by risk and ambiguity:

- **S0 — immediate:** one or two obvious checks, explanations, or tiny edits stay with the current agent; delegation overhead would cost more tokens.
- **S1 — mechanical:** use `gpt-5.6-luna` at `low` or `medium` for bounded inventories, deterministic JSON/doc rewrites, formatting, and narrow tests.
- **S2 — evidence-heavy:** use `gpt-5.6-terra` at `medium` for long files, logs, site/repository comparison, ordinary review, and concise evidence gathering.
- **S3 — high judgment:** keep `gpt-5.6-sol` on requirements, architecture, ambiguous root causes, security or destructive decisions, cross-file integration, and final acceptance.

Run no more than two subagents concurrently. Give each agent exact paths, a bounded question, an edit ownership boundary, and a compact return contract: conclusion, exact evidence, risks, and verification status. Only one agent may edit a given file at a time. Escalate one tier after one bounded attempt cannot produce verifiable evidence; escalate directly to `gpt-5.6-sol` when requirements are ambiguous, a change crosses ownership boundaries, a destructive/external action is needed, or two evidence-backed attempts fail. The primary agent reviews the final diff and validation; subagent completion alone is not project acceptance.

Read [模型路由与 Token 使用规范](docs/00-项目协作/模型路由与Token使用规范.md) for the decision table and ComfyUI-specific examples.
