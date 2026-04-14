from fastapi import WebSocket

from app.schemas import ImuEnvelope, RobotState


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._imu_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, initial_state: RobotState) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        await websocket.send_json({"type": "robot_state", "data": initial_state.model_dump(mode="json")})

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        self._imu_connections.discard(websocket)

    async def broadcast_state(self, state: RobotState) -> None:
        stale_connections: list[WebSocket] = []
        payload = {"type": "robot_state", "data": state.model_dump(mode="json")}

        for connection in self._connections:
            try:
                await connection.send_json(payload)
            except Exception:
                stale_connections.append(connection)

        for connection in stale_connections:
            self.disconnect(connection)

    async def connect_imu(self, websocket: WebSocket, initial_imu: ImuEnvelope | None) -> None:
        await websocket.accept()
        self._imu_connections.add(websocket)
        await websocket.send_json(
            {
                "type": "imu",
                "data": initial_imu.model_dump(mode="json") if initial_imu is not None else None,
            }
        )

    async def broadcast_imu(self, imu: ImuEnvelope | None) -> None:
        stale_connections: list[WebSocket] = []
        payload = {"type": "imu", "data": imu.model_dump(mode="json") if imu is not None else None}

        for connection in self._imu_connections:
            try:
                await connection.send_json(payload)
            except Exception:
                stale_connections.append(connection)

        for connection in stale_connections:
            self.disconnect(connection)


ws_manager = WebSocketManager()
