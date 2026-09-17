"""FSM-состояния aiogram для пошаговых диалогов."""
from aiogram.fsm.state import State, StatesGroup


class ExpenseFSM(StatesGroup):
    category = State()
    amount = State()
    comment = State()


class SaleFSM(StatesGroup):
    product = State()
    quantity = State()
    price = State()
    more = State()
    payment = State()
    client = State()
    confirm = State()


class DebtPaymentFSM(StatesGroup):
    client = State()
    amount = State()


class ReversalFSM(StatesGroup):
    choose = State()       # выбор операции из последних
    confirm = State()      # подтверждение отмены


class ReceiptFSM(StatesGroup):
    product = State()      # выбор товара или «новый»
    new_name = State()     # для нового товара
    new_pack = State()
    new_units = State()
    packs = State()        # сколько фасовок пришло
    cost = State()         # себестоимость за штуку
    confirm = State()
