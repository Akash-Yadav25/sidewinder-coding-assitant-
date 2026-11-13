"""Unit tests for the AST symbol indexer and RepoMap."""

from __future__ import annotations

from pathlib import Path

from coder_agent.indexer.repomap import RepoMap
from coder_agent.indexer.symbols import extract_symbols_from_file


def test_extract_python_symbols(tmp_path: Path):
    code = """
import os
from math import sqrt

class Calculator:
    \"\"\"A simple calculator.\"\"\"
    def add(self, a, b):
        return a + b

async def fetch_data(url: str):
    \"\"\"Fetch remote data.\"\"\"
    pass
"""
    f = tmp_path / "calc.py"
    f.write_text(code, encoding="utf-8")

    symbols = extract_symbols_from_file(f, tmp_path)
    assert symbols.language == "python"
    assert "os" in symbols.imports
    assert "math" in symbols.imports

    names = {s.name for s in symbols.symbols}
    assert "Calculator" in names
    assert "Calculator.add" in names
    assert "fetch_data" in names

    calc_sym = next(s for s in symbols.symbols if s.name == "Calculator")
    assert calc_sym.docstring == "A simple calculator."


def test_extract_typescript_symbols(tmp_path: Path):
    code = """
import { Request, Response } from 'express';

export interface User {
    id: string;
}

export function getUser(id: string): User {
    return { id };
}

export const deleteUser = async (id: string) => {
    return true;
};
"""
    f = tmp_path / "service.ts"
    f.write_text(code, encoding="utf-8")

    symbols = extract_symbols_from_file(f, tmp_path)
    assert symbols.language == "typescript"
    assert "express" in symbols.imports

    names = {s.name for s in symbols.symbols}
    assert "User" in names
    assert "getUser" in names
    assert "deleteUser" in names


def test_repomap_generation(tmp_path: Path):
    (tmp_path / "app.py").write_text("import models\ndef main(): pass\n", encoding="utf-8")
    (tmp_path / "models.py").write_text("class User: pass\nclass Order: pass\n", encoding="utf-8")

    rm = RepoMap(project_dir=tmp_path, max_tokens=1000)
    map_str = rm.build_map()

    assert "## Key Repository Symbols & Architecture:" in map_str
    assert "models.py" in map_str
    assert "class **User**" in map_str
    assert "app.py" in map_str
    assert "fn `main()`" in map_str
