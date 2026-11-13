"""Hybrid code search combining AST symbol matching and lexical code search."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from coder_agent.indexer.symbols import Symbol, extract_symbols_from_file


@dataclass
class SearchResult:
    """Represents a matched code location with relevance score."""

    path: str
    line: int
    match_type: str  # "exact_symbol", "symbol", "content"
    matched_name: str
    snippet: str
    score: float


class HybridCodeSearch:
    """Hybrid search engine that indexes symbols and source files for fast, ranked retrieval."""

    DEFAULT_EXCLUDES = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".coder-agent",
        "dist",
        "build",
        ".pytest_cache",
    }

    SUPPORTED_EXTENSIONS = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".json",
        ".md",
        ".toml",
        ".yaml",
        ".yml",
        ".txt",
    }

    def __init__(self, project_dir: str | Path, exclude_dirs: set[str] | None = None):
        self.project_dir = Path(project_dir).resolve()
        self.exclude_dirs = exclude_dirs or self.DEFAULT_EXCLUDES
        self._symbols_cache: dict[str, list[Symbol]] = {}
        self._indexed = False

    def index(self) -> None:
        """Scan workspace and index source code symbols."""
        self._symbols_cache.clear()
        for fpath in self._walk_files():
            if fpath.suffix.lower() in (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs"):
                fs = extract_symbols_from_file(fpath, self.project_dir)
                if fs.symbols:
                    self._symbols_cache[fs.path] = fs.symbols
        self._indexed = True

    def _walk_files(self) -> list[Path]:
        """Collect source files excluding ignored directories."""
        matched: list[Path] = []
        for p in self.project_dir.rglob("*"):
            if any(part in self.exclude_dirs for part in p.parts):
                continue
            if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                matched.append(p)
        return matched

    def search(self, query: str, max_results: int = 15) -> list[SearchResult]:
        """Perform hybrid search over indexed symbols and file contents."""
        if not self._indexed:
            self.index()

        query = query.strip()
        if not query:
            return []

        results: list[SearchResult] = []
        seen_keys: set[tuple[str, int]] = set()
        q_lower = query.lower()

        # 1. Match against AST/Regex symbols
        for rel_path, symbols in self._symbols_cache.items():
            for sym in symbols:
                sym_name_lower = sym.name.lower()
                score = 0.0
                match_type = ""

                if sym_name_lower == q_lower:
                    score = 10.0
                    match_type = "exact_symbol"
                elif q_lower in sym_name_lower:
                    score = 5.0
                    match_type = "symbol"
                elif sym.docstring and q_lower in sym.docstring.lower():
                    score = 3.0
                    match_type = "symbol_doc"

                if score > 0:
                    key = (rel_path, sym.line)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        snippet = f"{sym.kind} {sym.name}{sym.signature}"
                        results.append(
                            SearchResult(
                                path=rel_path,
                                line=sym.line,
                                match_type=match_type,
                                matched_name=sym.name,
                                snippet=snippet,
                                score=score,
                            )
                        )

        # 2. Match against raw file content (lexical / grep search)
        query_pattern = re.compile(re.escape(query), re.IGNORECASE)
        for fpath in self._walk_files():
            try:
                rel_path = str(fpath.relative_to(self.project_dir))
            except ValueError:
                rel_path = fpath.name

            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for idx, line in enumerate(lines, start=1):
                key = (rel_path, idx)
                if key in seen_keys:
                    continue

                if query_pattern.search(line):
                    seen_keys.add(key)
                    snippet = line.strip()
                    if len(snippet) > 120:
                        snippet = snippet[:117] + "..."
                    results.append(
                        SearchResult(
                            path=rel_path,
                            line=idx,
                            match_type="content",
                            matched_name=query,
                            snippet=snippet,
                            score=1.0,
                        )
                    )

        # Sort by score descending, then by path and line
        results.sort(key=lambda r: (-r.score, r.path, r.line))
        return results[:max_results]
