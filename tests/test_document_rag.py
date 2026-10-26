"""Offline integration tests: real Chroma, deterministic embedding vectors."""

from math import sqrt

import pytest
from langchain_core.embeddings import Embeddings

from app.config import Settings
from app.services import document_rag


class FakeEmbeddings(Embeddings):
    """Distinguish two topics without loading a model or using an API."""

    def __init__(self):
        self.document_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += len(texts)
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [text.lower().count("asyncio"), text.lower().count("database"), 1]
        length = sqrt(sum(value * value for value in vector))
        return [value / length for value in vector]


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    def forbid_model_loading(*args, **kwargs):
        pytest.fail("Offline tests must not load an embedding model")

    monkeypatch.setattr(document_rag, "get_embeddings", forbid_model_loading)
    documents = tmp_path / "corpus"
    documents.mkdir()
    (documents / "async.md").write_text(
        "# Async guide\n" + "asyncio concurrency await tasks. " * 80,
        encoding="utf-8",
    )
    (documents / "database.txt").write_text(
        "database storage tables transactions.", encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        corpus_dir=documents,
        chroma_persist_dir=tmp_path / "index",
        embedding_model="offline-test-v1",
        retrieval_top_k=1,
    )
    return settings, FakeEmbeddings()


def test_chunk_content_and_provenance(corpus):
    settings, _ = corpus
    chunks = document_rag.load_chunks(settings.documents_path)
    assert len(chunks) > 2
    assert len({chunk.metadata["chunk_id"] for chunk in chunks}) == len(chunks)
    for chunk in chunks:
        assert len(chunk.page_content) <= 800
        metadata = chunk.metadata
        original = (settings.documents_path / metadata["source"]).read_text(encoding="utf-8")
        start = metadata["start_index"]
        assert original[start:start + len(chunk.page_content)] == chunk.page_content
        assert metadata["source_kind"] == "document"
        assert metadata["document_id"]
        if metadata["source"] == "async.md":
            assert metadata["title"] == "Async guide"


def test_retrieval_preserves_citation_metadata(corpus):
    settings, embeddings = corpus
    document_rag.ingest_documents(settings, embeddings)
    chunks = document_rag.retrieve_documents("asyncio", settings, embeddings)
    assert len(chunks) == 1
    assert chunks[0].metadata["source"] == "async.md"
    assert "asyncio" in chunks[0].page_content
    assert chunks[0].metadata["chunk_id"]
    assert chunks[0].metadata["document_id"]


def test_repeated_ingestion_preserves_ids_without_reembedding(corpus):
    settings, embeddings = corpus
    first = document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    before = set(store.get(include=[])["ids"])
    calls = embeddings.document_calls
    second = document_rag.ingest_documents(settings, embeddings)
    assert second == {**first, "added_chunks": 0, "removed_chunks": 0}
    assert set(store.get(include=[])["ids"]) == before
    assert embeddings.document_calls == calls


def test_edits_and_deleted_documents_remove_stale_chunks(corpus):
    settings, embeddings = corpus
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    before = set(store.get(include=[])["ids"])
    (settings.documents_path / "async.md").write_text("asyncio revised guidance", encoding="utf-8")
    (settings.documents_path / "database.txt").unlink()
    summary = document_rag.ingest_documents(settings, embeddings)
    assert summary == {"documents": 1, "chunks": 1, "added_chunks": 1, "removed_chunks": len(before)}
    assert set(store.get(include=[])["ids"]).isdisjoint(before)
    assert document_rag.retrieve_documents("asyncio", settings, embeddings)[0].page_content == "asyncio revised guidance"


@pytest.mark.parametrize("failure", ["empty_corpus", "invalid_utf8", "embedding_failure"])
def test_failed_ingestion_preserves_existing_index(corpus, monkeypatch, failure):
    settings, embeddings = corpus
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    before = store.get()
    if failure == "empty_corpus":
        for path in settings.documents_path.iterdir():
            path.write_text("", encoding="utf-8")
        expected_error = ValueError
    elif failure == "invalid_utf8":
        (settings.documents_path / "bad.txt").write_bytes(b"\xff\xfe\xff")
        expected_error = UnicodeDecodeError
    else:
        (settings.documents_path / "async.md").write_text("changed asyncio evidence", encoding="utf-8")

        def fail_embedding(texts):
            raise RuntimeError("Simulated embedding failure")

        monkeypatch.setattr(embeddings, "embed_documents", fail_embedding)
        expected_error = RuntimeError
    with pytest.raises(expected_error):
        document_rag.ingest_documents(settings, embeddings)
    assert store.get() == before


@pytest.mark.parametrize("query", ["", " \n "])
def test_blank_query_does_not_create_index(corpus, query):
    settings, embeddings = corpus
    with pytest.raises(ValueError, match="empty"):
        document_rag.retrieve_documents(query, settings, embeddings)
    assert not settings.chroma_path.exists()


def test_missing_index_and_corpus(corpus):
    settings, embeddings = corpus
    with pytest.raises(ValueError, match="missing"):
        document_rag.retrieve_documents("asyncio", settings, embeddings)
    with pytest.raises(ValueError, match="does not exist"):
        document_rag.load_chunks(settings.documents_path / "missing")


def test_embedding_model_mismatch_rejects_reads_and_writes(corpus):
    settings, embeddings = corpus
    document_rag.ingest_documents(settings, embeddings)
    other = settings.model_copy(update={"embedding_model": "different-model"})
    with pytest.raises(ValueError, match="differs"):
        document_rag.retrieve_documents("asyncio", other, embeddings)
    with pytest.raises(ValueError, match="differs"):
        document_rag.ingest_documents(other, embeddings)


def test_nested_unicode_documents_and_unsupported_files(corpus):
    settings, _ = corpus
    nested = settings.documents_path / "nested"
    nested.mkdir()
    (nested / "guide.MD").write_text("# Nested\nEvidence: caf\u00e9.", encoding="utf-8-sig")
    (nested / "ignored.csv").write_text("not indexed", encoding="utf-8")
    chunks = document_rag.load_chunks(settings.documents_path)
    matching = [chunk for chunk in chunks if chunk.metadata["source"] == "nested/guide.MD"]
    assert len(matching) == 1
    assert matching[0].metadata["title"] == "Nested"
    assert "caf\u00e9" in matching[0].page_content
    assert not any(chunk.metadata["source"].endswith(".csv") for chunk in chunks)


def test_ingestion_handles_multiple_batches(corpus):
    settings, embeddings = corpus
    for number in range(70):
        (settings.documents_path / f"file-{number}.txt").write_text(
            f"database document {number}", encoding="utf-8",
        )
    summary = document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    assert summary["documents"] == 72
    assert len(store.get(include=[])["ids"]) == summary["chunks"]


def test_title_changes_refresh_all_chunk_metadata(corpus):
    settings, embeddings = corpus
    document_rag.ingest_documents(settings, embeddings)
    path = settings.documents_path / "async.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("Async guide", "Fresh guide"),
        encoding="utf-8",
    )
    document_rag.ingest_documents(settings, embeddings)
    stored = document_rag.get_vector_store(settings, embeddings).get()
    for metadata in stored["metadatas"]:
        if metadata["source"] == "async.md":
            assert metadata["title"] == "Fresh guide"
