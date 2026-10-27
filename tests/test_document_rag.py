"""Offline PDF ingestion tests: mocked page extraction and real temporary Chroma."""

from math import sqrt
from unittest.mock import Mock

import pytest
from langchain_core.embeddings import Embeddings
from pypdf.errors import PdfReadError

from app.config import Settings
from app.services import document_rag


class FakeEmbeddings(Embeddings):
    def __init__(self):
        self.document_calls = 0

    def embed_documents(self, texts):
        self.document_calls += len(texts)
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        vector = [text.lower().count("consensus"), text.lower().count("storage"), 1]
        length = sqrt(sum(value * value for value in vector))
        return [value / length for value in vector]


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    root.mkdir()
    pages = {
        "raft.pdf": ["consensus leader election. " * 60, "consensus log replication."],
        "gfs.pdf": ["storage chunks and replicas."],
    }
    for filename in pages:
        (root / filename).write_bytes(b"PDF placeholder; extraction is mocked")

    def read_pdf(path):
        relative = path.relative_to(root).as_posix()
        return Mock(is_encrypted=False, pages=[
            Mock(extract_text=Mock(return_value=text)) for text in pages[relative]
        ])

    def forbid_model_loading(*args, **kwargs):
        pytest.fail("Offline tests must not download an embedding model")

    reader = Mock(side_effect=read_pdf)
    monkeypatch.setattr(document_rag, "PdfReader", reader)
    monkeypatch.setattr(document_rag, "get_embeddings", forbid_model_loading)
    settings = Settings(
        _env_file=None, corpus_dir=root, chroma_persist_dir=tmp_path / "index",
        embedding_model="offline-test", retrieval_top_k=1,
    )
    return settings, FakeEmbeddings(), pages, reader


def test_chunks_preserve_paper_page_and_content(corpus):
    settings, _, pages, _ = corpus
    chunks = document_rag.load_chunks(settings.documents_path)
    assert len(chunks) > 3
    assert len({chunk.metadata["chunk_id"] for chunk in chunks}) == len(chunks)
    for chunk in chunks:
        metadata = chunk.metadata
        original = pages[metadata["source"]][metadata["page"] - 1]
        start = metadata["start_index"]
        assert original[start:start + len(chunk.page_content)] == chunk.page_content
        assert len(chunk.page_content) <= 800
        assert metadata["source_kind"] == "document"
        assert metadata["document_id"] == f"document:{metadata['source']}"
        assert f":p{metadata['page']}:c" in metadata["chunk_id"]


def test_blank_pages_keep_original_page_numbers(corpus):
    settings, _, pages, _ = corpus
    pages["raft.pdf"] = [None, "  ", "consensus evidence on page three"]
    chunks = document_rag.load_chunks(settings.documents_path)
    raft = [chunk for chunk in chunks if chunk.metadata["source"] == "raft.pdf"]
    assert len(raft) == 1
    assert raft[0].metadata["page"] == 3


def test_nested_pdf_and_other_files(corpus):
    settings, _, pages, _ = corpus
    nested = settings.documents_path / "papers"
    nested.mkdir()
    (nested / "Borg.PDF").write_bytes(b"placeholder")
    (nested / "notes.txt").write_text("Not part of this PDF corpus")
    pages["papers/Borg.PDF"] = ["Cluster management evidence"]
    chunks = document_rag.load_chunks(settings.documents_path)
    borg = [chunk for chunk in chunks if chunk.metadata["source"] == "papers/Borg.PDF"]
    assert len(borg) == 1
    assert borg[0].metadata["title"] == "Borg"
    assert not any(chunk.metadata["source"].endswith(".txt") for chunk in chunks)


def test_retrieval_preserves_citation_metadata(corpus):
    settings, embeddings, _, _ = corpus
    document_rag.ingest_documents(settings, embeddings)
    result = document_rag.retrieve_documents("consensus", settings, embeddings)
    assert len(result) == 1
    assert result[0].metadata["source"] == "raft.pdf"
    assert result[0].metadata["page"] in (1, 2)
    assert result[0].metadata["chunk_id"]
    assert "consensus" in result[0].page_content


