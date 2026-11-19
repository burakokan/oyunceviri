package com.gametranslate.tv

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.SpannableString
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.ForegroundColorSpan
import android.view.View
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.max

/**
 * Draws one subtitle exactly as configured in [Style]: outlined text, shadow, colored speaker name,
 * rounded background box, optional English original and optional previous line.
 * Used both by the overlay on top of the HDMI picture and by the preview in the settings screen.
 */
class SubtitleView(context: Context) : View(context) {

    var style: Style = Style.DEFAULT
        private set

    /** Width the max-width percentage refers to (the screen, or the preview box). */
    var referenceWidth: Int = resources.displayMetrics.widthPixels

    /** Size multiplier; the preview draws a scaled-down screen. */
    var scale: Float = 1f

    private var speaker = ""
    private var text = ""
    private var english = ""
    /** The PC's id of the current line (a later line may be written over it) and its speaker's color. */
    private var lineId = Int.MIN_VALUE
    private var color: String? = null
    /** Earlier lines still on screen (oldest first), each with the time it may go away. */
    private data class Older(val id: Int, val speaker: String, val text: String, val until: Long, val color: String?)
    private val older = ArrayList<Older>()

    private var fill: StaticLayout? = null
    private var stroke: StaticLayout? = null
    private var englishLayout: StaticLayout? = null
    private var olderLayouts: List<Pair<StaticLayout, StaticLayout?>> = emptyList()
    private var contentWidth = 0
    private val box = RectF()
    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val density = resources.displayMetrics.density
    private val trLocale = Locale("tr", "TR")

    fun applyStyle(s: Style) {
        style = s
        rebuild()
    }

    /** The current line is an unfinished sentence fragment; its completion will replace it. */
    private var partial = false

    /**
     * Lines never sit side by side: a new line always starts on its own row at the bottom, and the
     * line before it moves up one row (dimmed) for a moment, so the eyes always find new text in the same place.
     * update = the same line grew, was read better or a fragment got its completion: replaced in place.
     * stack = move the current line up instead of dropping it.
     */
    fun setContent(speaker: String, text: String, english: String, update: Boolean = false,
                   stack: Boolean = false, partial: Boolean = false, holdUntil: Long = 0L,
                   id: Int = Int.MIN_VALUE, color: String? = null) {
        if (!update) {
            if (stack && this.text.isNotEmpty() && this.text != text) {
                // Busy scene: the line on screen moves up and stays until it could be read; the oldest goes
                // first when more than maxLines would be shown.
                older.add(Older(lineId, this.speaker, this.text, holdUntil, this.color))
                while (older.size > style.maxLines - 1) older.removeAt(0)
            } else {
                older.clear()
            }
        }
        this.lineId = id
        this.color = color
        this.speaker = speaker
        this.text = text
        this.english = english
        this.partial = partial
        rebuild()
    }

    /**
     * Writes a line over the row of line [oldId] (an unfinished sentence got its rest, a line was read better, the
     * same person said something short again), wherever that row is now.
     * -> 1: it was the newest row, 2: a row moved up (it now stays at least until [until]), 0: not on screen.
     */
    fun replace(oldId: Int, newId: Int, speaker: String, text: String, english: String, partial: Boolean,
                color: String?, until: Long): Int {
        if (this.text.isNotEmpty() && oldId == lineId) {
            setContent(speaker, text, english, update = true, partial = partial, id = newId, color = color)
            return 1
        }
        val i = older.indexOfFirst { it.id == oldId }
        if (i < 0) return 0
        older[i] = Older(newId, speaker, text, maxOf(older[i].until, until), color)
        rebuild()
        return 2
    }

    fun clearPrevious() {
        if (older.isNotEmpty()) {
            older.clear()
            rebuild()
        }
    }

    /** Drops the earlier lines whose time is up. -> the next time one goes away, or 0 when none is left. */
    fun expire(now: Long): Long {
        if (older.removeAll { it.until <= now }) rebuild()
        return older.minOfOrNull { it.until } ?: 0L
    }

    /** The latest time an earlier line may still be on screen (0: none). */
    val olderUntil get() = older.maxOfOrNull { it.until } ?: 0L

