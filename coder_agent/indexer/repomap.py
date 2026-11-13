"""High-signal, token-budgeted repository map generator."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from coder_agent.indexer.symbols import FileSymbols, extract_symbols_from_file
from coder_agent.tools.list_directory import _is_excluded

logger = logging.getLogger("coder_agent.indexer.repomap")


class RepoMap:
    """Constructs a dependency-ranked, token-budgeted structural map of the codebase."""

    def __init__(
        self,
        project_dir: str | Path,
        exclude_patterns: list[str] | None = None,
        max_tokens: int = 1500,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.exclude_patterns = exclude_patterns or []
        self.max_tokens = max_tokens

    def _collect_source_files(self) -> list[Path]:
        """Collect all relevant source files in the repository."""
        source_files: list[Path] = []
        supported_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}

        for item in self.project_dir.rglob("*"):
            if not item.is_file():
                continue
            if item.suffix.lower() not in supported_exts:
                continue
            if _is_excluded(item, self.project_dir, self.exclude_patterns):
                continue
            # Skip hidden files or test caches
            if any(part.startswith(".") for part in item.relative_to(self.project_dir).parts):
                continue
            source_files.append(item)

        return source_files

    def build_map(self) -> str:
        """Analyze project sources and render a compact skeletal map within token budget."""
        files = self._collect_source_files()
        if not files:
            return ""

        file_symbols_list: list[FileSymbols] = []
        reference_scores: dict[str, int] = defaultdict(int)

        # 1. Parse symbols and track imports
        for f in files:
            fs = extract_symbols_from_file(f, self.project_dir)
            if fs.symbols:
                file_symbols_list.append(fs)
                for imp in fs.imports:
                    # Increment reference count for imported modules
                    reference_scores[imp] += 1

        # 2. Rank files by structural centrality
        def _score(fs: FileSymbols) -> int:
            module_name = Path(fs.path).stem
            score = reference_scores.get(module_name, 0)
            # Boost core models, types, config
            if module_name in ("types", "models", "schema", "config", "base", "core"):
                score += 5
            return score

        ranked_files = sorted(file_symbols_list, key=_score, reverse=True)

        # 3. Format compact skeletal view within character budget (~4 chars per token)
        max_chars = self.max_tokens * 4
        lines: list[str] = ["## Key Repository Symbols & Architecture:"]
        current_length = sum(len(line) + 1 for line in lines)

        for fs in ranked_files:
            file_header = f"📄 `{fs.path}`:"
            symbol_lines: list[str] = []

            for sym in fs.symbols:
                if sym.kind in ("class", "interface", "struct"):
                    doc_hint = f" — {sym.docstring}" if sym.docstring else ""
                    symbol_lines.append(f"  • {sym.kind} **{sym.name}**{doc_hint}")
                elif sym.kind in ("function", "async_function"):
                    doc_hint = f" — {sym.docstring}" if sym.docstring else ""
                    symbol_lines.append(f"  • fn `{sym.name}{sym.signature}`{doc_hint}")
                elif sym.kind in ("method", "async_method"):
                    # Only include key methods, limit clutter
                    if not sym.name.split(".")[-1].startswith("_") or sym.name.endswith(".__init__"):
                        symbol_lines.append(f"    - `{sym.name}{sym.signature}`")

            block = "\n".join([file_header] + symbol_lines)
            if current_length + len(block) > max_chars:
                lines.append(f"... [Remaining {len(ranked_files) - len(lines)} files omitted for brevity] ...")
                break

            lines.append(block)
            current_length += len(block) + 1

        return "\n\n".join(lines)