def test_manual_reingestion_reembeds_every_chunk(corpus):
    settings, embeddings, _, _ = corpus
    first = document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    before = store.get()
    calls = embeddings.document_calls
    second = document_rag.ingest_documents(settings, embeddings)
    assert second == first
    assert store.get() == before
    assert embeddings.document_calls == calls + first["chunks"]


def test_edits_and_removed_papers_replace_old_evidence(corpus):
    settings, embeddings, pages, _ = corpus
    document_rag.ingest_documents(settings, embeddings)
    pages["raft.pdf"] = ["consensus revised findings"]
    (settings.documents_path / "gfs.pdf").unlink()
    summary = document_rag.ingest_documents(settings, embeddings)
    stored = document_rag.get_vector_store(settings, embeddings).get()
    assert summary["documents"] == summary["chunks"] == 1
    assert stored["documents"] == ["consensus revised findings"]
    assert stored["metadatas"][0]["source"] == "raft.pdf"
    assert stored["metadatas"][0]["page"] == 1


@pytest.mark.parametrize("failure", ["empty_corpus", "no_text", "encrypted", "corrupt", "embedding"])
def test_failed_ingestion_preserves_existing_evidence(corpus, monkeypatch, failure):
    settings, embeddings, pages, reader = corpus
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    before = store.get()
    if failure == "empty_corpus":
        for path in settings.documents_path.iterdir():
            path.unlink()
        error = ValueError
    elif failure == "no_text":
        pages["raft.pdf"] = [None, "  "]
        error = ValueError
    elif failure == "encrypted":
        reader.side_effect = None
        reader.return_value = Mock(is_encrypted=True, decrypt=Mock(return_value=0))
        error = ValueError
    elif failure == "corrupt":
        reader.side_effect = PdfReadError("Broken PDF")
        error = PdfReadError
    else:
        monkeypatch.setattr(embeddings, "embed_documents", Mock(side_effect=RuntimeError("Embedding failed")))
        error = RuntimeError
    with pytest.raises(error):
        document_rag.ingest_documents(settings, embeddings)
    assert store.get() == before


def test_later_embedding_failure_happens_before_index_writes(corpus, monkeypatch):
    settings, embeddings, pages, _ = corpus
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    before = store.get()
    pages["raft.pdf"] = ["consensus evidence"] * 70
    embed = Mock(side_effect=[[[1.0, 0.0, 0.0]] * 64, RuntimeError("Embedding failed")])
    monkeypatch.setattr(embeddings, "embed_documents", embed)
    with pytest.raises(RuntimeError, match="Embedding failed"):
        document_rag.ingest_documents(settings, embeddings)
    assert embed.call_count == 2
    assert store.get() == before


def test_missing_corpus_and_index(corpus):
    settings, embeddings, _, _ = corpus
    with pytest.raises(ValueError, match="does not exist"):
        document_rag.load_chunks(settings.documents_path / "missing")
    with pytest.raises(ValueError, match="missing"):
        document_rag.retrieve_documents("consensus", settings, embeddings)


@pytest.mark.parametrize("query", ["", "  \n"])
def test_empty_query_does_not_create_index(corpus, query):
    settings, embeddings, _, _ = corpus
    with pytest.raises(ValueError, match="empty"):
        document_rag.retrieve_documents(query, settings, embeddings)
    assert not settings.chroma_path.exists()


def test_embedding_model_mismatch_is_rejected(corpus):
    settings, embeddings, _, _ = corpus
    document_rag.ingest_documents(settings, embeddings)
    other = settings.model_copy(update={"embedding_model": "different-model"})
    with pytest.raises(ValueError, match="differs"):
        document_rag.retrieve_documents("consensus", other, embeddings)
    with pytest.raises(ValueError, match="differs"):
        document_rag.ingest_documents(other, embeddings)


def test_empty_password_encryption_is_readable(corpus):
    settings, _, _, reader = corpus
    reader.side_effect = None
    reader.return_value = Mock(
        is_encrypted=True, decrypt=Mock(return_value=1),
        pages=[Mock(extract_text=Mock(return_value="consensus paper text"))],
    )
    chunks = document_rag.load_chunks(settings.documents_path)
    assert len(chunks) == 2
    assert all(chunk.metadata["page"] == 1 for chunk in chunks)
    reader.return_value.decrypt.assert_called_with("")


