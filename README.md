# Oyun Çeviri

PS5 oyunlarının İngilizce altyazılarını okuyup Türkçeye çevirir ve TV'de, oyunun üstünde gösterir. Kişisel, ticari olmayan kullanım içindir.

Lisans: [GNU AGPL-3.0](LICENSE) · Telif ve kaynak bildirimi: [NOTICE](NOTICE) · Kullanılan bileşenler, modeller ve oyun paketlerinin kaynakları: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)

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

- **Taşınanlar:** altyazı alanı, görev ve telefon alanları, filtreler, çeviri motoru, TV görünümü, konuşmacı renkleri.
- **API anahtarları:** Dosyaya yalnızca kullanıcı "Evet, anahtarlarla" derse girer. Anahtarsız bir dosya yüklenirse bilgisayardaki mevcut anahtarlar korunur.
- **Taşınmayanlar:** PS5 bağlantısı ve PSN hesabı (`ps5.json`), TV'nin adresi ve markası, chiaki-ng yolu. Okuma eşikleri (parlaklık / renk) ve "Oyunda altyazı arka planı açık" seçeneği de taşınmaz, çünkü o PS5'in görüntüsüne göre değişir. Her bilgisayarda Altyazı Alanı → "Otomatik ayarla" ile bulunur. Bu ayarlar dosyaya elle eklense bile yükleme sırasında dikkate alınmaz.

## Yazı okuma modeli

Altyazılar, RapidOCR'daki PP-OCRv6 tiny modelinin oyun altyazılarıyla eğitilmiş hâliyle okunur (`assets/ocr/game_rec_tiny_en.onnx`, Genel → "Yazı okuma motoru" → "Oyunlar için eğitilmiş").

- Model, uygulamayla kaydedilmiş yaklaşık 9.000 altyazı satırıyla ince ayarlandı. Satırların çoğu GTA 6'dan, bir kısmı başka oyunlardan.
- Yalnızca İngilizce karakterleri ve Türkçe harfleri tanır. Standart modelden hızlıdır ve daha az hata yapar.
- Ölçüm sonuçları, elle kontrol edilmiş 132 satırda:
  - tam doğru satır %79,5'ten %96,2'ye çıktı;
  - satır başına süre 7,9 ms'den 5,9 ms'ye düştü.
  - Büyük modelle ikinci okuma artık gerekmediği için varsayılan olarak kapalı.
- Nasıl eğitildiği ve yeniden nasıl eğitileceği `tools/ocr_egitim/README.md` dosyasında.

## Altyazı okuma ve oyunun altyazı arka planı

Altyazılar varsayılan olarak parlaklık ve renk eşiğiyle okunur (Altyazı Alanı → "Okumayı ayarla").

Oyunun altyazı ayarlarında arka plan (yarı saydam ya da koyu kutu) açıksa, Altyazı Alanı → "Oyunda altyazı arka planı açık" seçeneği de açılabilir. Bu seçenek açıkken:

- Harfler arkalarındaki kutuya göre okunur, sabit eşik kullanılmaz.
- Görüntü soluk ya da renk tonu kaymış olsa bile (TV görüntü modu, HDR) okuma bozulmaz. Renkli konuşmacı adları da kaçmaz.
- Kutu bulunamazsa eski eşikli okumaya dönülür.

Oyunda kutu kapalıysa bu seçenek kapalı kalmalı. Kutu yokken aydınlık sahnelerde eşikli okuma daha iyi sonuç verir.

"Otomatik ayarla" düğmesi iki yolu da dener. Kutuya göre okuma belirgin şekilde daha iyiyse seçeneği açar, kötüyse kapatır.

## Lisans

Oyun Çeviri, [GNU Affero General Public License 3.0](LICENSE) ile dağıtılır. Kaynak kodu bu depodadır.

Bu lisansın seçilme sebebi, Remote Play için kullanılan `vendor/couchsubs_native.dll` kitaplığının (CouchSubs, chiaki-ng tabanlı) AGPL-3.0 lisanslı olmasıdır. Kitaplık değiştirilmeden kullanılır; kaynak kodu CouchSubs deposunda, `windows/native/` klasöründedir.

Lisansın kısa özeti:
- Programı kullanmak, değiştirmek ve paylaşmak serbesttir.
- Paylaşılan her kopyada (değiştirilmiş olanlar dahil) kaynak kodu ve bu lisans da verilmelidir.
- Program olduğu gibi verilir, hiçbir garanti yoktur.

Kurulumdaki diğer bileşenlerin her biri kendi lisansıyla dağıtılır: Qt / PySide6, llama.cpp, adb, CUDA dosyaları, OPUS-MT, quickmt ve Gemma modelleri gibi. Liste ve lisanslar [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) dosyasındadır. Gemma modeli [Gemma Terms of Use](https://ai.google.dev/gemma/terms) koşullarına tabidir.

## Oyun paketleri

`packs/` klasöründeki paketler, oyun diyaloglarının Türkçe çevirileridir.

- Bir kısmı [CouchSubs](https://github.com/yorulmazsinan/couchsubs) ve [GameTranslator](https://gitlab.com/sefflex/GameTranslator) projelerinden alınmıştır.
- Bir kısmı bu proje için topluluk vikilerindeki İngilizce metinlerden Gemini ile çevrilmiştir. Kaynak CC BY-SA ise paket de CC BY-SA 3.0 ile, kaynağın yazarları belirtilerek paylaşılır.

Hangi paketin nereden geldiği [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) dosyasındadır.

Oyunların adları, karakterleri ve diyalogları yapımcılarına aittir. Paketler yalnızca sahip olunan oyunlarla kişisel ve ticari olmayan kullanım içindir. Hak sahibiyseniz ve bir paketin kaldırılmasını istiyorsanız depoda bir *issue* açın; paket kaldırılır.

## Teşekkürler

- [CouchSubs](https://github.com/yorulmazsinan/couchsubs) (Sinan Yorulmaz): Remote Play kitaplığı, oyun paketleri ve paket biçimi.
- [GameTranslator](https://gitlab.com/sefflex/GameTranslator) (sefflex): altyazı ayıklama fikirleri ve oyun paketleri.
- [chiaki-ng](https://github.com/chiaki-ng/chiaki-ng): açık kaynak PlayStation Remote Play istemcisi.
- Helsinki-NLP (OPUS-MT), quickmt, Google (Gemma), RapidOCR / PaddleOCR, llama.cpp ve listedeki diğer projelerin geliştiricileri.

## Yasal uyarı

- Bu proje Sony Interactive Entertainment, herhangi bir oyun yapımcısı, CouchSubs ya da GameTranslator ile bağlantılı değildir ve onlar tarafından desteklenmez.
- PlayStation, PS5, PSN ve Remote Play, Sony Interactive Entertainment Inc.'in ticari markalarıdır. Oyun adları sahiplerinin markalarıdır ve burada yalnızca uygulamanın çalıştığı oyunları belirtmek için anılır.
- Uygulama oyunlara ya da PS5'e müdahale etmez. Yalnızca kullanıcının kendi PS5'inden Remote Play ile gelen görüntüyü okur.
