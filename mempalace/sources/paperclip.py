"""Source adapter for Paperclip (AI agent company orchestration)."""

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


class PaperclipSourceAdapter(BaseSourceAdapter):
    name = "paperclip"
    adapter_version = "1.0.0"

    def ingest(
        self,
        *,
        source: SourceRef,
        palace,
    ) -> Iterator[IngestResult]:
        # Path to Paperclip data
        base_path = Path(source.local_path or os.environ.get("PAPERCLIP_ROOT", "~/.paperclip")).expanduser()
        instance_path = base_path / "instances" / "default"
        
        # 1. Company and Agent Metadata
        companies_path = instance_path / "companies"
        if companies_path.exists():
            for company_dir in companies_path.iterdir():
                if not company_dir.is_dir():
                    continue
                
                company_id = company_dir.name
                agents_path = company_dir / "agents"
                if agents_path.exists():
                    for agent_dir in agents_path.iterdir():
                        if not agent_dir.is_dir():
                            continue
                        
                        agent_id = agent_dir.name
                        instr_file = agent_dir / "instructions" / "AGENTS.md"
                        if instr_file.exists():
                            content = instr_file.read_text()
                            yield DrawerRecord(
                                content=f"Agent {agent_id} Instructions:\n\n{content}",
                                source_file=str(instr_file),
                                metadata={
                                    "type": "agent_instructions",
                                    "company_id": company_id,
                                    "agent_id": agent_id,
                                },
                                route_hint=RouteHint(wing=f"wing_paperclip_{company_id}", room=f"room_agent_{agent_id}"),
                            )

        # 2. Run Logs (NDJSON)
        logs_path = instance_path / "data" / "run-logs"
        if logs_path.exists():
            # Run logs are deeply nested: run-logs/<company_id>/<agent_id>/<session_id>.ndjson
            for company_dir in logs_path.iterdir():
                if not company_dir.is_dir():
                    continue
                company_id = company_dir.name
                
                for agent_dir in company_dir.iterdir():
                    if not agent_dir.is_dir():
                        continue
                    agent_id = agent_dir.name
                    
                    for log_file in agent_dir.glob("*.ndjson"):
                        try:
                            with open(log_file, "r") as f:
                                for line in f:
                                    if not line.strip():
                                        continue
                                    entry = json.loads(line)
                                    if entry.get("stream") != "stdout":
                                        continue
                                    
                                    chunk_raw = entry.get("chunk")
                                    if not chunk_raw:
                                        continue
                                    
                                    chunk = json.loads(chunk_raw)
                                    msg = chunk.get("message", {})
                                    content_blocks = msg.get("content", [])
                                    
                                    for block in content_blocks:
                                        if block.get("type") == "thinking":
                                            thinking = block.get("thinking")
                                            if thinking:
                                                yield DrawerRecord(
                                                    content=f"Agent Thinking ({entry.get('ts')}):\n\n{thinking}",
                                                    source_file=str(log_file),
                                                    metadata={
                                                        "type": "agent_thinking",
                                                        "company_id": company_id,
                                                        "agent_id": agent_id,
                                                        "timestamp": entry.get("ts"),
                                                    },
                                                    route_hint=RouteHint(wing=f"wing_paperclip_{company_id}", room=f"room_reasoning"),
                                                )
                                        elif block.get("type") == "text":
                                            text = block.get("text")
                                            if text and len(text) > 50:
                                                yield DrawerRecord(
                                                    content=f"Agent Response ({entry.get('ts')}):\n\n{text}",
                                                    source_file=str(log_file),
                                                    metadata={
                                                        "type": "agent_response",
                                                        "company_id": company_id,
                                                        "agent_id": agent_id,
                                                        "timestamp": entry.get("ts"),
                                                    },
                                                    route_hint=RouteHint(wing=f"wing_paperclip_{company_id}", room=f"room_outputs"),
                                                )
                        except Exception as e:
                            # Skip malformed logs
                            continue

    def describe_schema(self) -> AdapterSchema:
        return AdapterSchema(
            version="1.0.0",
            fields={
                "type": FieldSpec(type="string", required=True, description="Type of paperclip data (instructions, thinking, response)"),
                "company_id": FieldSpec(type="string", required=True, description="The Paperclip company UUID"),
                "agent_id": FieldSpec(type="string", required=True, description="The Paperclip agent UUID"),
                "timestamp": FieldSpec(type="string", required=False, description="ISO timestamp of the event"),
            },
        )
