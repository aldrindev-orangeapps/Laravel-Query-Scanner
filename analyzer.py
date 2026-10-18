"""Static Laravel query analysis with no third-party dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple


SCANNER_VERSION = "0.1.0"
QUERY_TERMINALS = (
    "get", "first", "firstOrFail", "find", "findOrFail", "value", "pluck",
    "count", "exists", "doesntExist", "sum", "avg", "min", "max", "paginate",
    "simplePaginate", "cursor", "chunk", "each", "update", "delete", "insert",
)
RELATION_BUILDERS = (
    "hasOne", "hasMany", "belongsTo", "belongsToMany", "morphOne", "morphMany",
    "morphTo", "morphToMany", "morphedByMany", "hasOneThrough", "hasManyThrough",
)
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class PhpMethod:
    name: str
    start: int
    end: int
    start_line: int
    end_line: int
    source: str
    body_start: int


@dataclass
class Finding:
    rule_id: str
    severity: str
    confidence: str
    file: str
    line: int
    method: str
    title: str
    message: str
    suggestion: str
    snippet: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, object]) -> "Finding":
        return cls(**value)  # type: ignore[arg-type]


@dataclass
class ScanSummary:
    files_scanned: int
    files_cached: int
    findings: List[Finding]
    cancelled: bool = False


def mask_php(source: str) -> str:
    """Replace comments and string contents while preserving offsets and newlines."""
    chars = list(source)
    index = 0
    length = len(source)
    state = "code"
    quote = ""

    while index < length:
        current = source[index]
        following = source[index + 1] if index + 1 < length else ""

        if state == "code":
            if current in ("'", '"', "`"):
                state = "string"
                quote = current
                index += 1
                continue
            if current == "/" and following == "/":
                chars[index] = chars[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if current == "#":
                chars[index] = " "
                state = "line_comment"
                index += 1
                continue
            if current == "/" and following == "*":
                chars[index] = chars[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
        elif state == "string":
            if current == "\\":
                if current != "\n":
                    chars[index] = " "
                if index + 1 < length and source[index + 1] != "\n":
                    chars[index + 1] = " "
                index += 2
                continue
            if current == quote:
                state = "code"
                quote = ""
            elif current != "\n":
                chars[index] = " "
        elif state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                chars[index] = " "
        elif state == "block_comment":
            if current == "*" and following == "/":
                chars[index] = chars[index + 1] = " "
                state = "code"
                index += 2
                continue
            if current != "\n":
                chars[index] = " "
        index += 1

    return "".join(chars)


def find_matching(text: str, start: int, opening: str, closing: str) -> Optional[int]:
    if start < 0 or start >= len(text) or text[start] != opening:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, max(0, offset)) + 1


def extract_methods(source: str) -> List[PhpMethod]:
    masked = mask_php(source)
    pattern = re.compile(
        r"\bfunction\s+&?\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    methods: List[PhpMethod] = []
    for match in pattern.finditer(masked):
        parameters_end = find_matching(masked, match.end() - 1, "(", ")")
        if parameters_end is None:
            continue
        body_start = masked.find("{", parameters_end)
        semicolon = masked.find(";", parameters_end)
        if body_start < 0 or (semicolon >= 0 and semicolon < body_start):
            continue
        body_end = find_matching(masked, body_start, "{", "}")
        if body_end is None:
            continue
        declaration_start = source.rfind("\n", 0, match.start()) + 1
        methods.append(
            PhpMethod(
                name=match.group("name"),
                start=declaration_start,
                end=body_end + 1,
                start_line=line_number(source, declaration_start),
                end_line=line_number(source, body_end),
                source=source[declaration_start:body_end + 1],
                body_start=body_start,
            )
        )
    return methods


def discover_relationships(project_root: Path) -> Tuple[Set[str], Dict[str, List[str]], str]:
    relationships: Set[str] = set()
    by_model: Dict[str, List[str]] = {}
    digest = hashlib.sha256()
    app_dir = project_root / "app"
    if not app_dir.is_dir():
        return relationships, by_model, digest.hexdigest()

    relation_pattern = re.compile(
        r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)[^{]*\{(?P<body>.*?)\}",
        re.DOTALL,
    )
    builder_pattern = re.compile(r"\$this\s*->\s*(?:" + "|".join(RELATION_BUILDERS) + r")\s*\(")

    for path in sorted(app_dir.rglob("*.php")):
        try:
            raw = path.read_bytes()
            source = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        digest.update(str(path.relative_to(project_root)).encode("utf-8", errors="replace"))
        digest.update(raw)
        names: List[str] = []
        for match in relation_pattern.finditer(mask_php(source)):
            body_source = source[match.start("body"):match.end("body")]
            if builder_pattern.search(body_source):
                names.append(match.group(1))
                relationships.add(match.group(1))
        if names:
            by_model[path.stem] = sorted(set(names))
    return relationships, by_model, digest.hexdigest()


def _statement_snippet(source: str, offset: int) -> str:
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", offset)
    if end < 0:
        end = len(source)
    return source[start:end].strip()[:240]


def _query_pattern() -> re.Pattern[str]:
    terminals = "|".join(re.escape(name) for name in QUERY_TERMINALS)
    return re.compile(
        r"(?:\\?[A-Z][A-Za-z0-9_\\]*\s*::|\$[A-Za-z_][A-Za-z0-9_]*\s*->)"
        r"(?:(?!;|\{\{|\?>).){0,1200}?"
        r"(?:->|::)(?:" + terminals + r")\s*\(",
        re.DOTALL,
    )


QUERY_PATTERN = _query_pattern()


def _is_query_candidate(query: str, relationships: Set[str]) -> bool:
    """Reject common non-database chains such as request()->session()->get()."""
    compact = re.sub(r"\s+", "", query)
    if re.match(r"\\?[A-Z][A-Za-z0-9_\\]*::", compact):
        return True
    builder_methods = (
        "where", "orWhere", "whereIn", "whereHas", "select", "addSelect", "table",
        "query", "join", "leftJoin", "rightJoin", "orderBy", "latest", "oldest",
        "groupBy", "having", "limit", "take", "offset", "skip", "with", "on",
        "from", "distinct", "lockForUpdate",
    )
    if any("->%s(" % name in compact for name in builder_methods):
        return True
    return any("->%s(" % name in compact for name in relationships)


def _loop_ranges(method_source: str) -> List[Tuple[int, int, int, str, str]]:
    masked = mask_php(method_source)
    ranges: List[Tuple[int, int, int, str, str]] = []
    loop_pattern = re.compile(r"\b(foreach|for|while)\s*\(")
    for match in loop_pattern.finditer(masked):
        condition_end = find_matching(masked, match.end() - 1, "(", ")")
        if condition_end is None:
            continue
        body_start = condition_end + 1
        while body_start < len(masked) and masked[body_start].isspace():
            body_start += 1
        if body_start < len(masked) and masked[body_start] == "{":
            body_end = find_matching(masked, body_start, "{", "}")
            if body_end is None:
                continue
            content_start, content_end = body_start + 1, body_end
        else:
            body_end = masked.find(";", body_start)
            if body_end < 0:
                continue
            content_start, content_end = body_start, body_end + 1
        header = method_source[match.start():condition_end + 1]
        ranges.append((content_start, content_end, match.start(), match.group(1), header))
    return ranges


def _normalize_query(query: str) -> str:
    normalized = re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", "?", query, flags=re.DOTALL)
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "?", normalized)
    normalized = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", "$?", normalized)
    return re.sub(r"\s+", "", normalized).lower()


class CacheStore:
    def __init__(self, directory: Optional[Path] = None) -> None:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        self.directory = directory or base / "LaravelQueryScanner" / "cache"

    def _path(self, key: str) -> Path:
        return self.directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def load(self, key: str, fingerprint: str) -> Optional[List[Finding]]:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("fingerprint") != fingerprint:
                return None
            return [Finding.from_dict(item) for item in payload.get("findings", [])]
        except (OSError, ValueError, TypeError):
            return None

    def save(self, key: str, fingerprint: str, findings: Sequence[Finding]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        temporary = path.with_suffix(".tmp")
        payload = {"fingerprint": fingerprint, "findings": [item.to_dict() for item in findings]}
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)


class LaravelQueryScanner:
    def __init__(self, project_root: Path, use_cache: bool = True) -> None:
        self.project_root = project_root.resolve()
        self.use_cache = use_cache
        self.cache = CacheStore()
        self.relationships, self.relationships_by_model, self.relationship_signature = discover_relationships(
            self.project_root
        )

    @staticmethod
    def is_laravel_project(path: Path) -> bool:
        return (path / "artisan").is_file() and (path / "composer.json").is_file() and (path / "app").is_dir()

    def discover_files(self, selected_file: Optional[Path] = None) -> List[Path]:
        if selected_file:
            candidate = selected_file.resolve()
            return [candidate] if candidate.is_file() and candidate.suffix.lower() == ".php" else []
        app_dir = self.project_root / "app"
        return sorted(path for path in app_dir.rglob("*.php") if path.is_file())

    def scan(
        self,
        selected_file: Optional[Path] = None,
        selected_method: Optional[str] = None,
        progress: Optional[Callable[[int, int, Path], None]] = None,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> ScanSummary:
        files = self.discover_files(selected_file)
        findings: List[Finding] = []
        cached_count = 0
        completed = 0
        was_cancelled = False

        for index, path in enumerate(files, 1):
            if cancelled and cancelled():
                was_cancelled = True
                break
            if progress:
                progress(index, len(files), path)
            file_findings, cached = self.scan_file(path, selected_method if selected_file else None)
            findings.extend(file_findings)
            cached_count += int(cached)
            completed += 1

        findings.sort(key=lambda item: (SEVERITY_ORDER.get(item.severity, 9), item.file, item.line))
        return ScanSummary(completed, cached_count, findings, was_cancelled)

    def scan_file(self, path: Path, selected_method: Optional[str] = None) -> Tuple[List[Finding], bool]:
        try:
            raw = path.read_bytes()
        except OSError:
            return [], False
        relative = str(path.resolve().relative_to(self.project_root)).replace("\\", "/")
        fingerprint = hashlib.sha256(
            raw + self.relationship_signature.encode("ascii") + SCANNER_VERSION.encode("ascii")
            + (selected_method or "").encode("utf-8")
        ).hexdigest()
        cache_key = str(self.project_root) + "|" + relative + "|" + (selected_method or "*")
        if self.use_cache:
            cached = self.cache.load(cache_key, fingerprint)
            if cached is not None:
                return cached, True

        source = raw.decode("utf-8", errors="replace")
        findings: List[Finding] = []
        for method in extract_methods(source):
            if selected_method and method.name != selected_method:
                continue
            findings.extend(self._scan_method(relative, method))
        if self.use_cache:
            self.cache.save(cache_key, fingerprint, findings)
        return findings, False

    def _scan_method(self, relative: str, method: PhpMethod) -> List[Finding]:
        findings: List[Finding] = []
        method_source = method.source
        masked = mask_php(method_source)

        for body_start, body_end, loop_start, loop_kind, header in _loop_ranges(method_source):
            loop_body = method_source[body_start:body_end]
            query_match = next(
                (match for match in QUERY_PATTERN.finditer(mask_php(loop_body))
                 if _is_query_candidate(loop_body[match.start():match.end()], self.relationships)),
                None,
            )
            if query_match:
                offset = body_start + query_match.start()
                findings.append(Finding(
                    "LQS001", "high", "high", relative,
                    method.start_line + line_number(method_source, offset) - 1,
                    method.name, "Query inside loop",
                    "A database query appears inside a %s loop and may execute once per item." % loop_kind,
                    "Load the data before the loop, eager-load the relationship, or replace per-item work with a bulk query.",
                    _statement_snippet(method_source, offset),
                ))

            foreach_variable = re.search(r"\bas\s+(?:\$\w+\s*=>\s*)?\$(\w+)", header)
            if foreach_variable and self.relationships:
                variable = re.escape(foreach_variable.group(1))
                relation_names = "|".join(re.escape(name) for name in sorted(self.relationships, key=len, reverse=True))
                lazy_pattern = re.compile(r"\$" + variable + r"\s*->\s*(" + relation_names + r")\b(?!\s*\()")
                lazy_match = lazy_pattern.search(loop_body)
                if lazy_match:
                    offset = body_start + lazy_match.start()
                    findings.append(Finding(
                        "LQS002", "high", "medium", relative,
                        method.start_line + line_number(method_source, offset) - 1,
                        method.name, "Possible N+1 relationship access",
                        "Relationship '%s' is accessed for each loop item and may be lazy-loaded." % lazy_match.group(1),
                        "Add the relationship to with()/load() before the loop, then confirm with Laravel query logging.",
                        _statement_snippet(method_source, offset),
                    ))

        explicit_patterns = (
            re.compile(r"(?:->|::)\s*(?:select|addSelect)\s*\(\s*['\"](?:[^'\"]+\.)?\*['\"]", re.I),
            re.compile(r"\bselect\s+\*\s+from\b", re.I),
        )
        for pattern in explicit_patterns:
            for match in pattern.finditer(method_source):
                findings.append(Finding(
                    "LQS003", "medium", "high", relative,
                    method.start_line + line_number(method_source, match.start()) - 1,
                    method.name, "Explicit SELECT *",
                    "This query requests every column, which can transfer unnecessary data.",
                    "Select only the columns used by this method and include keys needed by relationships.",
                    _statement_snippet(method_source, match.start()),
                ))

        for match in re.finditer(r"(?<![A-Za-z0-9_\\])(\\?[A-Z][A-Za-z0-9_\\]*)\s*::\s*all\s*\(", masked):
            findings.append(Finding(
                "LQS004", "low", "high", relative,
                method.start_line + line_number(method_source, match.start()) - 1,
                method.name, "Unbounded all() query",
                "%s::all() loads every row and every column into memory." % match.group(1).split("\\")[-1],
                "Use select() plus a filter, pagination, chunk(), or cursor() based on the workflow.",
                _statement_snippet(method_source, match.start()),
            ))

        queries: Dict[str, List[Tuple[int, str]]] = {}
        for match in QUERY_PATTERN.finditer(masked):
            query_text = method_source[match.start():match.end()]
            if not _is_query_candidate(query_text, self.relationships):
                continue
            normalized = _normalize_query(query_text)
            queries.setdefault(normalized, []).append((match.start(), query_text))
        for occurrences in queries.values():
            if len(occurrences) < 2:
                continue
            offset, query_text = occurrences[1]
            findings.append(Finding(
                "LQS005", "medium", "medium", relative,
                method.start_line + line_number(method_source, offset) - 1,
                method.name, "Repeated query pattern",
                "A similar query appears %d times in this method." % len(occurrences),
                "Run it once and reuse/index the result, or consolidate the work into one set-based query.",
                _statement_snippet(method_source, offset) or query_text.strip()[:240],
            ))

        unique: Dict[Tuple[str, int, str], Finding] = {}
        for finding in findings:
            unique[(finding.rule_id, finding.line, finding.method)] = finding
        return list(unique.values())


def findings_to_json(summary: ScanSummary) -> str:
    payload = {
        "scanner_version": SCANNER_VERSION,
        "files_scanned": summary.files_scanned,
        "files_cached": summary.files_cached,
        "cancelled": summary.cancelled,
        "findings": [finding.to_dict() for finding in summary.findings],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)

