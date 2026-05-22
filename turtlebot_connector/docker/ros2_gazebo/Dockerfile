# SPDX-FileCopyrightText: 2026 Deliverance Enterprises
#
# SPDX-License-Identifier: MIT

# ROS 2 Humble is the practical target for TurtleBot3 + Nav2 + Gazebo classic.
# The VNC image gives a browser-accessible desktop at http://localhost:6080.
FROM tiryoh/ros2-desktop-vnc:humble

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=humble
ENV TURTLEBOT3_MODEL=burger
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    python3-pip \
    python3-venv \
    ros-humble-gazebo-ros-pkgs \
    ros-humble-navigation2 \
    ros-humble-nav2-bringup \
    ros-humble-turtlebot3 \
    ros-humble-turtlebot3-gazebo \
    ros-humble-turtlebot3-navigation2 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir uv

WORKDIR /workspace/turtlebot_connector

COPY docker/ros2_gazebo/entrypoint.sh /ros2_gazebo_entrypoint.sh
RUN chmod +x /ros2_gazebo_entrypoint.sh

ENTRYPOINT ["/ros2_gazebo_entrypoint.sh"]
CMD ["/entrypoint.sh"]
