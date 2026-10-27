from datetime import datetime, timezone

from app.schemas import DetectionStatus, PlatformStatus, RobotState, SystemMode


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

    def update_detection_status(self, detection_status: DetectionStatus) -> RobotState:
        latest_state = self.get_latest_state().model_copy(
            update={
                "detection_status": detection_status,
                "updated_at": self._timestamp(),
            }
        )
        self._latest_state = latest_state
        return self.get_latest_state()

    def update_platform_status(self, platform_status: PlatformStatus) -> RobotState | None:
        if self._system_mode.mode != "real":
            return None
        latest_state = self.get_latest_state().model_copy(
            update={
                "platform_status": platform_status,
                "updated_at": self._timestamp(),
            }
        )
        real_fpga = (platform_status.source == "fpga_bridge" and
                     (platform_status.nav_link == "online" or (platform_status.nav_link_kind or "").startswith("uart:")))
        if real_fpga:
            latest_state = self._without_unmeasured_fields(latest_state)
        self._latest_state = latest_state
        return self.get_latest_state()

    def switch_mode(self, system_mode: SystemMode) -> RobotState:
        was_mock = self._system_mode.mode == "mock"
        self._system_mode = system_mode.model_copy(deep=True)
        latest_state = self.get_latest_state().model_copy(
            update={
                "system_mode": self.get_system_mode(),
                "updated_at": self._timestamp(),
            }
        )
        if was_mock and system_mode.mode == "real":
            latest_state = self._without_unmeasured_fields(latest_state)
        self._latest_state = latest_state
        return self.get_latest_state()

    @staticmethod
    def _without_unmeasured_fields(state: RobotState) -> RobotState:
        # This FPGA profile has no battery/environment measurement channel.
        # Do not preserve values from the previous mock snapshot.
        return state.model_copy(update={
            "device_status": state.device_status.model_copy(update={"battery_percent": None}),
            "env_sensor": state.env_sensor.model_copy(update={
                "temperature_c": None, "humidity_percent": None, "status": "offline"}),
        })

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
        detection_status = state.detection_status
        if detection_status is None and self._latest_state is not None:
            detection_status = self._latest_state.detection_status
        platform_status = state.platform_status
        if platform_status is None and self._latest_state is not None:
            platform_status = self._latest_state.platform_status
        if platform_status is not None and platform_status.source == "mock" and self._system_mode.mode == "real":
            platform_status = None

        stored_state = state.model_copy(
            update={
                "system_mode": self.get_system_mode(),
                "detection_status": detection_status,
                "platform_status": platform_status,
            }
        )
        self._latest_state = stored_state
        return self.get_latest_state()


state_store = StateStore()
