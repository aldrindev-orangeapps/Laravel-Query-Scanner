# Laravel Query Scanner

A reusable Windows desktop application that scans Laravel projects for common
query-performance risks. Analysis is local and static: it does not boot Laravel,
connect to a database, or send source code to an AI service.

The first release is tuned for Laravel 7-style Eloquent and Query Builder code,
while remaining useful for other Laravel versions.

## Features

- Select any Laravel project folder and scan every PHP file under `app/`.
- Scan one PHP file or one named method for a focused review.
- Detect queries inside loops, possible relationship N+1 access, explicit
  `SELECT *`, unbounded `Model::all()`, and repeated query shapes.
- Show file, line, method, severity, confidence, reason, and a suggested direction.
- Filter findings and jump directly to the relevant VS Code line.
- Export a complete machine-readable JSON report.
- Build compact AI context for only the selected method, related models,
  relationships, migrations, indexes, and `Branch::get()` calls.
- Cache results by source-content hash and relationship definitions.
- Run scans in the background and cancel safely between files.

## Safety and privacy

- No AI API is included or called.
- No project source is uploaded.
- No database credentials are read.
- The selected Laravel project is read-only to this tool.
- Recent projects and cached findings are stored under
  `%LOCALAPPDATA%\LaravelQueryScanner`.

The **Copy AI context** and **Save AI context** buttons only prepare Markdown.
You decide whether to paste that content into an AI tool.

## Run from source

Requirements: Windows and Python 3.9 or newer. The runtime uses only the Python
standard library.

```powershell
python .\laravel_query_scanner.py
```

Workflow:

1. Select a folder containing `artisan`, `composer.json`, and `app/`.
2. Choose **Full project** or **Selected PHP file**.
3. Optionally enter an exact method name for the selected file.
4. Start the scan and select any finding to see its explanation.
5. Use **Open in VS Code**, **Export JSON**, or one of the AI-context actions.

## Command-line usage

The optional CLI uses the same analyzer as the desktop app.

```powershell
# Full project
python .\scanner_cli.py scan C:\xampp\htdocs\clinic

# One file and method
python .\scanner_cli.py scan C:\xampp\htdocs\clinic `
  --file C:\xampp\htdocs\clinic\app\Http\Controllers\ConsultationController.php `
  --method syncRFIDEntries

# JSON output
python .\scanner_cli.py scan C:\xampp\htdocs\clinic --json

# AI-ready context printed to the terminal
python .\scanner_cli.py context C:\xampp\htdocs\clinic `
  app/Http/Controllers/ConsultationController.php syncRFIDEntries
```

The scan command exits with code `1` when a high-severity finding exists, making
it usable as an optional CI quality check. It exits with `0` otherwise.

## Rules

| Rule | Default severity | Meaning |
| --- | --- | --- |
| `LQS001` | High | A database query appears inside a loop. |
| `LQS002` | High | A known Eloquent relationship may be lazy-loaded inside a loop. |
| `LQS003` | Medium | The query explicitly selects every column. |
| `LQS004` | Low | `Model::all()` loads all rows and columns. |
| `LQS005` | Medium | A normalized query shape repeats inside one method. |

This is a static heuristic scanner, not a query profiler. A finding identifies
code worth reviewing; it does not prove that the code is slow. Confirm important
findings with real request timing, Laravel query logs, and database `EXPLAIN`.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use temporary Laravel fixtures and do not need XAMPP or a database.

## Build the standalone EXE

Install PyInstaller only in the build environment, then run:

```powershell
python -m PyInstaller --noconfirm ".\Laravel Query Scanner.spec"
```

The portable executable is produced at:

```text
dist\Laravel Query Scanner.exe
```

PyInstaller is not a runtime dependency for users of the built EXE.

## Current limitations

- Dynamic PHP and query construction can produce false positives or missed findings.
- Relationship N+1 checks depend on recognizable Eloquent relationship methods.
- Migration schema summaries are intentionally compact and do not connect to the
  live database, so indexes created outside migrations are not visible.
- The scanner does not automatically edit project code.

