from dataclasses import dataclass, field
import re


class QueryValidationError(ValueError):
    """Safe validation error. Messages must not include secrets or connection data."""


@dataclass(frozen=True)
class QueryValidationResult:
    is_valid: bool
    normalized_sql: str
    bind_names: list[str] = field(default_factory=list)
    referenced_objects: list[str] = field(default_factory=list)
    reason: str | None = None


DISALLOWED_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "upsert",
    "alter",
    "drop",
    "truncate",
    "create",
    "grant",
    "revoke",
    "call",
    "exec",
    "execute",
    "begin",
    "declare",
    "commit",
    "rollback",
}

BIND_RE = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
OBJECT_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_$#]*(?:\.[A-Za-z_][A-Za-z0-9_$#]*)?)", re.I)
INTERPOLATION_PATTERNS = [
    re.compile(r"\$\{[^}]+\}"),
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)s"),
    re.compile(r"\.format\s*\("),
]


def strip_sql_comments(sql_text: str) -> str:
    without_line_comments = re.sub(r"--.*?$", "", sql_text, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", without_line_comments, flags=re.DOTALL)


def strip_string_literals(sql_text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(sql_text):
        char = sql_text[index]
        if char != "'":
            result.append(char)
            index += 1
            continue
        result.append("''")
        index += 1
        while index < len(sql_text):
            if sql_text[index] == "'":
                if index + 1 < len(sql_text) and sql_text[index + 1] == "'":
                    index += 2
                    continue
                index += 1
                break
            index += 1
    return "".join(result)


def validate_read_only_template(
    sql_text: str,
    *,
    allowed_objects: list[str] | None = None,
) -> QueryValidationResult:
    try:
        return _validate(sql_text, allowed_objects=allowed_objects)
    except QueryValidationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive sanitization
        raise QueryValidationError("SQL template validation failed safely.") from exc


def _validate(sql_text: str, *, allowed_objects: list[str] | None = None) -> QueryValidationResult:
    if not sql_text or not sql_text.strip():
        raise QueryValidationError("SQL template cannot be empty.")

    for pattern in INTERPOLATION_PATTERNS:
        if pattern.search(sql_text):
            raise QueryValidationError("SQL template must not use string interpolation patterns.")

    without_comments = strip_sql_comments(sql_text).strip()
    if not without_comments:
        raise QueryValidationError("SQL template cannot contain only comments.")

    without_strings = strip_string_literals(without_comments)
    if _has_multiple_statements(without_strings):
        raise QueryValidationError("Only one read-only SELECT/WITH statement is allowed.")

    normalized = without_comments.rstrip(";").strip()
    token_sql = strip_string_literals(normalized).lower()
    leading = token_sql.lstrip()
    if not (leading.startswith("select") or leading.startswith("with")):
        raise QueryValidationError("SQL templates must start with SELECT or WITH.")

    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_$#]*\b", token_sql)
    for token in tokens:
        if token in DISALLOWED_KEYWORDS:
            raise QueryValidationError("SQL template contains a disallowed non-read-only keyword.")
    if re.search(r"\bdbms_[A-Za-z0-9_$#]*\b", token_sql, re.I):
        raise QueryValidationError("SQL template may not call DBMS_* packages.")

    bind_names = sorted(set(BIND_RE.findall(strip_string_literals(normalized))))
    if not bind_names:
        raise QueryValidationError("SQL templates must use named bind parameters.")

    referenced_objects = sorted({match.group(1).lower() for match in OBJECT_RE.finditer(token_sql)})
    if allowed_objects:
        allowed = {item.lower() for item in allowed_objects}
        blocked = [item for item in referenced_objects if item not in allowed]
        if blocked:
            raise QueryValidationError("SQL template references an object outside the configured allowlist.")

    return QueryValidationResult(
        is_valid=True,
        normalized_sql=normalized,
        bind_names=bind_names,
        referenced_objects=referenced_objects,
    )


def apply_oracle_row_limit(sql_text: str, row_limit: int) -> str:
    normalized = validate_read_only_template(sql_text).normalized_sql
    return f"SELECT * FROM ({normalized}) WHERE ROWNUM <= :__jobrun_row_limit"


def _has_multiple_statements(sql_text_without_strings: str) -> bool:
    stripped = sql_text_without_strings.strip()
    if ";" not in stripped:
        return False
    return ";" in stripped.rstrip(";")
