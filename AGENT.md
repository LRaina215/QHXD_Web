# AGENTS.md

## Project overview
This repository is the RK3588 onboard interaction and state middleware for a robot project with three computing layers:

- NUC11: main compute node for SLAM, localization, navigation, perception, and mission management
- RT-Thread controller: real-time motion control, low-level safety, encoder/IMU acquisition, emergency-stop loop
- RK3588: onboard interaction, state aggregation, task ingress, edge service, and future voice-entry node

The final system is collaborative:
RK3588 -> NUC11 -> RT-Thread for business/task flow,
while NUC11 <-> RT-Thread is the direct control/status loop.

## Current phase
We are in Phase 1: empty-shell middleware bootstrap.

Important:
- Do NOT implement real robot communication unless explicitly requested
- Do NOT move SLAM, Nav2, or main perception onto RK3588
- Prefer mock data and placeholder adapters first
- The goal now is to establish project skeleton, contracts, and dashboard workflow

## Source of truth
Always read and follow these files before starting work:
1. docs/prd.md
2. docs/arc.md
3. docs/project.md

If the docs and code disagree, prefer the docs and report the mismatch.

## RK3588 scope
RK3588 is responsible for:
- state aggregation
- task ingress APIs
- websocket state push
- local persistence
- web dashboard
- future voice entry and sensor data service
- business/status bridge toward NUC11

RK3588 is NOT responsible for:
- SLAM
- main navigation stack
- global/local planning
- main visual inference
- motor control
- emergency-stop control loop
- low-level realtime safety logic

## Working rules
- Make small, reviewable changes
- Keep changes tightly scoped
- Do not refactor unrelated files
- Do not redesign UI unless explicitly asked
- Use mock data first, real adapters later
- Keep backend and frontend contracts explicit and typed
- Prefer simple, mature tools over novel stacks
- Write code that is easy to review and test

## Preferred stack
Backend:
- FastAPI
- Pydantic
- WebSocket
- SQLite
- SQLAlchemy only if needed; otherwise keep it simple

Frontend:
- Vue 3
- TypeScript
- Vite

## Data contract discipline
The backend is the source of truth for public state contracts.
State models should cover at least:
- robot_pose
- nav_status
- task_status
- device_status
- env_sensor
- alert_event

Mission commands should cover at least:
- go_to_waypoint
- start_patrol
- pause_task
- resume_task
- return_home

Do not invent overlapping or duplicate fields without updating docs.

## File safety
Only modify files directly required for the current task.
If architecture, data models, or scope changes, update:
- docs/arc.md
- docs/project.md
and mention why.

## Validation
After each task:
- run the smallest relevant validation
- report exactly what was run
- report blockers clearly
- summarize files changed

## Prompt safety
Assume the user wants:
- minimal blast radius
- no surprise refactors
- no hidden dependency sprawl

When uncertain, ask or leave a TODO with explanation instead of guessing.