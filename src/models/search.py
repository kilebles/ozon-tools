from dataclasses import dataclass


@dataclass
class SearchTask:
    item_id: str
    query: str
    row: int  # 1-based row index in the sheet


@dataclass
class SearchResult:
    task: SearchTask
    position: int | None  # None if not found
