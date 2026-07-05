# Navigation Web visualization

The navigation visualization path is read-only and independent from Nav2 control:

```text
/map + TF(map -> base_link) + /plan + /local_plan + /odometry
  -> navigation_web_bridge (ROS 2 C++)
  -> RK FastAPI navigation cache
  -> /api/navigation/* + /ws/navigation
  -> cloud gateway
  -> dashboard Canvas
```

It does not publish ROS topics, TF, goals, or velocity commands. Failure of this bridge must not
affect mapping, localization, planning, or chassis control.

## Start

Start the QHXD backend first, then run:

```bash
cd ~/QHXD
./scripts/start_navigation_web_bridge.sh
```

Stop only the visualization bridge:

```bash
cd ~/QHXD
./scripts/stop_navigation_web_bridge.sh
```

The bridge can also be run in the foreground:

```bash
cd ~/livox_ws
unset LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
source ~/livox_ws/install/setup.bash
ros2 launch navigation_web_bridge navigation_web_bridge.launch.py
```

## Public read API

- `GET /api/navigation/map/metadata`: map dimensions, resolution, origin, frame, and version.
- `GET /api/navigation/map/image`: cached grayscale occupancy map PNG with ETag.
- `GET /api/navigation/latest`: latest pose, paths, velocity, and navigation state.
- `WS /ws/navigation`: compact dynamic snapshots, normally 10 Hz.

Internal ingest endpoints are local bridge interfaces:

- `POST /api/internal/navigation/map`
- `POST /api/internal/navigation/state`

The occupancy map is uploaded only when its content version changes or after a backend reconnect.
It is not included in each WebSocket frame.

## Parameters

Edit `~/livox_ws/src/navigation_web_bridge/config/navigation_web_bridge.yaml`, rebuild the package,
and restart the bridge. `state_rate_hz` controls Web position refresh rate; it does not change lidar,
Point-LIO, AMCL, or Nav2 rates.

## Checks

```bash
curl http://127.0.0.1:8000/api/navigation/map/metadata
curl http://127.0.0.1:8000/api/navigation/latest
curl -o /tmp/navigation-map.png http://127.0.0.1:8000/api/navigation/map/image
tail -f ~/QHXD/.runtime/navigation_web_bridge.log
```

The web pose is sourced from TF `map -> base_link`. It is never reconstructed by integrating
odometry or velocity.
