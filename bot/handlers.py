import asyncio
import json
import shutil
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

router = Router()

SHEETS_DIR = Path("sheets")


class AddSheet(StatesGroup):
    name = State()
    spread_id = State()
    company_id = State()
    cookies = State()


def sheets_keyboard() -> InlineKeyboardMarkup:
    sheets = [d for d in SHEETS_DIR.iterdir() if d.is_dir()] if SHEETS_DIR.exists() else []
    buttons = []
    for sheet in sheets:
        buttons.append([
            InlineKeyboardButton(text=sheet.name, callback_data=f"sheet:{sheet.name}"),
            InlineKeyboardButton(text="удалить", callback_data=f"delete:{sheet.name}"),
        ])
    buttons.append([InlineKeyboardButton(text="+ Добавить таблицу", callback_data="add_sheet")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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

    # Список таблиц с количеством запросов
    sheets_info = []
    if SHEETS_DIR.exists():
        for sheet_dir in sorted(SHEETS_DIR.iterdir()):
            if not sheet_dir.is_dir():
                continue
            cookies_ok = (sheet_dir / "cookies.json").exists()
            spread_ok = (sheet_dir / "spread_id.txt").exists()
            company_ok = (sheet_dir / "company_id.txt").exists()
            status = "OK" if (cookies_ok and spread_ok and company_ok) else "неполная конфигурация"
            sheets_info.append(f"- {sheet_dir.name} [{status}]")

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
    await message.answer("Введите ID таблицы")


@router.message(AddSheet.spread_id)
async def fsm_spread_id(message: Message, state: FSMContext) -> None:
    await state.update_data(spread_id=message.text.strip())
    await state.set_state(AddSheet.company_id)
    await message.answer("Введите ID компании")


@router.message(AddSheet.company_id)
async def fsm_company_id(message: Message, state: FSMContext) -> None:
    await state.update_data(company_id=message.text.strip())
    await state.set_state(AddSheet.cookies)
    await message.answer("Отправьте файл cookies.json")


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


@router.message(AddSheet.cookies)
async def fsm_cookies_wrong(message: Message) -> None:
    await message.answer("Отправьте именно файл cookies.json")


@router.callback_query(F.data.startswith("delete:"))
async def cb_delete(callback: CallbackQuery) -> None:
    name = callback.data.split(":", 1)[1]
    sheet_dir = SHEETS_DIR / name
    if sheet_dir.exists():
        shutil.rmtree(sheet_dir)
    await callback.message.edit_text("Таблицы:", reply_markup=sheets_keyboard())
    await callback.answer(f"'{name}' удалена")
