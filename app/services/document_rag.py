"""Ingest a UTF-8 text/Markdown corpus into Chroma and retrieve source chunks.

Run ingestion explicitly with: python -m app.services.document_rag
The configured collection belongs to this corpus. Run ingestion while requests
are stopped: synchronization is repeatable, but is not an atomic index swap.
"""

from functools import lru_cache
from hashlib import sha256
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings, get_settings


def load_chunks(corpus_path: Path) -> list[Document]:
    """Split supported files into 800-character chunks with 120 overlap.

    Source paths are relative to the corpus, so citations survive deployment.
    Chunk IDs depend on source path, title, character offset, and content. Re-ingesting
    unchanged files therefore preserves IDs; edited chunks get new IDs.
    """
    if not corpus_path.is_dir():
        raise ValueError(f"Corpus directory does not exist: {corpus_path}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=120, add_start_index=True,
    )
    chunks = []
    for path in sorted(corpus_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".md", ".txt"):
            continue
        text = path.read_text(encoding="utf-8-sig")
        if not text.strip():
            continue
        source = path.relative_to(corpus_path).as_posix()
        title = next(
            (line.lstrip("# ").strip() for line in text.splitlines()
             if line.startswith("# ") and line[2:].strip()),
            path.stem,
        )
        document = Document(page_content=text, metadata={
            "source": source,
            "title": title,
            "document_id": "doc-" + sha256(source.encode()).hexdigest(),
            "source_kind": "document",
        })
        for chunk in splitter.split_documents([document]):
            identity = (
                f"{source}\n{title}\n{chunk.metadata['start_index']}\n{chunk.page_content}"
            )
            chunk.metadata["chunk_id"] = "chunk-" + sha256(identity.encode()).hexdigest()
            chunks.append(chunk)

    if not chunks:
        raise ValueError("Corpus contains no nonempty UTF-8 .md or .txt documents")
    return chunks


@lru_cache(maxsize=1)
def get_embeddings(model_name: str) -> HuggingFaceEmbeddings:
    """Load the local CPU model on first use; reuse it for later requests."""
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vector_store(
    settings: Settings,
    embeddings: Embeddings | None = None,
    *,
    create: bool = False,
) -> Chroma:
    """Open the configured collection, rejecting incompatible embedding models.

    Only explicit ingestion may create an index. Inject embeddings for offline
    tests; normal application calls use the configured local model.
    """
    if not create and not settings.chroma_path.is_dir():
        raise ValueError("Document index is missing; run document ingestion first")
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    if create:
        collection = client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"embedding_model": settings.embedding_model},
        )
    else:
        collection = client.get_collection(name=settings.chroma_collection)
    if (collection.metadata or {}).get("embedding_model") != settings.embedding_model:
        raise ValueError("Embedding model differs from index; use a new collection name")
    if not create and collection.count() == 0:
        raise ValueError("Document index is empty; run document ingestion first")

    return Chroma(
        client=client,
        collection_name=settings.chroma_collection,
        embedding_function=embeddings if embeddings is not None else get_embeddings(
            settings.embedding_model,
        ),
        create_collection_if_not_exists=False,
    )


def ingest_documents(
    settings: Settings | None = None,
    embeddings: Embeddings | None = None,
) -> dict[str, int]:
    """Synchronize the dedicated collection with the complete configured corpus.

    Add new/changed chunks in batches, skip unchanged IDs, then remove obsolete
    chunks. Loading failures or an empty corpus never clear the existing index.
    Failed writes propagate; rerun ingestion to finish an interrupted sync.
    """
    settings = settings or get_settings()
    chunks = load_chunks(settings.documents_path)
    store = get_vector_store(settings, embeddings, create=True)
    existing_ids = set(store.get(include=[])["ids"])
    current_ids = {chunk.metadata["chunk_id"] for chunk in chunks}
    new_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_id"] not in existing_ids]

    for start in range(0, len(new_chunks), 64):
        batch = new_chunks[start:start + 64]
        store.add_documents(batch, ids=[chunk.metadata["chunk_id"] for chunk in batch])

    obsolete_ids = sorted(existing_ids - current_ids)
    for start in range(0, len(obsolete_ids), 64):
        store.delete(ids=obsolete_ids[start:start + 64])
    return {
        "documents": len({chunk.metadata["document_id"] for chunk in chunks}),
        "chunks": len(chunks),
        "added_chunks": len(new_chunks),
        "removed_chunks": len(obsolete_ids),
    }


def retrieve_documents(
    query: str,
    settings: Settings | None = None,
    embeddings: Embeddings | None = None,
) -> list[Document]:
    """Return top-k similar chunks with citation metadata via a LangChain retriever.

    Similarity ranks candidates; it does not guarantee they answer the question.
    Retrieval never falls back to web search or silently builds a missing index.
    """
    if not query.strip():
        raise ValueError("Document query cannot be empty")
    settings = settings or get_settings()
    store = get_vector_store(settings, embeddings)
    retriever = store.as_retriever(search_kwargs={"k": settings.retrieval_top_k})
    return retriever.invoke(query)


if __name__ == "__main__":
    print(ingest_documents())
