package com.sirui.ego;

import android.content.Intent;
import android.os.Build;
import android.os.Bundle;

import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;

/**
 * Deliverance Agent -- runs ON the robot's own tablet, connecting directly to
 * the embedded chassis computer via the manufacturer's official SDK
 * (SelfChassisState, same class used by the production wdc_robot app's
 * WdcRobotApi -- see connectors/deliverance-connectors/wdc_robot_sdk/CLAUDE.md).
 *
 * This is a SEPARATE app (package com.sirui.ego, not com.sirui.wdc_robot) --
 * installs alongside the production app without touching it, no signing-key
 * conflict, no risk to the app already in daily use.
 *
 * Built 2026-08-27 in direct response to the project requirement that the
 * code run on the robot itself and read its data locally, rather than
 * through an external server.
 *
 * The actual telemetry loop lives in TelemetryService, not here -- a plain
 * Activity gets killed the moment the screen changes or the tablet sleeps,
 * so this Activity's only job is to make sure that service is running (both
 * when someone opens the app by hand, and via BootReceiver on every power-on
 * -- see that class's docstring).
 */
public class MainActivity extends AppCompatActivity {

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent serviceIntent = new Intent(this, TelemetryService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }
    }
}
