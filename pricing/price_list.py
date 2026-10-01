"""Цены и правила предварительного расчёта для клиентского Telegram-бота.

Цены в рублях. Для окон и балконных блоков итог включает монтаж 17%.
Балконные рамы показываются только как ориентировочный диапазон.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

PROFILES = {
    "58": "Профиль 58 мм (3–4 камеры)",
    "70": "Профиль 70 мм (5 камер)",
}

GLAZING = {
    "24": "СП 24 мм",
    "32": "СП 32 мм",
    "24_i": "СП 24 мм + i (2 стороны)",
    "32_i": "СП 32 мм + i (2 стороны)",
}


SASH_TYPES = {"fixed": "Глухая", "turn": "Поворотная", "tilt_turn": "Поворотно-откидная"}

WINDOW_CONFIGS = [
    ("1_fixed", "Глухое", 1, "fixed"),
    ("1_turn", "Поворотное", 1, "turn"),
    ("1_tilt_turn", "Поворотно-откидное", 1, "tilt_turn"),
    ("2_fixed_fixed", "Глухое | Глухое", 2, "fixed_fixed"),
    ("2_fixed_tilt_turn", "Глухое | ПО", 2, "fixed_tilt_turn"),
    ("2_tilt_turn_fixed", "ПО | Глухое", 2, "tilt_turn_fixed"),
    ("2_fixed_turn", "Глухое | Поворот", 2, "fixed_turn"),
    ("2_turn_turn", "Поворот | Поворот", 2, "turn_turn"),
    ("3_fixed_fixed_fixed", "Глухое | Глухое | Глухое", 3, "fixed_fixed_fixed"),
    ("3_fixed_tilt_turn_fixed", "Глухое | ПО | Глухое", 3, "fixed_tilt_turn_fixed"),
    ("3_tilt_turn_fixed_tilt_turn", "ПО | Глухое | ПО", 3, "tilt_turn_fixed_tilt_turn"),
    ("custom", "✏️ Своя конфигурация", None, None),
]

WINDOW_SCHEMES = {
    "1_fixed": "┌─────────┐\n│  глухая │\n└─────────┘",
    "1_turn": "┌─────────┐\n│   [П]   │\n└─────────┘",
    "1_tilt_turn": "┌─────────┐\n│  [ПО]   │\n└─────────┘",
    "2_fixed_fixed": "┌────┬────┐\n│ Г  │ Г  │\n└────┴────┘",
    "2_fixed_turn": "┌────┬────┐\n│ Г  │[П] │\n└────┴────┘",
    "2_fixed_tilt_turn": "┌────┬────┐\n│ Г  │[ПО]│\n└────┴────┘",
    "2_tilt_turn_fixed": "┌────┬────┐\n│[ПО]│ Г  │\n└────┴────┘",
    "2_turn_turn": "┌────┬────┐\n│[П] │[П] │\n└────┴────┘",
    "3_fixed_fixed_fixed": "┌────┬────┬────┐\n│ Г  │ Г  │ Г  │\n└────┴────┴────┘",
    "3_fixed_tilt_turn_fixed": "┌────┬────┬────┐\n│ Г  │[ПО]│ Г  │\n└────┴────┴────┘",
    "3_tilt_turn_fixed_tilt_turn": "┌────┬────┬────┐\n│[ПО]│ Г  │[ПО]│\n└────┴────┴────┘",
}

NONSTANDARD_SCHEMES = {
    "transom_v": {
        "label": "Фрамуга + низ с вертикальным импостом",
        "scheme": "┌─────────────┐\n│   фрамуга   │\n├──────┬──────┤\n│  Л   │  П   │\n└──────┴──────┘",
    },
    "transom_h": {
        "label": "Фрамуга + глухой низ",
        "scheme": "┌─────────────┐\n│   фрамуга   │\n├─────────────┤\n│     низ     │\n└─────────────┘",
    },
    "triple_v": {
        "label": "Три секции вертикальными импостами",
        "scheme": "┌────┬────┬────┐\n│ Л  │ Ц  │ П  │\n└────┴────┴────┘",
    },
    "door_sidelight": {
        "label": "Дверь + боковое окно",
        "scheme": "┌──────┬────┐\n│ дверь│бок.│\n└──────┴────┘",
    },
}

# Балконные рамы — только ориентировочные диапазоны, без точной сметы.
BALCONY_GLAZING_TYPES = {
    "frame": {
        "label": "Балконная рама от пола до потолка (≈ 3,0 × 2,5 м)",
        "scheme": "┌─────────────────┐\n│    рама балкона │\n│                 │\n└─────────────────┘",
    },
    "frame_slab": {
        "label": "Балконная рама от плиты до потолка (≈ 3,0 × 1,3 м)",
        "scheme": "┌─────────────────┐\n│    рама балкона │\n│                 │\n├─────────────────┤\n│      плита      │\n└─────────────────┘",
    },
}

DOOR_OPENING = {"single": "Однопольная", "double": "Двупольная (штульповая)"}
DOOR_SASH = {"T": "T-створка", "Z": "Z-створка"}
DOOR_THRESHOLD = {
    "alu_low": "Низкий алюминиевый порог",
    "frame": "Рамная коробка (замкнутый контур)",
}
DOOR_LOCK = {"single": "Однозапорный", "multi": "Многозапорный («рейка»)"}
DOOR_FITTINGS = {
    "push": "Нажимная гарнитура",
    "handles_closer": "Ручки-скобы с доводчиком",
}

LIMITS = {
    "width_min": 400, "width_max": 3000,
    "height_min": 400, "height_max": 2800,
    "sash_turn_max_width": 1000,
    "door_width_min": 600, "door_width_max": 1800,
    "door_height_min": 1800, "door_height_max": 2400,
}

# ---------------------------------------------------------------------------
# Окна — ориентировочная клиентская база конструкции без стеклопакета.
# Стеклопакет добавляется отдельно по площади.
# ---------------------------------------------------------------------------

WINDOW_CONSTRUCTION_BASE = {
    # Цена конструкции без стеклопакета и без монтажа. Стеклопакет считается по площади.
    "single": {
        "fixed": {"58": Decimal("4500"), "70": Decimal("5500")},
        "turn": {"58": Decimal("5000"), "70": Decimal("6000")},
        "tilt_turn": {"58": Decimal("5500"), "70": Decimal("6500")},
    },
    "double": {
        "fixed_fixed": {"58": Decimal("6500"), "70": Decimal("8000")},
        "fixed_turn": {"58": Decimal("7000"), "70": Decimal("8500")},
        "fixed_tilt_turn": {"58": Decimal("7000"), "70": Decimal("8500")},
        "tilt_turn_fixed": {"58": Decimal("7000"), "70": Decimal("8500")},
        "turn_turn": {"58": Decimal("8000"), "70": Decimal("9500")},
    },
    "triple": {
        "fixed_fixed_fixed": {"58": Decimal("9000"), "70": Decimal("11000")},
        "fixed_tilt_turn_fixed": {"58": Decimal("10000"), "70": Decimal("12000")},
        "tilt_turn_fixed_tilt_turn": {"58": Decimal("11500"), "70": Decimal("14000")},
    },
}

GLASS_PRICE_PER_M2 = {
    "24": Decimal("5500"),
    "32": Decimal("7500"),
}
I_GLASS_SURCHARGE_PER_CONSTRUCTION = Decimal("2000")

# Балконный блок: база профиля/фурнитуры без стеклопакета; СП добавляется по площади.
BALCONY_BLOCK_BASE = {
    # Снижено примерно на 25% относительно предыдущей версии.
    "58": {
        "door": Decimal("3375"),
        "window_fixed": Decimal("1500"),
        "window_tilt_turn": Decimal("2250"),
        "connector": Decimal("375"),
    },
    "70": {
        "door": Decimal("6000"),
        "window_fixed": Decimal("2625"),
        "window_tilt_turn": Decimal("3375"),
        "connector": Decimal("525"),
    },
}

# Балконные рамы — только ориентир, без попытки выдать их за точную смету.
BALCONY_GLAZING_PACKAGE = {
    # (от, до), без попытки заменить замер специалиста.
    # Для 70 мм задан ориентир выше 58 мм; отдельная цена для рамы от плиты пока не задана,
    # поэтому используется тот же ориентир, что и для базовой балконной рамы.
    "frame": {"58": (Decimal("75000"), Decimal("85000")), "70": (Decimal("95000"), Decimal("110000"))},
    "frame_slab": {"58": (Decimal("75000"), Decimal("85000")), "70": (Decimal("95000"), Decimal("110000"))},
}

GLASS_UNIT_PRICE_PER_M2 = {"24": Decimal("5500"), "32": Decimal("7500")}


# Двери ПВХ — ориентировочная клиентская база.
DOOR_PRICES = {
    "single": {"T": Decimal("22000.00"), "Z": Decimal("23000.00")},
    "double": {"T": Decimal("32000.00"), "Z": Decimal("33500.00")},
}

# Входные ПВХ-двери: только шесть стандартных вариантов.
# Значения здесь — финальная цена из Dealer с монтажом 17%.
STANDARD_PVC_DOORS = {
    "900x2100": Decimal("42889.97"),
    "1000x2100": Decimal("44300.00"),
    "1100x2100": Decimal("44315.00"),
    "1300x2100": Decimal("60000.00"),
    "1400x2100": Decimal("62000.00"),
    "1600x2100": Decimal("64486.67"),
}

def get_standard_pvc_door_price(size_key: str) -> Decimal:
    """Возвращает базовую цену стандартной входной двери без монтажа 17%."""
    try:
        total = STANDARD_PVC_DOORS[size_key]
    except KeyError as exc:
        raise ValueError("Стандартный размер двери не найден") from exc
    return money(total / (Decimal("1.00") + INSTALLATION_RATE))


DOOR_THRESHOLD_PRICE = {"alu_low": Decimal("1500.00"), "frame": Decimal("0.00")}
DOOR_LOCK_PRICE = {"single": Decimal("0.00"), "multi": Decimal("3200.00")}
DOOR_FITTINGS_PRICE = {"push": Decimal("1800.00"), "handles_closer": Decimal("4800.00")}

CONNECTOR_PROFILE_PER_M = Decimal("1100.00")
MOSQUITO_NET = {"standard": Decimal("800.00"), "reinforced": Decimal("1100.00")}

PVC_SILL_PRICES = {
    150: Decimal("800"), 200: Decimal("900"), 250: Decimal("1050"), 300: Decimal("1200"),
    350: Decimal("1400"), 400: Decimal("1600"), 450: Decimal("1800"), 500: Decimal("2000"),
    550: Decimal("2200"), 600: Decimal("2400"),
}
DANKE_SILL_PRICES = {
    100: Decimal("2500"), 150: Decimal("3500"), 200: Decimal("4500"), 250: Decimal("5500"),
    300: Decimal("6800"), 350: Decimal("8000"), 400: Decimal("9200"), 450: Decimal("10400"),
    500: Decimal("11600"), 550: Decimal("12800"), 600: Decimal("14000"),
}
EBB_PRICES = {
    100: Decimal("550"), 150: Decimal("650"), 200: Decimal("780"), 250: Decimal("950"),
    300: Decimal("1100"), 350: Decimal("1300"), 400: Decimal("1500"),
}

DELIVERY_CITY = Decimal("2500.00")
DELIVERY_OUTSIDE = Decimal("4000.00")

INSTALLATION_RATE = Decimal("0.17")
MONEY = Decimal("0.01")

# Сервис / ремонт (не новое изделие)
SERVICE_PRICES = {
    # Обычный замер изделия — бесплатно. 500 ₽ только для специальных замеров.
    "special_measure": Decimal("500.00"),   # замер москитных сеток / стеклопакетов
    "install_visit": Decimal("1000.00"),    # выезд на монтаж / монтажные работы (минимум)
    "glass24_replace": Decimal("5500.00"),  # замена стеклопакета 24 мм (1 шт)
    "glass32_replace": Decimal("7500.00"),  # замена стеклопакета 32 мм (1 шт)
    "adjust_visit": Decimal("1000.00"),     # выезд мастера на регулировку
    "adjust_window": Decimal("300.00"),     # регулировка 1 окна
    "adjust_door": Decimal("500.00"),       # регулировка 1 двери
    "seal_visit": Decimal("1000.00"),       # выезд на замену уплотнителя
    "seal_meter": Decimal("250.00"),        # уплотнитель, ₽ / пог. м
}


def money(v: Decimal) -> Decimal:
    return v.quantize(MONEY, rounding=ROUND_HALF_UP)


def base_glass_key(glass: str) -> str:
    for suffix in ("_i", "_satin"):
        if glass.endswith(suffix):
            return glass[: -len(suffix)]
    return glass


def glass_mod(glass: str) -> str | None:
    if glass.endswith("_i"):
        return "i"
    if glass.endswith("_satin"):
        return "satin"
    return None


def get_window_price(sash_count: int, configuration: str, profile: str, glass: str,
                     width_mm: int | None = None, height_mm: int | None = None) -> Decimal:
    group = {1: "single", 2: "double", 3: "triple"}.get(sash_count)
    if not group:
        raise ValueError("Недопустимое количество створок")
    base_glass = base_glass_key(glass)
    if base_glass not in GLASS_PRICE_PER_M2:
        raise ValueError("Доступны только стеклопакеты 24 и 32 мм")
    try:
        construction = WINDOW_CONSTRUCTION_BASE[group][configuration][profile]
    except KeyError as exc:
        raise ValueError("Эта комбинация окна пока не настроена в прайсе") from exc
    if not width_mm or not height_mm:
        raise ValueError("Для расчёта окна нужны размеры")
    area = Decimal(width_mm * height_mm) / Decimal("1000000")
    # Ориентировочная итоговая стоимость окна снижена примерно на 20%.
    # Отдельный стеклопакет по-прежнему имеет собственный фиксированный прайс.
    price = money((construction + area * GLASS_PRICE_PER_M2[base_glass]) * Decimal("0.80"))
    return money(price)


def get_sill_price(kind: str, depth_mm: int, length_mm: int) -> Decimal:
    table = PVC_SILL_PRICES if kind == "pvc" else DANKE_SILL_PRICES if kind == "danke" else None
    if table is None or depth_mm not in table:
        raise ValueError("Недопустимый тип или размер подоконника")
    return money(table[depth_mm] * Decimal(length_mm) / Decimal(1000))


def get_ebb_price(width_mm: int, length_mm: int) -> Decimal:
    if width_mm not in EBB_PRICES:
        raise ValueError("Недопустимая ширина отлива")
    return money(EBB_PRICES[width_mm] * Decimal(length_mm) / Decimal(1000))


def get_connector_price(height_mm: int) -> Decimal:
    return money(CONNECTOR_PROFILE_PER_M * Decimal(height_mm) / Decimal(1000))


def get_door_price(opening: str, sash: str, threshold: str, lock: str, fittings: str, glass: str = "32") -> Decimal:
    try:
        price = DOOR_PRICES[opening][sash]
    except KeyError as exc:
        raise ValueError("Эта комбинация двери пока не настроена в прайсе") from exc
    base = base_glass_key(glass)
    if base not in GLASS_PRICE_PER_M2:
        raise ValueError("Доступны только стеклопакеты 24 и 32 мм")
    price += DOOR_THRESHOLD_PRICE.get(threshold, Decimal("0"))
    price += DOOR_LOCK_PRICE.get(lock, Decimal("0"))
    price += DOOR_FITTINGS_PRICE.get(fittings, Decimal("0"))
    # Для двери стеклопакет тоже считается по площади полотна.
    # Размеры двери передаются отдельной функцией в калькуляторе.
    return money(price)


BALCONY_DOOR_MOSQUITO_NET = Decimal("5000.00")


def get_balcony_block_parts(profile: str, window_cfg: str = "tilt_turn") -> dict[str, Decimal]:
    """Ориентировочная клиентская база балконного блока без стеклопакета."""
    p = BALCONY_BLOCK_BASE.get(profile) or BALCONY_BLOCK_BASE["70"]
    wkey = "window_fixed" if window_cfg == "fixed" else "window_tilt_turn"
    return {
        "door": money(p["door"]),
        "window": money(p[wkey]),
        "connector": money(p["connector"]),
    }


def get_balcony_glazing_package(kind: str, profile: str) -> tuple[Decimal, Decimal]:
    try:
        low, high = BALCONY_GLAZING_PACKAGE[kind][profile]
        return money(low), money(high)
    except KeyError as exc:
        raise ValueError("Тип балконной рамы не настроен") from exc


def calculate_installation(subtotal: Decimal) -> Decimal:
    return money(subtotal * INSTALLATION_RATE)


def validate_size(width_mm: int, height_mm: int, construction_type: str = "window",
                  sash_count: int | None = None, configuration: str | None = None) -> str | None:
    L = LIMITS
    if construction_type == "door":
        if not (L["door_width_min"] <= width_mm <= L["door_width_max"]):
            return f"Ширина двери {L['door_width_min']}–{L['door_width_max']} мм"
        if not (L["door_height_min"] <= height_mm <= L["door_height_max"]):
            return f"Высота двери {L['door_height_min']}–{L['door_height_max']} мм"
        return None
    if construction_type in ("balcony_glazing", "frame", "frame_slab"):
        return None
    if not (L["width_min"] <= width_mm <= L["width_max"]):
        return f"Ширина {L['width_min']}–{L['width_max']} мм"
    if not (L["height_min"] <= height_mm <= L["height_max"]):
        return f"Высота {L['height_min']}–{L['height_max']} мм"
    if sash_count == 1 and configuration in ("turn", "tilt_turn"):
        if width_mm > L["sash_turn_max_width"]:
            return f"Поворотная/ПО створка: ширина до {L['sash_turn_max_width']} мм"
    if sash_count == 2 and configuration == "turn_turn":
        if width_mm / 2 > L["sash_turn_max_width"]:
            return f"Створки слишком широкие для turn+turn"
    return None


def service_measure() -> Decimal:
    """Обычный замер окон/дверей/балконных блоков — бесплатно."""
    return Decimal("0.00")


def service_special_measure() -> Decimal:
    """Платный специальный замер: москитные сетки или стеклопакеты."""
    return money(SERVICE_PRICES["special_measure"])


def service_mosquito_measure() -> tuple[Decimal, list[tuple[str, Decimal]]]:
    fee = service_special_measure()
    return fee, [("Замер москитных сеток", fee)]


def service_install_visit() -> Decimal:
    return money(SERVICE_PRICES["install_visit"])


def service_glass_replace(glass: str = "32", qty: int = 1, with_measure: bool = True, with_install: bool = True) -> tuple[Decimal, list[tuple[str, Decimal]]]:
    if glass not in {"24", "32"}:
        raise ValueError("Доступны стеклопакеты 24 и 32 мм")
    price_key = "glass24_replace" if glass == "24" else "glass32_replace"
    items = [(f"Замена стеклопакета {glass} мм ×{qty}", money(SERVICE_PRICES[price_key] * qty))]
    if with_measure:
        items.append(("Замер стеклопакетов", service_special_measure()))
    if with_install:
        items.append(("Монтаж", SERVICE_PRICES["install_visit"]))
    total = money(sum((p for _, p in items), Decimal("0")))
    return total, items


def service_glass32(qty: int = 1, with_measure: bool = False, with_install: bool = False) -> tuple[Decimal, list[tuple[str, Decimal]]]:
    return service_glass_replace("32", qty, with_measure, with_install)


def service_adjust(windows: int = 0, doors: int = 0) -> tuple[Decimal, list[tuple[str, Decimal]]]:
    items = [("Выезд мастера (регулировка)", SERVICE_PRICES["adjust_visit"])]
    if windows:
        items.append((f"Регулировка окон ×{windows}", money(SERVICE_PRICES["adjust_window"] * windows)))
    if doors:
        items.append((f"Регулировка дверей ×{doors}", money(SERVICE_PRICES["adjust_door"] * doors)))
    total = money(sum((p for _, p in items), Decimal("0")))
    return total, items


def service_seal(meters: Decimal) -> tuple[Decimal, list[tuple[str, Decimal]]]:
    items = [
        ("Выезд мастера (уплотнитель)", SERVICE_PRICES["seal_visit"]),
        (f"Уплотнитель {meters} п.м. × 250 ₽", money(SERVICE_PRICES["seal_meter"] * meters)),
    ]
    total = money(sum((p for _, p in items), Decimal("0")))
    return total, items
