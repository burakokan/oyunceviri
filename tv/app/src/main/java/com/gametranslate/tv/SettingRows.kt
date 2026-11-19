package com.gametranslate.tv

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView

object Ui {
    const val BG = 0xFF0E1116.toInt()
    const val PANEL = 0xFF12161C.toInt()
    const val CARD = 0xFF181D25.toInt()
    const val FOCUS = 0xFF24324A.toInt()
    const val ACCENT = 0xFF4C8DFF.toInt()
    const val TEXT = 0xFFE8ECF1.toInt()
    const val MUTED = 0xFF8B97A7.toInt()
    const val GREEN = 0xFF34D399.toInt()

    fun dp(context: Context, v: Int) = (v * context.resources.displayMetrics.density).toInt()

    /** Rounded background that lights up with an accent border when focused (D-pad navigation). */
    fun focusBackground(context: Context, normal: Int = Color.TRANSPARENT): StateListDrawable {
        fun shape(fill: Int, border: Int) = GradientDrawable().apply {
            cornerRadius = dp(context, 10).toFloat()
            setColor(fill)
            if (border != 0) setStroke(dp(context, 2), border)
        }
        return StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused), shape(FOCUS, ACCENT))
            addState(intArrayOf(android.R.attr.state_selected), shape(CARD, 0))
            addState(intArrayOf(), shape(normal, 0))
        }
    }

    fun text(context: Context, sizeSp: Float, color: Int = TEXT, bold: Boolean = false) = TextView(context).apply {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
        setTextColor(color)
        if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
    }
}

/**
 * One settings row: title on the left, value on the right.
 * D-pad LEFT/RIGHT changes the value, OK toggles / opens it.
 */
class SettingRow(
    context: Context,
    title: String,
    private val valueText: () -> CharSequence,
    private val onLeft: (() -> Unit)? = null,
    private val onRight: (() -> Unit)? = null,
    private val onClick: (() -> Unit)? = null,
    description: String? = null,
) : LinearLayout(context) {

    private val value = Ui.text(context, 17f, Ui.TEXT, bold = true)

    init {
        orientation = HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        isFocusable = true
        isFocusableInTouchMode = true
        background = Ui.focusBackground(context)
        val p = Ui.dp(context, 14)
        setPadding(p + 4, p - 2, p + 4, p - 2)
        val texts = LinearLayout(context).apply { orientation = VERTICAL }
        texts.addView(Ui.text(context, 17f))
        (texts.getChildAt(0) as TextView).text = title
        if (description != null) {
            texts.addView(Ui.text(context, 13f, Ui.MUTED).apply { text = description })
        }
        addView(texts, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        value.gravity = Gravity.END
        addView(value, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT))
        setOnClickListener { onClick?.invoke(); refresh() }
        refresh()
    }

    fun refresh() {
        val v = valueText()
        val arrows = onLeft != null || onRight != null
        value.text = if (arrows) android.text.TextUtils.concat("‹   ", v, "   ›") else v
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        when (keyCode) {
            KeyEvent.KEYCODE_DPAD_LEFT -> onLeft?.let { it(); refresh(); return true }
            KeyEvent.KEYCODE_DPAD_RIGHT -> onRight?.let { it(); refresh(); return true }
        }
        return super.onKeyDown(keyCode, event)
    }
}

/** Color name with a small square of that color in front of it. */
fun swatch(list: List<Pair<String, String>>, value: String): CharSequence {
    val s = android.text.SpannableString("■  ${colorName(list, value)}")
    s.setSpan(android.text.style.ForegroundColorSpan(SubtitleView.parse(value)), 0, 1,
        android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    return s
}

val COLORS = listOf(
    "#FFFFFF" to "Beyaz", "#FFF59D" to "Açık sarı", "#FFD54F" to "Sarı", "#FFB74D" to "Turuncu",
    "#80DEEA" to "Camgöbeği", "#90CAF9" to "Mavi", "#A5D6A7" to "Yeşil", "#F48FB1" to "Pembe",
    "#CE93D8" to "Mor", "#CFD8DC" to "Gri", "#B0BEC5" to "Koyu gri", "#000000" to "Siyah",
)

val BG_COLORS = listOf(
    "#000000" to "Siyah", "#0D1B2A" to "Lacivert", "#1B1B1B" to "Koyu gri", "#263238" to "Antrasit",
    "#1A237E" to "Mavi", "#3E2723" to "Kahve", "#FFFFFF" to "Beyaz",
)

fun colorName(list: List<Pair<String, String>>, value: String) =
    list.firstOrNull { it.first.equals(value, ignoreCase = true) }?.second ?: value

fun <T> cycle(list: List<T>, current: T, step: Int): T {
    val i = list.indexOf(current).let { if (it < 0) 0 else it }
    return list[(i + step + list.size) % list.size]
}
