"""Full NV V2 fields survive backend request/response validation, even when stale."""
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from yuntuo.fpga_link import nv_proto as nv
from yuntuo.fpga_link import telemetry as tm
from app.schemas import PlatformStatusUpdateRequest, PlatformStatusResponse


def test_complete_nv_frame_survives_backend_contract():
    values = {n: i+1 for i,n in enumerate(tm.NAMES_V1+tm.NAMES_V2_EXTRA)}
    values.update(ax_raw=-32768, gx_raw=32767, left_delta=-2147483648,
                  right_delta=2147483647, left_cms=-123, sequence=65535)
    frame = nv.decode(b"NV\x01\x83"+tm.encode_frame(values))
    full = dict(transport="nv_udp", source="fpga", version=2, fresh=False,
                receive_age_ms=1300.0, measurement_age_ms=None, raw=frame.raw)
    request = PlatformStatusUpdateRequest.model_validate({"platform_status": {
        "updated_at": datetime.now(timezone.utc).isoformat(), "control_link": "offline",
        "control_telemetry": full}})
    response = PlatformStatusResponse(data=request.platform_status).model_dump(mode="json")
    assert response["data"]["control_telemetry"] == full
    assert tm.encode_frame(response["data"]["control_telemetry"]["raw"]) == tm.encode_frame(values)
