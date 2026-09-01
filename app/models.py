from datetime import datetime

from pydantic import BaseModel, Field


class FollowEvent(BaseModel):
    user_id: str = ""
    user_login: str = ""
    username: str = "—"
    timestamp: datetime | None = None


class SubscriptionEvent(BaseModel):
    user_id: str = ""
    user_login: str = ""
    username: str = "—"
    tier: str = ""
    timestamp: datetime | None = None


class CheerEvent(BaseModel):
    user_login: str = ""
    username: str = "—"
    bits: int = 0
    message: str = ""
    timestamp: datetime | None = None


class RaidEvent(BaseModel):
    broadcaster_login: str = ""
    username: str = "—"
    viewers: int = 0
    timestamp: datetime | None = None


class StreamState(BaseModel):
    twitch_stream_id: str = ""
    broadcaster_id: str = ""
    broadcaster_login: str = ""
    streamer: str = "STREAMER"
    game: str = "NO GAME SELECTED"
    category: str = ""
    category_id: str = ""
    title: str = ""
    status: str = "AFK"
    episode: str = ""
    custom_message: str = ""
    is_live: bool = False
    viewer_count: int = 0
    stream_started_at: datetime | None = None
    last_follower: FollowEvent = Field(default_factory=FollowEvent)
    last_subscriber: SubscriptionEvent = Field(default_factory=SubscriptionEvent)
    last_cheer: CheerEvent = Field(default_factory=CheerEvent)
    last_raid: RaidEvent = Field(default_factory=RaidEvent)
