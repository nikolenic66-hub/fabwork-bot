from __future__ import annotations

from decimal import Decimal

from models import CalculationConfig, Estimate, EstimateItem
from pricing.price_list import (
    BALCONY_GLAZING_TYPES,
    DELIVERY_CITY,
    DELIVERY_OUTSIDE,
    DOOR_FITTINGS,
    DOOR_LOCK,
    DOOR_OPENING,
    DOOR_SASH,
    DOOR_THRESHOLD,
    GLAZING,
    MOSQUITO_NET,
    NONSTANDARD_SCHEMES,
    calculate_installation,
    base_glass_key,
    glass_mod,
    get_balcony_block_parts,
    get_balcony_glazing_package,
    get_connector_price,
    get_door_price,
    get_ebb_price,
    get_sill_price,
    get_window_price,
    BALCONY_DOOR_MOSQUITO_NET,
    GLASS_UNIT_PRICE_PER_M2,
    GLASS_PRICE_PER_M2,
    I_GLASS_SURCHARGE_PER_CONSTRUCTION,
    money,
    validate_size,
)

FRIENDLY_WINDOW_CONFIGS = {
    "fixed": "глухое",
    "tilt_turn": "открывающееся с проветриванием",
    "turn": "открывающееся",
    "fixed_fixed": "два глухих стекла",
    "fixed_turn": "глухое + открывающееся",
    "fixed_tilt_turn": "глухое + открывающееся с проветриванием",
    "tilt_turn_fixed": "открывающееся с проветриванием + глухое",
    "turn_turn": "два открывающихся стекла",
    "fixed_fixed_fixed": "три глухих стекла",
    "fixed_tilt_turn_fixed": "глухое + открывающееся с проветриванием + глухое",
    "tilt_turn_fixed_tilt_turn": "два крайних открываются с проветриванием",
}
FRIENDLY_GLASS = {
    "24": "стеклопакет 24 мм",
    "32": "стеклопакет 32 мм",
    "24_i": "стеклопакет 24 мм + i (2 стороны)",
    "32_i": "стеклопакет 32 мм + i (2 стороны)",
}
FRIENDLY_DOOR = {
    "single": "одностворчатая дверь",
    "double": "двустворчатая дверь",
}
FRIENDLY_SASH = {"T": "обычная створка", "Z": "усиленная створка"}
FRIENDLY_THRESHOLD = {"alu_low": "низкий порог", "frame": "обычная рамная коробка"}
FRIENDLY_LOCK = {"single": "обычный замок", "multi": "многозапорный замок"}
FRIENDLY_FITTINGS = {"push": "нажимная ручка", "handles_closer": "ручки + доводчик"}


class PricingError(ValueError):
    pass


