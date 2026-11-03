"""Existing-result display must not invent depth or treat stale detections as current."""
from datetime import datetime, timezone, timedelta
from scripts.observe_ai_pipeline import yolo_snapshot

NOW = datetime(2026,11,3,6,10,tzinfo=timezone.utc)


def snapshot(objects, seconds=.1):
    return ({'detection_status':{'enabled':True,'model_name':'yolo26n_int8.rknn',
             'source':'yuntuo-astra','timestamp':(NOW-timedelta(seconds=seconds)).isoformat(),
             'objects':objects}},
            {'latest_frame_fresh':True,'perception':{'detect_fps':5.0,'model':'yolo26n_int8.rknn','target_task':False}})


def test_existing_values_and_actual_fps_are_preserved():
    item={'class_name':'bottle','confidence':.91,'color':'red','track_id':7,
          'bbox_xyxy':[10,20,100,200],'position_body_m':[1.2,.1,.2],'distance_m':1.204}
    data=yolo_snapshot(*snapshot([item]), now=NOW)
    assert data['fresh'] and data['detect_fps']==5.0
    assert data['objects'][0]['distance_m']==1.204
    assert data['objects'][0]['confidence']==.91
    assert data['single_frame_npu_ms'] is None


def test_missing_depth_is_not_invented():
    data=yolo_snapshot(*snapshot([{'class_name':'person','confidence':.8}]),now=NOW)
    assert data['objects'][0]['position_body_m'] is None
    assert data['objects'][0]['distance_m'] is None


def test_stale_result_is_not_shown_as_current_target():
    data=yolo_snapshot(*snapshot([{'class_name':'person','confidence':.8}], seconds=10),now=NOW)
    assert data['status']=='stale' and not data['fresh']
    assert data['objects']==[] and data['last_reported_object_count']==1


def test_fresh_empty_frame_is_not_a_detection_failure():
    data=yolo_snapshot(*snapshot([]),now=NOW)
    assert data['status']=='ok' and data['fresh'] and data['object_count']==0
