#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -eo pipefail

cd /workspace/turtlebot_connector
CONNECTOR_VENV="${CONNECTOR_VENV:-.venv-ros2}"

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user uv
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [ ! -x "${CONNECTOR_VENV}/bin/python" ]; then
  uv venv --python /usr/bin/python3 --system-site-packages "${CONNECTOR_VENV}"
fi

uv pip install --python "${CONNECTOR_VENV}/bin/python" -e ".[dev]"

echo "Connector environment ready at /workspace/turtlebot_connector/${CONNECTOR_VENV}"
echo "Python: $("${CONNECTOR_VENV}/bin/python" --version)"
echo "rclpy import check:"
"${CONNECTOR_VENV}/bin/python" -c "import rclpy; print('rclpy OK')"
