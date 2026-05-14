"""Source adapter for macOS iMessage (chat.db)."""

import os
import sqlite3
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


class IMessageSourceAdapter(BaseSourceAdapter):
    name = "imessage"
    adapter_version = "1.0.0"

    def ingest(
        self,
        *,
        source: SourceRef,
        palace,
    ) -> Iterator[IngestResult]:
        # Path to macOS chat database
        db_path = Path("~/Library/Messages/chat.db").expanduser()
        if not db_path.exists():
            return

        # Connect to DB (requires Full Disk Access in modern macOS)
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            
            # Query last 1000 messages (as a sample/starting point)
            query = """
            SELECT 
                m.text, 
                h.id as handle, 
                m.date, 
                m.is_from_me
            FROM message m
            JOIN handle h ON m.handle_id = h.rowid
            WHERE m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT 1000
            """
            cursor.execute(query)
            
            for text, handle, date, is_from_me in cursor.fetchall():
                # Core logic: filter out short messages/noise
                if len(text) < 10:
                    continue
                
                who = "Me" if is_from_me else handle
                content = f"[{who}] {text}"
                
                yield DrawerRecord(
                    content=content,
                    source_file=str(db_path),
                    metadata={
                        "handle": handle,
                        "is_from_me": bool(is_from_me),
                        "timestamp": date,
                    },
                    route_hint=RouteHint(wing=f"wing_imessage_{handle.replace('+', '').replace('@', '_')}", room="room_chat"),
                )
                
            conn.close()
        except sqlite3.OperationalError as e:
            # Likely permission error
            print(f"iMessage access error: {e}. Ensure Full Disk Access is granted to terminal.")
            return

    def describe_schema(self) -> AdapterSchema:
        return AdapterSchema(
            version="1.0.0",
            fields={
                "handle": FieldSpec(type="string", required=True, description="The phone number or email of the sender"),
                "is_from_me": FieldSpec(type="bool", required=True, description="Whether I sent the message"),
                "timestamp": FieldSpec(type="int", required=True, description="Internal Apple timestamp"),
            },
        )
