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
- `/local_plan` published in `base_link` is transformed into `map` before Web upload.
- Omni PID Pursuit `/local_plan` is used as the displayed global-route fallback when NavigateToPose
  does not publish a separate `/plan`; both path lines may overlap for this controller.
- Local and cloud WebSocket rate: approximately 10.1 Hz.
- Cached map PNG is valid and is not sent in each WebSocket message.
- Backend restart replayed the map automatically in approximately 1.2 seconds.
- Steady bridge usage measured approximately 4.2% of one CPU core and 34 MB RSS.
- Public frontend and Cloud Gateway were deployed with timestamped backups.

## Remaining field acceptance

- Send a real Nav2 goal and visually compare `/plan`, the robot marker, and RViz.
- Perform final desktop/mobile visual acceptance in the operator's browser.

## Disabled-chassis Nav2 path acceptance (2026-07-05)

- Started the documented six-process Point-LIO front end and `rk3588_navigation` bringup.
- Front-end rates were approximately 10 Hz for Point-LIO odometry, registered scan, and LaserScan.
- The previous guessed initial pose `(1.49, 0.72)` was rejected for planning because its global
  costmap cell was inflated/occupied. AMCL global localization plus no-motion updates converged to
  approximately `(-0.33, 3.82, -0.84 rad)` with low covariance and a free robot-radius area.
- Theta* successfully planned a disabled-chassis test route to `(0.072, 3.821)`.
- During NavigateToPose, both RK local API and the public cloud API reported `global_path=9`,
  `local_path=9`, state `navigating`, and approximately `0.42 m` remaining distance.
- The current Omni PID Pursuit controller exposes the same active controller route through
  `/local_plan`; after transformation to `map`, it is also used as the global display fallback, so
  the two displayed lines overlap by design.
- The Canvas renders the overlapping global route as a wide orange underlay and the controller
  route as a narrow cyan dashed line so both remain visually distinguishable.
- NavigateToPose was canceled successfully. After one second without local-plan updates, the Web
  state returned to `localized` and both path arrays were cleared.
- The cancellation velocity stream decelerated to about `0.04 m/s` but an explicit zero frame was
  not observed before publishing stopped. A zero `/cmd_vel` was sent explicitly after each test.
  This is a separate velocity-smoother safety observation and was not addressed by changing Nav2
  behavior in the visualization task.
