#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

set -euo pipefail

docker build -f docker/Dockerfile -t deliverance/turtlebot-connector:latest .
