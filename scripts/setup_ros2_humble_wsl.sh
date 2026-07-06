#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
USER_NAME="${ROS2_USER:-wan}"

if ! id "${USER_NAME}" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "${USER_NAME}"
fi

apt-get update
apt-get install -y \
  ca-certificates \
  curl \
  git \
  gnupg \
  locales \
  lsb-release \
  software-properties-common \
  sudo \
  wget

printf '%s ALL=(ALL) NOPASSWD:ALL\n' "${USER_NAME}" >"/etc/sudoers.d/${USER_NAME}"
chmod 0440 "/etc/sudoers.d/${USER_NAME}"

locale-gen en_US en_US.UTF-8
update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8

add-apt-repository -y universe

ROS_KEYRING=/usr/share/keyrings/ros-archive-keyring.gpg
if ! curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o "${ROS_KEYRING}"; then
  curl -fsSL http://packages.ros.org/ros.key -o "${ROS_KEYRING}"
fi

UBUNTU_CODENAME="$(. /etc/os-release && echo "${UBUNTU_CODENAME}")"
ARCHITECTURE="$(dpkg --print-architecture)"
cat > /etc/apt/sources.list.d/ros2.list <<EOF
deb [arch=${ARCHITECTURE} signed-by=${ROS_KEYRING}] http://packages.ros.org/ros2/ubuntu ${UBUNTU_CODENAME} main
EOF

apt-get update
apt-get install -y \
  ros-dev-tools \
  ros-humble-desktop \
  ros-humble-rqt-robot-steering \
  ros-humble-turtlesim \
  terminator

USER_HOME="$(getent passwd "${USER_NAME}" | cut -d: -f6)"
mkdir -p "${USER_HOME}/ros2_ws/src"
grep -qxF 'source /opt/ros/humble/setup.bash' "${USER_HOME}/.bashrc" || \
  printf '\nsource /opt/ros/humble/setup.bash\n' >> "${USER_HOME}/.bashrc"
chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}"

cat > /etc/wsl.conf <<EOF
[user]
default=${USER_NAME}

[boot]
systemd=true
EOF

echo "ROS2 Humble setup complete for ${USER_NAME}."
