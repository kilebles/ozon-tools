import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

router = Router()

SHEETS_DIR = Path("sheets")


class AddSheet(StatesGroup):
    name = State()
    spread_id = State()
    sheet_type = State()  # ожидаем выбор типа через кнопки
    company_id = State()
    cookies = State()


class AddSegment(StatesGroup):
    # sheet_name и next_start_row хранятся в data
    company_id = State()
    cookies = State()
    end_row = State()


def sheets_keyboard() -> InlineKeyboardMarkup:
    sheets = [d for d in SHEETS_DIR.iterdir() if d.is_dir()] if SHEETS_DIR.exists() else []
    buttons = []
    for sheet in sheets:
        is_segmented = (sheet / "segments.json").exists()
        label = f"{sheet.name} [сегменты]" if is_segmented else sheet.name
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"sheet:{sheet.name}"),
            InlineKeyboardButton(text="удалить", callback_data=f"delete:{sheet.name}"),
        ])
    buttons.append([InlineKeyboardButton(text="+ Добавить таблицу", callback_data="add_sheet")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def sheet_detail_keyboard(sheet_name: str) -> InlineKeyboardMarkup:
    sheet_dir = SHEETS_DIR / sheet_name
    segments_file = sheet_dir / "segments.json"
    buttons = []
    if segments_file.exists():
        segs = json.loads(segments_file.read_text())
        for i, seg in enumerate(segs):
            start = seg.get("start_row", "?")
            end = seg.get("end_row", "конец")
            buttons.append([
                InlineKeyboardButton(text=f"#{i+1} строки {start}–{end}", callback_data=f"seg_info:{sheet_name}:{i}"),
                InlineKeyboardButton(text="удалить", callback_data=f"del_seg:{sheet_name}:{i}"),
            ])
    buttons.append([InlineKeyboardButton(text="+ Добавить сегмент", callback_data=f"add_segment:{sheet_name}")])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="back_sheets")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _more_or_done_keyboard(sheet_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить таблицу", callback_data=f"seg_done:{sheet_name}")],
        [InlineKeyboardButton(text="У таблицы есть ещё сегменты", callback_data=f"seg_more:{sheet_name}")],
    ])


async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