def split_html_message(text: str, limit: int = 4000) -> list[str]:
    """Делит Telegram HTML-сообщение по строкам, не разрывая строку с тегами."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        extra = len(line) + (1 if current else 0)
        if current and current_len + extra > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            for start in range(0, len(line), limit):
                chunks.append(line[start:start + limit])
            continue
        current.append(line)
        current_len += extra
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def measurement_fee_for_cart(cart: list[dict]) -> Decimal:
    """Стоимость специального замера для сохранённых конструкций.

    Обычный замер бесплатный. 500 ₽ берётся только если заявка содержит
    отдельный стеклопакет или москитную сетку.
    """
    for item in cart or []:
        product = item.get("product") or {}
        if product.get("construction_type") == "glass_unit" or bool(product.get("mosquito")):
            return Decimal("500.00")
    return Decimal("0.00")


class Calculator:
    def calculate(self, c: CalculationConfig) -> Estimate:
        ct = c.construction_type
        if ct == "window":
            items = self._window_items(c)
        elif ct == "balcony":
            items = self._balcony_items(c)
        elif ct == "balcony_glazing":
            items = self._balcony_glazing_items(c)
        elif ct == "door":
            items = self._door_items(c)
        elif ct == "glass_unit":
            items = self._glass_unit_items(c)
        elif ct == "nonstandard":
            items = self._nonstandard_items(c)
        else:
            raise PricingError("Неизвестный тип конструкции")

        service_items = self._service_items(c)
        product_subtotal = money(sum((x.price for x in items), Decimal("0")))
        service_subtotal = money(sum((x.price for x in service_items), Decimal("0")))
        # i с двух сторон — фиксированная доплата 2 000 ₽ за конструкцию, не увеличивает базу монтажа.
        i_surcharge = Decimal("0.00")
        if getattr(c, "glass", None) and c.glass.endswith("_i") and ct != "glass_unit":
            i_surcharge = I_GLASS_SURCHARGE_PER_CONSTRUCTION
            items.append(EstimateItem("Энергосберегающее покрытие i, 2 стороны", i_surcharge))
        # Монтаж 17% считается от конструкции и доп. элементов, но не от доставки и не от фиксированной i-доплаты.
        installation = Decimal("0.00") if ct == "glass_unit" else calculate_installation(product_subtotal)
        items.extend(service_items)
        subtotal = money(product_subtotal + service_subtotal + i_surcharge)
        return Estimate(items, subtotal, installation, money(subtotal + installation))

    def _check_size(self, c: CalculationConfig, w: int, h: int) -> None:
        err = validate_size(
            w, h,
            construction_type=c.construction_type or "window",
            sash_count=c.sash_count,
            configuration=c.extras.get("sash_configuration") or c.opening,
        )
        if err:
            raise PricingError(err)

    def _window_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.width_mm or not c.height_mm or c.width_mm <= 0 or c.height_mm <= 0:
            raise PricingError("Укажите корректные размеры")
        self._check_size(c, c.width_mm, c.height_mm)
        if not c.profile or not c.glass or not c.sash_count:
            raise PricingError("Не заполнены параметры окна")
        config = c.extras.get("sash_configuration") or c.opening
        if not config:
            raise PricingError("Не выбрана конфигурация створок")
        try:
            base = get_window_price(c.sash_count, config, c.profile, c.glass, c.width_mm, c.height_mm)
        except ValueError as e:
            raise PricingError(str(e)) from e
        direction = ""
        if c.opening_direction and config in ("turn", "tilt_turn", "fixed_turn", "fixed_tilt_turn", "turn_turn"):
            direction = f", открывание {'левое' if c.opening_direction == 'left' else 'правое'}"
        items = [
            EstimateItem(
                f"Окно {c.width_mm}×{c.height_mm} мм, {c.profile} мм, "
                f"{FRIENDLY_GLASS.get(c.glass, c.glass)}{direction}",
                base,
            )
        ]
        items.extend(self._sill_items(c))
        items.extend(self._ebb_items(c))
        items.extend(self._mosquito_items(c))
        return items

    def _balcony_items(self, c: CalculationConfig) -> list[EstimateItem]:
        """Балконный блок: дверь + окно + соединительный профиль.

        Базовый прайс задан для типового блока 700×2100 + 600×1400.
        Для собственных размеров оконная и дверная части масштабируются по площади,
        чтобы введённые размеры действительно влияли на ориентировочную цену.
        """
        profile = c.profile or "70"
        glass = c.glass or "32"
        door_w = c.door_width_mm or 700
        door_h = c.door_height_mm or 2100
        win_w = c.window_width_mm or c.width_mm or 600
        win_h = c.window_height_mm or 1400
        win_cfg = c.window_configuration or c.extras.get("sash_configuration") or "tilt_turn"
        opening = c.door_type or "single"
        sash = c.door_sash or "T"

        door_err = validate_size(door_w, door_h, "door")
        if door_err:
            raise PricingError(door_err)
        win_err = validate_size(win_w, win_h, "window", c.window_sash_count or 1, win_cfg)
        if win_err:
            raise PricingError(win_err)

        parts = get_balcony_block_parts(profile, win_cfg)
        door_area_ratio = Decimal(door_w * door_h) / Decimal(700 * 2100)
        window_area_ratio = Decimal(win_w * win_h) / Decimal(600 * 1400)
        door_area_ratio = max(Decimal("0.60"), min(door_area_ratio, Decimal("3.00")))
        window_area_ratio = max(Decimal("0.60"), min(window_area_ratio, Decimal("3.00")))

        from pricing.price_list import DOOR_THRESHOLD_PRICE, DOOR_LOCK_PRICE, DOOR_FITTINGS_PRICE
        thr = c.door_threshold or "frame"
        lock = c.door_lock or "single"
        fit = c.door_fittings or "push"
        door_extra = (
            DOOR_THRESHOLD_PRICE.get(thr, Decimal("0"))
            + DOOR_LOCK_PRICE.get(lock, Decimal("0"))
            + DOOR_FITTINGS_PRICE.get(fit, Decimal("0"))
        )
        door_price = money(parts["door"] * door_area_ratio + door_extra)
        window_price = money(parts["window"] * window_area_ratio)
        connector_price = money(parts["connector"] * Decimal(max(door_h, win_h)) / Decimal("2100"))
        glass_base = base_glass_key(glass)
        if glass_base not in GLASS_PRICE_PER_M2:
            raise PricingError("Для балконного блока доступны СП 24 и 32 мм")
        glass_area = Decimal(door_w * door_h + win_w * win_h) / Decimal("1000000")
        glass_price = money(glass_area * GLASS_PRICE_PER_M2[glass_base])
        door_mode = getattr(c, "door_opening_mode", None) or "tilt_turn"
        door_mode_label = "поворотно-откидная" if door_mode == "tilt_turn" else "поворотная"
        items = [
            EstimateItem(
                f"Дверь блока {door_w}×{door_h} мм, {profile} мм, "
                f"{door_mode_label}, {FRIENDLY_GLASS.get(glass, glass)}",
                door_price,
            ),
            EstimateItem(
                f"Окно блока {win_w}×{win_h} мм, {profile} мм, {FRIENDLY_WINDOW_CONFIGS.get(win_cfg, win_cfg)}, "
                f"{FRIENDLY_GLASS.get(glass, glass)}",
                window_price,
            ),
            EstimateItem(
                f"Соединительный профиль H={max(door_h, win_h)} мм",
                connector_price,
            ),
            EstimateItem(f"Стеклопакет {FRIENDLY_GLASS.get(glass, glass)}, {glass_area:.2f} м²", glass_price),
        ]
        # Если клиент выбрал «Без подоконника», ничего за него не начисляем.
        if c.sill_type:
            sill_kind = c.sill_type
            sill_depth = c.sill_depth_mm or 300
            sill_len_win = c.sill_length_mm or win_w
            try:
                p1 = get_sill_price(sill_kind, sill_depth, sill_len_win)
            except ValueError as e:
                raise PricingError(str(e)) from e
            items.append(EstimateItem(f"Подоконник внутренний (окно) {sill_depth}×{sill_len_win} мм", p1))
            sill2_kind = c.sill2_type or sill_kind
            sill2_depth = c.sill2_depth_mm or sill_depth
            sill2_len = c.sill2_length_mm or door_w
            try:
                p2 = get_sill_price(sill2_kind, sill2_depth, sill2_len)
            except ValueError as e:
                raise PricingError(str(e)) from e
            items.append(EstimateItem(f"Подоконник внутренний (дверь) {sill2_depth}×{sill2_len} мм", p2))
        if getattr(c, "door_mosquito", False):
            items.append(EstimateItem("Дверная москитная сетка", BALCONY_DOOR_MOSQUITO_NET))
        items.extend(self._mosquito_items(c))
        return items

    def _door_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.width_mm or not c.height_mm or c.width_mm <= 0 or c.height_mm <= 0:
            raise PricingError("Укажите корректные размеры двери")
        self._check_size(c, c.width_mm, c.height_mm)
        opening = c.door_type or c.opening
        sash = c.door_sash
        threshold = c.door_threshold
        lock = c.door_lock
        fittings = c.door_fittings
        glass = c.glass or "32"
        if not all([opening, sash, threshold, lock, fittings]):
            raise PricingError("Не заполнены параметры двери")
        try:
            price = get_door_price(opening, sash, threshold, lock, fittings, glass)
        except ValueError as e:
            raise PricingError(str(e)) from e
        base_glass = base_glass_key(glass)
        if base_glass not in GLASS_PRICE_PER_M2:
            raise PricingError("Доступны только стеклопакеты 24 и 32 мм")
        price += money((Decimal(c.width_mm * c.height_mm) / Decimal("1000000")) * GLASS_PRICE_PER_M2[base_glass])
        # i-доплата учитывается единообразно в общем калькуляторе,
        # чтобы она не попадала в базу, к которой применяется монтаж 17%.
        price = money(price)
        direction = ""
        if c.opening_direction:
            direction = f", {'левое' if c.opening_direction == 'left' else 'правое'} открывание"
        parts = [
            f"Дверь ПВХ {c.width_mm}×{c.height_mm} мм, 70 мм",
            FRIENDLY_DOOR.get(opening, opening),
            FRIENDLY_SASH.get(sash, sash),
            FRIENDLY_THRESHOLD.get(threshold, threshold),
            FRIENDLY_LOCK.get(lock, lock),
            FRIENDLY_FITTINGS.get(fittings, fittings),
            FRIENDLY_GLASS.get(glass, glass) + direction,
        ]
        items = [EstimateItem(", ".join(parts), price)]
        items.extend(self._sill_items(c))
        items.extend(self._mosquito_items(c))
        return items

    def _nonstandard_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.scheme_key or c.scheme_key not in NONSTANDARD_SCHEMES:
            raise PricingError("Не выбрана схема другой конструкции")
        if not c.width_mm or not c.height_mm or c.width_mm <= 0 or c.height_mm <= 0:
            raise PricingError("Укажите корректные размеры")
        config = c.extras.get("sash_configuration") or "fixed_tilt_turn"
        size_err = validate_size(c.width_mm, c.height_mm, "window", c.sash_count, config)
        if size_err:
            raise PricingError(size_err)
        if not c.profile or not c.glass:
            raise PricingError("Не заполнены профиль и стеклопакет")
        scheme = NONSTANDARD_SCHEMES[c.scheme_key]
        sash_count = c.sash_count or 2
        try:
            base = get_window_price(sash_count, config, c.profile, c.glass, c.width_mm, c.height_mm)
        except ValueError as e:
            raise PricingError(str(e)) from e
        complexity = money(base * Decimal("0.12"))
        items = [
            EstimateItem(
                f"Другая конструкция {c.width_mm}×{c.height_mm} мм, {c.profile} мм, "
                f"{scheme['label']}, {FRIENDLY_GLASS.get(c.glass, c.glass)}",
                base,
            ),
            EstimateItem("Составная конструкция (импосты / фрамуга)", complexity),
        ]
        items.extend(self._sill_items(c))
        items.extend(self._ebb_items(c))
        items.extend(self._mosquito_items(c))
        return items

    def _sill_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.sill_type:
            return []
        try:
            p = get_sill_price(c.sill_type, c.sill_depth_mm or 0, c.sill_length_mm or c.width_mm or 0)
        except ValueError as e:
            raise PricingError(str(e)) from e
        return [EstimateItem("Подоконник", p)]

    def _ebb_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.ebb_width_mm:
            return []
        try:
            p = get_ebb_price(c.ebb_width_mm, c.width_mm or 0)
        except ValueError as e:
            raise PricingError(str(e)) from e
        return [EstimateItem("Отлив", p)]

    def _mosquito_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.mosquito:
            return []
        return [EstimateItem("Москитная сетка", MOSQUITO_NET["standard"])]

    def _glass_unit_items(self, c: CalculationConfig) -> list[EstimateItem]:
        if not c.width_mm or not c.height_mm or c.width_mm <= 0 or c.height_mm <= 0:
            raise PricingError("Укажите размеры стеклопакета")
        glass = c.glass or "32"
        base = base_glass_key(glass)
        if base not in GLASS_UNIT_PRICE_PER_M2:
            raise PricingError("Доступны стеклопакеты 24 и 32 мм")
        area = Decimal(c.width_mm * c.height_mm) / Decimal("1000000")
        price = money(area * GLASS_UNIT_PRICE_PER_M2[base])
        items = [EstimateItem(f"Стеклопакет {FRIENDLY_GLASS.get(glass, glass)}, {c.width_mm}×{c.height_mm} мм ({area:.2f} м²)", price)]
        if glass_mod(glass) == "i":
            items.append(EstimateItem("Энергосберегающее покрытие i, 2 стороны", I_GLASS_SURCHARGE_PER_CONSTRUCTION))
        return items

    def _service_items(self, c: CalculationConfig) -> list[EstimateItem]:
        items: list[EstimateItem] = []
        if c.delivery == "city":
            items.append(EstimateItem("Доставка по городу", DELIVERY_CITY))
        elif c.delivery == "outside":
            items.append(EstimateItem("Доставка за город", DELIVERY_OUTSIDE))
        return items

    def _balcony_glazing_items(self, c: CalculationConfig) -> list[EstimateItem]:
        """Балконная рама — ориентировочный диапазон без точной сметы."""
        kind = c.scheme_key or (c.extras or {}).get("glazing_kind") or "frame"
        profile = c.profile or "58"
        if kind not in BALCONY_GLAZING_TYPES:
            raise PricingError("Выберите тип балконной рамы")
        try:
            low, high = get_balcony_glazing_package(kind, profile)
        except ValueError as e:
            raise PricingError(str(e)) from e
        label = BALCONY_GLAZING_TYPES[kind]["label"]
        midpoint = money((low + high) / Decimal("2"))
        items = [
            EstimateItem(
                f"{label}, профиль {profile} мм — ориентир {low:,.0f}–{high:,.0f} ₽".replace(",", " "),
                midpoint,
            )
        ]
        items.extend(self._mosquito_items(c))
        return items



calculator = Calculator()
