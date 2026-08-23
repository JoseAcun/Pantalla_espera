import asyncio

from app.models import StreamState


class StreamStateStore:
    """Single source of truth; EventSub will update this store in a later phase."""

    def __init__(self, initial_state: StreamState) -> None:
        self._state = initial_state
        self._lock = asyncio.Lock()

    async def get(self) -> StreamState:
        async with self._lock:
            return self._state.model_copy(deep=True)

    async def replace(self, state: StreamState) -> StreamState:
        async with self._lock:
            self._state = state
            return self._state.model_copy(deep=True)

    async def update(self, **changes: object) -> StreamState:
        async with self._lock:
            self._state = self._state.model_copy(update=changes)
            return self._state.model_copy(deep=True)
