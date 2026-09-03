"""Pure, versioned progression rules for STREAM_OS players."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class ProgressionConfig:
    base_xp: int = 100
    growth: Decimal = Decimal("1.15")
    rounding: int = 5

    def __post_init__(self) -> None:
        if self.base_xp < 1:
            raise ValueError("base_xp debe ser positivo.")
        if self.growth <= 1:
            raise ValueError("growth debe ser mayor que 1.")
        if self.rounding < 1:
            raise ValueError("rounding debe ser positivo.")


DEFAULT_PROGRESSION = ProgressionConfig()


def xp_required_for_next_level(level: int, config: ProgressionConfig = DEFAULT_PROGRESSION) -> int:
    """XP needed to advance from ``level`` to ``level + 1``."""
    if level < 1:
        raise ValueError("El nivel debe ser al menos 1.")
    raw = Decimal(config.base_xp) * (config.growth ** (level - 1))
    units = (raw / Decimal(config.rounding)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(units * config.rounding)


def cumulative_xp_for_level(level: int, config: ProgressionConfig = DEFAULT_PROGRESSION) -> int:
    """Total XP required to have reached ``level`` (level 1 starts at zero)."""
    if level < 1:
        raise ValueError("El nivel debe ser al menos 1.")
    return sum(xp_required_for_next_level(current, config) for current in range(1, level))


def level_from_total_xp(total_xp: int, config: ProgressionConfig = DEFAULT_PROGRESSION) -> int:
    """Derive a player level from immutable total earned XP."""
    if total_xp < 0:
        raise ValueError("La XP total no puede ser negativa.")
    level = 1
    remaining = total_xp
    while remaining >= (required := xp_required_for_next_level(level, config)):
        remaining -= required
        level += 1
    return level


def xp_progress_in_level(total_xp: int, config: ProgressionConfig = DEFAULT_PROGRESSION) -> tuple[int, int]:
    """Return XP earned in the current level and the requirement for its next level."""
    level = level_from_total_xp(total_xp, config)
    return total_xp - cumulative_xp_for_level(level, config), xp_required_for_next_level(level, config)
