from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    ts: datetime  # timezone-aware
    kind: str
