
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Tuple
from .parse import fmt_hhmm

def build_work_kb(templates: List[Tuple[int,int,int]], include_help: bool = True):
    kb = InlineKeyboardBuilder()
    for start, end, brk in templates[:4]:
        total = (end - start) - brk
        if brk:
            text = f"{fmt_hhmm(start)}-{fmt_hhmm(end)}-{fmt_hhmm(brk)}"
        else:
            text = f"{fmt_hhmm(start)}-{fmt_hhmm(end)}"
        kb.button(text=text, callback_data=f"tpl:{start}:{end}:{brk}")
    if templates:
        kb.adjust(*([1] * min(4, len(templates))))
    kb.button(text="Выходной", callback_data="dayoff")
    if include_help:
        kb.button(text="help", callback_data="help")
        if templates:
            kb.adjust(2)
        else:
            kb.adjust(2)
    else:
        kb.adjust(1)
    return kb.as_markup()
