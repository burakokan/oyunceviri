package com.gametranslate.tv

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Prefs(context).autoStart) {
            runCatching { OverlayService.start(context) }
        }
    }
}
