package com.gametranslate.tv

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Settings screen with a live preview, driven with the TV remote. */
class MainActivity : Activity() {

    private class Category(val name: String, val rows: () -> List<View>)

    private lateinit var prefs: Prefs
    private lateinit var statusView: TextView
    private lateinit var categoryTitle: TextView
    private lateinit var rowsBox: LinearLayout
    private lateinit var preview: FrameLayout
    private lateinit var previewSubtitle: SubtitleView
    private val categoryViews = mutableListOf<TextView>()
    private var current = 0
    private val main = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            updateStatus()
            main.postDelayed(this, 1000)
        }
    }
    private val styleListener: (Style, Boolean) -> Unit = { _, fromPc ->
        main.post {
            updatePreview()
            if (fromPc) rowsBox.children().filterIsInstance<SettingRow>().forEach { it.refresh() }
        }
    }

    private val style get() = StyleStore.style
    private fun edit(change: (Style) -> Style) = StyleStore.update(this, change(style))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        StyleStore.load(this)
        setContentView(buildLayout())
        selectCategory(0, focusRows = false)
        categoryViews[0].requestFocus()
        StyleStore.addListener(styleListener)
        if (!OverlayService.running && Settings.canDrawOverlays(this)) OverlayService.start(this)
    }

    override fun onDestroy() {
        StyleStore.removeListener(styleListener)
        super.onDestroy()
    }

    override fun onResume() {
        super.onResume()
        main.post(refresh)
        if (Settings.canDrawOverlays(this)) {
            if (!OverlayService.running) OverlayService.start(this)
        } else if (!askedOverlay) {
            askedOverlay = true
            askOverlayPermission()
        }
    }

    private var askedOverlay = false

    /** Installed from a USB stick (no PC to grant it): send the user to the permission screen. */
    private fun askOverlayPermission() {
        AlertDialog.Builder(this)
            .setTitle("Ekran üstü izni gerekiyor")
            .setMessage("Türkçe altyazının oyunun üstünde görünmesi için Oyun Çeviri'ye \"Diğer uygulamaların " +
                "üzerinde göster\" izni ver. İzin ver'e basınca ayar ekranı açılır; Oyun Çeviri'yi seçip izni aç, " +
                "sonra geri gel.")
            .setPositiveButton("İzin ver") { _, _ ->
                val direct = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                val list = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
                val ok = runCatching { startActivity(direct) }.isSuccess || runCatching { startActivity(list) }.isSuccess
                if (!ok) {
                    AlertDialog.Builder(this)
                        .setTitle("Ayar ekranı açılamadı")
                        .setMessage("TV'de elle aç: Ayarlar → Uygulamalar → Özel uygulama erişimi → Diğer " +
                            "uygulamaların üzerinde göster → Oyun Çeviri → İzin ver.")
                        .setPositiveButton("Tamam", null)
                        .show()
                }
            }
            .setNegativeButton("Sonra", null)
            .show()
    }

    override fun onPause() {
        main.removeCallbacks(refresh)
        super.onPause()
    }

    @Deprecated("Back moves from the settings back to the category list before leaving.")
    override fun onBackPressed() {
        if (currentFocus?.parent === rowsBox) {
            categoryViews[current].requestFocus()
        } else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }

    // ---- layout ----

    private fun dp(v: Int) = Ui.dp(this, v)

    private fun buildLayout(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(Ui.BG)
        }

        val left = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Ui.PANEL)
            setPadding(dp(28), dp(32), dp(20), dp(24))
        }
        left.addView(Ui.text(this, 28f, bold = true).apply { text = getString(R.string.app_name) })
        left.addView(Ui.text(this, 14f, Ui.MUTED).apply { text = "PS5 altyazıları · Türkçe" })
        statusView = Ui.text(this, 14f, Ui.GREEN).apply { setPadding(0, dp(14), 0, dp(18)) }
        left.addView(statusView)
        CATEGORIES.forEachIndexed { i, cat ->
            val item = Ui.text(this, 18f).apply {
                text = cat.name
                isFocusable = true
                isFocusableInTouchMode = true
                background = Ui.focusBackground(this@MainActivity)
                setPadding(dp(16), dp(11), dp(16), dp(11))
                setOnFocusChangeListener { _, has -> if (has) selectCategory(i, focusRows = false) }
                setOnClickListener { selectCategory(i, focusRows = true) }
            }
            categoryViews.add(item)
            left.addView(item, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(2) })
        }
        left.addView(View(this), LinearLayout.LayoutParams(1, 0, 1f))
        left.addView(Ui.text(this, 12f, Ui.MUTED).apply { text = "Sürüm ${BuildConfig.VERSION_NAME}" })
        root.addView(left, LinearLayout.LayoutParams(dp(300), ViewGroup.LayoutParams.MATCH_PARENT))

        val right = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(32), dp(28), dp(32), dp(16))
        }
        preview = FrameLayout(this).apply {
            background = GradientDrawable(GradientDrawable.Orientation.TL_BR,
                intArrayOf(0xFF52624F.toInt(), 0xFF2E3A2C.toInt(), 0xFF151B14.toInt())).apply {
                cornerRadius = dp(14).toFloat()
            }
            clipToOutline = true
        }
        preview.addView(Ui.text(this, 12f, 0xAAFFFFFF.toInt()).apply {
            text = "ÖNİZLEME"
            setPadding(dp(14), dp(10), 0, 0)
        })
        previewSubtitle = SubtitleView(this).apply {
            setContent(OverlayService.SAMPLE_SPEAKER, OverlayService.SAMPLE_TR, OverlayService.SAMPLE_EN)
        }
        preview.addView(previewSubtitle)
        preview.addOnLayoutChangeListener { _, l, t, r, b, ol, ot, or, ob ->
            if (r - l != or - ol || b - t != ob - ot) preview.post { updatePreview() }
        }
        right.addView(preview, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(250)))

        categoryTitle = Ui.text(this, 22f, bold = true).apply { setPadding(dp(4), dp(18), 0, dp(8)) }
        right.addView(categoryTitle)
        rowsBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(rowsBox)
        }
        right.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(right, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
        return root
    }

    private fun selectCategory(i: Int, focusRows: Boolean) {
        current = i
        categoryViews.forEachIndexed { j, v -> v.isSelected = j == i }
        categoryTitle.text = CATEGORIES[i].name
        rowsBox.removeAllViews()
        CATEGORIES[i].rows().forEach { row ->
            rowsBox.addView(row, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(4) })
        }
        if (focusRows) rowsBox.getChildAt(0)?.requestFocus()
    }

    private fun updatePreview() {
        val w = preview.width
        if (w == 0) return
        val screen = resources.displayMetrics
        previewSubtitle.scale = w.toFloat() / screen.widthPixels
        previewSubtitle.referenceWidth = w
        previewSubtitle.applyStyle(style)
        val vertical = when (style.position) {
            "top" -> Gravity.TOP
            "middle" -> Gravity.CENTER_VERTICAL
            else -> Gravity.BOTTOM
        }
        val horizontal = when (style.align) {
            "left" -> Gravity.LEFT
            "right" -> Gravity.RIGHT
            else -> Gravity.CENTER_HORIZONTAL
        }
        val margin = if (style.position == "middle") 0 else preview.height * style.offset / 100
        val side = if (style.align == "center") 0 else w * 3 / 100
        previewSubtitle.translationX = w * style.xOffset / 100f
        previewSubtitle.layoutParams = FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT, vertical or horizontal).apply {
            if (style.position == "top") topMargin = margin else bottomMargin = margin
            leftMargin = side
            rightMargin = side
        }
    }

    private fun updateStatus() {
        statusView.text = if (!Settings.canDrawOverlays(this)) {
            "Ekran üstü izni yok — TV Ayarlar → Uygulamalar → Özel uygulama erişimi → Diğer uygulamaların üzerinde göster"
        } else {
            "● ${OverlayService.status}"
        }
        rowsBox.children().filterIsInstance<SettingRow>().forEach { it.refresh() }
    }

    // ---- rows ----

    private fun number(title: String, desc: String?, get: (Style) -> Int, set: (Style, Int) -> Style,
                       min: Int, max: Int, step: Int, fmt: (Int) -> String = { "$it" }) =
        SettingRow(this, title, { fmt(get(style)) },
            onLeft = { edit { set(it, (get(it) - step).coerceIn(min, max)) } },
            onRight = { edit { set(it, (get(it) + step).coerceIn(min, max)) } },
            description = desc)

    private fun toggle(title: String, desc: String?, get: (Style) -> Boolean, set: (Style, Boolean) -> Style) =
        SettingRow(this, title, { if (get(style)) "Açık" else "Kapalı" },
            onLeft = { edit { set(it, !get(it)) } }, onRight = { edit { set(it, !get(it)) } },
            onClick = { edit { set(it, !get(it)) } }, description = desc)

    private fun choice(title: String, desc: String?, options: List<Pair<String, String>>,
                       get: (Style) -> String, set: (Style, String) -> Style): SettingRow {
        val values = options.map { it.first }
        return SettingRow(this, title, { options.firstOrNull { it.first == get(style) }?.second ?: get(style) },
            onLeft = { edit { set(it, cycle(values, get(it), -1)) } },
            onRight = { edit { set(it, cycle(values, get(it), +1)) } },
            onClick = { edit { set(it, cycle(values, get(it), +1)) } }, description = desc)
    }

    private fun color(title: String, palette: List<Pair<String, String>>, get: (Style) -> String,
                      set: (Style, String) -> Style): SettingRow {
        val values = palette.map { it.first }
        return SettingRow(this, title, { swatch(palette, get(style)) },
            onLeft = { edit { set(it, cycle(values, get(it).uppercase(), -1)) } },
            onRight = { edit { set(it, cycle(values, get(it).uppercase(), +1)) } },
            onClick = { edit { set(it, cycle(values, get(it).uppercase(), +1)) } })
    }

    private fun action(title: String, desc: String?, value: () -> CharSequence = { "" }, run: () -> Unit) =
        SettingRow(this, title, value, onClick = run, description = desc)

    private fun preset(name: String, desc: String, change: (Style) -> Style) =
        action(name, desc, { "Uygula" }) { StyleStore.update(this, change(Style.DEFAULT)); OverlayService.showTest(this) }

    private val CATEGORIES by lazy {
        listOf(
            Category("Bağlantı") {
                listOf(
                    action("Durum", null, { OverlayService.status }) {},
                    action("PC adresi", "Boş bırakırsan PC otomatik bulunur.",
                        { prefs.host.ifEmpty { "Otomatik" } }) { askHost() },
                    SettingRow(this, "TV açılınca otomatik başlat", { if (prefs.autoStart) "Açık" else "Kapalı" },
                        onLeft = { prefs.autoStart = !prefs.autoStart }, onRight = { prefs.autoStart = !prefs.autoStart },
                        onClick = { prefs.autoStart = !prefs.autoStart }),
                    action("Test yazısı göster", "Görünümü oyunun üstünde dene.") { OverlayService.showTest(this) },
                    action("Altyazı hizmetini yeniden başlat", null) {
                        OverlayService.stop(this)
                        main.postDelayed({ OverlayService.start(this) }, 400)
                    },
                )
            },
            Category("Hazır görünümler") {
                listOf(
                    preset("Klasik", "Yarı saydam siyah kutu, beyaz yazı.") { it },
                    preset("Sinema", "Kutusuz, kalın siyah kenarlıklı beyaz yazı.") {
                        it.copy(bgOpacity = 0, outline = 4, shadow = 8)
                    },
                    preset("Sarı altyazı", "Kutusuz, sarı yazı.") {
                        it.copy(bgOpacity = 0, textColor = "#FFF59D", speakerColor = "#FFFFFF", outline = 4)
                    },
                    preset("Büyük ve okunaklı", "Uzaktan okumak için büyük yazı, koyu kutu.") {
                        it.copy(textSize = 40, bgOpacity = 75, maxWidth = 90)
                    },
                    preset("Sade", "İnce yazı, hafif kutu, gölgesiz.") {
                        it.copy(font = "light", bold = false, outline = 0, shadow = 0, bgOpacity = 40)
                    },
                    preset("Üstte", "Altyazı ekranın üstünde, oyunun kendi altyazısıyla çakışmaz.") {
                        it.copy(position = "top", offset = 5)
                    },
                )
            },
            Category("Yazı") {
                listOf(
                    number("Yazı boyutu", null, { it.textSize }, { s, v -> s.copy(textSize = v) }, 16, 72, 2),
                    choice("Yazı tipi", null, FONTS, { it.font }, { s, v -> s.copy(font = v) }),
                    toggle("Kalın", null, { it.bold }, { s, v -> s.copy(bold = v) }),
                    color("Yazı rengi", COLORS, { it.textColor }, { s, v -> s.copy(textColor = v) }),
                    toggle("BÜYÜK HARF", null, { it.uppercase }, { s, v -> s.copy(uppercase = v) }),
                    number("Satır aralığı", null, { it.lineSpacing }, { s, v -> s.copy(lineSpacing = v) },
                        80, 200, 5) { "%$it" },
                    number("Harf aralığı", null, { it.letterSpacing }, { s, v -> s.copy(letterSpacing = v) },
                        -5, 30, 1),
                    number("En fazla genişlik", "Satır bu genişliği geçince alta kayar.", { it.maxWidth },
                        { s, v -> s.copy(maxWidth = v) }, 30, 100, 5) { "%$it" },
                    toggle("Uzun satırları küçült", "Çok uzun cümlelerde yazı biraz küçülür. Kapalıyken tüm satırlar " +
                        "aynı boyuttadır.", { it.autoShrink }, { s, v -> s.copy(autoShrink = v) }),
                    toggle("Önceki satır küçük olsun", "Yukarı kayan önceki satır daha küçük yazılır.",
                        { it.prevSmaller }, { s, v -> s.copy(prevSmaller = v) }),
                )
            },
            Category("Konuşmacı adı") {
                listOf(
                    toggle("Konuşmacı adını göster", "\"Karl:\" gibi isimler.", { it.speakerShow },
                        { s, v -> s.copy(speakerShow = v) }),
                    toggle("Her konuşmacı kendi renginde", "Aynı isim hep aynı renk.", { it.speakerColors },
                        { s, v -> s.copy(speakerColors = v) }),
                    color("İsim rengi", COLORS, { it.speakerColor }, { s, v -> s.copy(speakerColor = v) }),
                    toggle("İsim ayrı satırda", null, { it.speakerOwnLine }, { s, v -> s.copy(speakerOwnLine = v) }),
                )
            },
            Category("Kenarlık ve gölge") {
                listOf(
                    number("Kenarlık kalınlığı", "Yazının etrafındaki çizgi. 0 = yok.", { it.outline },
                        { s, v -> s.copy(outline = v) }, 0, 8, 1),
                    color("Kenarlık rengi", COLORS, { it.outlineColor }, { s, v -> s.copy(outlineColor = v) }),
                    number("Gölge", "0 = yok.", { it.shadow }, { s, v -> s.copy(shadow = v) }, 0, 20, 1),
                )
            },
            Category("Arka plan") {
                listOf(
                    number("Opaklık", "0 = kutu yok, 100 = tamamen dolu.", { it.bgOpacity },
                        { s, v -> s.copy(bgOpacity = v) }, 0, 100, 5) { "%$it" },
                    color("Kutu rengi", BG_COLORS, { it.bgColor }, { s, v -> s.copy(bgColor = v) }),
                    number("Köşe yuvarlaklığı", null, { it.bgRadius }, { s, v -> s.copy(bgRadius = v) }, 0, 40, 2),
                    number("İç boşluk", null, { it.bgPadding }, { s, v -> s.copy(bgPadding = v) }, 0, 40, 2),
                )
            },
            Category("Konum") {
                listOf(
                    choice("Dikey konum", null, listOf("bottom" to "Altta", "middle" to "Ortada", "top" to "Üstte"),
                        { it.position }, { s, v -> s.copy(position = v) }),
                    number("Kenardan uzaklık", "Ekranın alt/üst kenarına mesafe.", { it.offset },
                        { s, v -> s.copy(offset = v) }, 0, 45, 1) { "%$it" },
                    choice("Yatay hizalama", null, listOf("left" to "Sola", "center" to "Ortaya", "right" to "Sağa"),
                        { it.align }, { s, v -> s.copy(align = v) }),
                    number("Yatay kaydırma", "Altyazıyı sola (−) ya da sağa (+) kaydırır.", { it.xOffset },
                        { s, v -> s.copy(xOffset = v) }, -45, 45, 1) { "%$it" },
                )
            },
            Category("İngilizce orijinal") {
                listOf(
                    toggle("İngilizcesini de göster", "Çevirinin yanında oyundaki orijinal cümle.",
                        { it.showEnglish }, { s, v -> s.copy(showEnglish = v) }),
                    number("Boyutu", "Türkçe yazıya göre.", { it.englishSize }, { s, v -> s.copy(englishSize = v) },
                        30, 100, 5) { "%$it" },
                    color("Rengi", COLORS, { it.englishColor }, { s, v -> s.copy(englishColor = v) }),
                    choice("Yeri", null, listOf("below" to "Altında", "above" to "Üstünde"),
                        { if (it.englishAbove) "above" else "below" }, { s, v -> s.copy(englishAbove = v == "above") }),
                )
            },
            Category("Zamanlama") {
                listOf(
                    number("Ekranda kalma", "İngilizce altyazı kaybolduktan sonra Türkçesi ne kadar kalsın.",
                        { it.lingerMs }, { s, v -> s.copy(lingerMs = v) }, 0, 5000, 100) { "${it} ms" },
                    number("Geçiş efekti", "Belirme/kaybolma süresi. 0 = anında.", { it.fadeMs },
                        { s, v -> s.copy(fadeMs = v) }, 0, 600, 20) { "${it} ms" },
                    number("Önceki satır üstte kalsın", "Yeni satır gelince eskisi bir satır yukarı kayıp soluk olarak " +
                        "bu kadar kalır. 0 = hemen kaybolur.", { it.prevHoldMs }, { s, v -> s.copy(prevHoldMs = v) },
                        0, 8000, 250) { if (it == 0) "Kapalı" else "${it} ms" },
                    toggle("Önceki satır hep kalsın", "Süre dolmadan, bir sonraki satır gelene kadar üstte kalır.",
                        { it.stackPrevious }, { s, v -> s.copy(stackPrevious = v) }),
                    number("En az okuma süresi", "Her satır en az bu kadar + karakter başına süre ekranda kalır.",
                        { it.readBaseMs }, { s, v -> s.copy(readBaseMs = v) }, 0, 5000, 250) { "${it} ms" },
                    number("Karakter başına okuma süresi", null, { it.readPerCharMs },
                        { s, v -> s.copy(readPerCharMs = v) }, 0, 150, 5) { "${it} ms" },
                    number("En fazla okuma süresi", null, { it.readMaxMs }, { s, v -> s.copy(readMaxMs = v) },
                        1000, 10000, 500) { "${it} ms" },
                    toggle("Yarım cümleyi italik göster", "Devamı gelecek parça italik ve soluk görünür; devamı " +
                        "gelince tam cümle aynı yerde onun yerini alır.", { it.provisional },
                        { s, v -> s.copy(provisional = v) }),
                )
            },
            Category("Sıfırla") {
                listOf(
                    action("Görünümü varsayılana döndür", "Tüm yazı, renk ve konum ayarları ilk haline döner.",
                        { "Sıfırla" }) { StyleStore.update(this, Style.DEFAULT); OverlayService.showTest(this) },
                )
            },
        )
    }

    private fun askHost() {
        val input = EditText(this).apply {
            setText(prefs.host)
            hint = "örn. 192.168.1.4 (boş = otomatik)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        AlertDialog.Builder(this)
            .setTitle("PC adresi")
            .setView(input)
            .setPositiveButton("Kaydet") { _, _ ->
                prefs.host = input.text.toString()
                OverlayService.stop(this)
                main.postDelayed({ OverlayService.start(this) }, 400)
            }
            .setNegativeButton("Vazgeç", null)
            .show()
    }

    private fun ViewGroup.children() = (0 until childCount).map { getChildAt(it) }

    companion object {
        val FONTS = listOf("sans" to "Standart", "condensed" to "Dar", "medium" to "Orta kalın",
            "light" to "İnce", "serif" to "Tırnaklı", "mono" to "Eş aralıklı")
    }
}
