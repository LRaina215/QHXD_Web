from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from h264_stream_publisher import StreamPublisherConfig, build_pipeline_description, redact_stream_url


class StreamPublisherConfigTest(unittest.TestCase):
    def test_rejects_unbounded_queue(self) -> None:
        config = StreamPublisherConfig(url="rtmp://example/live/front", queue_size=3)
        with self.assertRaisesRegex(ValueError, "queue_size"):
            config.validate()

    def test_builds_mpp_rtmp_pipeline(self) -> None:
        config = StreamPublisherConfig(
            url="rtmp://publisher:secret@example/live/front",
            fps=10,
            width=1280,
            height=720,
            bitrate=1_200_000,
            queue_size=2,
        )
        pipeline = build_pipeline_description(config, 1624, 1224, "RGB")
        self.assertIn("mpph264enc", pipeline)
        self.assertIn("leaky=downstream", pipeline)
        self.assertIn("width=1280,height=720", pipeline)
        self.assertIn("rtmpsink", pipeline)

    def test_builds_absolute_file_pipeline(self) -> None:
        output = Path(tempfile.gettempdir()) / "qhxd-stream-test.ts"
        config = StreamPublisherConfig(url=f"file://{output}")
        pipeline = build_pipeline_description(config, 640, 480, "BGR")
        self.assertIn("mpegtsmux", pipeline)
        self.assertIn(str(output), pipeline)

    def test_redacts_password(self) -> None:
        redacted = redact_stream_url("rtmp://publisher:secret@example:1935/robot/front")
        self.assertEqual(redacted, "rtmp://publisher:***@example:1935/robot/front")

    def test_redacts_rtmp_query_password(self) -> None:
        redacted = redact_stream_url("rtmp://example/robot/front?user=publisher&pass=secret")
        self.assertEqual(redacted, "rtmp://example/robot/front?user=publisher&pass=%2A%2A%2A")


if __name__ == "__main__":
    unittest.main()
