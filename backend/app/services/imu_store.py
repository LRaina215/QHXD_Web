from app.schemas import ImuEnvelope


class ImuStore:
    """Stores the latest IMU sample received from NUC."""

    def __init__(self) -> None:
        self._latest_imu: ImuEnvelope | None = None

    def initialize(self) -> None:
        self._latest_imu = None

    def get_latest(self) -> ImuEnvelope | None:
        if self._latest_imu is None:
            return None
        return self._latest_imu.model_copy(deep=True)

    def store(self, imu: ImuEnvelope) -> ImuEnvelope:
        self._latest_imu = imu.model_copy(deep=True)
        return self.get_latest()

    def clear(self) -> None:
        self._latest_imu = None


imu_store = ImuStore()
