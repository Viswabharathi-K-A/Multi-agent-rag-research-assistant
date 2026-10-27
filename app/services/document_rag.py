"""Load local research PDFs, index their page chunks, and retrieve evidence.

Run ingestion explicitly: python -m app.services.document_rag
Run while requests are stopped; index writes are not an atomic swap.
"""

from functools import lru_cache
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import Settings, get_settings


def load_chunks(corpus_path: Path) -> list[Document]:
    """Split PDF pages into chunks, preserving filename and 1-based PDF page.

    Chunks stay within a page so citations have an unambiguous location. IDs use
    filename, page, and chunk position; no hashes or version tracking are needed.
    """
    if not corpus_path.is_dir():
        raise ValueError(f"Corpus directory does not exist: {corpus_path}")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=120, add_start_index=True,
    )
    chunks = []
    for path in sorted(corpus_path.rglob("*")):
        if (not path.is_file() or path.suffix.lower() != ".pdf" or path.is_symlink()
                or not path.resolve().is_relative_to(corpus_path.resolve())):
            continue
        source = path.relative_to(corpus_path).as_posix()
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError(f"PDF requires a password: {source}")
        previous_count = len(chunks)
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            document = Document(page_content=text, metadata={
                "source": source, "title": path.stem, "page": page_number,
                "document_id": f"document:{source}", "source_kind": "document",
            })
            for chunk_number, chunk in enumerate(splitter.split_documents([document]), start=1):
                chunk.metadata["chunk_id"] = f"{source}:p{page_number}:c{chunk_number}"
                chunks.append(chunk)
        if len(chunks) == previous_count:
            raise ValueError(f"PDF has no extractable text: {source}")
    if not chunks:
        raise ValueError("Corpus contains no usable PDF documents")
    return chunks


@lru_cache(maxsize=1)
def get_embeddings(model_name: str) -> HuggingFaceEmbeddings:
    """Lazily load and reuse the configured local CPU embedding model."""
    return HuggingFaceEmbeddings(
        model_name=model_name, model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vector_store(
    settings: Settings, embeddings: Embeddings | None = None, *, create: bool = False,
) -> Chroma:
    """Open the dedicated collection and reject mismatched embedding models."""
    if not create and not settings.chroma_path.is_dir():
        raise ValueError("Document index is missing; run document ingestion first")
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    if create:
        collection = client.get_or_create_collection(
            name=settings.chroma_collection, metadata={"embedding_model": settings.embedding_model},
        )
    else:
        collection = client.get_collection(name=settings.chroma_collection)
    if (collection.metadata or {}).get("embedding_model") != settings.embedding_model:
        raise ValueError("Embedding model differs from index; use a new collection name")
    if not create and collection.count() == 0:
        raise ValueError("Document index is empty; run document ingestion first")
    return Chroma(
        client=client, collection_name=settings.chroma_collection,
        embedding_function=embeddings if embeddings is not None else get_embeddings(settings.embedding_model),
        create_collection_if_not_exists=False,
    )


def ingest_documents(
    settings: Settings | None = None, embeddings: Embeddings | None = None,
) -> dict[str, int]:
    """Manually re-embed every chunk, overwrite current IDs, then remove stale IDs.

    All embeddings are prepared before index writes. No content hashes or change
    tracking are used. A failed write can leave a partial rebuild; rerun offline.
    """
    settings = settings or get_settings()
    chunks = load_chunks(settings.documents_path)
    store = get_vector_store(settings, embeddings, create=True)
    vectors = []
    for start in range(0, len(chunks), 64):
        batch = chunks[start:start + 64]
        batch_vectors = store.embeddings.embed_documents([chunk.page_content for chunk in batch])
        if len(batch_vectors) != len(batch):
            raise ValueError("Embedding count does not match source chunk count")
        vectors.extend(batch_vectors)
    collection = chromadb.PersistentClient(path=str(settings.chroma_path)).get_collection(settings.chroma_collection)
    old_ids = set(collection.get(include=[])["ids"])
    current_ids = {chunk.metadata["chunk_id"] for chunk in chunks}
    for start in range(0, len(chunks), 64):
        batch = chunks[start:start + 64]
        collection.upsert(
            ids=[chunk.metadata["chunk_id"] for chunk in batch],
            embeddings=vectors[start:start + 64],
            documents=[chunk.page_content for chunk in batch],
            metadatas=[chunk.metadata for chunk in batch],
        )
    obsolete_ids = sorted(old_ids - current_ids)
    for start in range(0, len(obsolete_ids), 64):
        collection.delete(ids=obsolete_ids[start:start + 64])
    return {
        "documents": len({chunk.metadata["document_id"] for chunk in chunks}),
        "chunks": len(chunks), "embedded_chunks": len(chunks), "removed_chunks": len(obsolete_ids),
    }


def retrieve_documents(
    query: str, settings: Settings | None = None, embeddings: Embeddings | None = None,
) -> list[Document]:
    """Retrieve top-k matches plus one continuation chunk per match.

    Prefer the next chunk on the same page. At page end, try the first chunk of
    the next PDF page in the same paper. Keep ranked matches first and deduplicate.
    At most 2*k chunks are returned, with original text and citation metadata.
    """
    if not query.strip():
        raise ValueError("Document query cannot be empty")
    settings = settings or get_settings()
    store = get_vector_store(settings, embeddings)
    matches = store.as_retriever(search_kwargs={"k": settings.retrieval_top_k}).invoke(query)
    seen = {chunk.metadata["chunk_id"] for chunk in matches}
    next_ids = []
    for chunk in matches:
        page_prefix, chunk_number = chunk.metadata["chunk_id"].rsplit(":c", 1)
        next_id = f"{page_prefix}:c{int(chunk_number) + 1}"
        if next_id not in seen:
            next_ids.append(next_id)
            seen.add(next_id)
    if next_ids:
        stored = store.get(ids=next_ids, include=["documents", "metadatas"])
        neighbors = {}
        for chunk_id, text, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"]):
            neighbors[chunk_id] = Document(id=chunk_id, page_content=text, metadata=metadata)
        next_pages = {}
        for chunk in matches:
            page_prefix, chunk_number = chunk.metadata["chunk_id"].rsplit(":c", 1)
            next_id = f"{page_prefix}:c{int(chunk_number) + 1}"
            if next_id in next_ids and next_id not in neighbors:
                metadata = chunk.metadata
                next_pages[next_id] = f"{metadata['source']}:p{metadata['page'] + 1}:c1"
        page_ids = list(set(next_pages.values()) - seen)
        if page_ids:
            stored = store.get(ids=page_ids, include=["documents", "metadatas"])
            for chunk_id, text, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"]):
                neighbors[chunk_id] = Document(id=chunk_id, page_content=text, metadata=metadata)
        seen = {chunk.metadata["chunk_id"] for chunk in matches}
        for next_id in next_ids:
            neighbor_id = next_id if next_id in neighbors else next_pages.get(next_id)
            if neighbor_id in neighbors and neighbor_id not in seen:
                matches.append(neighbors[neighbor_id])
                seen.add(neighbor_id)
    return matches


if __name__ == "__main__":
    print(ingest_documents())
