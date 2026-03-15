import json
import shutil
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


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Воспользуйтесь командами из меню")


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
    name = message.text.strip()
    await state.update_data(name=name)
    await state.set_state(AddSheet.spread_id)
    await message.answer("Введите ID таблицы")


@router.message(AddSheet.spread_id)
async def fsm_spread_id(message: Message, state: FSMContext) -> None:
    await state.update_data(spread_id=message.text.strip())
    await state.set_state(AddSheet.cookies)
    await message.answer("Отправьте файл cookies.json")


@router.message(AddSheet.cookies, F.document)
async def fsm_cookies(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data["name"]
    spread_id = data["spread_id"]

    sheet_dir = SHEETS_DIR / name
    sheet_dir.mkdir(parents=True, exist_ok=True)

    (sheet_dir / "spread_id.txt").write_text(spread_id)

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
