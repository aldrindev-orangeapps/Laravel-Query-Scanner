"""Build compact, reviewable AI context for one Laravel method."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from analyzer import Finding, LaravelQueryScanner, extract_methods


def _snake_plural(name: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    if snake.endswith("y") and not snake.endswith(("ay", "ey", "iy", "oy", "uy")):
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"


def _model_files(project_root: Path) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for path in (project_root / "app").rglob("*.php"):
        result.setdefault(path.stem, path)
    return result


def _relevant_model_summaries(project_root: Path, method_source: str) -> Tuple[List[str], List[str]]:
    model_map = _model_files(project_root)
    referenced = sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\s*::", method_source)))
    summaries: List[str] = []
    tables: List[str] = []
    relation_pattern = re.compile(
        r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)[^{]*\{(?P<body>.*?)\}", re.DOTALL
    )
    for class_name in referenced:
        path = model_map.get(class_name)
        if not path:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        table_match = re.search(r"\$table\s*=\s*['\"]([^'\"]+)['\"]", source)
        table = table_match.group(1) if table_match else _snake_plural(class_name)
        tables.append(table)
        relations = []
        for match in relation_pattern.finditer(source):
            body = match.group("body")
            builder = re.search(
                r"\$this\s*->\s*(hasOne|hasMany|belongsTo|belongsToMany|morph\w+|has\w+Through)\s*\(([^;]+)",
                body,
            )
            if builder:
                relations.append("%s(): %s(%s" % (match.group(1), builder.group(1), builder.group(2).strip()))
        relative = path.relative_to(project_root).as_posix()
        text = "- `%s` → table `%s` (%s)" % (class_name, table, relative)
        if relations:
            text += "\n  - " + "\n  - ".join(relations[:12])
        summaries.append(text)
    return summaries, tables


def _schema_summary(project_root: Path, tables: Iterable[str]) -> List[str]:
    wanted = set(tables)
    if not wanted:
        return []
    summaries: List[str] = []
    migrations = project_root / "database" / "migrations"
    if not migrations.is_dir():
        return summaries
    create_pattern = re.compile(r"Schema\s*::\s*(?:create|table)\s*\(\s*['\"]([^'\"]+)['\"]")
    column_pattern = re.compile(
        r"\$table\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([^;]*)\)(?:\s*->\s*(index|unique|primary)\s*\([^;]*\))?"
    )
    for path in sorted(migrations.glob("*.php")):
        source = path.read_text(encoding="utf-8", errors="replace")
        mentioned = {name for name in create_pattern.findall(source) if name in wanted}
        if not mentioned:
            continue
        entries = []
        for match in column_pattern.finditer(source):
            entry = "%s(%s)" % (match.group(1), re.sub(r"\s+", " ", match.group(2).strip())[:100])
            if match.group(3):
                entry += " ->%s" % match.group(3)
            entries.append(entry)
        summaries.append(
            "- `%s` from `%s`: %s" % (", ".join(sorted(mentioned)), path.name, "; ".join(entries[:30]) or "no columns parsed")
        )
    return summaries


def build_context(
    project_root: Path,
    relative_file: str,
    method_name: str,
    findings: Optional[Sequence[Finding]] = None,
) -> str:
    path = (project_root / relative_file).resolve()
    source = path.read_text(encoding="utf-8", errors="replace")
    method = next((item for item in extract_methods(source) if item.name == method_name), None)
    if method is None:
        raise ValueError("Method '%s' was not found in %s." % (method_name, relative_file))

    model_summaries, tables = _relevant_model_summaries(project_root, method.source)
    schema = _schema_summary(project_root, tables)
    branch_lines = [line.strip() for line in method.source.splitlines() if "Branch::get(" in line]
    relevant_findings = [item for item in (findings or []) if item.file == relative_file and item.method == method_name]

    parts = [
        "# Laravel query optimization context",
        "",
        "## Constraints",
        "",
        "- Project uses Laravel 7 and PHP 7.2.5/8.0 compatibility.",
        "- Do not use APIs introduced after Laravel 7.",
        "- Preserve existing Branch::get() and multi-database behavior.",
        "- Optimize only this method and explain any behavioral or index changes.",
        "- Return a focused diff; do not rewrite unrelated code.",
        "",
        "## Target",
        "",
        "- File: `%s`" % relative_file,
        "- Method: `%s` (lines %d-%d)" % (method_name, method.start_line, method.end_line),
        "",
        "```php",
        method.source.rstrip(),
        "```",
    ]
    if relevant_findings:
        parts.extend(["", "## Local scanner findings", ""])
        for item in relevant_findings:
            parts.append("- **%s %s, line %d:** %s — %s" % (
                item.rule_id, item.severity, item.line, item.title, item.message
            ))
    if model_summaries:
        parts.extend(["", "## Relevant models and relationships", "", *model_summaries])
    if schema:
        parts.extend(["", "## Relevant schema/index summary", "", *schema])
    if branch_lines:
        parts.extend(["", "## Branch/multi-database calls", ""])
        parts.extend("- `%s`" % line for line in branch_lines)
    parts.extend([
        "",
        "## Requested response",
        "",
        "1. Explain the root query problem and expected impact.",
        "2. Provide Laravel 7-compatible optimized code for this method only.",
        "3. List required eager loads, selected columns, or indexes separately.",
        "4. Call out assumptions that must be verified before applying the diff.",
        "",
    ])
    return "\n".join(parts)

