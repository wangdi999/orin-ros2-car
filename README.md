# Orin ROS2 Smart Car

This repository contains the original smart-car remote-control project and the
`devcp` implementation scaffold for deterministic patrol execution with a
LangGraph task-orchestration layer.

It contains:

- `smart-car-console/`: Windows-side React and Node control console.
- `agent-runtime/`: FastAPI, LangGraph, SQLite persistence, plan validation,
  human approval, task/event APIs, and a safe mock robot gateway.
- `ros2_agent_ws/`: ROS2 Foxy interfaces, Patrol Manager, Safety Supervisor,
  and orchestration launch files.
- `ros2_car_remote_ws/src/icar_ctrl/`: car-side ROS2 keyboard and joystick teleop package.
- `ros2_car_remote_ws/src/icar_bringup/`: car-side chassis bringup and driver reference package, including `Mcnamu_driver_X3`.
- `docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md`: AI handoff manual for connection, operation, and future development.
- `scripts/connect_car_vnc.ps1`: helper script for VNC desktop access.
- `wifi/ohcar_wifi_profile.xml`: lab Wi-Fi profile used by the car manuals.

Not included:

- `node_modules/`, `dist/`, runtime `logs/`, and `local-config.json`.
- Full navigation, SLAM, laser, camera SDK, and complete car OS workspaces.
- The car Docker image and already-installed ROS2 dependencies.

Start with:

```powershell
cd .\smart-car-console
npm install
npm run dev
```

Then open `http://127.0.0.1:5173`.

Run the Agent Runtime in safe mock mode:

```bash
cd agent-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
pytest
uvicorn car_agent.api.app:create_app --factory --port 8100
```

Build the additional ROS2 packages inside the car's ROS2 Foxy environment:

```bash
cd ros2_agent_ws
source /opt/ros/foxy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
```

The default Agent gateway is `mock`. Named locations that have not been
measured on the real map remain disabled. No entity-motion test should be run
until Nav2, TF, topics, device bindings, and the emergency-stop path have been
verified on the car.

Read `docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md` before connecting to the physical car or changing motion-control code.
Read `docs/LANGGRAPH_IMPLEMENTATION_STATUS.md` for the design analysis,
implemented scope, and remaining real-car integration checks.
