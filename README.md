# Oyun Çeviri

PS5 oyunlarının İngilizce altyazılarını okuyup Türkçeye çevirir ve TV'de, oyunun üstünde gösterir. Kişisel, ticari olmayan kullanım içindir.

Lisans: [GNU AGPL-3.0](LICENSE) · Telif ve kaynak bildirimi: [NOTICE](NOTICE) · Kullanılan bileşenler, modeller ve oyun paketlerinin kaynakları: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)

## Kurulum

### Gerekenler

- **Bilgisayar:**
  - Windows 10 ya da 11 (64 bit).
  - Diskte yaklaşık 12 GB boş yer: indirme 4,6 GB, kurulu hâli 6,5 GB. Kurulumdan sonra indirilen dosyalar silinebilir.
- **Ekran kartı (isteğe bağlı):** NVIDIA ekran kartı varsa yedek çeviri modeli (Gemma) onda çalışır. Yoksa öteki çeviri yolları kullanılır, uygulama yine çalışır.
- **PS5:** Bilgisayar, PS5 ve TV aynı modeme bağlı olmalı. Bilgisayar ve PS5 için kablo önerilir.
- **TV:**
  - Android TV / Google TV (TCL, Sony, Philips, Xiaomi, Hisense…);
  - Samsung (2019 ve sonrası);
  - LG (webOS).
- **İkinci PSN hesabı:** Ücretsiz. Neden gerektiği aşağıda, 4. adımda anlatılıyor.

### 1. Kurulum dosyalarını indir

