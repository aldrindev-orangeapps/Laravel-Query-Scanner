"""Optional command-line interface for automation and editor tasks."""

from __future__ import annotations

import argparse
from pathlib import Path

from analyzer import LaravelQueryScanner, findings_to_json
from context_builder import build_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Static Laravel query scanner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a Laravel project or PHP file")
    scan_parser.add_argument("project", type=Path)
    scan_parser.add_argument("--file", type=Path)
    scan_parser.add_argument("--method")
    scan_parser.add_argument("--no-cache", action="store_true")
    scan_parser.add_argument("--json", action="store_true")

    context_parser = subparsers.add_parser("context", help="Print compact AI context for one method")
    context_parser.add_argument("project", type=Path)
    context_parser.add_argument("file")
    context_parser.add_argument("method")

    args = parser.parse_args()
    project = args.project.resolve()
    if not LaravelQueryScanner.is_laravel_project(project):
        parser.error("project must contain artisan, composer.json, and app/")

    if args.command == "context":
        print(build_context(project, args.file.replace("\\", "/"), args.method))
        return 0

    selected_file = args.file.resolve() if args.file else None
    scanner = LaravelQueryScanner(project, use_cache=not args.no_cache)
    summary = scanner.scan(selected_file=selected_file, selected_method=args.method)
    if args.json:
        print(findings_to_json(summary))
    else:
        for finding in summary.findings:
            print("[{0}] {1} {2}:{3} {4}() - {5}".format(
                finding.severity.upper(), finding.rule_id, finding.file,
                finding.line, finding.method, finding.title,
            ))
        print("\n{0} finding(s), {1} file(s), {2} cached".format(
            len(summary.findings), summary.files_scanned, summary.files_cached
        ))
    return 1 if any(item.severity == "high" for item in summary.findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

