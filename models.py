from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class EstimateItem:
    name: str
    price: Decimal


@dataclass(frozen=True)
class Estimate:
    items: list[EstimateItem]
    subtotal: Decimal
    installation: Decimal
    total: Decimal

    def summary_line(self) -> str:
        return f"{self.total:,.2f}".replace(",", "\u00a0") + " ₽"


@dataclass
class CalculationConfig:
    construction_type: str = ""
    profile: str | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    sash_count: int | None = None
    blind_parts: int | None = None
    opening: str | None = None
    glass: str | None = None
    transom: bool | None = None
    door_type: str | None = None
    door_sash: str | None = None
    door_threshold: str | None = None
    door_lock: str | None = None
    door_fittings: str | None = None
    door_opening_mode: str | None = None  # turn | tilt_turn, для двери балконного блока
    door_mosquito: bool = False
    opening_direction: str | None = None  # left | right
    sill_type: str | None = None
    sill_depth_mm: int | None = None
    sill_length_mm: int | None = None
    sill2_type: str | None = None
    sill2_depth_mm: int | None = None
    sill2_length_mm: int | None = None
    ebb_type: str | None = None
    ebb_width_mm: int | None = None
    mosquito: bool = False
    # Дополнительные услуги
    delivery: str | None = None  # None | city | outside
    scheme_key: str | None = None
    window_width_mm: int | None = None
    window_height_mm: int | None = None
    window_sash_count: int | None = None
    window_configuration: str | None = None
    door_width_mm: int | None = None
    door_height_mm: int | None = None
    house_type: str | None = None  # panel | brick | new
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def short_title(self) -> str:
        ct = self.construction_type
        if ct == "window":
            return f"Окно {self.width_mm}×{self.height_mm}"
        if ct == "door":
            return f"Дверь {self.width_mm}×{self.height_mm}"
        if ct == "glass_unit":
            return f"Стеклопакет {self.width_mm}×{self.height_mm}"
        if ct == "balcony":
            return f"Балконный блок {self.door_width_mm}+{self.window_width_mm}"
        if ct == "nonstandard":
            return f"Другая конструкция {self.width_mm}×{self.height_mm}"
        return ct or "Изделие"
