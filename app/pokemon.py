"""PokéAPI lookup plus a small persistent six-member team for the OBS overlay."""

import asyncio
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field


POKEAPI_URL = "https://pokeapi.co/api/v2"
MAX_TEAM_SIZE = 6


class PokemonError(RuntimeError):
    pass


class PokemonMember(BaseModel):
    slot: int = Field(ge=1, le=MAX_TEAM_SIZE)
    pokemon_id: int
    pokemon_name: str
    display_name: str
    nickname: str = ""
    types: list[str] = Field(default_factory=list)
    sprite_url: str


class PokemonTeam(BaseModel):
    members: list[PokemonMember] = Field(default_factory=list)


class PokemonTeamStore:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.file = self.data_dir / "pokemon_team.json"
        self.sprites_dir = self.data_dir / "pokemon-sprites"
        self.lock = threading.Lock()

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sprites_dir.mkdir(parents=True, exist_ok=True)

    def get_team(self) -> PokemonTeam:
        with self.lock:
            if not self.file.exists():
                return PokemonTeam()
            try:
                return PokemonTeam.model_validate_json(self.file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise PokemonError("No se pudo leer la configuración del equipo Pokémon.") from error

    def save_member(self, member: PokemonMember) -> PokemonTeam:
        with self.lock:
            team = self.get_team_unlocked()
            members = [item for item in team.members if item.slot != member.slot]
            members.append(member)
            team = PokemonTeam(members=sorted(members, key=lambda item: item.slot))
            self.write_unlocked(team)
            return team

    def clear_slot(self, slot: int) -> PokemonTeam:
        with self.lock:
            team = self.get_team_unlocked()
            team = PokemonTeam(members=[item for item in team.members if item.slot != slot])
            self.write_unlocked(team)
            return team

    def get_team_unlocked(self) -> PokemonTeam:
        if not self.file.exists():
            return PokemonTeam()
        try:
            return PokemonTeam.model_validate_json(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PokemonError("No se pudo leer la configuración del equipo Pokémon.") from error

    def write_unlocked(self, team: PokemonTeam) -> None:
        temp_file = self.file.with_suffix(".tmp")
        temp_file.write_text(team.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temp_file, self.file)


class PokeApiClient:
    def __init__(self, store: PokemonTeamStore) -> None:
        self.store = store
        self._catalog: list[dict[str, str]] | None = None
        self._catalog_lock = asyncio.Lock()

    async def search(self, query: str) -> list[dict[str, str]]:
        normalized = self.normalize_identifier(query)
        if not normalized:
            return []
        catalog = await self.catalog()
        return [item for item in catalog if normalized in item["name"]][:18]

    async def make_member(self, slot: int, identifier: str, nickname: str) -> PokemonMember:
        name = self.normalize_identifier(identifier)
        if not name:
            raise PokemonError("Elige un Pokémon válido.")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            pokemon_response = await client.get(f"{POKEAPI_URL}/pokemon/{name}")
            if pokemon_response.status_code == 404:
                raise PokemonError("No encontré ese Pokémon en PokéAPI.")
            if pokemon_response.is_error:
                raise PokemonError(f"PokéAPI no respondió correctamente ({pokemon_response.status_code}).")
            pokemon = pokemon_response.json()
            species_response = await client.get(pokemon["species"]["url"])
            if species_response.is_error:
                raise PokemonError("No se pudo consultar el nombre localizado del Pokémon.")
            species = species_response.json()
            sprite_source = (pokemon.get("sprites", {}).get("other", {}).get("official-artwork", {}).get("front_default")
                             or pokemon.get("sprites", {}).get("front_default"))
            if not sprite_source:
                raise PokemonError("Ese Pokémon no tiene un sprite disponible.")
            sprite_url = await self.cache_sprite(client, int(pokemon["id"]), sprite_source)
        spanish_name = next((entry["name"] for entry in species.get("names", []) if entry.get("language", {}).get("name") == "es"), pokemon["name"].replace("-", " ").title())
        return PokemonMember(
            slot=slot,
            pokemon_id=pokemon["id"],
            pokemon_name=pokemon["name"],
            display_name=spanish_name,
            nickname=nickname.strip(),
            types=[entry["type"]["name"] for entry in pokemon.get("types", [])],
            sprite_url=sprite_url,
        )

    async def catalog(self) -> list[dict[str, str]]:
        if self._catalog is not None:
            return self._catalog
        async with self._catalog_lock:
            if self._catalog is not None:
                return self._catalog
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{POKEAPI_URL}/pokemon", params={"limit": 2000, "offset": 0})
            if response.is_error:
                raise PokemonError(f"No se pudo obtener el catálogo Pokémon ({response.status_code}).")
            self._catalog = response.json().get("results", [])
            return self._catalog

    async def cache_sprite(self, client: httpx.AsyncClient, pokemon_id: int, source_url: str) -> str:
        destination = self.store.sprites_dir / f"{pokemon_id}.png"
        if not destination.exists():
            response = await client.get(source_url)
            if response.is_error:
                raise PokemonError("No se pudo descargar el sprite del Pokémon.")
            destination.write_bytes(response.content)
        return f"/pokemon/sprites/{pokemon_id}.png"

    @staticmethod
    def normalize_identifier(value: str) -> str:
        return re.sub(r"[^a-z0-9-]", "", value.strip().lower().replace(" ", "-"))
