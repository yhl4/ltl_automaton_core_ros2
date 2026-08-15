"""State observer for the in-memory fake plant."""


class FakeStateObserver:
    """Forward FakePlant events through the generic observer contract."""

    def __init__(self, plant):
        self._plant = plant
        self._callback = None

    def start(self, on_observation):
        """Subscribe to future fake-plant updates."""
        if self._callback is not None:
            raise RuntimeError("FakeStateObserver is already running.")
        self._callback = on_observation
        self._plant.add_listener(self._emit)

    def stop(self):
        """Stop forwarding fake-plant updates."""
        if self._callback is None:
            return
        self._plant.remove_listener(self._emit)
        self._callback = None

    def _emit(self, observation):
        if self._callback is not None:
            self._callback(observation)
