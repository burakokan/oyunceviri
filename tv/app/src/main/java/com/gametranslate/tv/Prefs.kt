package com.gametranslate.tv

import android.content.Context
import android.content.SharedPreferences

/** Connection settings stored on the TV. The subtitle look lives in [StyleStore]. */
class Prefs(context: Context) {
    private val p: SharedPreferences = context.getSharedPreferences("gametranslate", Context.MODE_PRIVATE)

    /** PC address; empty = find the PC automatically from its UDP beacon. */
    var host: String
        get() = p.getString("host", "") ?: ""
        set(v) = p.edit().putString("host", v.trim()).apply()

    var port: Int
        get() = p.getInt("port", 8765)
        set(v) = p.edit().putInt("port", v).apply()

    var autoStart: Boolean
        get() = p.getBoolean("autoStart", true)
        set(v) = p.edit().putBoolean("autoStart", v).apply()
}
