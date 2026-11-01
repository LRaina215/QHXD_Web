"""Patrols must obey the same map binding as individual waypoint navigation."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pydantic import ValidationError
from app.schemas import StartPatrolRequest, PlatformSetPoseRequest
from app.services.mission_gateway import MissionGateway
import app.services.mission_gateway as gateway_module


@pytest.mark.parametrize('wrong_point', ['wp_b', 'home'])
def test_patrol_rejects_a_point_or_return_home_bound_to_another_map(monkeypatch, wrong_point):
    gateway = MissionGateway()
    monkeypatch.setattr(gateway_module.state_store, 'get_system_mode', lambda: SimpleNamespace(mode='real'))
    monkeypatch.setattr(gateway_module.patrol_registry, 'require', lambda _: {
        'waypoints': ['wp_a', 'wp_b'], 'return_home': True,
    })
    monkeypatch.setattr(gateway_module.waypoint_registry, 'require_navigation_target',
                        lambda wid: SimpleNamespace(map_id='other-map' if wid == wrong_point else 'field'))
    def ready(expected_map_id=None, **_):
        if expected_map_id and expected_map_id != 'field':
            raise ValueError('点位地图 other-map 与当前地图 field 不一致。')
    monkeypatch.setattr(gateway, '_require_navigation_ready', ready)
    rejected = Mock(return_value=('rejected', None))
    dispatch = Mock(return_value=('dispatched', None))
    monkeypatch.setattr(gateway, '_record_rejection', rejected)
    monkeypatch.setattr(gateway, '_dispatch', dispatch)
    assert gateway.start_patrol(StartPatrolRequest(patrol_id='default_patrol')) == ('rejected', None)
    rejected.assert_called_once()
    dispatch.assert_not_called()


def test_patrol_checks_all_points_and_home_before_dispatch(monkeypatch):
    gateway = MissionGateway()
    monkeypatch.setattr(gateway_module.state_store, 'get_system_mode', lambda: SimpleNamespace(mode='real'))
    monkeypatch.setattr(gateway_module.patrol_registry, 'require', lambda _: {
        'waypoints': ['wp_a', 'wp_b'], 'return_home': True,
    })
    required = Mock(side_effect=lambda _: SimpleNamespace(map_id='field'))
    monkeypatch.setattr(gateway_module.waypoint_registry, 'require_navigation_target', required)
    ready = Mock()
    monkeypatch.setattr(gateway, '_require_navigation_ready', ready)
    monkeypatch.setattr(gateway, '_dispatch', Mock(return_value=('dispatched', None)))
    assert gateway.start_patrol(StartPatrolRequest(patrol_id='default_patrol')) == ('dispatched', None)
    assert [call.args[0] for call in required.call_args_list] == ['wp_a', 'wp_b', 'home']
    assert all(call.kwargs['expected_map_id'] == 'field' for call in ready.call_args_list)


@pytest.mark.parametrize('key', ['x', 'y', 'yaw'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_public_pose_contract_rejects_nonfinite_coordinates(key, value):
    payload = {'x': 0, 'y': 0, 'yaw': 0, key: value}
    with pytest.raises(ValidationError):
        PlatformSetPoseRequest.model_validate(payload)
