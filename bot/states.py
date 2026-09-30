"""FSM-состояния aiogram для пошаговых диалогов."""
from aiogram.fsm.state import State, StatesGroup


class ExpenseFSM(StatesGroup):
    category = State()
    custom_category = State()   # «свой вариант» — статья вводится текстом
    amount = State()
    comment = State()


class SaleFSM(StatesGroup):
    # Порядок шагов: сначала ТИП ОПЛАТЫ и клиент, потом уже товары.
    # Так при реализации сразу видно, кому продаём, и корзина собирается
    # уже «на клиента», а не выясняется в самом конце.
    payment = State()
    client = State()
    new_client = State()        # «свой вариант» — имя нового клиента
    product = State()
    quantity = State()
    price = State()
    more = State()
    confirm = State()


class DebtPaymentFSM(StatesGroup):
    client = State()
    find_client = State()       # «свой вариант» — поиск клиента по имени
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
