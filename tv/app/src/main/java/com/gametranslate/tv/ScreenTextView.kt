package com.gametranslate.tv

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.ReplacementSpan
import android.util.Base64
import android.view.View
import org.json.JSONArray
import org.json.JSONObject

/**
 * Screen translation (menus, quest log, map names) and the extra areas (hint box, phone messages): the Turkish
 * text drawn over the English one at the same place. The PC sends every box in screen fractions (the HDMI picture
 * fills the screen) with the look chosen on the PC (background, opacity, text size and colour) and the room the
 * text may use: a box never grows over the next translated text, the font gets smaller instead.
 * A box may carry button icons ("icons": {"1": base64 PNG}); "⟦1⟧" in its text is drawn as that picture, as high
 * as the letters. "align": "center" keeps the box centred on the English text (the room "mw" then reaches the same
 * distance to both sides), like a mission objective under the subtitles.
 */
class ScreenTextView(context: Context) : View(context) {

    private class Box(val x: Float, val y: Float, val w: Float, val h: Float, val mw: Float, val mh: Float,
                      val lines: Int, val text: CharSequence, val fg: Int, val bg: Int, val scale: Float,
                      val shadow: Boolean, val center: Boolean)

    /** A button icon inside the text: scales with the font, centred on the letters. */
    private class IconSpan(val bitmap: Bitmap) : ReplacementSpan() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)

        private fun height(p: Paint) = p.textSize * 1.15f

        override fun getSize(p: Paint, text: CharSequence?, start: Int, end: Int, fm: Paint.FontMetricsInt?): Int {
            val h = height(p)
            if (fm != null) {
                val m = p.fontMetricsInt
                fm.ascent = m.ascent; fm.descent = m.descent; fm.top = m.top; fm.bottom = m.bottom
            }
            return (h * bitmap.width / bitmap.height.coerceAtLeast(1)).toInt() + 2
        }

        override fun draw(canvas: Canvas, text: CharSequence?, start: Int, end: Int, x: Float, top: Int, y: Int,
                          bottom: Int, p: Paint) {
            val h = height(p)
            val w = h * bitmap.width / bitmap.height.coerceAtLeast(1)
            val mid = y + (p.ascent() + p.descent()) / 2f
            canvas.drawBitmap(bitmap, null, RectF(x + 1, mid - h / 2, x + 1 + w, mid + h / 2), paint)
        }
    }

    private var boxes = emptyList<Box>()
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
    }

    fun setBoxes(json: JSONArray) {
        boxes = (0 until json.length()).mapNotNull { i ->
            val b = json.optJSONObject(i) ?: return@mapNotNull null
            val bg = runCatching { Color.parseColor(b.optString("bg", "#000000")) }.getOrDefault(Color.BLACK)
            val alpha = (b.optDouble("alpha", 0.9) * 255).toInt().coerceIn(0, 255)
            val w = b.optDouble("w").toFloat()
            val h = b.optDouble("h").toFloat()
            Box(b.optDouble("x").toFloat(), b.optDouble("y").toFloat(), w, h,
                b.optDouble("mw", w * 1.8).toFloat(), b.optDouble("mh", h.toDouble()).toFloat(),
                b.optInt("lines", 1).coerceAtLeast(1), withIcons(b.optString("tr"), b.optJSONObject("icons")),
                runCatching { Color.parseColor(b.optString("fg", "#ffffff")) }.getOrDefault(Color.WHITE),
                Color.argb(alpha, Color.red(bg), Color.green(bg), Color.blue(bg)),
                b.optDouble("scale", 1.0).toFloat().coerceIn(0.4f, 2.5f), b.optBoolean("shadow", false),
                b.optString("align") == "center")
        }
        visibility = if (boxes.isEmpty()) GONE else VISIBLE
        invalidate()
    }

    private val token = Regex("⟦(\\d+)⟧")

    /** "⟦1⟧ tuşuna bas" -> the icon picture in place of the token (an icon that cannot be decoded is left out). */
    private fun withIcons(text: String, icons: JSONObject?): CharSequence {
        if (icons == null || !token.containsMatchIn(text)) return token.replace(text, "")
        val out = SpannableStringBuilder()
        var last = 0
        for (m in token.findAll(text)) {
            out.append(text, last, m.range.first)
            val bitmap = runCatching {
                val bytes = Base64.decode(icons.optString(m.groupValues[1]), Base64.DEFAULT)
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            }.getOrNull()
            if (bitmap != null) {
                val at = out.length
                out.append("￼")
                out.setSpan(IconSpan(bitmap), at, at + 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
            last = m.range.last + 1
        }
        out.append(text, last, text.length)
        return out
    }

    override fun onDraw(canvas: Canvas) {
        val sw = width.toFloat()
        val sh = height.toFloat()
        for (b in boxes) {
            val left = b.x * sw
            val top = b.y * sh
            val boxW = (b.w * sw).coerceAtLeast(8f)
            val boxH = (b.h * sh).coerceAtLeast(8f)
            val roomW = maxOf(boxW, b.mw * sw)
            val roomH = maxOf(boxH, b.mh * sh)
            val lineH = boxH / b.lines
            val pad = minOf(lineH * 0.12f, 6f)
            paint.color = b.fg
            if (b.shadow) paint.setShadowLayer(lineH * 0.15f, 0f, lineH * 0.05f, Color.BLACK)
            else paint.clearShadowLayer()
            val layout = fit(b.text, roomW - 2 * pad, roomH - 2 * pad, lineH, b.scale, b.center)
            val textW = (0 until layout.lineCount).maxOf { layout.getLineWidth(it) }
            val rectW = minOf(roomW, maxOf(boxW, textW + 2 * pad))
            val rectH = minOf(roomH, maxOf(boxH, layout.height + 2 * pad))
            // Centred: around the middle of the English text; otherwise from its left edge to the right.
            val cx = left + boxW / 2
            if (Color.alpha(b.bg) > 0) {
                fill.color = b.bg
                val rect = if (b.center) RectF(cx - rectW / 2, top - pad, cx + rectW / 2, top + rectH)
                    else RectF(left - pad, top - pad, left + rectW, top + rectH)
                canvas.drawRoundRect(rect, pad, pad, fill)
            }
            canvas.save()
            if (b.center) canvas.clipRect(cx - roomW / 2, top - pad, cx + roomW / 2, top + roomH)
            else canvas.clipRect(left - pad, top - pad, left + roomW, top + roomH)
            val textLeft = if (b.center) cx - layout.width / 2f else left
            canvas.translate(textLeft, top + maxOf(0f, (rectH - layout.height) / 2 - pad))
            layout.draw(canvas)
            canvas.restore()
        }
    }

    /** The original text height x the chosen size first, smaller until it fits the room. */
    private fun fit(text: CharSequence, w: Float, h: Float, lineH: Float, scale: Float,
                    center: Boolean): StaticLayout {
        var size = lineH * 0.72f * scale
        val min = lineH * 0.35f
        var layout = make(text, w, size, center)
        while (size > min && (layout.height > h * 1.02f || widest(layout) > w)) {
            size *= 0.92f
            layout = make(text, w, size, center)
        }
        return layout
    }

    private fun widest(l: StaticLayout) = (0 until l.lineCount).maxOf { l.getLineWidth(it) }

    private fun make(text: CharSequence, w: Float, size: Float, center: Boolean): StaticLayout {
        paint.textSize = size
        return StaticLayout.Builder.obtain(text, 0, text.length, paint, w.toInt().coerceAtLeast(20))
            .setAlignment(if (center) Layout.Alignment.ALIGN_CENTER else Layout.Alignment.ALIGN_NORMAL)
            .setLineSpacing(0f, 1.05f)
            .setIncludePad(false)
            .build()
    }
}
