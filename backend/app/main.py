import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.schemas import (
    AlertsResponse,
    CommandLogsResponse,
    CurrentTaskResponse,
    GoToWaypointRequest,
    HealthResponse,
    MissionActionResponse,
    ModeSwitchRequest,
    ModeSwitchResponse,
    PauseMissionRequest,
    ResumeMissionRequest,
    ReturnHomeRequest,
    StartPatrolRequest,
    StateLatestResponse,
)
from app.services.mock_state import mock_state_service
from app.services.ws_manager import ws_manager


async def _mock_state_loop() -> None:
    while True:
        state = mock_state_service.tick()
        await ws_manager.broadcast_state(state)
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    mock_state_service.initialize()
    state_task = asyncio.create_task(_mock_state_loop())
    try:
        yield
    finally:
        state_task.cancel()
        with suppress(asyncio.CancelledError):
            await state_task


app = FastAPI(title="RK3588 Middleware", version="0.1.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/state/latest", response_model=StateLatestResponse)
async def get_latest_state() -> StateLatestResponse:
    return StateLatestResponse(data=mock_state_service.get_latest_state())


@app.get("/api/alerts", response_model=AlertsResponse)
async def get_alerts() -> AlertsResponse:
    return AlertsResponse(data=mock_state_service.get_alerts())


@app.get("/api/commands/logs", response_model=CommandLogsResponse)
async def get_command_logs() -> CommandLogsResponse:
    return CommandLogsResponse(data=mock_state_service.get_command_logs())


@app.get("/api/tasks/current", response_model=CurrentTaskResponse)
async def get_current_task() -> CurrentTaskResponse:
    return CurrentTaskResponse(data=mock_state_service.get_current_task())


@app.post("/api/mission/go_to_waypoint", response_model=MissionActionResponse)
async def go_to_waypoint(request: GoToWaypointRequest) -> MissionActionResponse:
    return MissionActionResponse(data=mock_state_service.go_to_waypoint(request))


@app.post("/api/mission/start_patrol", response_model=MissionActionResponse)
async def start_patrol(request: StartPatrolRequest) -> MissionActionResponse:
    return MissionActionResponse(data=mock_state_service.start_patrol(request))


@app.post("/api/mission/pause", response_model=MissionActionResponse)
async def pause_mission(request: PauseMissionRequest) -> MissionActionResponse:
    return MissionActionResponse(data=mock_state_service.pause(request))


@app.post("/api/mission/resume", response_model=MissionActionResponse)
async def resume_mission(request: ResumeMissionRequest) -> MissionActionResponse:
    return MissionActionResponse(data=mock_state_service.resume(request))


@app.post("/api/mission/return_home", response_model=MissionActionResponse)
async def return_home(request: ReturnHomeRequest) -> MissionActionResponse:
    return MissionActionResponse(data=mock_state_service.return_home(request))


@app.post("/api/system/mode/switch", response_model=ModeSwitchResponse)
async def switch_system_mode(request: ModeSwitchRequest) -> ModeSwitchResponse:
    return ModeSwitchResponse(data=mock_state_service.switch_system_mode(request))


@app.websocket("/ws/state")
async def state_stream(websocket: WebSocket) -> None:
    await ws_manager.connect(websocket, mock_state_service.get_latest_state())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
