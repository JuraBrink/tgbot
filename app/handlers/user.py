# app/handlers/user.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# UsersRepo инжектится через middleware (data["users_repo"])
from db.users_repo import UsersRepo

router = Router(name="user_cmd")

class UserStates(StatesGroup):
    waiting_for_id = State()


@router.message(Command("user"))
async def ask_user_id(message: types.Message, state: FSMContext):
    await state.set_state(UserStates.waiting_for_id)
    await message.answer(
        "Пришлите числовой ID пользователя, которого нужно сохранить.\n"
        "Можно отменить командой /cancel."
    )


@router.message(UserStates.waiting_for_id, F.text.regexp(r"^\d{1,20}$"))
async def save_user_id(
    message: types.Message,
    state: FSMContext,
    users_repo: UsersRepo,   # <-- DI из мидлвари
):
    tg_id = int(message.text)

    # простая валидация «похоже на Telegram ID»
    if tg_id <= 0:
        await message.answer("ID должен быть положительным числом. Попробуйте снова.")
        return

    user = await users_repo.upsert_user(tg_id=tg_id, username=None)
    await state.clear()

    await message.answer(
        f"Сохранил пользователя:\n"
        f"• tg_id: <code>{user.tg_id}</code>\n"
        f"• id в базе: <code>{user.id}</code>"
    )


@router.message(UserStates.waiting_for_id)
async def wrong_format(message: types.Message):
    await message.answer("Нужно отправить только число. Например: 123456789.")


@router.message(Command("cancel"))
async def cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Ок, отменил.")
