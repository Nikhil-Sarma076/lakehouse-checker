# Contributing to lakecheck

Thank you for your interest in contributing! To keep this tool lightweight and focused, we adhere strictly to the following design philosophy.

## The "Ponytail" Convention (Lazy & Efficient Engineering)
This codebase operates on "lazy senior dev mode." Lazy means efficient, not careless. The best code is the code never written. Before adding a feature, ask:
1.  **Is it O(1) or O(Δ)?** If a check requires a full-table scan, it does not belong in this tool. `lakecheck`'s primary value proposition is bounding compute to the transaction log or the newly inserted files.
2.  **Can we use the standard library?** Do not introduce third-party dependencies (like `click`, `typer`, or Spark) if `argparse`, `urllib`, or `boto3` (which is already required for EKS) can solve the problem.
3.  **Is it a symptom or a root cause?** If you are fixing a bug, trace it to the root. Do not scatter `if` statements at the call sites; fix the shared abstraction.

## Development Setup
1. Clone the repository.
2. Install with dev dependencies: `pip install -e .[dev]`
3. Run tests: `pytest`
4. Run linters: `ruff check .` and `ruff format .`

## Pull Request Process
*   Ensure all tests pass (local Delta fixtures run in < 5 seconds).
*   Ensure Ruff passes (we strictly enforce security rules via `flake8-bandit`).
*   If you add a new check, document whether it is O(1) (metadata only) or O(Δ) (scans new Parquet files).
