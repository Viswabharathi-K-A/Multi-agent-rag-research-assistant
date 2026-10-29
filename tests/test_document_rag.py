"""Real ingestion and retrieval with local fake embeddings and one PDF page."""

from unittest.mock import Mock

from langchain_core.embeddings import DeterministicFakeEmbedding

from app.config import Settings
from app.services import document_rag


def test_retrieval_preserves_source_metadata(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "raft.pdf").write_bytes(b"PDF placeholder; text extraction is mocked")
    text = "Raft uses leader election to reach consensus."
    reader = Mock(is_encrypted=False, pages=[Mock(extract_text=Mock(return_value=text))])
    monkeypatch.setattr(document_rag, "PdfReader", lambda path: reader)
    monkeypatch.setattr(document_rag, "get_embeddings", Mock(
        side_effect=AssertionError("This test must not load a real embedding model")))
    settings = Settings(
        _env_file=None, corpus_dir=corpus, chroma_persist_dir=tmp_path / "index",
        embedding_model="offline-test", retrieval_top_k=1,
    )
    embeddings = DeterministicFakeEmbedding(size=8)

    document_rag.ingest_documents(settings, embeddings)
    results = document_rag.retrieve_documents("leader election", settings, embeddings)

    assert len(results) == 1
    assert results[0].page_content == text
    assert results[0].metadata["source"] == "raft.pdf"
    assert results[0].metadata["page"] == 1
    assert results[0].metadata["chunk_id"] == "raft.pdf:p1:c1"
