package com.gametranslate.tv

import android.content.Context
import org.json.JSONObject

/** Every look-and-feel setting of the subtitle. Shared by the overlay, the preview and the PC app. */
data class Style(
    // text
    val textSize: Int = 30,
    val font: String = "sans",
    val bold: Boolean = true,
    val textColor: String = "#FFFFFF",
    val uppercase: Boolean = false,
    val lineSpacing: Int = 115,      // % of the font height
    val letterSpacing: Int = 0,      // 1/100 em
    // speaker
    val speakerShow: Boolean = true,
    val speakerColors: Boolean = true,       // every speaker in their own color (sent by the PC, same name same color)
    val speakerColor: String = "#FFD54F",
    val speakerOwnLine: Boolean = false,
    // outline and shadow
    val outline: Int = 3,
    val outlineColor: String = "#000000",
    val shadow: Int = 6,
    // background box
    val bgColor: String = "#000000",
    val bgOpacity: Int = 55,         // %
    val bgRadius: Int = 12,          // dp
    val bgPadding: Int = 14,         // dp
    // position
    val position: String = "bottom", // bottom | middle | top
    val offset: Int = 6,             // % of screen height from the edge
    val align: String = "center",    // left | center | right
    val maxWidth: Int = 80,          // % of screen width
    // original English
    val showEnglish: Boolean = false,
    val englishSize: Int = 60,       // % of textSize
    val englishColor: String = "#B0BEC5",
    val englishAbove: Boolean = false,
    // timing
    val lingerMs: Int = 400,
    val fadeMs: Int = 120,
    val stackPrevious: Boolean = false,      // keep the previous line above until the next one (no time limit)
    val prevHoldMs: Int = 2500,              // previous line stays above (dimmed) this long; 0 = never
    val readBaseMs: Int = 1500,              // a line stays at least base + perChar * length on screen
    val readPerCharMs: Int = 50,
    val readMaxMs: Int = 5000,
    val provisional: Boolean = true,         // unfinished sentence fragments in italic, dimmed
    // size: every line the same size unless these are turned on
    val autoShrink: Boolean = false,         // very long lines get a smaller font
    val prevSmaller: Boolean = false,        // the previous line (moved up) is drawn smaller
    // busy scenes: up to this many lines stay stacked (newest at the edge), each until it could be read
    val maxLines: Int = 4,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("textSize", textSize); put("font", font); put("bold", bold); put("textColor", textColor)
        put("uppercase", uppercase); put("lineSpacing", lineSpacing); put("letterSpacing", letterSpacing)
        put("speakerShow", speakerShow); put("speakerColors", speakerColors); put("speakerColor", speakerColor); put("speakerOwnLine", speakerOwnLine)
        put("outline", outline); put("outlineColor", outlineColor); put("shadow", shadow)
        put("bgColor", bgColor); put("bgOpacity", bgOpacity); put("bgRadius", bgRadius); put("bgPadding", bgPadding)
        put("position", position); put("offset", offset); put("align", align); put("maxWidth", maxWidth)
        put("showEnglish", showEnglish); put("englishSize", englishSize); put("englishColor", englishColor)
        put("englishAbove", englishAbove)
        put("lingerMs", lingerMs); put("fadeMs", fadeMs); put("stackPrevious", stackPrevious)
        put("prevHoldMs", prevHoldMs); put("readBaseMs", readBaseMs); put("readPerCharMs", readPerCharMs)
        put("readMaxMs", readMaxMs); put("provisional", provisional)
        put("autoShrink", autoShrink); put("prevSmaller", prevSmaller); put("maxLines", maxLines)
    }

    /** How long a line must stay visible so it can be read. */
    fun readTimeMs(chars: Int) = (readBaseMs + readPerCharMs * chars).coerceAtMost(readMaxMs)

    companion object {
        val DEFAULT = Style()

        fun fromJson(j: JSONObject, base: Style = DEFAULT) = Style(
            textSize = j.optInt("textSize", base.textSize),
            font = j.optString("font", base.font),
            bold = j.optBoolean("bold", base.bold),
            textColor = j.optString("textColor", base.textColor),
            uppercase = j.optBoolean("uppercase", base.uppercase),
            lineSpacing = j.optInt("lineSpacing", base.lineSpacing),
            letterSpacing = j.optInt("letterSpacing", base.letterSpacing),
            speakerShow = j.optBoolean("speakerShow", base.speakerShow),
            speakerColors = j.optBoolean("speakerColors", base.speakerColors),
            speakerColor = j.optString("speakerColor", base.speakerColor),
            speakerOwnLine = j.optBoolean("speakerOwnLine", base.speakerOwnLine),
            outline = j.optInt("outline", base.outline),
            outlineColor = j.optString("outlineColor", base.outlineColor),
            shadow = j.optInt("shadow", base.shadow),
            bgColor = j.optString("bgColor", base.bgColor),
            bgOpacity = j.optInt("bgOpacity", base.bgOpacity),
            bgRadius = j.optInt("bgRadius", base.bgRadius),
            bgPadding = j.optInt("bgPadding", base.bgPadding),
            position = j.optString("position", base.position),
            offset = j.optInt("offset", base.offset),
            align = j.optString("align", base.align),
            maxWidth = j.optInt("maxWidth", base.maxWidth),
            showEnglish = j.optBoolean("showEnglish", base.showEnglish),
            englishSize = j.optInt("englishSize", base.englishSize),
            englishColor = j.optString("englishColor", base.englishColor),
            englishAbove = j.optBoolean("englishAbove", base.englishAbove),
            lingerMs = j.optInt("lingerMs", base.lingerMs),
            fadeMs = j.optInt("fadeMs", base.fadeMs),
            stackPrevious = j.optBoolean("stackPrevious", base.stackPrevious),
            prevHoldMs = j.optInt("prevHoldMs", base.prevHoldMs),
            readBaseMs = j.optInt("readBaseMs", base.readBaseMs),
            readPerCharMs = j.optInt("readPerCharMs", base.readPerCharMs),
            readMaxMs = j.optInt("readMaxMs", base.readMaxMs),
            provisional = j.optBoolean("provisional", base.provisional),
            autoShrink = j.optBoolean("autoShrink", base.autoShrink),
            prevSmaller = j.optBoolean("prevSmaller", base.prevSmaller),
            maxLines = j.optInt("maxLines", base.maxLines).coerceIn(1, 6),
        )
    }
}

/** Holds the current style, saves it and tells the overlay / settings screen when it changes. */
object StyleStore {
    private const val PREFS = "gametranslate"
    private const val KEY = "style"

    @Volatile var style: Style = Style.DEFAULT
        private set
    private var loaded = false
    private val listeners = mutableListOf<(Style, Boolean) -> Unit>()

    fun load(context: Context): Style {
        if (!loaded) {
            val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
            style = raw?.let { runCatching { Style.fromJson(JSONObject(it)) }.getOrNull() } ?: Style.DEFAULT
            loaded = true
        }
        return style
    }

    /** fromPc = the change came from the PC app (so it is not echoed back). */
    fun update(context: Context, newStyle: Style, fromPc: Boolean = false) {
        style = newStyle
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY, newStyle.toJson().toString()).apply()
        listeners.toList().forEach { it(newStyle, fromPc) }
    }

    fun addListener(l: (Style, Boolean) -> Unit) { listeners.add(l) }
    fun removeListener(l: (Style, Boolean) -> Unit) { listeners.remove(l) }
}
