"""Extension contract only; no extra provider is registered or selected at runtime."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Literal

@dataclass(frozen=True)
class Segment:
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None

@dataclass(frozen=True)
class PollResult:
    status: Literal['pending', 'failed', 'completed']
    segments: tuple[Segment, ...] = ()

class TranscriptionProvider(Protocol):
    provider_id: str
    adapter_version: str
    def submit(self, audio: Path) -> str:
        """Return task ID; credentials are session-only, unknown POST is not retried."""
        ...
    def poll(self, task_id: str) -> PollResult:
        """Query only; never submit a new job or persist transport secrets."""
        ...
    def close(self) -> None:
        """Release session credential references; not a guarantee of memory zeroing."""
        ...