Tam kurulum dosyaları **[v1.0.0 sürüm sayfasında](https://github.com/burakokan/oyunceviri/releases/tag/v1.0.0)**. Sonraki sürümlerin sayfalarında yalnızca güncelleme paketleri var; uygulama kurulduktan sonra kendini son sürüme günceller.

1. Sayfanın altındaki **Assets** bölümünü aç.
2. Şu 4 dosyanın **hepsini** indir (toplam yaklaşık 4,6 GB):
   - `OyunCeviri-Kurulum.exe`
   - `OyunCeviri-Kurulum-1.bin`
   - `OyunCeviri-Kurulum-2.bin`
   - `OyunCeviri-Kurulum-3.bin`
3. Dördünü **aynı klasöre** koy (örneğin İndirilenler) ve **adlarını değiştirme**.
4. Dördünün de indirmesi **bitmeden** kurulumu açma. `.bin` dosyaları büyüktür ve tarayıcı onları exe'den sonra bitirir.

`.bin` dosyaları kurulumun parçalarıdır, tek başlarına açılmaz. Kurulum programı (`.exe`) bu parçaları kendi yanında arar. Biri eksikse ya da başka klasördeyse kurulum "disk" ister ve devam etmez.

`Source code (zip)` ve `Source code (tar.gz)` kaynak koddur; kurulum için gerekmez.

### 2. Kurulumu çalıştır

1. `OyunCeviri-Kurulum.exe`'ye çift tıkla.
2. "Windows bilgisayarınızı korudu" uyarısı çıkabilir (kurulum dosyası imzalı değil). **Ek bilgi**'ye, sonra **Yine de çalıştır**'a bas.
3. Kurulum yönetici izni istemez. Uygulama `%LOCALAPPDATA%\Programs\Oyun Ceviri` klasörüne kurulur.
4. Seçenekler:
   - **Masaüstüne kısayol koy:** isteğe bağlı.
   - **Windows güvenlik duvarında izin ver:** açık bırak. TV'nin bu bilgisayara bağlanabilmesi için gerekir; bir kez yönetici onayı ister.
5. Kurulum bitince **Oyun Çeviri'yi şimdi aç** işaretli kalsın ve **Son**'a bas.

### 3. Son sürüme güncelle

Uygulama açılınca yeni sürüm olup olmadığına kendisi bakar. "Yeni sürüm var" bildirimi gelince **Genel → Güncelleme → İndir ve kur**'a bas. Uygulama güncellemeyi indirir, kapanıp yeniden açılır. 1.0.0'dan son sürüme geçiş yaklaşık 70 MB'tır.

Bundan sonra da uygulama açılışta ve açıkken saatte bir yeni sürüme bakar. Yeni sürüm varsa yalnızca haber verir, sen istemeden hiçbir şey kurmaz. Ayarların ve kayıtların güncellemede korunur.

### 4. İlk ayar (Başlarken)

Uygulama ilk açılışta **Başlarken** rehberiyle açılır. Her adım uygulamanın içinden yapılır ve bittiğinde ✓ ile işaretlenir. Rehber her zaman soldaki menüde durur.

1. **İkinci PSN hesabı:**
   - Remote Play'e oyunu oynadığın hesapla bağlanılırsa PS5 o hesabın kolunu kapatır. Bu yüzden bilgisayar **ikinci bir hesapla** bağlanır; sen kendi hesabınla oynamaya devam edersin.
   - Ücretsiz yeni bir PSN hesabı aç ve PS5'te bu hesapla bir kez oturum aç.
2. **PS5 ayarları:**
   - **Ayarlar → Sistem → Uzaktan Oynatma → Uzaktan Oynatmayı Etkinleştir:** açık.
   - **Ayarlar → Sistem → Güç Tasarrufu → Dinlenme Modunda Kullanılabilen Özellikler:** **İnternete Bağlı Kal** ve **PS5'in Ağ Üzerinden Açılmasını Etkinleştir** açık. Böylece uygulama dinlenme modundaki PS5'i uyandırabilir.
3. **PS5'i bağla:** Uygulamadaki PSN girişini **ikinci hesapla** yap. Sonra PS5'te ikinci hesap açıkken **Ayarlar → Sistem → Uzaktan Oynatma → Cihazı Bağla** (Link Device) ekranında çıkan 8 haneli kodu uygulamaya yaz. Bu adım bir kez yapılır.
4. **TV uygulaması:** TV'nin markasını seç; adımlar uygulamada markaya göre gösterilir.
   - **Android TV / Google TV:**
     1. **Ayarlar → Sistem → Hakkında**'da **Android TV OS derlemesi**'ne 7 kez bas.
     2. **Geliştirici seçenekleri**'nde **USB hata ayıklama**'yı aç.
     3. Uygulamada **TV'de aç**'a bas. TV'de "USB hata ayıklamaya izin verilsin mi?" sorusunda "Her zaman izin ver"i işaretleyip **İzin ver**'e bas. Uygulama TV'ye kendisi kurulur; sonraki güncellemeleri de kendisi yapar.
   - **Samsung:**
     1. TV'de **Uygulamalar**'ı aç, kumandada **1 2 3 4 5**'e bas.
     2. **Developer mode**'u **On** yap. **Host PC IP** olarak uygulamada yazan bilgisayar adresini gir.
     3. Güç tuşuna 3 saniye basılı tutarak TV'yi yeniden başlat.
     4. Uygulamada **Kur ve aç**'a bas. Samsung giriş sayfası açılırsa ücretsiz Samsung hesabınla giriş yap.
     5. Yeni sürüm çıkınca TV uygulamasını bu sayfadan yeniden kur.
   - **LG:**
     1. [webostv.developer.lge.com](https://webostv.developer.lge.com) adresinde ücretsiz LG geliştirici hesabı aç.
     2. TV'de LG Content Store'dan **Developer Mode** uygulamasını kur ve bu hesapla giriş yap.
     3. **Dev Mode Status**'u aç; TV yeniden başlar.
     4. **Key Server**'ı aç. Ekrandaki **Passphrase**'i uygulamaya yazıp **Kur ve aç**'a bas.
5. **Altyazı alanı:** Oyunda bir konuşma altyazısı ekrandayken **Altyazı alanını seç**'e bas. Görüntünün üstünde altyazının çıktığı yeri fareyle çerçeve içine al; iki satırlık altyazıya yer bırak. Sonra **Okumayı ayarla** bölümünde **Otomatik ayarla**'ya bas.
6. **Kol:** Uygulama PS5'e bağlanınca kolun bağlantısı bir anlık düşebilir. Koldaki **PS tuşuna** bas ve **kendi hesabını** seç.

### Her oyunda

1. PS5'te oyunu aç.
2. Uygulamada oynadığın oyunu seç. Emin değilsen "Otomatik algıla"da bırak; paketi olan oyunlarda replikler hazır Türkçesiyle çıkar.
3. Sağ üstteki **Başlat**'a bas. TV uygulaması kendiliğinden açılır ve TV PS5'in ekranına geçer.

İsteğe bağlı:
- **Çeviri** sayfasında DeepL ya da Gemini anahtarı girersen paketi olmayan satırlar daha iyi çevrilir.
- Yazı boyutu, renk ve konum **TV Görünümü** sayfasında.

### Sorun olursa

1. **Genel → Sorun bildir → Kayıtları paketle**'ye bas. Masaüstüne bir kayıt dosyası koyar; API anahtarların ve PS5 / PSN bilgilerin bu dosyaya girmez.
2. Konuşmacı adları ya da renkleriyle ilgili bir sorunsa, önce aynı bölümde **Diyalog görüntülerini topla**'yı açıp birkaç dakika oyna.
3. Kayıt dosyasını, bu depoda açacağın bir *issue*'ya ekle.

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

Her sürüm sayfasının metni de bu komutla yazılır: önce yeni bilgisayara kurulum, sonra "Zaten kuruluysa", en sonda `--notes`. Kurulum dosyalarının bulunduğu en yeni sürüm GitHub'dan bulunur; `--setup` ile yeni bir kurulum yüklenince bütün sayfalar ona yönlenir. O zaman bu README'deki Kurulum bölümündeki bağlantıyı da güncelle. Yalnızca sayfaları yeniden yazmak için `packaging\publish.py --fix-notes` kullanılır.

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
