"""Unit tests for HybridCodeSearch."""

from __future__ import annotations

from pathlib import Path

from coder_agent.indexer.search import HybridCodeSearch


def test_hybrid_search_symbol_and_content(tmp_path: Path):
    # Setup test workspace
    py_file = tmp_path / "math_service.py"
    py_file.write_text(
        "class MathEngine:\n"
        "    def calculate_tax(self, amount: float) -> float:\n"
        "        # internal calculation constant\n"
        "        rate = 0.15\n"
        "        return amount * rate\n",
        encoding="utf-8",
    )

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("Here are calculation notes for reference.\n", encoding="utf-8")

    searcher = HybridCodeSearch(tmp_path)
    searcher.index()

    # Search for symbol name
    results_sym = searcher.search("calculate_tax")
    assert len(results_sym) > 0
    top = results_sym[0]
    assert top.path == "math_service.py"
    assert "calculate_tax" in top.matched_name
    assert top.score >= 5.0
    assert "calculate_tax" in top.snippet

    # Search for lexical content
    results_txt = searcher.search("calculation")
    assert len(results_txt) >= 1
    paths = [r.path for r in results_txt]
    assert "notes.txt" in paths or "math_service.py" in paths


def test_hybrid_search_empty_and_no_match(tmp_path: Path):
    searcher = HybridCodeSearch(tmp_path)
    assert searcher.search("") == []
    assert searcher.search("nonexistent_symbol_12345") == []


def test_hybrid_search_respects_excludes(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "secret_file.py").write_text("def secret(): pass\n", encoding="utf-8")

    searcher = HybridCodeSearch(tmp_path)
    res = searcher.search("secret")
    assert len(res) == 0
