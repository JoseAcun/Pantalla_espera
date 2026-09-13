"""CLI entrypoint: docker compose exec overlay python -m app.tloz.import_catalog."""

from app.config import get_settings
from app.tloz.catalog import TlozCatalogImporter


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL no está configurada.")
    result = TlozCatalogImporter(settings.database_url).import_default_catalog()
    print(f"Catálogo TLOZ sincronizado: {result.games} juegos, {result.zones} zonas y {result.objectives} objetivos.")


if __name__ == "__main__":
    main()
