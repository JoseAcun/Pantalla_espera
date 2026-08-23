from functools import lru_cache

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
    overlay_status: str = "AFK"
    overlay_episode: str = ""
    overlay_custom_message: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
