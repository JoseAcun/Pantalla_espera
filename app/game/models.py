from datetime import datetime

from pydantic import BaseModel, Field


class ChatActor(BaseModel):
    user_id: str
    login: str
    display_name: str


class PlayerProfile(BaseModel):
    user_id: str
    display_name: str
    level: int = 1
    xp: int = 0
    credits: int = 0


class EncounterState(BaseModel):
    id: str
    category_id: str = ""
    boss_name: str
    max_hp: int
    current_hp: int
    max_party_integrity: int
    party_integrity: int
    round_number: int
    round_seconds: int = 15
    boss_damage: int = 12
    boss_intent: str = "attack"
    round_ends_at: datetime
    status: str


class CategoryContent(BaseModel):
    category_id: str
    name: str
    theme_key: str = "stream_os_generic"
    enabled: bool = True


class BossDefinitionInput(BaseModel):
    category_id: str | None = None
    name: str = Field(min_length=2, max_length=255)
    max_hp: int = Field(ge=100, le=1_000_000)
    base_party_damage: int = Field(default=12, ge=0, le=10_000)
    round_seconds: int = Field(default=30, ge=5, le=120)
    party_integrity: int = Field(default=1000, ge=100, le=1_000_000)


class ItemDefinitionInput(BaseModel):
    category_id: str | None = None
    name: str = Field(min_length=2, max_length=255)
    rarity: str = Field(default="common", pattern=r"^(common|uncommon|rare|epic|legendary|corrupted)$")
    slot: str = Field(default="weapon", pattern=r"^(weapon|armor|accessory|consumable)$")
    effect_type: str = Field(default="none", max_length=64)
    effect_value: int = Field(default=0, ge=-1000, le=1000)
    weight: int = Field(default=100, ge=1, le=10000)


class ItemDefinition(ItemDefinitionInput):
    id: int
    enabled: bool = True


class QuestDefinitionInput(BaseModel):
    """A reusable personal quest template managed from Game Master."""

    category_id: str | None = None
    cadence: str = Field(pattern=r"^(daily|weekly)$")
    name: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=500)
    objective_type: str = Field(
        pattern=r"^(chat_messages|activity_windows|stream_days|raid_actions)$"
    )
    objective_target: int = Field(ge=1, le=10_000)
    reward_xp: int = Field(default=0, ge=0, le=1_000_000)
    reward_credits: int = Field(default=0, ge=0, le=1_000_000)
    reward_random_item: bool = False


class QuestDefinition(QuestDefinitionInput):
    id: int
    enabled: bool = True
