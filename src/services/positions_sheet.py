from datetime import datetime

import gspread
from loguru import logger

from models.search import SearchResult, SearchTask


def read_search_tasks(ws: gspread.Worksheet) -> list[SearchTask]:
    logger.debug(f"Reading search tasks from sheet '{ws.title}'")
    rows = ws.get_all_values()
    tasks: list[SearchTask] = []
    current_item_id: str = ""

    for i, row in enumerate(rows):
        row_num = i + 1
        col_a = row[0].strip() if row else ""
        col_c = row[2].strip() if len(row) > 2 else ""

        if col_a == "Артикул":
            continue

        if col_a:
            current_item_id = col_a
            logger.debug(f"Row {row_num}: item_id={current_item_id} name={col_c!r}")
            continue

        if current_item_id and col_c:
            tasks.append(SearchTask(item_id=current_item_id, query=col_c, row=row_num))
            logger.debug(f"Row {row_num}: task item_id={current_item_id} query={col_c!r}")

    logger.info(f"Loaded {len(tasks)} search tasks from sheet '{ws.title}'")
    return tasks


def _insert_daily_summary(ws: gspread.Worksheet, rows: list[list[str]], day_label: str, col_indices: list[int]) -> None:
    """Вставляет колонку с итогами дня перед текущей колонкой D (startIndex=3)."""
    logger.info(f"Inserting daily summary for {day_label}")

    ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
        "inheritFromBefore": False,
    }}]})

    col = 4
    ws.update_cell(1, col, f"Итоги {day_label}")

    updates = []
    for row_i, row in enumerate(rows):
        row_num = row_i + 1
        if row_num == 1:
            continue
        vals = []
        has_1000 = False
        for ci in col_indices:
            v = row[ci].strip() if ci < len(row) else ""
            if v == "1000+":
                has_1000 = True
            elif v:
                try:
                    vals.append(int(v))
                except ValueError:
                    pass
        if vals:
            avg = round(sum(vals) / len(vals))
            updates.append({"range": gspread.utils.rowcol_to_a1(row_num, col), "values": [[avg]]})
        elif has_1000:
            updates.append({"range": gspread.utils.rowcol_to_a1(row_num, col), "values": [["1000+"]]})

    if updates:
        ws.batch_update(updates)
    logger.info(f"Daily summary '{day_label}' written with {len(updates)} values")


def _maybe_insert_daily_summary(ws: gspread.Worksheet) -> None:
    """Проверяет нужно ли подвести итоги за прошлый день и делает это."""
    rows = ws.get_all_values()
    header = rows[0]

    today = datetime.now().strftime("%d.%m")

    # Собираем все даты снимков начиная с D (индекс 3)
    # Формат заголовка: "14.03 19:47" или "Итоги 14.03"
    snapshot_cols: dict[str, list[int]] = {}  # day -> [col_indices]
    for i, h in enumerate(header[3:], start=3):
        if not h or h.startswith("Итоги"):
            continue
        parts = h.split(" ")
        if len(parts) == 2:
            day = parts[0]
            snapshot_cols.setdefault(day, []).append(i)

    # Ищем дни у которых нет итоговой колонки и которые не сегодня
    days_with_summary = {
        h.replace("Итоги ", "").strip()
        for h in header
        if h.startswith("Итоги ")
    }

    for day, col_indices in snapshot_cols.items():
        if day != today and day not in days_with_summary:
            _insert_daily_summary(ws, rows, day, col_indices)
            # После вставки колонки индексы сдвигаются — перечитывать не нужно,
            # т.к. итоги всегда вставляются в D и не влияют на уже обработанные дни
            # (но на практике обычно один день за раз)


def insert_results_column(ws: gspread.Worksheet, results: list[SearchResult]) -> None:
    # Сначала проверяем нужно ли подвести итоги за прошлый день
    _maybe_insert_daily_summary(ws)

    logger.info(f"Inserting new column D into sheet '{ws.title}' with {len(results)} results")

    ws.spreadsheet.batch_update({
        "requests": [{
            "insertDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 3,
                    "endIndex": 4,
                },
                "inheritFromBefore": False,
            }
        }]
    })
    logger.debug("Column D inserted, writing header and values")

    col = 4
    header = datetime.now().strftime("%d.%m %H:%M")
    ws.update_cell(1, col, header)
    logger.debug(f"Header set to '{header}'")

    updates = []
    for result in results:
        value = result.position if result.position else "1000+"
        updates.append({"range": gspread.utils.rowcol_to_a1(result.task.row, col), "values": [[value]]})

    if updates:
        ws.batch_update(updates)
        logger.info(f"Written {len(updates)} position values to column D")