async def _get_status_text() -> str:
    # Статус сервиса (для oneshot: inactive = завершился нормально, active = выполняется сейчас)
    active = await _run(["systemctl", "is-active", "ozon-positions.service"])
    is_running = active == "active"

    # Время последнего запуска
    last_output = await _run([
        "systemctl", "show", "ozon-positions.service",
        "--property=ExecMainStartTimestamp",
    ])
    last_run_str = ""
    if "=" in last_output:
        val = last_output.split("=", 1)[1].strip()
        if val and val != "0":
            try:
                # Формат: "Sun 2026-03-15 18:48:56 MSK"
                parts = val.split()
                last_dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
                last_run_str = last_dt.strftime("%d.%m %H:%M")
            except Exception:
                last_run_str = val

    # Время следующего запуска из таймера
    timer_output = await _run(["systemctl", "list-timers", "ozon-positions.timer", "--no-pager"])
    next_run_str = ""
    for line in timer_output.splitlines():
        if "ozon-positions" in line:
            parts = line.split()
            # Формат: "Sun 2026-03-15 19:48:56 MSK 5min ..."
            try:
                next_dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
                diff = next_dt - datetime.now()
                mins = int(diff.total_seconds() // 60)
                next_run_str = f"{next_dt.strftime('%d.%m %H:%M')} (через {mins} мин)"
            except Exception:
                next_run_str = f"{parts[1]} {parts[2]}" if len(parts) >= 3 else ""
            break

    # Список таблиц
    from services.sheets_client import SheetsClient
    from core.settings import settings

    sheets_info = []
    if SHEETS_DIR.exists():
        for sheet_dir in sorted(SHEETS_DIR.iterdir()):
            if not sheet_dir.is_dir():
                continue
            spread_id_file = sheet_dir / "spread_id.txt"
            segments_file = sheet_dir / "segments.json"
            spread_ok = spread_id_file.exists()
            if segments_file.exists() and spread_ok:
                segs = json.loads(segments_file.read_text())
                try:
                    client = SheetsClient(settings.google_credentials_path, spread_id_file.read_text().strip())
                    gs_title = client._spreadsheet.title
                    sheets_info.append(f"- {sheet_dir.name} [{len(segs)} сегм.] — {gs_title}")
                except Exception:
                    sheets_info.append(f"- {sheet_dir.name} [{len(segs)} сегм., ошибка подключения]")
            elif (sheet_dir / "cookies.json").exists() and spread_ok and (sheet_dir / "company_id.txt").exists():
                try:
                    client = SheetsClient(settings.google_credentials_path, spread_id_file.read_text().strip())
                    gs_title = client._spreadsheet.title
                    sheets_info.append(f"- {sheet_dir.name} — {gs_title}")
                except Exception:
                    sheets_info.append(f"- {sheet_dir.name} [ошибка подключения]")
            else:
                sheets_info.append(f"- {sheet_dir.name} [неполная конфигурация]")

    lines = [
        f"Парсер: {'выполняется' if is_running else 'ожидает'}",
    ]
    if last_run_str:
        lines.append(f"Последний запуск: {last_run_str}")
    lines.append(f"Следующий запуск: {next_run_str}" if next_run_str else "Следующий запуск: неизвестно")
    lines += ["", "Таблицы:" if sheets_info else "Таблицы: нет"] + sheets_info

    return "\n".join(lines)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Воспользуйтесь командами из меню")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    text = await _get_status_text()
    await message.answer(text)


@router.message(Command("sheets"))
async def cmd_sheets(message: Message) -> None:
    await message.answer("Таблицы:", reply_markup=sheets_keyboard())


@router.callback_query(F.data == "add_sheet")
async def cb_add_sheet(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Введите название таблицы")
    await state.set_state(AddSheet.name)
    await callback.answer()


@router.message(AddSheet.name)
async def fsm_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddSheet.spread_id)
    await message.answer("Введите ID таблицы (Google Sheets)")


@router.message(AddSheet.spread_id)
async def fsm_spread_id(message: Message, state: FSMContext) -> None:
    await state.update_data(spread_id=message.text.strip())
    await state.set_state(AddSheet.sheet_type)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обычная (один магазин)", callback_data="sheet_type:simple")],
        [InlineKeyboardButton(text="Сегментированная (несколько магазинов)", callback_data="sheet_type:segmented")],
    ])
    await message.answer("Тип таблицы:", reply_markup=keyboard)


@router.callback_query(AddSheet.sheet_type, F.data.startswith("sheet_type:"))
async def fsm_sheet_type(callback: CallbackQuery, state: FSMContext) -> None:
    sheet_type = callback.data.split(":", 1)[1]
    data = await state.get_data()

    if sheet_type == "segmented":
        sheet_dir = SHEETS_DIR / data["name"]
        sheet_dir.mkdir(parents=True, exist_ok=True)
        (sheet_dir / "spread_id.txt").write_text(data["spread_id"])
        await state.clear()
        await state.update_data(sheet_name=data["name"], next_start_row=1)
        await state.set_state(AddSegment.company_id)
        await callback.message.answer("Введите ID компании (company_id) первого магазина")
    else:
        await state.set_state(AddSheet.company_id)
        await callback.message.answer("Введите ID компании")

    await callback.answer()


@router.message(AddSheet.company_id)
async def fsm_company_id(message: Message, state: FSMContext) -> None:
    await state.update_data(company_id=message.text.strip())
    await state.set_state(AddSheet.cookies)
    await message.answer("Отправьте файл cookies.json или вставьте JSON текстом (можно несколькими сообщениями)")


