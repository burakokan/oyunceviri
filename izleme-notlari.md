# GTA 6 canlı izleme notları (19 Kasım gecesi) — durum

Oyun sırasında bulunanlar ve ne yapıldığı. ✅ düzeltildi · ⏳ sonra · 💬 konuşalım

## 19 Kasım öğlen yapılanlar (sürüm 0.9, TV uygulaması 1.2)

- ✅ Ekranda takılı kalan yazı: altyazı alanında 6 sn'den uzun duran satır (görev, bildirim), altında yeni
  konuşma başlayınca yok sayılır (Filtreler → "Ekranda takılı kalan yazıyı atla").
- ✅ Tekrar eden tabela / reklam: konuşmacısız, noktalamasız aynı yazı 5 dk'da 3 kez çıkarsa 10 dk gösterilmez.
- ✅ Görev / ipucu kutusu: "Altyazı Alanı" sayfasında "Görev / ipucu kutusu" seçilip alanı çizilir. Kutudaki
  bütün satırlar tek cümle gibi çevrilir (DeepL), TV'de tek kutuda gösterilir. Tuş simgeleri (L3, L2…) resim
  olarak kesilip Türkçe cümlede doğru yere konur ("⟦L3⟧ tuşuna basın"). Yazı kaybolunca kutu da kalkar.
- ✅ Telefon mesajları: aynı sayfada "Telefon mesajları" alanı; her mesaj ayrı çevrilir, tek kutuda alt alta.
- ⏳ İkisi de yalnızca sahte görüntüyle denendi; GTA 6'da gerçek kutuda / telefonda bakmak gerek (tuş simgesi
  harflerden en az ~1,2 kat büyük olmalı; değilse simge yazı olarak "L3" diye okunur).

## 19 Kasım sabahı yapılanlar (sürüm 0.8, TV uygulaması 1.1)

- ✅ Bölünen cümle bekletilmiyor: ilk parça hemen gösterilir, devamı gelince TV'de aynı satır tam cümleyle değişir.
  Parçaların ikisi de paketteyse birleşik çeviri paketten anında gelir. "-" ve "…" ile bitenler bekletilmez.
