#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import pty
import select
import sys
import time
import tty


def main() -> int:
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    tty.setraw(slave_fd)
    print(slave_name, flush=True)
    print(f'use: ros2 run rtt_nav_bridge rtt_nav_bridge_node --ros-args -p port:={slave_name}', file=sys.stderr, flush=True)
    started = time.monotonic()
    last_rx = b''
    try:
        while True:
            now = time.monotonic()
            t_ms = int((now - started) * 1000)
            yaw = 0.1 * math.sin(now * 0.5)
            vx = 0.02
            vy = 0.0
            wz = 0.01
            x = vx * (now - started)
            y = 0.0
            qw = math.cos(yaw * 0.5)
            qz = math.sin(yaw * 0.5)
            frames = [
                f'ODOM,{t_ms},{x:.4f},{y:.4f},{yaw:.4f},{vx:.4f},{vy:.4f},{wz:.4f}\n',
                f'IMU,{t_ms},{qw:.6f},0.0,0.0,{qz:.6f},0.0,0.0,{wz:.4f},0.0,0.0,9.81\n',
                f'STAT,{t_ms},mock,24000,0,0\n',
            ]
            for frame in frames:
                os.write(master_fd, frame.encode('utf-8'))
            ready, _, _ = select.select([master_fd], [], [], 0.0)
            if ready:
                chunk = os.read(master_fd, 4096)
                if chunk and chunk != last_rx:
                    last_rx = chunk
                    print('rx:', chunk.decode('utf-8', errors='replace').strip(), file=sys.stderr, flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
