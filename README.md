# Oyun Çeviri

PS5 oyunlarının İngilizce altyazılarını okuyup Türkçeye çevirir ve TV'de, oyunun üstünde gösterir. Kişisel kullanım içindir.

## Klasörler

| Klasör | Ne var |
|---|---|
| `pc/` | Windows uygulaması (PySide6). Başlangıç dosyası: `pc/app.py`. Asıl iş `pc/gt/` içinde: OCR, çeviri, Remote Play, paketler, güncelleme. |
| `tv/` | Android TV uygulaması (Kotlin) |
| `tv-web/` | Samsung / LG TV uygulaması (web) |
| `packs/` | Hazır oyun çevirileri (`*.json.gz`), düzeltmeler (`fixes/`) ve paket yapım dosyaları (`build/`) |
| `packaging/` | Kurulum dosyası ve sürüm yayınlama |
| `tools/SamsungHelper/` | Samsung TV'ye kurulum yardımcısı (.NET) |
| `vendor/` | adb ve Remote Play kitaplığı (`couchsubs_native.dll`, AGPL) |

Git'e konmayanlar: `config.json` (API anahtarları), `ps5.json` (PS5 anahtarları), `logs/`, `models/` (çeviri modelleri), `vendor/llama/` (llama.cpp b12100, CUDA 12), `vendor/samsung/` (`tools/SamsungHelper`'dan derlenir).

## Yeni sürüm yayınlama

1. `pc/gt/version.py` içindeki `VERSION` değerini artır (örnek `1.0.1`). TV uygulaması değiştiyse `TV_APP` / `TV_WEB` değerlerini de artır.
2. Yayınla:

```powershell
.venv\Scripts\python.exe packaging\publish.py --notes "Ne değişti"
```

Bu komut uygulamayı derler. Yalnız değişen dosyaları içeren bir güncelleme paketi hazırlar ve GitHub Releases'e yükler. Kurulu uygulamalar bu paketi kendileri indirir. Tam kurulum dosyasını da yüklemek için komuta `--setup` ekle.

`packaging/releases/` klasöründe her sürümün dosya listesi durur. Bir sonraki güncellemenin neyin değiştiğini bulması bu listeye bağlıdır, o yüzden klasör git'te kalmalı.

## Kurulu uygulamanın güncellenmesi

- Uygulama açılışta ve açıkken saatte bir yeni sürüme bakar. Yeni sürüm varsa yalnızca haber verir; hiçbir şeyi kendiliğinden indirmez ya da kurmaz. Kurulum, Genel → Güncelleme → "İndir ve kur" düğmesine basınca olur. Böylece oyun sırasında program hiç yeniden başlamaz.
- Depo herkese açık, o yüzden erişim anahtarı gerekmez.
- Güncelleme kullanıcının kendi dosyalarına hiç dokunmaz: `config.json`, `ps5.json`, `speakers.json`, önbellekler, `logs/`, `tv-keys/`, `packs/build/`. Bir sürüm bu dosyaları yanlışlıkla içerse ya da silinecekler listesine koysa bile durum değişmez. Kanıt testi gerçek uygulamaya dokunmaz, `D:\OyunCeviriTest` içinde ayrı bir kurulum kullanır:

```powershell
.venv\Scripts\python.exe packaging\update_proof.py
```

- Bağlanan Android TV uygulaması eskiyse, altyazı durdurulmuşken ağ üzerinden kendiliğinden güncellenir.

## Ayarları başka bilgisayara taşıma

Genel → "Ayarları başka bilgisayara taşı" bölümünde iki düğme var: "Dosyaya yaz" ve "Dosyadan yükle". Bunlar `pc/gt/settings_io.py` kodunu kullanır.

- **Taşınanlar:** altyazı alanı ve eşikleri, görev ve telefon alanları, filtreler, çeviri motoru, TV görünümü, konuşmacı renkleri.
- **API anahtarları:** Dosyaya yalnızca kullanıcı "Evet, anahtarlarla" derse girer. Anahtarsız bir dosya yüklenirse bilgisayardaki mevcut anahtarlar korunur.
- **Taşınmayanlar:** PS5 bağlantısı ve PSN hesabı (`ps5.json`), TV'nin adresi ve markası, chiaki-ng yolu. Bunlar her bilgisayarda yeniden kurulur. Dosyaya elle eklenseler bile yükleme sırasında dikkate alınmaz.
