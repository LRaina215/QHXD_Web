"""Map-specific patrol and return-home dispatch, without operating hardware."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.schemas import ReturnHomeRequest
from app.services.patrol_registry import PatrolRegistry
from app.services.waypoint_registry import WaypointRegistry
from app.services.mission_gateway import MissionGateway
import app.services.mission_gateway as gateway
import app.services.patrol_registry as patrol
from yuntuo.bridge.config import BridgeConfig, load_routes, load_waypoints
from yuntuo.bridge.tasks import TaskRunner

ROOT = Path(__file__).resolve().parents[2]
POINTS = ROOT / 'backend/app/config/yuntuo/waypoints.json'
ROUTES = ROOT / 'backend/app/config/yuntuo/patrol_routes.json'


def registry(monkeypatch):
    w = WaypointRegistry(POINTS)
    monkeypatch.setattr(patrol, 'waypoint_registry', w)
    monkeypatch.setenv('PATROL_ROUTES_CONFIG_PATH', str(ROUTES))
    return w, PatrolRegistry()


def test_both_map_routes_have_separate_points_and_homes(monkeypatch):
    w, p = registry(monkeypatch)
    routes = p.list()
    assert {r['map_id'] for r in routes} == {'field_home', 'field_home2'}
    for r in routes:
        ids = r['waypoints'] + [r['home_waypoint_id']]
        assert {w.get(wid).map_id for wid in ids} == {r['map_id']}
        assert w.home_for_map(r['map_id']).waypoint_id == r['home_waypoint_id']
    assert w.get('wp_d').pose.y == -1.20  # original map-1 point stays intact
    assert w.get('map2_branch_end').pose.y == -.93


def test_mixed_map_return_home_is_rejected(monkeypatch, tmp_path):
    _, p = registry(monkeypatch)
    raw = json.loads(ROUTES.read_text(encoding='utf-8'))[1]
    raw['home_waypoint_id'] = 'home'
    file = tmp_path / 'routes.json'
    file.write_text(json.dumps([raw]), encoding='utf-8')
    monkeypatch.setenv('PATROL_ROUTES_CONFIG_PATH', str(file))
    with pytest.raises(ValueError, match='同一张地图'):
        p.list()


@pytest.mark.parametrize('map_id, home_id', [('field_home', 'home'), ('field_home2', 'home_map2')])
def test_return_home_uses_current_map(monkeypatch, map_id, home_id):
    monkeypatch.setattr(gateway, 'waypoint_registry', WaypointRegistry(POINTS))
    monkeypatch.setattr(gateway.state_store, 'get_system_mode', lambda: SimpleNamespace(mode='real'))
    monkeypatch.setattr(gateway.navigation_store, 'map_metadata', lambda: SimpleNamespace(map_id=map_id))
    g = MissionGateway()
    preflight = Mock(return_value=None)
    monkeypatch.setattr(g, '_preflight_enabled', lambda: True)
    monkeypatch.setattr(g, '_preflight_target', preflight)
    dispatch = Mock(return_value=('ok', None))
    monkeypatch.setattr(g, '_dispatch', dispatch)
    g.return_home(ReturnHomeRequest())
    preflight.assert_called_once_with('return_home', home_id)
    assert dispatch.call_args.kwargs['payload'] == ({'waypoint_id': home_id} if home_id != 'home' else {})


def test_bridge_keeps_map2_home_for_patrol_and_return_home():
    runner = TaskRunner(BridgeConfig(), load_waypoints(POINTS), load_routes(ROUTES), lambda *a: None, lambda *a: None)
    ok, _ = runner._start_goto('start_patrol', {'patrol_id': 'map2_patrol'}, 'test', 1)
    assert ok
    assert runner.task.points[-1].waypoint_id == 'home_map2'
    assert all(p.waypoint_id.startswith('map2_') or p.waypoint_id == 'home_map2' for p in runner.task.points)
    ok, _ = runner._start_goto('return_home', {'waypoint_id': 'home_map2'}, 'test', 2)
    assert ok and runner.task.current_point.waypoint_id == 'home_map2'


def test_waypoint_api_exposes_routes_through_existing_public_path(monkeypatch):
    import app.main as main
    w, p = registry(monkeypatch)
    monkeypatch.setattr(main, 'waypoint_registry', w)
    monkeypatch.setattr(main, 'patrol_registry', p)
    result = asyncio.run(main.get_waypoints()).model_dump()
    assert len(result['patrol_routes']) == 2
    assert any(w['map_id'] == 'field_home2' for w in result['data'])
