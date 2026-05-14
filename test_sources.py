from mempalace.sources.nlm_brain import NlmBrainSourceAdapter
from mempalace.sources.imessage import IMessageSourceAdapter
from mempalace.sources.base import SourceRef

# Test NLM Brain
adapter = NlmBrainSourceAdapter()
print(f"Adapter: {adapter.name}")
try:
    for record in adapter.ingest(source=SourceRef(local_path="~/work/nlm-brain"), palace=None):
        print(f"Record: {record.metadata['type']} -> {record.content[:50]}...")
        break # Just one
except Exception as e:
    print(f"NLM Brain error: {e}")

# Test iMessage
adapter = IMessageSourceAdapter()
print(f"Adapter: {adapter.name}")
# Expect potential permission error if not granted, but the logic should load
try:
    for record in adapter.ingest(source=SourceRef(), palace=None):
        print(f"Record: iMessage -> {record.content[:50]}...")
        break # Just one
except Exception as e:
    print(f"iMessage error: {e}")

print("Success")
