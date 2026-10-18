# AGENTS.md

## Project overview

Laravel Query Scanner is a dependency-light Windows desktop application for
static inspection of Laravel query patterns. It is implemented in Python and
Tkinter and must never require a Laravel project to boot or a database to be
available during analysis.

These instructions apply to the entire repository.

## Repository map

- `laravel_query_scanner.py`: thin desktop entry point.
- `app_ui.py`: Tkinter UI and background scan workflow.
- `analyzer.py`: PHP method extraction, static rules, and content-hash cache.
- `context_builder.py`: compact method/model/schema context generation.
- `project_store.py`: recent-project persistence.
- `scanner_cli.py`: optional automation interface.
- `tests/`: standard-library `unittest` suite.
- `Laravel Query Scanner.spec`: canonical PyInstaller build.

## Development commands

```powershell
python -m unittest discover -s tests -v
python .\laravel_query_scanner.py
python .\scanner_cli.py scan C:\path\to\laravel
python -m PyInstaller --noconfirm ".\Laravel Query Scanner.spec"
```

## Change guidelines

- Keep runtime dependencies limited to the Python standard library unless a
  dependency is explicitly approved.
- Preserve read-only treatment of selected Laravel projects.
- Never read `.env`, database credentials, application secrets, or live data.
- Never upload source or make an automatic AI request.
- Keep long scans off the Tkinter event thread and schedule UI changes with
  `root.after()`.
- Preserve source offsets and line numbers when changing PHP masking/parsing.
- Findings must say "possible" when static analysis cannot prove the problem.
- Cache keys must change when source, relationships, selected method, or scanner
  rule version changes.
- Keep AI context method-scoped and compact. Do not include entire controllers.
- Add focused tests for every rule or parser behavior change.
- Do not edit generated `build/`, `dist/`, or `__pycache__/` content.

## Compatibility target

- Python 3.9+ on Windows.
- Laravel 7 query syntax is the primary compatibility baseline.
- Do not recommend Laravel APIs introduced after Laravel 7 in generated context.
- Recognize `Branch::get()` as project-specific multi-database context and do not
  suggest replacing it automatically.

