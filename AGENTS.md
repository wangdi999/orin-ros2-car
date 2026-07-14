# AI Agent Handoff

This project controls a physical smart car. Treat every motion command as hardware-affecting.

Primary context:

- Read `docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md` before making changes.
- Windows console code lives in `smart-car-console/`.
- ROS2 teleop and chassis-related source lives in `ros2_car_remote_ws/src/`.
- The main command boundary is ROS topic `/cmd_vel` with type `geometry_msgs/msg/Twist`.

Safety rules for development agents:

- Do not send movement commands unless the user explicitly asks for a physical-car test.
- For physical tests, ask the user to lift the wheels or clear the area first.
- Use low limits first: linear `0.05` to `0.10` m/s and angular `0.2` to `0.4` rad/s.
- Always send a zero Twist after any motion test.
- Keep `smart-car-console/local-config.json` local-only; it may contain SSH credentials.

Useful verification:

```powershell
cd smart-car-console
npm test
```

The React build requires dependencies:

```powershell
npm install
npm run build
```

If editing ROS2 packages, validate on the car or in a ROS2 Foxy environment. This extracted folder does not include the full car dependency graph.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/001-ros2-navigation-safety/plan.md
<!-- SPECKIT END -->