@router.message(AddSheet.cookies, F.document)
async def fsm_cookies(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data["name"]

    sheet_dir = SHEETS_DIR / name
    sheet_dir.mkdir(parents=True, exist_ok=True)

    (sheet_dir / "spread_id.txt").write_text(data["spread_id"])
    (sheet_dir / "company_id.txt").write_text(data["company_id"])

    file = await message.bot.get_file(message.document.file_id)
    content = await message.bot.download_file(file.file_path)
    cookies_data = json.loads(content.read())
    (sheet_dir / "cookies.json").write_text(json.dumps(cookies_data, ensure_ascii=False, indent=2))

    await state.clear()
    await message.answer(f"Таблица '{name}' добавлена", reply_markup=sheets_keyboard())


@router.message(AddSheet.cookies, F.text)
async def fsm_cookies_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    accumulated = data.get("cookies_text", "") + (message.text or "")
    await state.update_data(cookies_text=accumulated)

    try:
        cookies_data = json.loads(accumulated)
    except json.JSONDecodeError:
        await message.answer("Получил часть JSON, жду продолжения...")
        return

    name = data["name"]
    sheet_dir = SHEETS_DIR / name
    sheet_dir.mkdir(parents=True, exist_ok=True)

    (sheet_dir / "spread_id.txt").write_text(data["spread_id"])
    (sheet_dir / "company_id.txt").write_text(data["company_id"])
    (sheet_dir / "cookies.json").write_text(json.dumps(cookies_data, ensure_ascii=False, indent=2))

    await state.clear()
    await message.answer(f"Таблица '{name}' добавлена", reply_markup=sheets_keyboard())


@router.message(AddSheet.cookies)
async def fsm_cookies_wrong(message: Message) -> None:
    await message.answer("Отправьте файл cookies.json или вставьте JSON текстом")


# ── Сегментированные таблицы ──────────────────────────────────────────────────

@router.message(AddSegment.company_id)
async def fsm_seg_company_id(message: Message, state: FSMContext) -> None:
    await state.update_data(company_id=message.text.strip())
    await state.set_state(AddSegment.cookies)
    await message.answer("Отправьте cookies.json для этого магазина (файл или JSON текстом)")


async def _handle_seg_cookies(message: Message, state: FSMContext, cookies_data: dict) -> None:
    data = await state.get_data()
    sheet_name = data["sheet_name"]
    company_id = data["company_id"]
    start_row = data["next_start_row"]

    sheet_dir = SHEETS_DIR / sheet_name
    segments_file = sheet_dir / "segments.json"
    segments = json.loads(segments_file.read_text()) if segments_file.exists() else []

    idx = len(segments) + 1
    cookies_filename = f"cookies_{idx}.json"
    (sheet_dir / cookies_filename).write_text(json.dumps(cookies_data, ensure_ascii=False, indent=2))

    # Сохраняем сегмент без end_row пока — он будет добавлен на следующем шаге (или не добавлен для последнего)
    seg = {"company_id": company_id, "cookies": cookies_filename, "start_row": start_row}
    segments.append(seg)
    segments_file.write_text(json.dumps(segments, ensure_ascii=False, indent=2))

    await state.update_data(current_seg_index=len(segments) - 1, cookies_text="")
    await state.set_state(AddSegment.end_row)
    await message.answer(
        "До какой строки включительно этот магазин?\n"
        "(если это последний сегмент — введите 'нет')"
    )


@router.message(AddSegment.cookies, F.document)
async def fsm_seg_cookies_file(message: Message, state: FSMContext) -> None:
    file = await message.bot.get_file(message.document.file_id)
    content = await message.bot.download_file(file.file_path)
    cookies_data = json.loads(content.read())
    await _handle_seg_cookies(message, state, cookies_data)


@router.message(AddSegment.cookies, F.text)
async def fsm_seg_cookies_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    accumulated = data.get("cookies_text", "") + (message.text or "")
    await state.update_data(cookies_text=accumulated)
    try:
        cookies_data = json.loads(accumulated)
    except json.JSONDecodeError:
        await message.answer("Получил часть JSON, жду продолжения...")
        return
    await _handle_seg_cookies(message, state, cookies_data)


@router.message(AddSegment.cookies)
async def fsm_seg_cookies_wrong(message: Message) -> None:
    await message.answer("Отправьте файл cookies.json или вставьте JSON текстом")


@router.message(AddSegment.end_row)
async def fsm_seg_end_row(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    data = await state.get_data()
    sheet_name = data["sheet_name"]
    seg_index = data["current_seg_index"]

    segments_file = SHEETS_DIR / sheet_name / "segments.json"
    segments = json.loads(segments_file.read_text())

    if text in ("нет", "-", ""):
        # Последний сегмент — end_row не нужен
        await state.clear()
        await message.answer(f"Таблица '{sheet_name}' сохранена.", reply_markup=sheets_keyboard())
        return

    try:
        end_row = int(text)
    except ValueError:
        await message.answer("Введите число или 'нет'")
        return

    segments[seg_index]["end_row"] = end_row
    segments_file.write_text(json.dumps(segments, ensure_ascii=False, indent=2))

    await state.update_data(next_start_row=end_row + 1)
    await message.answer(
        f"Сегмент #{seg_index + 1} сохранён (строки {segments[seg_index]['start_row']}–{end_row}).",
        reply_markup=_more_or_done_keyboard(sheet_name),
    )


@router.callback_query(F.data.startswith("seg_done:"))
async def cb_seg_done(callback: CallbackQuery, state: FSMContext) -> None:
    sheet_name = callback.data.split(":", 1)[1]
    await state.clear()
    await callback.message.edit_text(f"Таблица '{sheet_name}' сохранена.", reply_markup=sheets_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("seg_more:"))
async def cb_seg_more(callback: CallbackQuery, state: FSMContext) -> None:
    sheet_name = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.update_data(sheet_name=sheet_name, next_start_row=data.get("next_start_row", 1))
    await state.set_state(AddSegment.company_id)
    await callback.message.answer("Введите ID компании (company_id) следующего магазина")
    await callback.answer()


# ── Управление существующими таблицами ────────────────────────────────────────

@router.callback_query(F.data.startswith("delete:"))
async def cb_delete(callback: CallbackQuery) -> None:
    name = callback.data.split(":", 1)[1]
    sheet_dir = SHEETS_DIR / name
    if sheet_dir.exists():
        shutil.rmtree(sheet_dir)
    await callback.message.edit_text("Таблицы:", reply_markup=sheets_keyboard())
    await callback.answer(f"'{name}' удалена")


@router.callback_query(F.data.startswith("sheet:"))
async def cb_sheet_detail(callback: CallbackQuery) -> None:
    sheet_name = callback.data.split(":", 1)[1]
    sheet_dir = SHEETS_DIR / sheet_name
    segments_file = sheet_dir / "segments.json"
    if segments_file.exists():
        segs = json.loads(segments_file.read_text())
        text = f"Таблица: {sheet_name}\nСегментов: {len(segs)}"
    else:
        text = f"Таблица: {sheet_name}\n(обычная, без сегментов)"
    await callback.message.edit_text(text, reply_markup=sheet_detail_keyboard(sheet_name))
    await callback.answer()


@router.callback_query(F.data == "back_sheets")
async def cb_back_sheets(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Таблицы:", reply_markup=sheets_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("add_segment:"))
async def cb_add_segment(callback: CallbackQuery, state: FSMContext) -> None:
    sheet_name = callback.data.split(":", 1)[1]
    segments_file = SHEETS_DIR / sheet_name / "segments.json"
    segments = json.loads(segments_file.read_text()) if segments_file.exists() else []
    # next_start_row = end_row последнего сегмента + 1, или 1 если пусто
    last_end = segments[-1].get("end_row") if segments else None
    next_start = (last_end + 1) if last_end else 1
    await state.update_data(sheet_name=sheet_name, next_start_row=next_start)
    await state.set_state(AddSegment.company_id)
    await callback.message.answer("Введите ID компании (company_id) нового сегмента")
    await callback.answer()


@router.callback_query(F.data.startswith("del_seg:"))
async def cb_del_segment(callback: CallbackQuery) -> None:
    _, sheet_name, idx_str = callback.data.split(":", 2)
    segments_file = SHEETS_DIR / sheet_name / "segments.json"
    if segments_file.exists():
        segments = json.loads(segments_file.read_text())
        try:
            segments.pop(int(idx_str))
        except (IndexError, ValueError):
            pass
        segments_file.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    await callback.message.edit_text(f"Таблица: {sheet_name}", reply_markup=sheet_detail_keyboard(sheet_name))
    await callback.answer("Сегмент удалён")
