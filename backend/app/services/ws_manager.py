from fastapi import WebSocket

from app.schemas import RobotState


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, initial_state: RobotState) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        await websocket.send_json({"type": "robot_state", "data": initial_state.model_dump(mode="json")})

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

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


ws_manager = WebSocketManager()
