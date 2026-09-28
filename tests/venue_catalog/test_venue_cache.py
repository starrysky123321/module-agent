import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call

from redis.exceptions import RedisError

from module_agent.venue_catalog.domain.models import Venue, VenueRanking, VenueType
from module_agent.venue_catalog.adapters.cache import RedisVenueCache


def example_venue() -> Venue:
    return Venue(
        id=1,
        canonical_name="Example Conference",
        venue_type=VenueType.CONFERENCE,
        aliases=["EC"],
        rankings=[
            VenueRanking(
                ranking_system="core",
                level="A",
                edition_year=2026,
            )
        ],
    )


def redis_client_mock() -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock()
    client.set = AsyncMock()
    client.delete = AsyncMock()
    return client


async def scanned_keys(keys: list[str]):
    for key in keys:
        yield key


def test_venue_cache_returns_none_on_miss() -> None:
    client = redis_client_mock()
    client.get.return_value = None
    cache = RedisVenueCache(client)

    venue = asyncio.run(cache.get("Unknown"))

    assert venue is None
    client.get.assert_awaited_once_with("venue:v1:unknown")


def test_venue_cache_round_trips_json_with_ttl() -> None:
    client = redis_client_mock()
    venue = example_venue()
    client.get.return_value = venue.model_dump_json()
    cache = RedisVenueCache(client, ttl_seconds=300)

    async def round_trip() -> Venue | None:
        await cache.set(" Example   Conference ", venue)
        return await cache.get("example conference")

    restored = asyncio.run(round_trip())

    assert restored == venue
    set_call = client.set.await_args
    assert set_call.args[0] == "venue:v1:example conference"
    assert json.loads(set_call.args[1]) == venue.model_dump(mode="json")
    assert set_call.kwargs == {"ex": 300}


def test_venue_cache_deletes_invalid_json() -> None:
    client = redis_client_mock()
    client.get.return_value = "not-json"
    cache = RedisVenueCache(client)

    venue = asyncio.run(cache.get("Broken"))

    assert venue is None
    client.delete.assert_awaited_once_with("venue:v1:broken")


def test_venue_cache_clears_namespace_in_batches() -> None:
    client = redis_client_mock()
    keys = [f"venue:v1:{index}" for index in range(205)]
    client.scan_iter = MagicMock(return_value=scanned_keys(keys))
    cache = RedisVenueCache(client)

    asyncio.run(cache.clear())

    client.scan_iter.assert_called_once_with(match="venue:v1:*", count=100)
    assert client.delete.await_args_list == [
        call(*keys[:100]),
        call(*keys[100:200]),
        call(*keys[200:]),
    ]


def test_venue_cache_clear_degrades_when_scan_fails() -> None:
    client = redis_client_mock()

    async def failed_scan():
        raise RedisError("redis unavailable")
        yield ""  # pragma: no cover

    client.scan_iter = MagicMock(return_value=failed_scan())
    cache = RedisVenueCache(client)

    asyncio.run(cache.clear())

    client.delete.assert_not_awaited()
