import asyncio
import json
from collections import defaultdict
from pathlib import Path

from loguru import logger

from core.exceptions import OzonApiError
from core.logger import setup_logger
from core.settings import settings
from models.search import SearchResult
from services.ozon_client import OzonSearchClient
from services.sheets_client import SheetsClient
from services.positions_sheet import read_search_tasks, insert_results_column


def get_sheets() -> list[tuple[str, Path, str, str]]:
    """Возвращает список (название, cookies_path, spreadsheet_id, company_id) для каждой таблицы в sheets/.
    Таблицы с segments.json пропускаются здесь — они обрабатываются отдельно через get_segmented_sheets."""
    result = []
    if not settings.sheets_dir.exists():
        return result
    for sheet_dir in sorted(settings.sheets_dir.iterdir()):
        if not sheet_dir.is_dir():
            continue
        if (sheet_dir / "segments.json").exists():
            continue  # обрабатывается через get_segmented_sheets
        spread_id_file = sheet_dir / "spread_id.txt"
        cookies_file = sheet_dir / "cookies.json"
        company_id_file = sheet_dir / "company_id.txt"
        if not spread_id_file.exists() or not cookies_file.exists() or not company_id_file.exists():
            logger.warning(f"Skipping '{sheet_dir.name}': missing spread_id.txt, cookies.json or company_id.txt")
            continue
        spread_id = spread_id_file.read_text().strip()
        company_id = company_id_file.read_text().strip()
        result.append((sheet_dir.name, cookies_file, spread_id, company_id))
    return result


def get_segmented_sheets() -> list[tuple[str, str, list[dict]]]:
    """Возвращает список (название, spreadsheet_id, segments) для таблиц с segments.json.
    Каждый сегмент: {company_id, cookies, start_row, end_row (опционально)}."""
    result = []
    if not settings.sheets_dir.exists():
        return result
    for sheet_dir in sorted(settings.sheets_dir.iterdir()):
        if not sheet_dir.is_dir():
            continue
        segments_file = sheet_dir / "segments.json"
        spread_id_file = sheet_dir / "spread_id.txt"
        if not segments_file.exists() or not spread_id_file.exists():
            continue
        spread_id = spread_id_file.read_text().strip()
        segments = json.loads(segments_file.read_text())
        # Резолвим пути к cookies относительно папки таблицы
        for seg in segments:
            seg["cookies_path"] = sheet_dir / seg.get("cookies", "cookies.json")
        result.append((sheet_dir.name, spread_id, segments))
    return result


async def process_sheet(name: str, cookies_path: Path, spreadsheet_id: str, company_id: str) -> None:
    logger.info(f"=== Processing sheet '{name}' ===")

    sheets = SheetsClient(settings.google_credentials_path, spreadsheet_id)
    ws = sheets.get_worksheet("Позиции")

    tasks = read_search_tasks(ws)

    query_to_items: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        query_to_items[task.query].append(task.item_id)
    logger.info(f"Unique queries to fetch: {len(query_to_items)}")

    positions: dict[str, dict[str, int]] = {}

    async with OzonSearchClient(
        company_id=company_id,
        cookies_path=cookies_path,
        proxy_path=settings.proxy_path,
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
    logger.info(f"=== Done sheet '{name}' ===")


async def process_segmented_sheet(sheet_name: str, spreadsheet_id: str, segments: list[dict]) -> None:
    """Обрабатывает таблицу с несколькими сегментами (магазинами) на одном листе."""
    logger.info(f"=== Processing segmented sheet '{sheet_name}' ({len(segments)} segments) ===")

    sheets_client = SheetsClient(settings.google_credentials_path, spreadsheet_id)
    ws = sheets_client.get_worksheet("Позиции")

    all_results: list[SearchResult] = []

    for i, seg in enumerate(segments, 1):
        company_id = seg["company_id"]
        cookies_path: Path = seg["cookies_path"]
        start_row = seg.get("start_row", 1)
        end_row = seg.get("end_row")
        row_range = (start_row, end_row) if end_row else (start_row, 999999)

        logger.info(f"  Segment #{i} rows {start_row}-{end_row or 'end'}")

        tasks = read_search_tasks(ws, row_range=row_range)
        if not tasks:
            logger.warning(f"  Segment #{i}: no tasks found")
            continue

        query_to_items: dict[str, list[str]] = defaultdict(list)
        for task in tasks:
            query_to_items[task.query].append(task.item_id)

        positions: dict[str, dict[str, int]] = {}
        async with OzonSearchClient(
            company_id=company_id,
            cookies_path=cookies_path,
            proxy_path=settings.proxy_path,
        ) as client:
            for i, (query, item_ids) in enumerate(query_to_items.items()):
                if i > 0:
                    await asyncio.sleep(2)
                try:
                    positions[query] = await client.get_search_positions(query=query, item_ids=item_ids)
                except OzonApiError as e:
                    logger.error(f"Skipping query={query!r}: {e}")
                    positions[query] = {}

        for task in tasks:
            pos = positions.get(task.query, {}).get(task.item_id)
            all_results.append(SearchResult(task=task, position=pos))

    insert_results_column(ws, all_results)
    logger.info(f"=== Done segmented sheet '{sheet_name}' ===")


async def main() -> None:
    setup_logger()
    logger.info("=== Starting position check ===")

    sheets = get_sheets()
    segmented = get_segmented_sheets()

    if not sheets and not segmented:
        logger.error(f"No sheets found in '{settings.sheets_dir}'")
        return

    for name, cookies_path, spreadsheet_id, company_id in sheets:
        try:
            await process_sheet(name, cookies_path, spreadsheet_id, company_id)
        except Exception as e:
            logger.error(f"Failed to process sheet '{name}': {e}")

    for name, spreadsheet_id, segments in segmented:
        try:
            await process_segmented_sheet(name, spreadsheet_id, segments)
        except Exception as e:
            logger.error(f"Failed to process segmented sheet '{name}': {e}")


if __name__ == "__main__":
    asyncio.run(main())