- ✅ Yarım/eksik okunan satır, tamamı ya da daha iyi okuması gelince aynı satırın üstüne yazılır (tekrar yok).
- ✅ Adsız iki satır birleşince önceden gösterilen kısım atılır, yalnızca yeni kısım gösterilir.
- ✅ Yalnızca isimden oluşan satır gösterilir; konuşmacısız, çevrilmeyen tek kelime (araba logosu) gösterilmez.
- ✅ "Chuck's Gun Shop" gibi dükkân adları başlık sayılır; telefon bildirimi diyalog satırına yapışmaz.
- ✅ OCR harf kaçırma: satır harf yüksekliğine göre kırpılıyor ("I el" → "I tell", "realy tepped" → "really
  stepped"). Gece oturumunda pakette birebir bulunan satır 261 → 265.
- ✅ OCR yükü: değişmeyen satırlar yeniden okunmuyor.
- ✅ Hakaret kuralı: "asshole" → "siktir" seçilmiyor. GTA 6 paketindeki 5 yanlış satır düzeltildi (packs/fixes).
- ✅ Remote Play: kendiliğinden yeniden bağlanırken PS5 uyandırılmaz; kopunca 1–5 sn arayla yeniden dener;
  kopma sebebi logs/remoteplay.log'a yazılır.
- ✅ Her konuşmacı kendi renginde, aynı isim hep aynı renk (speakers.json). TV Görünümü'nden kapatılabilir.
- ✅ Samsung/LG uygulamasında da satır yığma + aynı satıra yazma + renkler.

## Düzeltilenler (03:30 sürümü — program yeniden başlatıldı, TV uygulaması 1.0 kuruldu)

- ✅ **Medium altyazıda satırlar okunmuyordu.** Asıl sebep: program, ekranda "yeterince değişiklik" olmadan
  OCR çalıştırmıyordu ve küçük/ince harfler bu ölçüye takılmıyordu. Kısa satırlar ("Yeah.", "What?",
  "Got it.") birbirinin yerine geçince hiç fark edilmiyordu. Medium testinde eskisi 12 satırın 7'sini,
  yenisi 12'sini okudu. Ayrıca yazı varken en geç saniyede bir yeniden okunuyor.
- ✅ **Kalabalık sahnede herkes tek uzun satırdı** ("Lucia: … CO Wilson: … Prisoner: …"). Artık her konuşan
  ayrı satır, ayrı çeviri.
- ✅ **TV'de en fazla 2 satır, üstteki okunmadan kayboluyordu.** TV uygulaması 1.0: en fazla 4 satır üst üste
  durur, her satır kendi okuma süresi dolmadan silinmez; yukarı kayanlar da renkli konuşan adıyla.
  ("TV Görünümü → Zamanlama → Kalabalık sahnede en fazla satır" ile 1–6 arası ayarlanır.)
- ✅ **Çeviri yapılırken ekran okunmuyordu** (her satırda 0,3–0,9 sn kör kalıyordu). Çeviri artık ayrı iş
  parçacığında; okuma hiç durmuyor.
- ✅ **Aynı satır tekrar tekrar gösteriliyordu** ("Wait for the guard" ~10 kez). Program yalnızca son 6 satırı
  hatırlıyordu; artık 60 satır + okuma farklarına dayanıklı karşılaştırma.
- ✅ **Görev yazıları ve tuş ipuçları** ("Go with the prison guard", "Press … to threaten the teller"):
  bekletilmeden bir kez gösteriliyor, diyalogla birleşmiyor, 2 dk içinde tekrar edilmiyor.
- ✅ **Başka oyunların paketleri kullanılıyordu** ("Figures." → "Rakamlar.", "Oh, yeah?" → "Aynen öyle.").
  Artık yalnızca oynanan (seçilen ya da algılanan) oyunun paketi; oyun adı elle yazıldıysa hiç paket yok.
- ✅ **Cümle başına "Siktir," yapıştırılıyordu** ve "küfür yumuşatılmış" kuralı yanlış çeviriyi seçtiriyordu
  ("don't fuck around" → "siktir etme"). "Siktir," ekleme kaldırıldı; ceza artık yalnızca gerçek
  küfür/hakarette (Fuck!, fuck you, bitch, asshole…), vurgu sözcüklerinde ("fuckin' stupid") değil.
- ✅ **Altyazı alanı dar → baş harf ve son nokta kesiliyordu** (nokta görünmeyince 2,6 sn bekleme). Alan artık
  iki yandan otomatik %6 geniş okunuyor.
- ✅ **Aynı kısa replik 20 sn içinde yeniden söylenince gösterilmiyordu** ("Got it."). Ekran boşaldıktan sonra
  tekrar söylenirse gösteriliyor.
- ✅ **Sessiz kalan anlar artık incelenebilir:** oturum loguna 15 sn'de bir durum kaydı (kare hızı, bulunan
  satır, okunan metin) ve hata ayıklama açıkken altyazı alanının saniyede bir resmi (logs/frames/).

## Hazır, bir sonraki açılışta devreye girecek (oyun bölünmesin diye program yeniden başlatılmadı)

- ✅ **Aynı konuşmacının kısa repliği yeni satır açmıyor:** aynı kişi 3 sn içinde yine konuşursa ve önceki
  repliği kısaysa (en fazla 3 kelime: "Hey!", "Big man!"), yeni replik onun yerine yazılır (oyunun yaptığı
  gibi). Uzun repliklerden sonra ya da konuşmacı değişince yine yeni satır.
- ✅ **Fare tekerleği ayarları hiç değiştirmiyor** (tıklanmış olsa bile); yalnızca sayfayı kaydırıyor.
- ✅ **Kaydet / Vazgeç:** ayar değişince üstte çubuk çıkar; değişiklik denenir ama Kaydet (Ctrl+S) olmadan diske
  yazılmaz, Vazgeç son kaydedilene döner (TV görünümü dahil). Çıkarken kaydedilmemiş değişiklik varsa sorar.
  Oyun adı kutusunun kendi Kaydet düğmesi var (Enter da olur).
- ⏳ TV uygulamasında küçük ayar: üstüne yazılan satırın okuma süresi yeniden başlasın (TV uygulamasını
  yeniden kurmak gerekiyor, oyun bitince).

## 2. izleme (04:12–, program 04:09 sürümü: GTA 6 paketi var, Kaydet / kısa replik henüz yok)

