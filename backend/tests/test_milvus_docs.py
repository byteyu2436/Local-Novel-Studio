from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_milvus_docs_cover_windows_linux_and_canon_boundary() -> None:
    milvus = (ROOT / "docs" / "milvus.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    development = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    assert "Windows 11" in milvus
    assert "Linux" in milvus
    assert "milvus-up.ps1" in milvus and "milvus-up.sh" in milvus
    assert "19530" in milvus and "9091" in milvus
    assert "not Canon" in milvus
    assert "rebuildable" in milvus.lower()
    assert "milvusdb/milvus:v2.5.4" in milvus
    assert "后续 Issue 接入" not in readme
    assert "milvus-up.ps1" in development
    assert "Canon" in development
