#!/usr/bin/env bash
set -euo pipefail

set +u
source /opt/ros/humble/setup.bash
set -u

WORKSPACE="${HOME}/ros2_ws"
mkdir -p "${WORKSPACE}/src"
cd "${WORKSPACE}/src"

if [ ! -d wpr_simulation2/.git ]; then
  git clone --depth 1 https://gitee.com/s-robot/wpr_simulation2.git
fi

cd wpr_simulation2/scripts
bash ./install_for_humble.sh

cd "${WORKSPACE}"
colcon build --symlink-install

grep -qxF "source ${WORKSPACE}/install/setup.bash" "${HOME}/.bashrc" || \
  printf '\nsource %s/install/setup.bash\n' "${WORKSPACE}" >> "${HOME}/.bashrc"

echo "wpr_simulation2 setup complete."
