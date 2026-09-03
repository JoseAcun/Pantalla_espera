from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded only by the backend from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
    twitch_access_token: str | None = None
    twitch_refresh_token: str | None = None
    twitch_broadcaster_id: str | None = None
    twitch_redirect_uri: str = "http://localhost:8000/auth/twitch/callback"
    twitch_token_file: str = ".twitch_tokens.json"
    database_url: str | None = None
    overlay_admin_token: str | None = None
    pokemon_data_dir: str = "data"
    overlay_status: str = "AFK"
    overlay_episode: str = ""
    overlay_custom_message: str = ""
    viewer_snapshot_interval_seconds: int = Field(default=300, ge=1)
    game_level_base_xp: int = Field(default=100, ge=1)
    game_level_growth: float = Field(default=1.15, gt=1)
    game_level_rounding: int = Field(default=5, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
