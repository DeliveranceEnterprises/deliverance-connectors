"""Data models for cached camera state."""

from dataclasses import dataclass, field


@dataclass
class CameraState:
    """Snapshot of the latest Ezviz cloud data for one camera.

    Attributes are populated by the DataPoller and consumed by the connector's
    execution loop to build the key-values published to InOrbit.
    """

    api_connected: bool = False
    online: bool = False  # Ezviz device.status == 1
    name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    firmware: str | None = None
    battery_percent: int | None = None  # 0..100, None when not a battery cam
    signal_percent: int | None = None  # Wi-Fi RSSI 0..100
    motion_triggered: bool | None = None
    last_motion_ts: int | None = None  # epoch ms
    seconds_since_last_motion: float | None = None
    extra: dict = field(default_factory=dict)
