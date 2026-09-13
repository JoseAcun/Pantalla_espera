import unittest

from app.tloz.catalog import TlozCatalogImporter, load_catalog


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one(self):
        return self.value


class _MemoryConnection:
    """A minimal SQL sink used to check import identity without a real MariaDB."""

    def __init__(self):
        self.games: dict[str, dict] = {}
        self.zones: dict[tuple[int, str], dict] = {}
        self.objectives: dict[tuple[int, str], dict] = {}
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        params = params or {}
        if "INSERT INTO tloz_games" in sql:
            self.games.setdefault(params["slug"], {"id": len(self.games) + 1}).update(params)
        elif "SELECT id FROM tloz_games" in sql:
            return _Result(self.games[params["slug"]]["id"])
        elif "INSERT INTO tloz_zones" in sql:
            key = (params["game_id"], params["slug"])
            self.zones.setdefault(key, {"id": len(self.zones) + 1}).update(params)
        elif "SELECT id FROM tloz_zones" in sql:
            return _Result(self.zones[(params["game_id"], params["slug"])]["id"])
        elif "INSERT INTO tloz_objectives" in sql:
            key = (params["zone_id"], params["slug"])
            self.objectives.setdefault(key, {}).update(params)
        return _Result()


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_):
        return False


class _MemoryEngine:
    def __init__(self, connection):
        self.connection = connection

    def begin(self):
        return _Transaction(self.connection)


class TlozCatalogTests(unittest.TestCase):
    def test_committed_catalog_is_consistent_and_has_two_playable_examples(self) -> None:
        catalog = load_catalog()
        self.assertEqual(len(catalog.chronology.games), 19)
        self.assertEqual({entry.game_slug for entry in catalog.content}, {"skyward-sword", "the-minish-cap"})
        self.assertEqual(sum(len(entry.zones) for entry in catalog.content), 22)
        self.assertEqual(sum(len(zone.objectives) for entry in catalog.content for zone in entry.zones), 71)
        self.assertTrue(all(not game.twitch_category_id for game in catalog.chronology.games))

    def test_reimport_uses_stable_slugs_without_duplicate_rows(self) -> None:
        connection = _MemoryConnection()
        importer = object.__new__(TlozCatalogImporter)
        importer.engine = _MemoryEngine(connection)
        catalog = load_catalog()

        first = importer.import_catalog(catalog)
        second = importer.import_catalog(catalog)

        self.assertEqual(first, second)
        self.assertEqual((len(connection.games), len(connection.zones), len(connection.objectives)), (19, 22, 71))
        upserts = [sql for sql in connection.statements if "INSERT INTO tloz_" in sql]
        self.assertTrue(upserts)
        self.assertTrue(all("ON DUPLICATE KEY UPDATE" in sql for sql in upserts))
        self.assertFalse(any("DELETE" in sql.upper() for sql in connection.statements))
