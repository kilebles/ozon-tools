from aiogram import Bot
from aiogram.types import BotCommand


async def set_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="status", description="Статус парсера"),
        BotCommand(command="sheets", description="Таблицы"),
    ]
    await bot.set_my_commands(commands)
