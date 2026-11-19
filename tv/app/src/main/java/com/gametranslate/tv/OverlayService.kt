package com.gametranslate.tv

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.util.concurrent.TimeUnit

/**
 * Keeps a WebSocket connection to the PC and draws the Turkish subtitle in an overlay window
 * above everything, including the HDMI input.
 *
 * PC -> TV: {"type":"line", id, speaker, tr, en, partial, update, replaces?, color?} · {"type":"clear"} ·
 * {"type":"regions", boxes: [screen boxes + icons {n: base64 PNG}, "⟦n⟧" in tr]} ·
 *           {"type":"style", style}
 * TV -> PC: {"type":"hello", version, style} · {"type":"ack", id} · {"type":"style", style}
 */
class OverlayService : Service() {

    companion object {
        const val BEACON_PORT = 8766
        const val SAMPLE_SPEAKER = "Karl"
        const val SAMPLE_TR = "Tüfek, dürbün yok, işleri ilginç tutuyor."
        const val SAMPLE_EN = "Rifle, no scope, keeps things interesting."
        @Volatile var status = "Durduruldu"
        @Volatile var running = false

        fun start(context: Context) {
            context.startForegroundService(Intent(context, OverlayService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, OverlayService::class.java))
        }

        fun showTest(context: Context) {
            context.startForegroundService(Intent(context, OverlayService::class.java).putExtra("test", true))
        }
    }