- 👍 GTA 6 paketi otomatik algılandı; satırların çoğu paketten 0,1 sn'de. Görüntü 19–20 kare/sn, donma yok.
- 🔧 **OCR çok sık çalışıyor:** yeni değişiklik algılama + kalabalık sahnede 7–9 satır adayı → 15 sn'de 222 OCR
  (neredeyse her kare). Şimdilik yetişiyor ama işlemciyi yoruyor; yalnızca altyazı satırlarına bakacak şekilde
  inceltilecek.
- 🔧 **Paket çevirisi tuhaf:** "Lock this shit down!" → paket: "Burayı siktir gibi kilitleyin." (paketteki yapay
  zekâ çevirisi; doğrusu "Burayı sıkı tutun lan!" gibi).
  "Yeah, of course. Pay the man." → paket: "Evet, tabii ki. Evet?" (YANLIŞ, "Adama parasını ver" eksik).
  Fikir: paket çevirisi İngilizceye göre çok kısaysa (cümle eksikse) DeepL'e sormak.
  Diğer paket kusurları: "Maybe even some chicks, y'know?" → "Belil belki…" (yazım hatası), "thank fuck you
  radioed" → "telsize geçtiğin için siktir iyi ki" (bozuk). Paketteki yanlış satırlar için bir "düzeltmeler"
  listesi tutulabilir (Çeviri → Düzeltmeler zaten var).

- 🔧 **Tire ile kesilen cümle 3 sn bekletiliyor:** "I promise I got-" (araya "Donnie, shut the fuck up!" girdi)
  devamı gelecek sanılıp 3 sn tutuldu, sonra yarım gösterildi. GTA'da sondaki "-" sözün kesildiği anlamına
  geliyor (devamı yok) → "-" ile bitenler bekletilmemeli. Aynısı "…" için: "Ugh, jackass..." (04:42:48) 2 sn
  bekletildi, devamı yoktu (söz yarıda bırakılmış).
- 💬 **Virgülle bölünen uzun cümleler 3–3,5 sn geç** (04:20:03, 04:20:13): "That's what I brought him in here,
  you know," + "for situations just like this, Brian." birleşip gösterildi. Bu bizim "cümle tam ve bir kez"
  kuralımız; gecikme hissinin en büyük kaynağı bu artık. Seçenek: ilk parçayı hemen göster, devamı gelince
  aynı satırı tam cümleyle değiştir.
  **Ek bulgu (04:26):** birleştirme paketi de devre dışı bırakıyor. Paket her ekran parçasını ayrı ayrı
  biliyor, ama birleşik cümle ("Going to the gunshop tomorrow, I'll make sure I can handle either way.")
  pakette yok → DeepL'e gidiyor ve 2,1–2,3 sn geç geliyor. Öneri: bir parça paketteyse hiç bekletme, parçayı
  paketten anında göster (devamı da paketten anında gelir).
  **Ek bulgu (04:28):** "Y'know, of all the guys I've met around here, you're-" 2,3 sn bekletilip yarım
  gösterildi, 0,8 sn sonra birleşik tam hali ("…you're- you're the only one that's not a…") ayrı satır olarak
  yine geldi → TV'de aynı başlangıç iki kez. Yarım gösterilen satırın tamamı gelince TV'de o satırın üstüne
  yazılmalı (yeni "yerine yaz" mantığıyla).

- 🔧 **Yalnızca isimden oluşan satır atlanıyor** (04:32:28 "Lucia: Lucia Caminos."): çevirisi İngilizcesiyle
  aynı çıktığı için program "bu İngilizce değil" sanıp göstermedi (Türkçe menü yazılarını elemek için konmuş
  kural). Yalnızca büyük harfle başlayan kelimelerden oluşan (isim) satırlar yine gösterilmeli.

- 🔧 **Kesme işaretli yer/başlık yazısı filtreden kaçıyor:** "Chuck's Gun Shop" (dükkân adı) başlık filtresine
  takılmadı, çünkü filtre içinde ' olan her şeyi diyalog sayıyor; noktasız olduğu için de 3,2 sn bekletilip
  "yarım" gösterildi. Başlık kuralı kesme işaretine izin vermeli ("Chuck's", "Joey's").
