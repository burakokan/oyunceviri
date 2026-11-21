# OCR modelini eğitme

Uygulamanın kullandığı `assets/ocr/game_rec_tiny_en.onnx` modeli, RapidOCR içindeki PP-OCRv6 tiny tanıyıcısının oyun altyazılarıyla ince ayar yapılmış hâlidir.

- Ağ aynı kaldığı için hız düşmez.
- Çıkış katmanı 6.906 karakterden (Çince, Japonca dahil) İngilizce karakterlere ve Türkçe harflere, yani 108 sınıfa indirildi. Bu yüzden model biraz daha hızlıdır ve "ó", "〇" gibi yanlış harfler üretemez.
- Bu karakterlerin başlangıç ağırlıkları asıl modelden alınır.

Bu klasördeki betikler modeli yeni kayıtlarla yeniden eğitmek içindir. Oyun kayıtları ve resimler depoya girmez. Veriler `OCR_VERI` klasöründe tutulur; tanımlı değilse proje klasörünün yanındaki `OyunCeviriData` kullanılır.

## Gerekenler

- Kayıtlar: Uygulamada Genel → "Teşhis kaydı" açıkken oynanmış olmalı. Uygulama saniyede bir altyazı alanı resmi kaydeder (`logs/frames`). "Diyalog görüntülerini topla" ile alınan resimler (`logs/snapshots`) ve gösterilen satırların resimleri (`logs/crops`) de kullanılır.
- Eğitim için ayrı bir Python ortamı: PyTorch (CUDA), torchvision (PyTorch ile aynı CUDA sürümünden), onnx, onnx2torch, opencv-python-headless, rapidfuzz, onnxruntime. Uygulamanın kendi ortamına kurulmaz.

## Adımlar

1–4 ve 6 numaralı adımlar uygulamanın ortamıyla (`.venv`), 5 numaralı adım eğitim ortamıyla çalıştırılır.

1. `1_satirlari_cikar.py`: Kayıtlardaki her altyazı satırını, uygulamanın kestiği gibi keser. Her satırı küçük ve büyük modelle okur.
2. `2_etiketle.py`: Aynı satır birkaç karede görünür. Büyük modelin bu karelerdeki okumalarının ortak noktası (medoid) o satırın etiketi olur.
3. `3_yeniden_kes.py`: Satır kesme kuralı değiştiyse satırları yeniden keser. Satır sonundaki "..." noktalarını resimden sayar.
   - `3b_turkce_satir_ciz.py`: Oyun paketlerindeki Türkçe satırları oyundaki gibi çizer: beyaz yazı, koyu çerçeve, renkli ad. Arka plan olarak altyazısız oyun sahneleri kullanılır. Kayıtlarda Türkçe yazı çok az olduğundan bu satırlar eğitime eklenir. Model böylece Türkçe harfleri tanır. PS5'in Türkçe menüleri de Türkçe yazı olarak tanınıp çevrilmez.
4. `4_olcum_seti.py`: Eğitime hiç girmeyecek gruplardan 150 satır seçer ve montaj resimlerini çıkarır. Bu satırların metni gözle kontrol edilip `gold.json` olarak kaydedilir.
5. `5_egit.py --rows rows2 --labels labels3.jsonl`: İnce ayarı yapar ve `models/` altına ONNX olarak kaydeder.
   - Toplu normalizasyon katmanları dondurulur.
   - CTC kaybı kullanılır.
   - Veri artırma: parlaklık, renk tonu, düşük çözünürlük, JPEG bozulması.
   - En iyi tur doğrulama satırlarına göre seçilir.
6. `6_karsilastir.py <model.onnx>`: Modelleri ölçüm setinde uygulamadaki gibi karşılaştırır: tek satır, 4 işlemci çekirdeği. Hata oranı, tam doğru satır, ad doğruluğu ve satır başına süre verir.

Lisans: Model, PP-OCRv6 tiny'nin (PaddleOCR, Apache-2.0) değiştirilmiş hâlidir.
