import math

import pytest

from rtt_nav_bridge.protocol import (
    ImuFrame,
    OdomFrame,
    ProtocolError,
    StatFrame,
    format_cmd,
    format_heartbeat,
    format_stop,
    parse_nav_line,
)


def test_parse_full_odom():
    frame = parse_nav_line('ODOM,100,1.0,2.0,0.5,0.1,0.2,0.3')
    assert isinstance(frame, OdomFrame)
    assert frame.pose_valid is True
    assert frame.x == 1.0
    assert frame.vy == 0.2


def test_parse_velocity_only_odom():
    frame = parse_nav_line('ODOM,100,0.1,0.2,0.3')
    assert isinstance(frame, OdomFrame)
    assert frame.pose_valid is False
    assert frame.x is None
    assert frame.wz == 0.3


def test_parse_quaternion_imu():
    frame = parse_nav_line('IMU,100,1,0,0,0,0.1,0.2,0.3,0,0,9.81')
    assert isinstance(frame, ImuFrame)
    assert frame.qw == 1.0
    assert frame.az == 9.81


def test_parse_euler_imu():
    frame = parse_nav_line('IMU,100,0,0,1.57079632679,0,0,0,0,0,9.81')
    assert isinstance(frame, ImuFrame)
    assert math.isclose(frame.qw, math.sqrt(0.5), rel_tol=1e-5)
    assert math.isclose(frame.qz, math.sqrt(0.5), rel_tol=1e-5)


def test_parse_stat():
    frame = parse_nav_line('STAT,100,auto,24000,1,7')
    assert isinstance(frame, StatFrame)
    assert frame.estop is True
    assert frame.fault_code == 7


def test_bad_frame_raises():
    with pytest.raises(ProtocolError):
        parse_nav_line('BAD,100')


def test_format_tx_frames():
    assert format_cmd(1, 0.1, -0.2, 0.3) == 'CMD,1,0.100000,-0.200000,0.300000\n'
    assert format_heartbeat(2) == 'HB,2\n'
    assert format_stop(3, 'cmd timeout') == 'STOP,3,cmd_timeout\n'
