from aiogram.fsm.state import State, StatesGroup


class CalculationStates(StatesGroup):
    SELECT_CONSTRUCTION = State()
    BUILDER = State()
    EDIT_CONFIG = State()
    EDIT_PROFILE = State()
    EDIT_SIZE = State()
    EDIT_SIZE_CUSTOM_W = State()
    EDIT_SIZE_CUSTOM_H = State()
    EDIT_BAL_DOOR_W = State()
    EDIT_BAL_DOOR_H = State()
    EDIT_BAL_WIN_W = State()
    EDIT_BAL_WIN_H = State()
    EDIT_GLASS = State()
    EDIT_EXTRAS = State()
    EDIT_SILL_DEPTH = State()
    EDIT_DOOR_PARAMS = State()
    EDIT_BALCONY = State()
    EDIT_SCHEME = State()
    EDIT_DIRECTION = State()
    # Корзина / заявка
    CART = State()
    CONFIRM_ESTIMATE = State()
    GET_NAME = State()
    GET_PHONE = State()
    GET_ADDRESS = State()
    GET_PHOTO = State()
    # Замер без расчёта
    MEASURE_NAME = State()
    MEASURE_PHONE = State()
    MEASURE_ADDRESS = State()


class HistoryStates(StatesGroup):
    VIEW = State()


class ServiceStates(StatesGroup):
    MENU = State()
    GLASS_WIDTH = State()
    GLASS_HEIGHT = State()
    GLASS_QTY = State()
    ADJUST = State()
    SEAL_METERS = State()
    NAME = State()
    PHONE = State()


class ManagerStates(StatesGroup):
    NAME = State()
    PHONE = State()