    private val main = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder()
        .pingInterval(5, TimeUnit.SECONDS)
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private lateinit var prefs: Prefs
    private lateinit var wm: WindowManager
    private var view: SubtitleView? = null
    private var socket: WebSocket? = null
    @Volatile private var beaconHost: String? = null
    private var beaconSocket: DatagramSocket? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private val hide = Runnable { fadeOut() }
    private val styleListener: (Style, Boolean) -> Unit = { s, fromPc ->
        main.post {
            applyStyle(s)
            if (!fromPc) socket?.send(JSONObject().put("type", "style").put("style", s.toJson()).toString())
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        StyleStore.load(this)
        StyleStore.addListener(styleListener)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat()
        if (!running) {
            running = true
            acquireWifiLock()
            addOverlay()
            listenForBeacon()
            connect()
        }
        if (intent?.getBooleanExtra("test", false) == true) {
            show(SAMPLE_SPEAKER, SAMPLE_TR, SAMPLE_EN)
            main.postDelayed(hide, 4000)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        status = "Durduruldu"
        StyleStore.removeListener(styleListener)
        main.removeCallbacksAndMessages(null)
        socket?.cancel()
        beaconSocket?.close()
        overlayRoot?.let { runCatching { wm.removeView(it) } }
        overlayRoot = null
        view = null
        screenView = null
        regionView = null
        multicastLock?.let { if (it.isHeld) it.release() }
        wifiLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    // ---- overlay ----

    private fun addOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            status = "Ekran üstü izni yok (PC uygulamasından TV > Kur / güncelle)"
            return
        }
        val v = SubtitleView(this).apply { visibility = View.GONE }
        // The window covers the whole screen and never changes size or position: a window that
        // wraps its text moves on every line, and Android animates such moves, so the subtitle
        // slid left/right/up/down. Now only the drawing inside a fixed window changes.
        val root = FrameLayout(this)
        // Screen translation (menus, quests) lies under the subtitles.
        val screen = ScreenTextView(this).apply { visibility = View.GONE }
        root.addView(screen, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        screenView = screen
        // Hint box / phone messages: one box per area, button icons inside the text.
        val regions = ScreenTextView(this).apply { visibility = View.GONE }
        root.addView(regions, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        regionView = regions
        root.addView(v, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        ).apply {
            windowAnimations = 0
        }
        wm.addView(root, lp)
        overlayRoot = root
        view = v
        applyStyle(StyleStore.style)
    }

    private var overlayRoot: FrameLayout? = null
    private var screenView: ScreenTextView? = null
    private var regionView: ScreenTextView? = null

    private fun applyStyle(s: Style) {
        val v = view ?: return
        val metrics = resources.displayMetrics
        v.referenceWidth = metrics.widthPixels
        v.applyStyle(s)
        if (!s.stackPrevious) v.clearPrevious()
        val vertical = when (s.position) {
            "top" -> Gravity.TOP
            "middle" -> Gravity.CENTER_VERTICAL
            else -> Gravity.BOTTOM
        }
        val horizontal = when (s.align) {
            "left" -> Gravity.LEFT
            "right" -> Gravity.RIGHT
            else -> Gravity.CENTER_HORIZONTAL
        }
        val edge = if (s.position == "middle") 0 else metrics.heightPixels * s.offset / 100
        val side = if (s.align == "center") 0 else metrics.widthPixels * 3 / 100
        v.layoutParams = FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT, vertical or horizontal).apply {
            if (s.position == "top") topMargin = edge else bottomMargin = edge
            leftMargin = side
            rightMargin = side
        }
    }

    private var shownAt = 0L
    private val expireOlder: Runnable = object : Runnable {
        override fun run() {
            val next = view?.expire(System.currentTimeMillis()) ?: 0L
            if (next > 0) main.postDelayed(this, maxOf(50L, next - System.currentTimeMillis()))
        }
    }

    private fun show(speaker: String, tr: String, en: String, update: Boolean = false, partial: Boolean = false,
                     id: Int = Int.MIN_VALUE, replaces: Int? = null, color: String? = null) {
        val v = view ?: return
        val s = StyleStore.style
        main.removeCallbacks(hide)
        val now = System.currentTimeMillis()
        if (replaces != null) {
            // Written over its row, wherever it is now; the row gets its full reading time again.
            when (v.replace(replaces, id, speaker, tr, en, partial, color, now + s.readTimeMs(tr.length))) {
                1 -> { shownAt = now; fadeIn(v); return }
                2 -> { main.removeCallbacks(expireOlder); main.post(expireOlder); fadeIn(v); return }
            }
        }
        val overwrite = update && replaces == null
        // A new line pushes the one on screen up a row (dimmed) instead of sitting next to it.
        val stack = !overwrite && v.visibility == View.VISIBLE && v.hasText && (s.stackPrevious || s.prevHoldMs > 0)
        // The line moving up stays until it could be read (from when it appeared), and at least prevHoldMs more.
        val holdUntil = if (s.stackPrevious) Long.MAX_VALUE
            else maxOf(shownAt + s.readTimeMs(v.textLength), now + s.prevHoldMs)
        v.setContent(speaker, tr, en, overwrite, stack, partial, holdUntil, id, color)
        // Also a line written over the one on screen gets its whole reading time.
        shownAt = now
        if (stack && !s.stackPrevious) {
            main.removeCallbacks(expireOlder)
            main.post(expireOlder)
        }
        fadeIn(v)
    }

    private fun fadeIn(v: SubtitleView) {
        v.animate().cancel()
        if (v.visibility != View.VISIBLE) {
            v.alpha = 0f
            v.visibility = View.VISIBLE
        }
        v.animate().alpha(1f).setDuration(StyleStore.style.fadeMs.toLong()).start()
    }

    private fun fadeOut() {
        val v = view ?: return
        v.animate().cancel()
        v.animate().alpha(0f).setDuration(StyleStore.style.fadeMs.toLong()).withEndAction {
            v.visibility = View.GONE
            v.clearPrevious()
        }.start()
    }

    // ---- connection ----

    private fun targetHost(): String? = prefs.host.ifEmpty { null } ?: beaconHost

    private fun connect() {
        if (!running) return
        val host = targetHost()
        if (host == null) {
            status = "PC aranıyor…"
            main.postDelayed({ connect() }, 500)
            return
        }
        status = "Bağlanıyor: $host"
        val request = Request.Builder().url("ws://$host:${prefs.port}").build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                status = "Bağlı: $host"
                webSocket.send(JSONObject().put("type", "hello").put("version", BuildConfig.VERSION_NAME)
                    .put("style", StyleStore.style.toJson()).toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
                when (msg.optString("type")) {
                    "line" -> {
                        val id = msg.optInt("id")
                        val replaces = if (msg.has("replaces") && !msg.isNull("replaces")) msg.optInt("replaces") else null
                        val color = msg.optString("color").ifEmpty { null }
                        main.post {
                            show(msg.optString("speaker"), msg.optString("tr"), msg.optString("en"),
                                msg.optBoolean("update"), msg.optBoolean("partial"), id, replaces, color)
                            // Lets the PC measure the PC -> TV delay.
                            webSocket.send("{\"type\":\"ack\",\"id\":$id}")
                        }
                    }
                    "clear" -> main.post {
                        // The game may remove its line before the Turkish one could be read.
                        val s = StyleStore.style
                        val now = System.currentTimeMillis()
                        val readLeft = s.readTimeMs(view?.textLength ?: 0) - (now - shownAt)
                        // Lines moved up in a busy scene keep their own time: hide when all could be read.
                        val olderLeft = (view?.olderUntil ?: 0L).let { if (it == Long.MAX_VALUE || it == 0L) 0L else it - now }
                        main.removeCallbacks(hide)
                        main.postDelayed(hide, maxOf(s.lingerMs.toLong(), readLeft, olderLeft))
                    }
                    "screen" -> {
                        val boxes = msg.optJSONArray("boxes") ?: org.json.JSONArray()
                        main.post { screenView?.setBoxes(boxes) }
                    }
                    "regions" -> {
                        val boxes = msg.optJSONArray("boxes") ?: org.json.JSONArray()
                        main.post { regionView?.setBoxes(boxes) }
                    }
                    "style" -> msg.optJSONObject("style")?.let { j ->
                        main.post { StyleStore.update(this@OverlayService, Style.fromJson(j, StyleStore.style), true) }
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = retry(webSocket)
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = retry(webSocket)
        })
    }

    private fun retry(failed: WebSocket) {
        if (!running || failed !== socket) return
        // Without the PC nobody takes old menu translations away: clear them.
        main.post {
            screenView?.setBoxes(org.json.JSONArray())
            regionView?.setBoxes(org.json.JSONArray())
        }
        status = "Bağlantı koptu, tekrar deneniyor…"
        main.post { main.postDelayed({ connect() }, 1000) }
    }

    /** The PC broadcasts "GAMETRANSLATE <port>" on UDP 8766 so the TV finds it without typing an IP. */
    private fun listenForBeacon() {
        val wifi = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        multicastLock = wifi.createMulticastLock("gametranslate").apply { setReferenceCounted(false); acquire() }
        Thread {
            try {
                val sock = DatagramSocket(null).apply {
                    reuseAddress = true
                    broadcast = true
                    bind(InetSocketAddress(BEACON_PORT))
                }
                beaconSocket = sock
                val buf = ByteArray(256)
                while (running) {
                    val packet = DatagramPacket(buf, buf.size)
                    sock.receive(packet)
                    if (String(packet.data, 0, packet.length).startsWith("GAMETRANSLATE")) {
                        beaconHost = packet.address.hostAddress
                    }
                }
            } catch (_: Exception) {
                // socket closed on stop
            }
        }.apply { isDaemon = true }.start()
    }

    @Suppress("DEPRECATION")
    private fun acquireWifiLock() {
        val wifi = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        // Keeps Wi-Fi out of power save so messages are not delayed by 100+ ms.
        wifiLock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "gametranslate")
            .apply { setReferenceCounted(false); acquire() }
    }

    // ---- foreground notification ----

    private fun startForegroundCompat() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("overlay", "Altyazı", NotificationManager.IMPORTANCE_MIN))
        val notification = Notification.Builder(this, "overlay")
            .setContentTitle(getString(R.string.app_name))
            .setContentText("Altyazı çevirisi açık")
            .setSmallIcon(R.drawable.icon)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notification)
        }
    }
}
