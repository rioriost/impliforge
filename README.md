# impliforge

`impliforge` is an orchestrator-centric multi-agent workflow tool built on top of the GitHub Copilot SDK.

It treats requirement analysis, planning, documentation generation, implementation proposals, test design and execution, review, fix loops, and artifact persistence as one end-to-end workflow.

## License

This project is licensed under the MIT License. See `LICENSE` for details.

## Features

- Multi-agent workflow covering requirements, planning, documentation, implementation, test design, test execution, review, and fix loops
- Session snapshot, restore, and rotation support
- Task-aware model routing
- Operator-facing run summaries, final summaries, review reports, and fix reports
- Acceptance gating and completion evidence
- Approval-aware safe edit orchestration

## Installation

This project uses `uv` for dependency management and execution.

Install the default dependencies:

```sh
uv sync
```

Install test dependencies as well:

```sh
uv sync --extra test
```

## CLI Usage

`impliforge` accepts a **requirement file path** as its positional argument, not an inline requirement string.

### Basic usage

```sh
uv run impliforge requirements/sample-requirement.md
```

Or run it as a module:

```sh
uv run python -m impliforge requirements/sample-requirement.md
```

### With options

```sh
uv run impliforge requirements/sample-requirement.md \
  --model gpt-5.4 \
  --routing-mode quality \
  --token-usage-ratio 0.35 \
  --artifacts-dir artifacts \
  --docs-dir docs
```

## Requirement File Format

Requirement files are expected to be plain text or Markdown. Multi-line requirements are supported and recommended.

Example:

```md
Build a multi-agent environment using the GitHub Copilot SDK

- Support session persistence
- Include review and fix loops
- Persist outputs under docs/ and artifacts/
```

## Error Handling

The CLI exits with an error when:

- The specified requirement file does not exist
- The requirement file is empty
- The requirement file cannot be read

Example:

```sh
uv run impliforge requirements/missing.md
# error: requirement file not found: requirements/missing.md
```

## Generated Outputs

The workflow primarily generates the following outputs.

### Documentation outputs

- `docs/design.md`
- `docs/runbook.md`
- `docs/test-plan.md`
- `docs/test-results.md`
- `docs/review-report.md`
- `docs/fix-report.md`
- `docs/final-summary.md`

### Artifact outputs

- `artifacts/workflow-state.json`
- `artifacts/sessions/<session_id>/session-snapshot.json`
- `artifacts/workflows/<workflow_id>/workflow-details.json`
- `artifacts/summaries/<workflow_id>/run-summary.json`

## Validation

Run the full test suite:

```sh
uv run pytest -q tests
```

Run tests with coverage:

```sh
uv run pytest --cov=src/impliforge --cov-report=term-missing:skip-covered -q tests
```

## Notes

- Generated outputs under `docs/` and `artifacts/` are treated as normal workflow outputs
- Source edits are expected to go through approval-aware paths
- Open questions should be treated as either resolved or explicitly deferred