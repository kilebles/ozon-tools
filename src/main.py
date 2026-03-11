import asyncio
from collections import defaultdict

from loguru import logger

from core.exceptions import OzonApiError
from core.logger import setup_logger
from core.settings import settings
from models.search import SearchResult
from services.ozon_client import OzonSearchClient
from services.sheets_client import SheetsClient
from services.positions_sheet import read_search_tasks, insert_results_column


async def main() -> None:
    setup_logger()
    logger.info("=== Starting position check ===")

    logger.info("Connecting to Google Sheets")
    sheets = SheetsClient(settings.google_credentials_path, settings.spreadsheet_id)
    ws = sheets.get_worksheet("Позиции")

    tasks = read_search_tasks(ws)

    query_to_items: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        query_to_items[task.query].append(task.item_id)
    logger.info(f"Unique queries to fetch: {len(query_to_items)}")

    positions: dict[str, dict[str, int]] = {}

    async with OzonSearchClient(
        company_id=settings.company_id,
        cookies_path=settings.cookies_path,
    ) as client:
        for i, (query, item_ids) in enumerate(query_to_items.items()):
            if i > 0:
                await asyncio.sleep(2)
            try:
                positions[query] = await client.get_search_positions(query=query, item_ids=item_ids)
            except OzonApiError as e:
                logger.error(f"Skipping query={query!r}: {e}")
                positions[query] = {}

    results: list[SearchResult] = []
    for task in tasks:
        pos = positions.get(task.query, {}).get(task.item_id)
        results.append(SearchResult(task=task, position=pos))

    insert_results_column(ws, results)
    logger.info("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
