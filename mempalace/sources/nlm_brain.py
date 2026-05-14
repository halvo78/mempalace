"""Source adapter for nlm-brain (Empire Mind AI intelligence layer)."""

import json
import os
from pathlib import Path
from typing import Iterator

from .base import (
    AdapterSchema,
    BaseSourceAdapter,
    DrawerRecord,
    FieldSpec,
    IngestResult,
    RouteHint,
    SourceRef,
)


class NlmBrainSourceAdapter(BaseSourceAdapter):
    name = "nlm-brain"
    adapter_version = "1.0.0"

    def ingest(
        self,
        *,
        source: SourceRef,
        palace,
    ) -> Iterator[IngestResult]:
        # source.local_path should point to the nlm-brain root or the specific json file.
        path = Path(source.local_path or os.environ.get("NLM_BRAIN_ROOT", "~/work/nlm-brain")).expanduser()
        
        # 1. Selector Memory
        selector_json = path / ".nlm-selector-memory.json"
        if not selector_json.exists():
            # Fallback to home dir
            selector_json = Path("~/.nlm-selector-memory.json").expanduser()

        if selector_json.exists():
            with open(selector_json, "r") as f:
                cache = json.load(f)
                for key, data in cache.items():
                    if key.startswith("_fail:"):
                        selector = key[6:]
                        content = f"Selector Failure: {selector}\nErrors: {json.dumps(data['errors'])}\nCount: {data['count']}"
                        yield DrawerRecord(
                            content=content,
                            source_file=str(selector_json),
                            metadata={"type": "selector_failure", "selector": selector},
                            route_hint=RouteHint(wing="wing_nlm_brain", room="room_failures"),
                        )
                    else:
                        content = f"Selector Fix: {key} -> {data['fix']}\nConfidence: {data['confidence']}\nUses: {data['uses']}"
                        yield DrawerRecord(
                            content=content,
                            source_file=str(selector_json),
                            metadata={"type": "selector_fix", "original": key, "fix": data["fix"]},
                            route_hint=RouteHint(wing="wing_nlm_brain", room="room_fixes"),
                        )

        # 2. Knowledge Graph (if exported as JSON/Markdown)
        # Assuming nlm-brain can be instructed to export its KG.
        # For now, we'll look for any .md files in the nlm-brain root that look like KG exports.
        for md_file in path.glob("**/*.md"):
            if "Knowledge Graph" in md_file.read_text()[:500]:
                yield DrawerRecord(
                    content=md_file.read_text(),
                    source_file=str(md_file),
                    metadata={"type": "knowledge_graph"},
                    route_hint=RouteHint(wing="wing_nlm_brain", room="room_knowledge"),
                )

    def describe_schema(self) -> AdapterSchema:
        return AdapterSchema(
            version="1.0.0",
            fields={
                "type": FieldSpec(type="string", required=True, description="Type of brain data"),
                "selector": FieldSpec(type="string", required=False, description="The broken selector"),
                "fix": FieldSpec(type="string", required=False, description="The working fix"),
            },
        )
