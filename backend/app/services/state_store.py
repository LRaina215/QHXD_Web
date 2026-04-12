from datetime import datetime, timezone

from app.schemas import RobotState, SystemMode


class StateStore:
    """Shared state store for mock/real state switching."""

    def __init__(self) -> None:
        self._latest_state: RobotState | None = None
        self._system_mode = SystemMode(mode="mock", updated_at=self._timestamp())

    def initialize(self, initial_state: RobotState) -> None:
        self._system_mode = initial_state.system_mode
        self._latest_state = initial_state.model_copy(deep=True)

    def get_latest_state(self) -> RobotState:
        if self._latest_state is None:
            raise RuntimeError("StateStore has not been initialized")
        return self._latest_state.model_copy(deep=True)

    def get_current_task(self):
        return self.get_latest_state().task_status

    def get_system_mode(self) -> SystemMode:
        return self._system_mode.model_copy(deep=True)

    def switch_mode(self, system_mode: SystemMode) -> RobotState:
        self._system_mode = system_mode.model_copy(deep=True)
        latest_state = self.get_latest_state().model_copy(
            update={
                "system_mode": self.get_system_mode(),
                "updated_at": self._timestamp(),
            }
        )
        self._latest_state = latest_state
        return self.get_latest_state()

    def publish_mock_state(self, state: RobotState) -> RobotState | None:
        if self._system_mode.mode != "mock":
            return None
        return self._store_state(state)

    def publish_real_state(self, state: RobotState) -> RobotState | None:
        if self._system_mode.mode != "real":
            return None
        return self._store_state(state)

    @staticmethod
    def _timestamp() -> datetime:
        return datetime.now(timezone.utc)

    def _store_state(self, state: RobotState) -> RobotState:
        stored_state = state.model_copy(
            update={
                "system_mode": self.get_system_mode(),
            }
        )
        self._latest_state = stored_state
        return self.get_latest_state()


state_store = StateStore()
