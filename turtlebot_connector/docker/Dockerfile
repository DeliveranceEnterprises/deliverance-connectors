# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY turtlebot_connector ./turtlebot_connector

RUN pip install --no-cache-dir .

ENTRYPOINT ["turtlebot-connector"]
