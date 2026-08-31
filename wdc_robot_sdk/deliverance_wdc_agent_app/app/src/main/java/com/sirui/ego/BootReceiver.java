package com.sirui.ego;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

/**
 * Starts TelemetryService automatically once the tablet finishes booting --
 * without this, someone would have to open the app by hand every time the
 * robot is power-cycled (the exact concern raised raised for Termux's own
 * auto-start, same fix pattern applied here on the Android-app side).
 */
public class BootReceiver extends BroadcastReceiver {

    private static final String TAG = "DeliveranceAgent";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            return;
        }
        Log.i(TAG, "Boot completed, starting TelemetryService");
        Intent serviceIntent = new Intent(context, TelemetryService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent);
        } else {
            context.startService(serviceIntent);
        }
    }
}
