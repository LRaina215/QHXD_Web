import math

import numpy as np
import pytest

from yuntuo.bridge.inputs import parse_detection_message
from yuntuo.bridge.targets import TargetSpec, pick_target
from yuntuo.perception.color import dominant_color
from yuntuo.perception.geometry import ASTRA_DEPTH_640, Intrinsics, Mount, bbox_depth_m, locate
from yuntuo.perception.pipeline import Pipeline, PipelineConfig, bridge_message, color_bbox_to_depth, detection_status
from yuntuo.perception.sources import RgbdFrame
from yuntuo.perception.tracker import Tracker


def test_mount_rotation_maps_optical_axis_to_body_forward():
    level = Mount(x=0.2, y=0.0, z=0.3, pitch_deg=0.0)
    np.testing.assert_allclose(level.to_body([0, 0, 1.0]), [1.2, 0.0, 0.3], atol=1e-9)
    np.testing.assert_allclose(level.to_body([1.0, 0, 0]), [0.2, -1.0, 0.3], atol=1e-9)   # 光学 x 右 = 机身 -y
    tilted = Mount(x=0.0, y=0.0, z=0.3, pitch_deg=30.0)
    p = tilted.to_body([0, 0, 0.6])                      # 下俯 30°：0.6 m 光轴前方点落在地面
    np.testing.assert_allclose(p, [0.6 * math.cos(math.radians(30)), 0.0, 0.0], atol=1e-9)


def test_bbox_depth_ignores_background_and_holes():
    depth = np.full((480, 640), 3000, np.uint16)
    depth[200:300, 300:340] = 1200                       # 瓶子
    depth[240:250, 310:320] = 0                          # 空洞
    assert abs(bbox_depth_m(depth, [290, 190, 350, 310]) - 1.2) < 0.01
    assert bbox_depth_m(np.zeros((480, 640), np.uint16), [290, 190, 350, 310]) is None


def test_locate_center_pixel_is_straight_ahead():
    depth = np.full((480, 640), 1500, np.uint16)
    k = ASTRA_DEPTH_640
    box = [k.cx - 20, k.cy - 20, k.cx + 20, k.cy + 20]
    p = locate(depth, box, k, Mount(0.2, 0.0, 0.3, 0.0))
    np.testing.assert_allclose(p, [1.7, 0.0, 0.3], atol=1e-3)


def test_color_bbox_maps_to_depth_with_view_geometry():
    kc = Intrinsics.from_fov(640, 480, 66.1, 51.0)
    kd = ASTRA_DEPTH_640
    box = color_bbox_to_depth([kc.cx - 10, kc.cy - 10, kc.cx + 10, kc.cy + 10], kc, kd)
    assert abs((box[0] + box[2]) / 2 - kd.cx) < 1e-6
    assert box[2] - box[0] > 20                           # 深度视场更窄：同一物体在深度图里更大


def test_dominant_color():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :] = (200, 200, 200)                           # BGR 灰白背景
    img[20:80, 30:70] = (30, 30, 220)                     # 红色瓶身
    assert dominant_color(img, [30, 20, 70, 80])[0] == "red"
    img[20:80, 30:70] = (220, 60, 20)
    assert dominant_color(img, [30, 20, 70, 80])[0] == "blue"
    assert dominant_color(np.full((50, 50, 3), 10, np.uint8), [0, 0, 50, 50])[0] == "black"


def test_tracker_keeps_ids_and_votes_color():
    tr = Tracker()
    a = tr.update([{"cls": "bottle", "bbox": [0, 0, 10, 10], "color": "red"}], 0.0)[0]
    b = tr.update([{"cls": "bottle", "bbox": [1, 0, 11, 10], "color": None},
                   {"cls": "person", "bbox": [50, 50, 80, 120]}], 0.1)
    assert b[0]["track_id"] == a["track_id"] and b[0]["color"] == "red"
    assert b[1]["track_id"] != a["track_id"]
    c = tr.update([{"cls": "bottle", "bbox": [0, 0, 10, 10]}], 2.0)[0]
    assert c["track_id"] not in (a["track_id"], b[1]["track_id"])     # 超时后新 ID


def test_pipeline_end_to_end_to_bridge_target():
    color = np.full((480, 640, 3), 180, np.uint8)
    color[180:300, 400:440] = (25, 25, 210)               # 偏右的红瓶
    depth = np.full((480, 640), 4000, np.uint16)
    depth[150:330, 380:460] = 1500
    k = Intrinsics.from_fov(640, 480, 60.0, 47.0)
    frame = RgbdFrame(color, depth, 100.0, k, k, registered=True)
    detector = lambda img: [{"class_name": "bottle", "confidence": 0.8, "bbox_xyxy": [400, 180, 440, 300]},
                            {"class_name": "bottle", "confidence": 0.2, "bbox_xyxy": [0, 0, 10, 10]}]
    pipe = Pipeline(detector, PipelineConfig(mount=Mount(0.2, 0.0, 0.3, 0.0)))
    dets = pipe.process(frame)
    assert len(dets) == 1 and dets[0]["color"] == "red"
    x, y, z = dets[0]["position"]
    assert 1.6 < x < 1.8 and y < -0.1                       # 图像右侧 = 机身右侧（y 负）
    msg = bridge_message(dets, frame, seq=1)
    parsed = parse_detection_message(__import__("json").dumps(msg).encode(), received_mono=100.05, seq=1)
    pick = pick_target(parsed, TargetSpec("水瓶", "红色"), None)
    assert pick is not None and pick.track_id == dets[0]["track_id"]
    assert pick_target(parsed, TargetSpec("bottle", "blue"), None) is None
    status = detection_status(dets, model_name="test")
    assert status["objects"][0]["color"] == "red" and status["objects"][0]["distance_m"] > 1.6


def test_detection_status_is_valid_backend_contract():
    pydantic = pytest.importorskip("pydantic")
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app.schemas import DetectionStatus

    dets = [{"cls": "person", "conf": 0.9, "bbox": [1, 2, 3, 4], "track_id": 3, "color": None,
             "position": [2.0, 0.5, 0.8]}]
    DetectionStatus.model_validate(detection_status(dets, model_name="m"))
    assert pydantic


def test_full_rate_only_while_a_target_task_is_active():
    from yuntuo.perception.node import task_is_target

    assert task_is_target({"task_type": "search_target", "state": "running"})
    assert task_is_target({"task_type": "follow_target", "state": "paused"})
    assert not task_is_target({"task_type": "search_target", "state": "succeeded"})
    assert not task_is_target({"task_type": "go_to_waypoint", "state": "running"})
    assert not task_is_target({"task_type": "placeholder", "state": "idle"})
