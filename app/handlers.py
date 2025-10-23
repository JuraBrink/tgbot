
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

@router.message(Command('mark'))
async def cmd_mark(message: Message):
    await message.answer('Day is marked')

@router.message(Command('report'))
async def cmd_mark(message: Message):
    await message.answer('Report is showed')

@router.message(Command('settings'))
async def cmd_mark(message: Message):
    await message.answer('Settings are saved')

@router.message(Command('user'))
async def cmd_mark(message: Message):
    await message.answer('New user is added')

@router.message()
async def cmd_start(message: Message):
    await message.answer(f'Hello {message.chat.full_name}. Please send your ID:{message.chat.id} to the administrator') # f"Ок, ставка: {s.rate} {s.currency}/час"
    # await message.reply('uu router')

   