@pytest.mark.parametrize("case", ["same_page", "next_page", "blank_page", "end_of_paper"])
def test_continuation_preserves_page_boundaries_and_citations(corpus, monkeypatch, case):
    settings, embeddings, pages, _ = corpus
    if case == "same_page":
        pages["raft.pdf"] = ["consensus evidence. " * 150, "Later page evidence"]
    elif case == "next_page":
        pages["raft.pdf"] = ["First page evidence", "Second page continuation"]
    elif case == "blank_page":
        pages["raft.pdf"] = ["First page evidence", " ", "Do not skip to page three"]
    else:
        pages["raft.pdf"] = ["Final page evidence"]
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    chunks = document_rag.load_chunks(settings.documents_path)
    seed = next(chunk for chunk in chunks if chunk.metadata["chunk_id"] == "raft.pdf:p1:c1")
    retriever = Mock()
    retriever.invoke.return_value = [seed]
    monkeypatch.setattr(store, "as_retriever", Mock(return_value=retriever))
    monkeypatch.setattr(document_rag, "get_vector_store", lambda *args: store)
    result = document_rag.retrieve_documents("consensus", settings, embeddings)
    assert result[0] == seed
    store.as_retriever.assert_called_once_with(search_kwargs={"k": 1})
    if case in ("same_page", "next_page"):
        expected_id = "raft.pdf:p1:c2" if case == "same_page" else "raft.pdf:p2:c1"
        expected = next(chunk for chunk in chunks if chunk.metadata["chunk_id"] == expected_id)
        assert len(result) == 2
        assert result[1].page_content == expected.page_content
        assert result[1].metadata == expected.metadata
    else:
        assert result == [seed]
    assert all(chunk.metadata["source"] == "raft.pdf" for chunk in result)


def test_existing_continuation_is_not_duplicated(corpus, monkeypatch):
    settings, embeddings, pages, _ = corpus
    pages["raft.pdf"] = ["First page", "Next page"]
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    seeds = [chunk for chunk in document_rag.load_chunks(settings.documents_path)
             if chunk.metadata["source"] == "raft.pdf"]
    monkeypatch.setattr(store, "as_retriever", Mock(return_value=Mock(invoke=Mock(return_value=seeds))))
    monkeypatch.setattr(document_rag, "get_vector_store", lambda *args: store)
    result = document_rag.retrieve_documents("consensus", settings.model_copy(update={"retrieval_top_k": 2}), embeddings)
    assert [chunk.metadata["chunk_id"] for chunk in result] == ["raft.pdf:p1:c1", "raft.pdf:p2:c1"]


def test_ranked_matches_stay_first_and_expansion_is_not_recursive(corpus, monkeypatch):
    settings, embeddings, pages, _ = corpus
    pages["raft.pdf"] = ["consensus evidence. " * 250]
    document_rag.ingest_documents(settings, embeddings)
    store = document_rag.get_vector_store(settings, embeddings)
    chunks = {chunk.metadata["chunk_id"]: chunk
              for chunk in document_rag.load_chunks(settings.documents_path)}
    seeds = [chunks["raft.pdf:p1:c3"], chunks["raft.pdf:p1:c1"]]
    monkeypatch.setattr(store, "as_retriever", Mock(return_value=Mock(invoke=Mock(return_value=seeds))))
    monkeypatch.setattr(document_rag, "get_vector_store", lambda *args: store)
    settings = settings.model_copy(update={"retrieval_top_k": 2})
    result = document_rag.retrieve_documents("consensus", settings, embeddings)
    ids = [chunk.metadata["chunk_id"] for chunk in result]
    assert ids == ["raft.pdf:p1:c3", "raft.pdf:p1:c1", "raft.pdf:p1:c4", "raft.pdf:p1:c2"]
    assert "raft.pdf:p1:c5" in chunks and "raft.pdf:p1:c5" not in ids
    assert len(result) == 2 * settings.retrieval_top_k
    assert len(ids) == len(set(ids))
