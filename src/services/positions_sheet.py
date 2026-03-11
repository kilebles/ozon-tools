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


def insert_results_column(ws: gspread.Worksheet, results: list[SearchResult]) -> None:
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
