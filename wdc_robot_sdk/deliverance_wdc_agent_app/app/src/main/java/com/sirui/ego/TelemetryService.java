package com.sirui.ego;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import com.sirui.selfstudysdk.main.SelfChassisState;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * Foreground service version of the polling loop that used to live directly
 * in MainActivity -- moved out 2026-08-27 so this survives (a) the tablet
 * rebooting (started from BootReceiver) and (b) Android backgrounding/
 * killing it once nobody is looking at the screen, which a plain Activity
 * loop does not survive (confirmed this was a real gap, not a hypothetical
 * one -- flagged after asking "y correrian solos cada vez que se
 * encienda el robot?").
 *
 * A foreground service needs a persistent notification (Android requirement
 * since API 26, not optional) -- that's the ongoing "Deliverance Agent
 * activo" notification this creates. targetSdk 34 additionally requires
 * declaring a foreground service TYPE; "dataSync" fits since this service's
 * whole job is polling and (eventually) forwarding telemetry data.
 */
public class TelemetryService extends Service {

    private static final String TAG = "DeliveranceAgent";
    private static final String CHASSIS_ADDR = "192.168.31.7:9090";
    private static final long POLL_PERIOD_MS = 2000L;
    private static final String CHANNEL_ID = "deliverance_agent_channel";
    private static final int NOTIFICATION_ID = 1;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean connected = false;

    private final Runnable pollLoop = new Runnable() {
        @Override
        public void run() {
            poll();
            handler.postDelayed(this, POLL_PERIOD_MS);
        }
    };

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null; // not a bound service, only started -- see BootReceiver / MainActivity
    }

    @Override
    public void onCreate() {
        super.onCreate();
        startForeground(NOTIFICATION_ID, buildNotification());

        connected = SelfChassisState.getInstance().init(CHASSIS_ADDR);
        Log.i(TAG, "SelfChassisState.init(" + CHASSIS_ADDR + ") -> " + connected);
        if (!connected) {
            Log.e(TAG, "Could not connect to chassis, polling loop not started");
            return;
        }
        handler.post(pollLoop);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // START_STICKY: if Android still kills this despite being a
        // foreground service (some OEM battery managers do, see
        // CLAUDE.md "Termux reliability" note -- same caveat applies here),
        // ask the system to recreate it rather than leaving it dead.
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(pollLoop);
        super.onDestroy();
    }

    private Notification buildNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Deliverance Agent", NotificationManager.IMPORTANCE_LOW);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Deliverance Agent activo")
                .setContentText("Leyendo datos del robot")
                .setSmallIcon(android.R.drawable.ic_menu_compass)
                .setOngoing(true)
                .build();
    }

    private void poll() {
        try {
            JSONObject telemetry = new JSONObject();
            telemetry.put("x", SelfChassisState.getInstance().getX());
            telemetry.put("y", SelfChassisState.getInstance().getY());
            telemetry.put("yaw", SelfChassisState.getInstance().getYaw());
            telemetry.put("charging_current", SelfChassisState.getInstance().getChargingCurrent());
            telemetry.put("charging_io", SelfChassisState.getInstance().getChargingIO());
            telemetry.put("stop", SelfChassisState.getInstance().isStop());
            telemetry.put("result", SelfChassisState.getInstance().getResult());
            Log.i(TAG, "telemetry: " + telemetry);
            sendTelemetry(telemetry);
        } catch (JSONException exc) {
            Log.e(TAG, "Failed to build telemetry JSON", exc);
        } catch (Exception exc) {
            // SelfChassisState getters throwing (chassis link dropped, etc.)
            // must never crash the polling loop -- just skip this tick, same
            // tolerance wdc_bridge_node.py's LocalApiClient.request() has.
            Log.w(TAG, "poll() failed, will retry next tick", exc);
        }
    }

    /**
     * Stub -- see this class's docstring and MainActivity's original one for
     * why the transport isn't wired up yet: it's a real open decision
     * (InOrbit via Termux's own Agent Core vs an HTTP endpoint into
     * Deliverance's platform that doesn't exist yet), not an oversight.
     */
    private void sendTelemetry(JSONObject telemetry) {
        // TODO: Objective 1 -> real InOrbit Agent Core via Termux, separate
        // process, not this method.
        // TODO: Objective 2 -> HTTP POST to Deliverance's platform, once an
        // intake endpoint exists (see deliverance_agent_sdk/CLAUDE.md).
    }
}
