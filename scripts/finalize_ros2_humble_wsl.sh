#!/usr/bin/env bash
set -euo pipefail

USER_NAME="${ROS2_USER:-wan}"

if ! id "${USER_NAME}" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "${USER_NAME}"
fi

if command -v sudo >/dev/null 2>&1; then
  printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${USER_NAME}" >"/etc/sudoers.d/${USER_NAME}"
  chmod 0440 "/etc/sudoers.d/${USER_NAME}"
fi

USER_HOME="$(getent passwd "${USER_NAME}" | cut -d: -f6)"
mkdir -p "${USER_HOME}/ros2_ws/src"
touch "${USER_HOME}/.bashrc"
grep -qxF 'source /opt/ros/humble/setup.bash' "${USER_HOME}/.bashrc" || \
  printf '\nsource /opt/ros/humble/setup.bash\n' >> "${USER_HOME}/.bashrc"
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}"

cat > /etc/wsl.conf <<EOF
[user]
default=${USER_NAME}
EOF

echo "Finalized ROS2 WSL user ${USER_NAME}."
