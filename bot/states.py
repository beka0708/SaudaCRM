"""FSM-состояния aiogram для пошаговых диалогов."""
from aiogram.fsm.state import State, StatesGroup


class ExpenseFSM(StatesGroup):
    category = State()
    amount = State()
    comment = State()


class SaleFSM(StatesGroup):
    product = State()
    packaging = State()
    quantity = State()
    more = State()
    payment = State()
    client = State()
    confirm = State()


class DebtPaymentFSM(StatesGroup):
    client = State()
    amount = State()
