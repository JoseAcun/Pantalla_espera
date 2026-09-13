"""Strict, versioned source data and idempotent MariaDB catalog import for TLOZ."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import create_engine, text


CATALOG_DIR = Path(__file__).resolve().parents[2] / "data" / "tloz"
LAYOUT_KEYS = {"16_9", "4_3", "handheld", "ds", "3ds"}
OBJECTIVE_KINDS = {"required", "optional"}


class CatalogError(ValueError):
    """The source data cannot safely be imported."""


class CatalogGame(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=160)
    era: str = Field(default="", max_length=80)
    timeline_branch: str = Field(default="", max_length=80)
    chronology_order: int = Field(ge=1, le=10_000)
    release_year: int | None = Field(default=None, ge=1980, le=2100)
    platform: str = Field(default="", max_length=80)
    layout_key: str
    twitch_category_id: str = Field(default="", max_length=32)
    enabled: bool = True

    @field_validator("layout_key")
    @classmethod
    def require_supported_layout(cls, value: str) -> str:
        if value not in LAYOUT_KEYS:
            raise ValueError(f"layout_key debe ser uno de {sorted(LAYOUT_KEYS)}")
        return value


class CatalogObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=255)
    kind: str
    chronology_order: int = Field(ge=1, le=10_000)
    description: str = Field(default="", max_length=500)
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def require_supported_kind(cls, value: str) -> str:
        if value not in OBJECTIVE_KINDS:
            raise ValueError("kind debe ser required u optional")
        return value


class CatalogZone(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    name: str = Field(min_length=2, max_length=160)
    chronology_order: int = Field(ge=1, le=10_000)
    objectives: list[CatalogObjective] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_objectives(self) -> "CatalogZone":
        _assert_unique([item.slug for item in self.objectives], f"objetivos de {self.slug}")
        _assert_unique([item.chronology_order for item in self.objectives], f"orden de objetivos de {self.slug}")
        return self


class ChronologyCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(eq=1)
    games: list[CatalogGame] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_games(self) -> "ChronologyCatalog":
        _assert_unique([game.slug for game in self.games], "slugs de juegos")
        _assert_unique([game.chronology_order for game in self.games], "orden de cronología")
        return self


class GameContentCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: int = Field(eq=1)
    game_slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    zones: list[CatalogZone] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_zones(self) -> "GameContentCatalog":
        _assert_unique([zone.slug for zone in self.zones], f"zonas de {self.game_slug}")
        _assert_unique([zone.chronology_order for zone in self.zones], f"orden de zonas de {self.game_slug}")
        return self


@dataclass(frozen=True)
class TlozCatalog:
    chronology: ChronologyCatalog
    content: tuple[GameContentCatalog, ...]


@dataclass(frozen=True)
class CatalogImportResult:
    games: int
    zones: int
    objectives: int


def _assert_unique(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Hay valores duplicados en {label}.")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"No se puede leer {path.name}: {error}") from error


def load_catalog(catalog_dir: Path = CATALOG_DIR) -> TlozCatalog:
    """Load every committed game content file before one database write occurs."""
    chronology_path = catalog_dir / "chronology.json"
    try:
        chronology = ChronologyCatalog.model_validate(_read_json(chronology_path))
        content = tuple(
            GameContentCatalog.model_validate(_read_json(path))
            for path in sorted(catalog_dir.glob("*.game.json"))
        )
    except ValidationError as error:
        raise CatalogError(f"Catálogo TLOZ inválido: {error}") from error
    known_games = {game.slug for game in chronology.games}
    for item in content:
        if item.game_slug not in known_games:
            raise CatalogError(f"{item.game_slug}.game.json referencia un juego ausente de chronology.json.")
    _assert_unique([item.game_slug for item in content], "archivos de contenido por juego")
    return TlozCatalog(chronology=chronology, content=content)


class TlozCatalogImporter:
    """Upserts catalog definitions; it never deletes progress, playthroughs or manual rows."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def import_catalog(self, catalog: TlozCatalog) -> CatalogImportResult:
        games = {game.slug: game for game in catalog.chronology.games}
        zone_count = objective_count = 0
        with self.engine.begin() as connection:
            game_ids = {slug: self._upsert_game(connection, game) for slug, game in games.items()}
            for game_content in catalog.content:
                game_id = game_ids[game_content.game_slug]
                for zone in game_content.zones:
                    zone_id = self._upsert_zone(connection, game_id, zone)
                    zone_count += 1
                    for objective in zone.objectives:
                        self._upsert_objective(connection, zone_id, objective)
                        objective_count += 1
        return CatalogImportResult(games=len(games), zones=zone_count, objectives=objective_count)

    def import_default_catalog(self) -> CatalogImportResult:
        return self.import_catalog(load_catalog())

    @staticmethod
    def _upsert_game(connection: Any, game: CatalogGame) -> int:
        connection.execute(text("""
            INSERT INTO tloz_games (
                slug, title, twitch_category_id, chronology_order, era, timeline_branch, release_year, platform, layout_key, enabled
            ) VALUES (
                :slug, :title, NULLIF(:twitch_category_id, ''), :chronology_order, :era, :timeline_branch, :release_year, :platform, :layout_key, :enabled
            ) ON DUPLICATE KEY UPDATE
                title=VALUES(title), chronology_order=VALUES(chronology_order), era=VALUES(era), timeline_branch=VALUES(timeline_branch),
                release_year=VALUES(release_year), platform=VALUES(platform), layout_key=VALUES(layout_key), enabled=VALUES(enabled),
                twitch_category_id=COALESCE(VALUES(twitch_category_id), twitch_category_id)
        """), game.model_dump())
        return int(connection.execute(text("SELECT id FROM tloz_games WHERE slug=:slug"), {"slug": game.slug}).scalar_one())

    @staticmethod
    def _upsert_zone(connection: Any, game_id: int, zone: CatalogZone) -> int:
        connection.execute(text("""
            INSERT INTO tloz_zones (game_id, slug, name, chronology_order)
            VALUES (:game_id, :slug, :name, :chronology_order)
            ON DUPLICATE KEY UPDATE name=VALUES(name), chronology_order=VALUES(chronology_order)
        """), {**zone.model_dump(exclude={"objectives"}), "game_id": game_id})
        return int(connection.execute(text("SELECT id FROM tloz_zones WHERE game_id=:game_id AND slug=:slug"), {"game_id": game_id, "slug": zone.slug}).scalar_one())

    @staticmethod
    def _upsert_objective(connection: Any, zone_id: int, objective: CatalogObjective) -> None:
        connection.execute(text("""
            INSERT INTO tloz_objectives (zone_id, slug, title, kind, chronology_order, description, enabled)
            VALUES (:zone_id, :slug, :title, :kind, :chronology_order, :description, :enabled)
            ON DUPLICATE KEY UPDATE title=VALUES(title), kind=VALUES(kind), chronology_order=VALUES(chronology_order),
                description=VALUES(description), enabled=VALUES(enabled)
        """), {**objective.model_dump(), "zone_id": zone_id})
