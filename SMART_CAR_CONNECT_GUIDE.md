# iCar Smart Car Connection Guide

## Local Setup Completed

- Installed TigerVNC Viewer at `C:\Program Files\TigerVNC\vncviewer.exe`.
- Added `connect_car_vnc.ps1` in this workspace to open the VNC client by car IP.
- Added `ohcar_wifi_profile.example.xml` as a template for the manual's `ohcar` Wi-Fi profile.
- Copied the manuals into this workspace:
  - `manual_smart_car.pdf`
  - `auto_drive_ros_env.docx`

## What The Manuals Require

- Smart car onboard system: Ubuntu 20.04, ROS2 Foxy.
- Laptop remote access: VNC Viewer.
- Default Wi-Fi/hotspot name: `ohcar`.
- Wi-Fi password: use the value from your car manual or lab handover notes.
- VNC password: use the value from your car manual or lab handover notes.

Do not commit real Wi-Fi or VNC passwords to this repository. Keep local credentials in your own notes or local-only profiles.

The separate ROS development document describes a VMware Ubuntu 20.04 + ROS Noetic environment. That is for ROS1 learning/simulation, not required just to connect to the car desktop.

## Connect To The Car

1. Charge the car if needed. The charger light turns green when full.
2. Confirm the chassis control Type-C cable is connected to the chassis control port and the middle USB port on top of the car.
3. Power on the car and wait until the Ubuntu 20.04 desktop appears. Three beeps means the chassis communication is normal.
4. Create or use a Wi-Fi hotspot named `ohcar` with the Wi-Fi password from your car manual or lab handover notes.
5. On the car touchscreen, connect the car to `ohcar`.
6. Open a new Terminal on the car. Note the displayed `MY_IP` address.
7. Connect this Windows laptop to the same `ohcar` Wi-Fi.
   If Windows does not auto-show it, run:

```powershell
netsh wlan connect name=ohcar
```

8. From PowerShell in this workspace, run:

```powershell
.\connect_car_vnc.ps1 -CarIp <MY_IP_FROM_CAR>
```

9. If VNC shows a security warning, continue.
10. Enter the VNC password from your car manual or lab handover notes.

## Start The Car Control Program

After VNC connects to the car desktop:

1. Open Terminal on the car.
2. Run:

```bash
ros
run
```

This starts the upper-computer service used by the app.

To use the car's built-in app instead:

```bash
ros
app
```

## Quick Checks On The Car

```bash
docker images
lsusb
```

For SLAM/navigation, the manual expects the depth camera to show two USB device entries with ID `2bc5`. If only one appears, reconnect the depth camera USB cable.

## Troubleshooting

- VNC cannot connect: confirm laptop and car are both on `ohcar`, and use the current `MY_IP` from the car screen.
- Password rejected: confirm you are using the VNC password, not the Wi-Fi password.
- Cannot find `ohcar`: check the two Wi-Fi antennas are installed, or create a phone hotspot named exactly `ohcar` with the expected Wi-Fi password.
- Car moves slowly or stops: charge the battery first.
- Line-following/IOT firmware tests require `ArteryISPProgrammer`; it is not needed for normal VNC connection or ROS/Gazebo/SLAM operation.
