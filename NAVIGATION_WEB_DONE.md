# Navigation Web foundation completed

## Scope

The first read-only navigation visualization path is complete:

```text
ROS 2 /map + TF(map -> base_link) + /plan + /local_plan + /odometry
  -> navigation_web_bridge (C++)
  -> QHXD Backend navigation cache
  -> REST + WebSocket
  -> Cloud Gateway
  -> Vue Canvas map
```

No mission behavior, Nav2 configuration, chassis communication, TF publisher, or velocity command
path was changed.

## Main implementation

- `~/livox_ws/src/navigation_web_bridge/`: independent ROS 2 C++ telemetry node.
- `backend/app/services/navigation_store.py`: latest navigation state and occupancy PNG cache.
- `backend/app/main.py`: internal ingest, public map/state APIs, and `/ws/navigation`.
- `backend/app/services/ws_manager.py`: isolated navigation WebSocket clients.
- `frontend/src/components/NavMapPlaceholder.vue`: real layered Canvas map, pose, goal, paths,
  pan, zoom, stale-state indication, and responsive metrics.
- `cloud_gateway/cloud_gateway.py`: navigation REST and WebSocket forwarding whitelist.
- `scripts/start_navigation_web_bridge.sh` and `stop_navigation_web_bridge.sh`: independent lifecycle.
- `docs/NAVIGATION_WEB.md`: startup, API, parameters, and checks.

## Validated on RK3588

- ROS package builds successfully on ROS 2 Humble/ARM64.
- Backend test suite: 28 passed.
- Frontend production build completed successfully.
- Actual `/map`: 209 x 261, 0.05 m/cell, version `d1f0a37f3932fec`.
- Actual `map -> base_link` pose and `/odometry` velocity reach the backend.
- Local and cloud WebSocket rate: approximately 10.1 Hz.
- Cached map PNG is valid and is not sent in each WebSocket message.
- Backend restart replayed the map automatically in approximately 1.2 seconds.
- Steady bridge usage measured approximately 4.2% of one CPU core and 34 MB RSS.
- Public frontend and Cloud Gateway were deployed with timestamped backups.

## Remaining field acceptance

- Send a real Nav2 goal and visually compare `/plan`, the robot marker, and RViz.
- Confirm local path frame behavior while the controller is active; non-`map` paths are currently
  omitted rather than rendered in the wrong coordinate frame.
- Perform final desktop/mobile visual acceptance in the operator's browser.
