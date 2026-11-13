"""Multi-language AST and pattern-based symbol extractor."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Symbol:
    """Represents a code symbol (class, function, method, interface)."""

    name: str
    kind: str  # "class" | "function" | "async_function" | "method" | "interface" | "struct"
    line: int
    signature: str = ""
    docstring: str = ""


@dataclass
class FileSymbols:
    """Symbols and references contained within a single source file."""

    path: str  # Relative path
    language: str
    imports: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)


def _extract_python_symbols(content: str, rel_path: str) -> FileSymbols:
    """Extract symbols from Python files using standard library ast."""
    symbols: list[Symbol] = []
    imports: list[str] = []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return FileSymbols(path=rel_path, language="python")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async_function" if isinstance(item, ast.AsyncFunctionDef) else "function"
            args_str = ", ".join(a.arg for a in item.args.args)
            sig = f"({args_str})"
            doc = ast.get_docstring(item) or ""
            symbols.append(
                Symbol(
                    name=item.name,
                    kind=kind,
                    line=item.lineno,
                    signature=sig,
                    docstring=doc.splitlines()[0] if doc else "",
                )
            )
        elif isinstance(item, ast.ClassDef):
            doc = ast.get_docstring(item) or ""
            symbols.append(
                Symbol(
                    name=item.name,
                    kind="class",
                    line=item.lineno,
                    docstring=doc.splitlines()[0] if doc else "",
                )
            )
            # Inspect class methods
            for member in item.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_kind = "async_method" if isinstance(member, ast.AsyncFunctionDef) else "method"
                    m_args = ", ".join(a.arg for a in member.args.args)
                    symbols.append(
                        Symbol(
                            name=f"{item.name}.{member.name}",
                            kind=m_kind,
                            line=member.lineno,
                            signature=f"({m_args})",
                        )
                    )

    return FileSymbols(path=rel_path, language="python", imports=imports, symbols=symbols)


def _extract_regex_symbols(content: str, rel_path: str, language: str) -> FileSymbols:
    """Regex-based symbol extractor for TypeScript, JavaScript, Go, and Rust."""
    symbols: list[Symbol] = []
    imports: list[str] = []

    lines = content.splitlines()

    # Import matchers
    if language in ("javascript", "typescript"):
        import_pattern = re.compile(r"""(?:import\s+.*?from\s+['"](.*?)['"]|require\(['"](.*?)['"]\))""")
        for line in lines:
            m = import_pattern.search(line)
            if m:
                target = m.group(1) or m.group(2)
                if target:
                    imports.append(target)

        # Function/Class patterns
        fn_pattern = re.compile(r"""(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\((.*?)\)""")
        arrow_pattern = re.compile(r"""(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>""")
        class_pattern = re.compile(r"""(?:export\s+)?(?:class|interface|type)\s+([a-zA-Z0-9_$]+)""")

        for idx, line in enumerate(lines, 1):
            m_fn = fn_pattern.search(line)
            if m_fn:
                symbols.append(Symbol(name=m_fn.group(1), kind="function", line=idx, signature=f"({m_fn.group(2)})"))
                continue
            m_arrow = arrow_pattern.search(line)
            if m_arrow:
                symbols.append(Symbol(name=m_arrow.group(1), kind="function", line=idx, signature=f"({m_arrow.group(2)})"))
                continue
            m_cls = class_pattern.search(line)
            if m_cls:
                symbols.append(Symbol(name=m_cls.group(1), kind="class", line=idx))

    elif language == "go":
        fn_pattern = re.compile(r"""func\s+(?:\(.*?\)\s*)?([a-zA-Z0-9_]+)\s*\((.*?)\)""")
        type_pattern = re.compile(r"""type\s+([a-zA-Z0-9_]+)\s+(?:struct|interface)""")
        for idx, line in enumerate(lines, 1):
            m_fn = fn_pattern.search(line)
            if m_fn:
                symbols.append(Symbol(name=m_fn.group(1), kind="function", line=idx, signature=f"({m_fn.group(2)})"))
                continue
            m_type = type_pattern.search(line)
            if m_type:
                symbols.append(Symbol(name=m_type.group(1), kind="struct", line=idx))

    elif language == "rust":
        fn_pattern = re.compile(r"""(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)\s*(?:<.*?>)?\s*\((.*?)\)""")
        type_pattern = re.compile(r"""(?:pub\s+)?(?:struct|enum|trait)\s+([a-zA-Z0-9_]+)""")
        for idx, line in enumerate(lines, 1):
            m_fn = fn_pattern.search(line)
            if m_fn:
                symbols.append(Symbol(name=m_fn.group(1), kind="function", line=idx, signature=f"({m_fn.group(2)})"))
                continue
            m_type = type_pattern.search(line)
            if m_type:
                symbols.append(Symbol(name=m_type.group(1), kind="struct", line=idx))

    return FileSymbols(path=rel_path, language=language, imports=imports, symbols=symbols)


def extract_symbols_from_file(file_path: Path, root_dir: Path) -> FileSymbols:
    """Extract all functions, classes, and import declarations from a code file."""
    try:
        rel_path = str(file_path.relative_to(root_dir))
    except ValueError:
        rel_path = file_path.name

    suffix = file_path.suffix.lower()
    if suffix not in (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs"):
        return FileSymbols(path=rel_path, language="unknown")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return FileSymbols(path=rel_path, language="error")

    if suffix == ".py":
        return _extract_python_symbols(content, rel_path)
    elif suffix in (".js", ".jsx"):
        return _extract_regex_symbols(content, rel_path, "javascript")
    elif suffix in (".ts", ".tsx"):
        return _extract_regex_symbols(content, rel_path, "typescript")
    elif suffix == ".go":
        return _extract_regex_symbols(content, rel_path, "go")
    elif suffix == ".rs":
        return _extract_regex_symbols(content, rel_path, "rust")

    return FileSymbols(path=rel_path, language="unknown")
