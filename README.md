# Smart Car Remote Control Extract

This folder is the extracted smart-car remote-control project.

It contains:

- `smart-car-console/`: Windows-side React and Node control console.
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

Read `docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md` before connecting to the physical car or changing motion-control code.