- 🔧 **OCR harf kaçırıyor → yanlış çeviri:** "Did I tell you I went through Marauder trainin'?" → "I el you…"
  okundu, Gemma "Sen Marauder eğitiminden geçtin mi?" diye ters çevirdi. Ayrıca "Oh, well yeah. … I'll" →
  "well eah", "I'l"; "You really stepped in it!" → "realy tepped" (DeepL yine de doğru çevirdi).
  Desen: çift harfler (ll → l) ve kelime başı harfler düşüyor. Ayrıca "!" bazen "l" okunuyor: "Tourist: You're a
  joke!" → "Tourist You're a jokel" → cümle bitmemiş sanıldı, yarım gösterildi, doğru okuması gelince aynı satır
  bir daha gösterildi (04:43:17). İkinci (doğru) okuma modelinin hangi
  durumlarda harf düşürdüğüne kare kayıtlarından bakılacak (logs/frames).

- 🔧 **Arabanın arka logosu altyazı sanıldı** (04:48, sürüş): önündeki arabanın arkasındaki "Carbonizzare" yazısı
  (krom el yazısı) ve plaka ("AL5553K") okuma alanının ortasında. Okumaların çoğu filtrede elendi ama bir kez
  "Canboniare!" diye geçip TV'ye gitti. Kare: logs/frames/20261119-041230/044819-515.jpg. Öneri: konuşmacısız,
  tek kelimelik satır ancak bilinen bir İngilizce kelimeyse ("Stop!", "What?") ya da birkaç kez aynı okunduysa
  gösterilsin (logo/plaka okuması her karede farklı çıkıyor: Carboniarare, Cantomiaaare, Canbonianare…).

- 🔧 **Konuşmacı adı olmayan iki satır birleşip tekrar gösteriliyor** (04:49:09, kavga): "Do you know how bad this
  will look?" gösterildi → sonra "You can still walk away Do you know how bad this will look?" (iki ayrı kişinin
  adsız satırı birleşti) → sonra "You can still walk away..." bir daha. Öneri: okunan satırın içinde son
  saniyelerde gösterilmiş bir cümle varsa onu çıkarıp yalnızca yeni kalan kısmı göstermek.

## Bekleyenler

- ⏳ **[KRİTİK, tekrarlıyor] Remote Play kopuyor, geri gelmesi ~30 sn** — 02:55 (38 sn) ve 04:25:29 → 04:26:01
  (32 sn). İkincisinde Remote Play süreci kapanıp yeniden açıldı (bağlantı 04:12:38'de kurulmuştu, ~13 dk
  sürdü). Bu sürede hiç altyazı okunamaz. Yapılacak: (1) Remote Play'in kendi mesajlarını (neden kapandı:
  PS5 mi kapattı, ağ mı, görüntü mü dondu) oturum loguna yazmak — şu an hiç kaydedilmiyor; (2) yeniden
  bağlanmayı hızlandırmak (8 sn donma bekleme + artan bekleme süresi + bağlantı kurulumu).
  3. kopma: 04:53:50 (bir önceki bağlantı ~28 dk sürdü); 04:55'te hâlâ bağlanmaya çalışıyordu.
  ⚠ Dikkat: yeniden bağlanırken PS5 bekleme modundaysa program onu UYANDIRIYOR. PS5'i bilerek kapattıysan
  program açıp durabilir. Kural olmalı: kopmadan sonra kendiliğinden yeniden bağlanırken PS5 uyandırılmasın;
  yalnızca Başlat'a basınca uyandırılsın.
- ⏳ **03:05'ten sonra hiçbir şey okunmadı** (Medium'a geçtiğin an). Büyük ihtimalle yukarıdaki "değişiklik
  ölçüsü" hatası; yeni sürümde tekrar bak.
- ⏳ Samsung/LG web uygulamasında da satır yığma (Android TV'de yapıldı).
- 💬 **Virgülle bölünen cümle bekletiliyor** ("Do you mind if I call you Lucia," + "or is there…" 2,5 sn).
  Kuralımız "cümle bir kez, tam gösterilsin". İstersen ilk parçayı hemen gösterip devamını alta ekleriz.
- 💬 **İsimle seslenme / argo:** "Caminos! By the door." → DeepL "Caminos'un yanına git!" (yanlış). Fikir:
  oyunun karakter adlarını çevirmenlere "bunlar isim" diye vermek.
- ⏳ Küçükler: "In Spanish:" konuşan adı sanılıyor; telsiz konuşmalarında OCR hataları ("tiie yard");
  köşeli parantezli ses açıklamaları ("[bell jingles") başında çöp harf varsa çevriliyor.