    val hasPrevious get() = older.isNotEmpty()
    val textLength get() = text.length

    val hasText get() = text.isNotEmpty()

    // ---- layout ----

    private fun px(dp: Int) = dp * density * scale

    private fun typeface(italic: Boolean = false): Typeface {
        val family = when (style.font) {
            "condensed" -> "sans-serif-condensed"
            "serif" -> "serif"
            "mono" -> "monospace"
            "light" -> "sans-serif-light"
            "medium" -> "sans-serif-medium"
            else -> "sans-serif"
        }
        val weight = when {
            style.bold && italic -> Typeface.BOLD_ITALIC
            style.bold -> Typeface.BOLD
            italic -> Typeface.ITALIC
            else -> Typeface.NORMAL
        }
        return Typeface.create(family, weight)
    }

    private fun paint(sizeSp: Float, color: Int, outline: Boolean, italic: Boolean = false): TextPaint {
        val s = style  // inside apply{} `style` would mean Paint.style
        return TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = sizeSp * density * scale
            typeface = typeface(italic)
            letterSpacing = s.letterSpacing / 100f
            this.color = color
            if (outline) {
                this.style = Paint.Style.STROKE
                strokeWidth = s.outline * 2 * density * scale
                strokeJoin = Paint.Join.ROUND
            } else if (s.shadow > 0) {
                setShadowLayer(s.shadow * density * scale, 0f, 0f, Color.BLACK)
            }
        }
    }

    /** The speaker's own color from the PC (same name, same color), or the one name color of the style. */
    private fun speakerColor(own: String?): Int =
        if (style.speakerColors && !own.isNullOrEmpty()) parse(own) else parse(style.speakerColor)

    private fun caseOf(s: String) = if (style.uppercase) s.uppercase(trLocale) else s

    private fun compose(speaker: String, text: String): String {
        if (!style.speakerShow || speaker.isEmpty()) return caseOf(text)
        val sep = if (style.speakerOwnLine) "\n" else ": "
        return caseOf(speaker) + sep + caseOf(text)
    }

    private fun alignment() = when (style.align) {
        "left" -> Layout.Alignment.ALIGN_NORMAL
        "right" -> Layout.Alignment.ALIGN_OPPOSITE
        else -> Layout.Alignment.ALIGN_CENTER
    }

    private fun layout(text: CharSequence, paint: TextPaint, width: Int): StaticLayout =
        StaticLayout.Builder.obtain(text, 0, text.length, paint, max(1, width))
            .setAlignment(alignment())
            .setLineSpacing(0f, style.lineSpacing / 100f)
            .setIncludePad(false)
            // Balanced: rows of similar length instead of one long row and a short leftover.
            .setBreakStrategy(Layout.BREAK_STRATEGY_BALANCED)
            .build()

    private fun widest(l: StaticLayout?) =
        l?.let { lay -> (0 until lay.lineCount).maxOfOrNull { ceil(lay.getLineWidth(it)).toInt() } ?: 0 } ?: 0

    /** Builds at the maximum width, then again at the widest line so the box hugs the text. */
    private fun pair(text: CharSequence, plain: String, sizeSp: Float, color: Int, maxW: Int, withStroke: Boolean,
                     italic: Boolean = false): Pair<StaticLayout, StaticLayout?> {
        val fillPaint = paint(sizeSp, color, false, italic)
        val w = widest(layout(text, fillPaint, maxW)).coerceAtMost(maxW) + 2
        val strokeLayout =
            if (withStroke) layout(plain, paint(sizeSp, parse(style.outlineColor), true, italic), w) else null
        return layout(text, fillPaint, w) to strokeLayout
    }

    private fun rebuild() {
        val pad = px(style.bgPadding).toInt()
        val maxW = (referenceWidth * style.maxWidth / 100) - 2 * pad
        val withStroke = style.outline > 0
        val textColor = parse(style.textColor)
        fill = null; stroke = null; englishLayout = null; olderLayouts = emptyList()
        if (text.isNotEmpty()) {
            val provisional = partial && style.provisional
            val plain = compose(speaker, text) + if (provisional && !text.trimEnd().endsWith("…")) " …" else ""
            val spanned = SpannableString(plain)
            if (style.speakerShow && speaker.isNotEmpty()) {
                spanned.setSpan(ForegroundColorSpan(speakerColor(color)), 0, speaker.length + 1,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
            // Optional: very long lines shrink (down to 75%) instead of growing past three rows.
            val shrink = if (style.autoShrink && plain.length > 126) (126f / plain.length).coerceAtLeast(0.75f) else 1f
            val color = if (provisional) Color.argb(200, Color.red(textColor), Color.green(textColor),
                Color.blue(textColor)) else textColor
            pair(spanned, plain, style.textSize * shrink, color, maxW, withStroke, italic = provisional).let { (f, s) ->
                fill = f; stroke = s
            }
            if (style.showEnglish && english.isNotEmpty()) {
                val size = style.textSize * style.englishSize / 100f
                englishLayout = pair(english, english, size, parse(style.englishColor), maxW, false).first
            }
            if (older.isNotEmpty()) {
                // Slightly dimmed, still easy to read: in a busy scene they are read after the new one appears.
                val dim = Color.argb(190, Color.red(textColor), Color.green(textColor), Color.blue(textColor))
                val prevSize = style.textSize * (if (style.prevSmaller) 0.8f else 1f)
                olderLayouts = older.map { o ->
                    val plain = compose(o.speaker, o.text)
                    val spanned = SpannableString(plain)
                    if (style.speakerShow && o.speaker.isNotEmpty()) {
                        val speakerDim = speakerColor(o.color).let {
                            Color.argb(190, Color.red(it), Color.green(it), Color.blue(it))
                        }
                        spanned.setSpan(ForegroundColorSpan(speakerDim), 0, o.speaker.length + 1,
                            Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                    }
                    pair(spanned, plain, prevSize, dim, maxW, withStroke)
                }
            }
        }
        contentWidth = (listOf(widest(fill), widest(englishLayout)) + olderLayouts.map { widest(it.first) })
            .maxOrNull() ?: 0
        requestLayout()
        invalidate()
    }

    private fun gap() = px(6)

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        if (fill == null) {
            setMeasuredDimension(0, 0)
            return
        }
        val pad = px(style.bgPadding)
        var h = 0f
        (olderLayouts.map { it.first } + listOfNotNull(englishLayout, fill)).forEachIndexed { i, l ->
            if (i > 0) h += gap()
            h += l.height
        }
        val extra = style.outline * 2 * density * scale
        setMeasuredDimension((contentWidth + 2 * pad + extra).toInt(), (h + 2 * pad + extra).toInt())
    }

    override fun onDraw(canvas: Canvas) {
        val main = fill ?: return
        val pad = px(style.bgPadding)
        if (style.bgOpacity > 0) {
            bgPaint.color = parse(style.bgColor)
            bgPaint.alpha = style.bgOpacity * 255 / 100
            box.set(0f, 0f, width.toFloat(), height.toFloat())
            val r = px(style.bgRadius)
            canvas.drawRoundRect(box, r, r, bgPaint)
        }
        val half = style.outline * density * scale
        var y = pad + half
        fun draw(f: StaticLayout, s: StaticLayout?) {
            val x = when (style.align) {
                "left" -> pad + half
                "right" -> width - pad - half - f.width
                else -> (width - f.width) / 2f
            }
            canvas.save()
            canvas.translate(x, y)
            s?.draw(canvas)
            f.draw(canvas)
            canvas.restore()
            y += f.height + gap()
        }
        // The previous line goes on the side away from the screen edge, so the new line never moves:
        // above it when the subtitle sits at the bottom, below it when it sits at the top.
        val prevAfter = style.position == "top"
        // Oldest farthest from the edge, so the order always reads toward the newest line.
        if (!prevAfter) olderLayouts.forEach { (f, s) -> draw(f, s) }
        if (style.englishAbove) englishLayout?.let { draw(it, null) }
        draw(main, stroke)
        if (!style.englishAbove) englishLayout?.let { draw(it, null) }
        if (prevAfter) olderLayouts.asReversed().forEach { (f, s) -> draw(f, s) }
    }

    companion object {
        fun parse(color: String): Int = runCatching { Color.parseColor(color) }.getOrDefault(Color.WHITE)
    }
}
