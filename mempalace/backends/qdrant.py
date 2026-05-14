"""Qdrant-backed MemPalace storage backend."""

import os
import uuid
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
    PointStruct,
    MatchText,
)
from qdrant_client.http.exceptions import UnexpectedResponse

from .base import (
    BaseBackend,
    BaseCollection,
    GetResult,
    PalaceNotFoundError,
    PalaceRef,
    QueryResult,
    _IncludeSpec,
)


class QdrantCollection(BaseCollection):
    def __init__(self, client: QdrantClient, collection_name: str, embedder):
        self._client = client
        self.collection_name = collection_name
        self._embedder = embedder

    def add(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ) -> None:
        if embeddings is None:
            embeddings = self._embedder(documents)

        points = []
        for i, (doc, doc_id, emb) in enumerate(zip(documents, ids, embeddings)):
            meta = metadatas[i] if metadatas else {}
            meta["_document"] = doc
            # Qdrant requires UUID or uint64 for ID. MemPalace uses string IDs.
            point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, doc_id))
            meta["_original_id"] = doc_id
            points.append(PointStruct(id=point_id, vector=emb, payload=meta))

        self._client.upsert(collection_name=self.collection_name, points=points)

    def upsert(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ) -> None:
        self.add(documents=documents, ids=ids, metadatas=metadatas, embeddings=embeddings)

    def _build_filter(self, where: Optional[dict], where_document: Optional[dict]) -> Optional[Filter]:
        conditions = []
        if where:
            for k, v in where.items():
                if isinstance(v, dict):
                    # For operators like $eq
                    if "$eq" in v:
                        conditions.append(FieldCondition(key=k, match=MatchValue(value=v["$eq"])))
                else:
                    conditions.append(FieldCondition(key=k, match=MatchValue(value=v)))
        
        if where_document:
            for k, v in where_document.items():
                if "$contains" in v:
                    conditions.append(FieldCondition(key="_document", match=MatchText(text=v["$contains"])))
                    
        if conditions:
            return Filter(must=conditions)
        return None

    def query(
        self,
        *,
        query_texts: Optional[list[str]] = None,
        query_embeddings: Optional[list[list[float]]] = None,
        n_results: int = 10,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None,
        include: Optional[list[str]] = None,
    ) -> QueryResult:
        spec = _IncludeSpec.resolve(include)
        if query_embeddings is None and query_texts is not None:
            query_embeddings = self._embedder(query_texts)

        if not query_embeddings:
            return QueryResult.empty(num_queries=0, embeddings_requested=spec.embeddings)

        query_filter = self._build_filter(where, where_document)
        res = QueryResult.empty(num_queries=len(query_embeddings), embeddings_requested=spec.embeddings)

        for i, emb in enumerate(query_embeddings):
            hits = self._client.search(
                collection_name=self.collection_name,
                query_vector=emb,
                limit=n_results,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=spec.embeddings,
            )

            res.ids[i] = [hit.payload.get("_original_id", "") for hit in hits if hit.payload]
            if spec.documents:
                res.documents[i] = [hit.payload.get("_document", "") for hit in hits if hit.payload]
            if spec.metadatas:
                res.metadatas[i] = [
                    {k: v for k, v in hit.payload.items() if k not in ("_document", "_original_id")}
                    for hit in hits if hit.payload
                ]
            if spec.distances:
                # MemPalace distances: smaller is closer (e.g. 1 - cosine_similarity for cosine)
                # Qdrant with COSINE distance returns similarity (1 is exact match)
                res.distances[i] = [1.0 - hit.score for hit in hits]
            if spec.embeddings:
                res.embeddings[i] = [hit.vector for hit in hits]  # type: ignore

        return res

    def get(
        self,
        *,
        ids: Optional[list[str]] = None,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Optional[list[str]] = None,
    ) -> GetResult:
        spec = _IncludeSpec.resolve(include)
        query_filter = self._build_filter(where, where_document)

        if ids:
            points = self._client.retrieve(
                collection_name=self.collection_name,
                ids=[str(uuid.uuid5(uuid.NAMESPACE_OID, i)) for i in ids],
                with_payload=True,
                with_vectors=spec.embeddings,
            )
        else:
            points, _ = self._client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=limit or 100,
                offset=offset,
                with_payload=True,
                with_vectors=spec.embeddings,
            )

        res = GetResult.empty()
        res.ids.extend([p.payload.get("_original_id", "") for p in points if p.payload])
        if spec.documents:
            res.documents.extend([p.payload.get("_document", "") for p in points if p.payload])
        if spec.metadatas:
            res.metadatas.extend(
                [{k: v for k, v in p.payload.items() if k not in ("_document", "_original_id")} for p in points if p.payload]
            )
        if spec.embeddings:
            res.embeddings = [p.vector for p in points]  # type: ignore
        return res

    def delete(
        self,
        *,
        ids: Optional[list[str]] = None,
        where: Optional[dict] = None,
    ) -> None:
        if ids:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=[str(uuid.uuid5(uuid.NAMESPACE_OID, i)) for i in ids],
            )
        else:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=self._build_filter(where, None),
            )

    def count(self) -> int:
        return self._client.count(collection_name=self.collection_name).count


class QdrantBackend(BaseBackend):
    name = "qdrant"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            url = os.environ.get("QDRANT_URL", "http://localhost:6333")
            self._client = QdrantClient(url=url)
        return self._client

    def get_collection(
        self,
        *,
        palace: PalaceRef,
        collection_name: str,
        create: bool = False,
        options: Optional[dict] = None,
    ) -> BaseCollection:
        client = self._get_client()
        # Qdrant collection names are global; prefix with palace ID.
        # Make sure palace ID is a valid Qdrant name.
        safe_palace_id = palace.id.replace("-", "_").replace("/", "_")
        full_name = f"{safe_palace_id}_{collection_name}"

        try:
            client.get_collection(full_name)
        except (UnexpectedResponse, ValueError) as e:
            if not create:
                raise PalaceNotFoundError(f"Palace {palace.id} not found in Qdrant") from e

            # Get embedding size
            from ..embedding import get_embedding_function

            emb_fn = get_embedding_function()
            test_emb = emb_fn(["test"])
            size = len(test_emb[0])

            client.create_collection(
                collection_name=full_name,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )

        from ..embedding import get_embedding_function

        return QdrantCollection(client, full_name, get_embedding_function())

    @classmethod
    def detect(cls, path: str) -> bool:
        return False
