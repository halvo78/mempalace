import os
from mempalace.backends.base import PalaceRef
from mempalace.backends.qdrant import QdrantBackend
from mempalace.embedding import get_embedding_function

# Check embedding function
ef = get_embedding_function(device="lmstudio")
print("LM Studio Embedder:", ef)

# Check Qdrant
backend = QdrantBackend()
print("Qdrant Backend:", backend)
try:
    palace_ref = PalaceRef(id="test_empire_palace")
    # Will fail if qdrant is not running locally, but we can catch it
    col = backend.get_collection(palace=palace_ref, collection_name="test_col", create=True)
    print("Qdrant Collection:", col)
except Exception as e:
    print("Qdrant connection exception (expected if offline):", type(e).__name__)

print("Success")
