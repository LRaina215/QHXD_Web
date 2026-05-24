---
name: rk3588-dashboard-design
description: Project-specific frontend design rules for the QHXD RK3588 robot dashboard. Read before changing frontend Dashboard UI.
---

# RK3588 Dashboard Design Skill

## Project Positioning

This frontend is the QHXD RK3588 vehicle robot middleware Dashboard. It is used for competition presentation and real integration work for a delivery and inspection sentinel robot.

It is not a generic admin template, not a decorative big-screen animation page, and not a raw debug page. The design goal is a clean robot control console: clear status hierarchy, reliable operation entry points, readable alerts, and enough visual polish for formal demonstration.

## Non-Breakable Business Functions

Never remove or hide these capabilities:

- Mock / Real mode display and switch entry.
- NUC online/offline state and RK3588 backend/WebSocket state.
- Current task, `task_status`, `nav_status`, `robot_pose`, device state, alerts, and faults.
- Mission command feedback and existing mission API calls.
- Text command entry and RK3588 board-side recording entry.
- `/api/voice/record_command` behavior and FunASR result fields.
- LLM parsing result, `need_confirm`, `pending_command_id`, and movement confirmation dialog.
- `/api/voice/confirm_command` confirm/cancel flow.
- YOLO `detection_status`, model/source, objects, events, visual alerts, and latest frame display if already present.
- Navigation visualization placeholder and future replacement point for `NavMapCanvas`.

Do not modify backend API paths, WebSocket protocol, mission behavior, voice behavior, LLM safety rules, YOLO data structure, or navigation business logic while doing visual work.

## Dashboard Information Architecture

Use this structure by default:

1. Top command header: system name, mode, NUC state, RK3588 state, clock, critical alert summary, Mock/Real switch.
2. Readiness strip: current task, robot online/health, battery/emergency/fault, latest alert, perception state.
3. Main operation grid: navigation visualization placeholder on the left; voice/LLM and YOLO on the right.
4. Mission control stays close to navigation because both affect robot movement.
5. Bottom observability: recent voice, LLM, YOLO, mission, runtime, and alert events.

The first screen must show the most important system state without requiring scrolling on a normal laptop display.

## Visual Style

Preferred direction:

- Clean technical blue/white style.
- Light surface with restrained deep-blue header accents.
- Card-based but dense enough for operations.
- No noisy neon, no excessive gradients, no decorative animation that reduces readability.
- Use an 8px spacing rhythm and stable grid tracks.
- Cards should use consistent 8px radius, border, header typography, and content spacing.
- Text must never overlap or overflow controls; long values should wrap inside their cell.

## Status Colors

Use unified status semantics:

- `online` / `normal`: green.
- `running` / `navigating`: blue.
- `pending` / `need_confirm`: yellow.
- `warning` / `alert`: orange.
- `fault` / `emergency_stop`: red.
- `offline` / `unknown`: gray.
- `mock`: muted gray-purple or gray.
- `real`: blue or green.

Use existing `.status-badge` and `.tone-*` classes, or equivalent project-local status components. Do not invent unrelated colors in each card.

## Component Rules

- Header: compact, status-first, with visible active mode and clock.
- Cards: one clear heading, one primary value, supporting metadata, status badge where useful.
- Buttons: 44px touch target, one primary action per group, secondary and warning actions visually distinct.
- Forms: visible labels above inputs; no placeholder-only fields.
- Lists: align time, source, level, and message consistently; wrap long messages.
- Empty states: quiet dashed container with operational text, not blank space.
- Modals: show close, cancel, confirm; risk note must be visible for robot movement.

## Navigation Placeholder Rules

`NavMapPlaceholder.vue` is a reserved operational region, not a decorative illustration. It must display:

- Current pose.
- Current goal.
- Navigation state.
- Frame/path metadata when available.
- A clear message that NUC navigation real-time stream is pending.

Keep props compatible for future `NavMapCanvas` replacement:

```ts
robotPose
currentGoal
globalPath
navState
```

Do not directly connect ROS2 topics from the frontend in this phase.

## Dialog And Dangerous Operation Rules

Movement commands produced by LLM parsing must remain gated by confirmation:

- `need_confirm=true` opens the movement confirmation dialog.
- Confirm calls `/api/voice/confirm_command` with `confirmed=true`.
- Cancel calls `/api/voice/confirm_command` with `confirmed=false` and must not trigger mission execution.
- Expired pending commands must show an error.
- Unknown commands must not trigger mission behavior.

The dialog must clearly display recognized text, intent, command, waypoint, parser/LLM info, confidence, and detail.

## Self-Check Before Finishing Frontend Changes

- Dashboard opens without blank screen.
- Mock / Real switch is still visible and calls the original endpoint.
- Board-side recording button is still visible and calls `/api/voice/record_command`.
- Text command entry still calls `/api/voice/text_command`.
- Movement confirmation dialog still appears and calls `/api/voice/confirm_command`.
- YOLO card still displays `detection_status` and latest frame if available.
- Navigation placeholder still shows pose, goal, state, and future stream notice.
- Alerts and runtime events are readable.
- No backend API path or WebSocket route has changed.
- Layout is checked around 375px, 768px, 1440px, and wide desktop widths.
