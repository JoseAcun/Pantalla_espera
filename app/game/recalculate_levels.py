"""CLI: refresh the cached game_players.level column from total XP."""

from decimal import Decimal

from app.config import get_settings
from app.game.progression import ProgressionConfig
from app.game.repository import GameRepository


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL no está configurada.")
    progression = ProgressionConfig(
        base_xp=settings.game_level_base_xp,
        growth=Decimal(str(settings.game_level_growth)),
        rounding=settings.game_level_rounding,
    )
    count = GameRepository(settings.database_url, progression).recalculate_levels()
    print(f"Niveles recalculados: {count}")


if __name__ == "__main__":
    main()
