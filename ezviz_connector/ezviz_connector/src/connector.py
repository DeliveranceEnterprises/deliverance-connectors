"""Main EzvizConnector implementation."""

import logging
from typing import override

from inorbit_connector.commands import CommandFailure, CommandResultCode, parse_custom_command_args
from inorbit_connector.connector import FleetConnector
from inorbit_edge.commands import COMMAND_NAV_GOAL
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND

from ezviz_connector import __version__ as connector_version

from .api.client import EzvizAPIClient
from .api.data_poller import DataPoller
from .api.models import CameraState
from .commands import DEFAULT_PTZ_NUDGE_MS, DEFAULT_PTZ_SPEED, PTZ_DIRECTIONS, CustomScripts
from .config.models import EzvizConnectorConfig, EzvizRobotConfig

logger = logging.getLogger(__name__)


class EzvizConnector(FleetConnector):
    """InOrbit Fleet Connector for Ezviz cloud cameras.

    Each configured camera is reported as a robot. Pose is not published — cameras
    are stationary. Key-values cover online status, battery, signal, firmware,
    and last motion timestamp.
    """

    def __init__(self, config: EzvizConnectorConfig) -> None:
        super().__init__(config, publish_connector_system_stats=True)

        self._robot_id_to_serial: dict[str, str] = {
            r.robot_id: r.fleet_robot_id for r in config.fleet
        }
        self._robot_configs: dict[str, EzvizRobotConfig] = {
            r.robot_id: r for r in config.fleet
        }
        self._states: dict[str, CameraState] = {
            r.robot_id: CameraState() for r in config.fleet
        }

        self._api_client: EzvizAPIClient | None = None
        self._data_poller: DataPoller | None = None

    @property
    def _cfg(self):
        return self.config.connector_config

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @override
    async def _connect(self) -> None:
        cfg = self._cfg
        self._api_client = EzvizAPIClient(
            account=cfg.account,
            password=cfg.password,
            region_url=cfg.region_url,
            timeout=cfg.request_timeout,
            sms_code=cfg.sms_code,
        )
        await self._api_client.login()

        self._data_poller = DataPoller(
            client=self._api_client,
            states=self._states,
            robot_id_to_serial=self._robot_id_to_serial,
            update_freq=self.config.update_freq,
        )
        self._data_poller.start()
        self._logger.info("Connected to Ezviz cloud at %s", cfg.region_url)

    @override
    async def _disconnect(self) -> None:
        if self._data_poller:
            await self._data_poller.stop()
        if self._api_client:
            await self._api_client.close()

    # ------------------------------------------------------------------
    # Execution loop
    # ------------------------------------------------------------------

    @override
    async def _execution_loop(self) -> None:
        for robot_id in self.robot_ids:
            self._publish(robot_id, self._states[robot_id])

    def _publish(self, robot_id: str, state: CameraState) -> None:
        cfg = self._robot_configs[robot_id]
        if cfg.default_map:
            # Cameras are stationary. Publish pose directly (not via
            # publish_robot_pose) to skip the map-fetch loop — the map
            # already exists in InOrbit.
            self._get_robot_session(robot_id).publish_pose(
                cfg.pose_x, cfg.pose_y, cfg.pose_theta, frame_id=cfg.default_map
            )

        kv: dict = {
            "connector_version": connector_version,
            "api_connected": state.api_connected,
            "online_status": state.online,
            "robot_model": cfg.robot_model,
        }
        if state.battery_percent is not None:
            kv["battery"] = state.battery_percent / 100.0
            kv["battery_percent"] = state.battery_percent / 100.0
        if state.signal_percent is not None:
            kv["signal_strength"] = state.signal_percent / 100.0
        if state.firmware:
            kv["firmware_version"] = state.firmware
        if state.name:
            kv["device_name"] = state.name
        if state.category:
            kv["device_category"] = state.category
        if state.subcategory:
            kv["device_subcategory"] = state.subcategory
        if state.motion_triggered is not None:
            kv["motion_triggered"] = state.motion_triggered
        if state.last_motion_ts:
            kv["last_motion_ts"] = state.last_motion_ts
        if state.seconds_since_last_motion is not None:
            kv["seconds_since_last_motion"] = state.seconds_since_last_motion

        self.publish_robot_key_values(robot_id, **kv)

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    @override
    async def _inorbit_robot_command_handler(
        self, robot_id: str, command_name: str, args: list, options: dict
    ) -> None:
        self._logger.info(
            "[cmd] received robot_id=%r command_name=%r args=%r",
            robot_id, command_name, args,
        )
        if self._api_client is None:
            raise CommandFailure(
                execution_status_details="API client not connected",
                stderr="Connector is not yet connected to the Ezviz cloud",
            )

        serial = self._robot_id_to_serial[robot_id]

        # Click-on-map → pan/tilt toward the click. Works as an alternative
        # "click to aim" teleop because the SDK doesn't dispatch joystick
        # velocity messages.
        if command_name == COMMAND_NAV_GOAL:
            await self._handle_nav_goal_as_ptz(serial, args)
            return

        if command_name != COMMAND_CUSTOM_COMMAND:
            self._logger.info("[cmd] ignoring non-custom command %r", command_name)
            return

        result_fn = options["result_function"]
        try:
            script_name, script_args = parse_custom_command_args(args)
        except Exception as exc:
            self._logger.error("[cmd] parse_custom_command_args failed: %s", exc)
            raise
        self._logger.info("[cmd] parsed script=%r args=%r", script_name, script_args)

        # Use plain string comparison — match against StrEnum value patterns
        # has surprising edge cases; explicit `in` is unambiguous.
        try:
            if script_name in PTZ_DIRECTIONS:
                direction = PTZ_DIRECTIONS[script_name]
                self._logger.info(
                    "[cmd] PTZ nudge serial=%s direction=%s duration=%dms speed=%d",
                    serial, direction, DEFAULT_PTZ_NUDGE_MS, DEFAULT_PTZ_SPEED,
                )
                await self._api_client.ptz_nudge(
                    serial, direction,
                    duration_ms=DEFAULT_PTZ_NUDGE_MS,
                    speed=DEFAULT_PTZ_SPEED,
                )
                self._logger.info("[cmd] PTZ nudge done")

            elif script_name == CustomScripts.PTZ_STOP:
                self._logger.info("[cmd] PTZ STOP serial=%s", serial)
                await self._api_client.ptz_control(serial, "UP", "STOP", DEFAULT_PTZ_SPEED)

            else:
                self._logger.warning("[cmd] unknown script %r", script_name)
                raise CommandFailure(
                    execution_status_details=f"Unknown command: {script_name}",
                    stderr=f"Command '{script_name}' is not supported",
                )
        except CommandFailure:
            raise
        except Exception as exc:
            self._logger.exception("[cmd] PTZ call failed")
            raise CommandFailure(
                execution_status_details=f"PTZ call failed: {type(exc).__name__}",
                stderr=str(exc),
            )

        result_fn(CommandResultCode.SUCCESS)
        self._logger.info("[cmd] reported SUCCESS")

    async def _handle_nav_goal_as_ptz(self, serial: str, args: list) -> None:
        """Translate a click-on-map navGoal into a PTZ direction nudge.

        InOrbit dispatches navGoal as ``[{"x": "..", "y": "..", "theta": ".."}]``
        (strings, from a ``|``-delimited MQTT payload). The click coordinates
        are interpreted relative to the camera marker; the dominant axis
        decides whether to pan or tilt.
        """
        if not args or not isinstance(args[0], dict):
            return
        try:
            x = float(args[0].get("x", 0))
            y = float(args[0].get("y", 0))
        except (TypeError, ValueError):
            return

        threshold = 0.5  # metres — ignore taps right on the camera
        if abs(x) < threshold and abs(y) < threshold:
            return

        if abs(x) >= abs(y):
            direction = "RIGHT" if x > 0 else "LEFT"
        else:
            direction = "UP" if y > 0 else "DOWN"

        self._logger.info("navGoal (%.2f, %.2f) → PTZ %s nudge", x, y, direction)
        await self._api_client.ptz_nudge(
            serial, direction,
            duration_ms=DEFAULT_PTZ_NUDGE_MS,
            speed=DEFAULT_PTZ_SPEED,
        )

    # ------------------------------------------------------------------
    # Online check — drives the InOrbit "online" indicator
    # ------------------------------------------------------------------

    @override
    def _is_fleet_robot_online(self, robot_id: str) -> bool:
        state = self._states.get(robot_id)
        if state is None:
            return False
        # api_connected covers the connector→cloud link.
        # state.online covers the cloud→camera link.
        return state.api_connected and state.online
