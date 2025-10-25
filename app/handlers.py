
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="main_router")

@router.message(Command('mark'))
async def cmd_mark(message: Message):
    await message.answer('Day is marked')

@router.message(Command('report'))
async def cmd_mark(message: Message):
    await message.answer('Report is showed')

@router.message(Command('settings'))
async def cmd_mark(message: Message):
    await message.answer('Settings are saved')

@router.message()
async def cmd_start(message: Message):
    await message.answer('Error!!!') # f"Ок, ставка: {s.rate} {s.currency}/час"
    # await message.reply('uu router')

   