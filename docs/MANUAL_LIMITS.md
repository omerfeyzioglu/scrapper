# Crawler – Manuel kısıtlamalar ve sabitler

Bu dosya, kodda sabitlenmiş sayısal eşikleri ve limitleri listeler. Davranışı değiştirmek için bu değerleri güncelleyebilir veya (ileride) config/CLI ile yapılandırılabilir hale getirebilirsiniz.

---

## extract.py

| Sabit / eşik | Değer | Yer | Açıklama |
|--------------|--------|-----|----------|
| **TEXT_LIMIT** | 50_000 | Satır 20, 214 | `extracted_text` için maksimum karakter; fazlası kesilir. |
| **LLM_HTML_BYTES** | 40_000 | Satır 23, 247 | LLM’e giden HTML parçasının byte üst sınırı. |
| **Min text (auto-detect)** | 100 | Satır 93 | `_auto_detect_block`: Bu uzunluktan kısa bloklar aday sayılmaz. |
| **max_tables** | 10 | Satır 120, 122 | Sayfa başına en fazla kaç tablo çıkarılır. |
| **max_rows** (tablo) | 50 | Satır 131 | Her tabloda en fazla kaç veri satırı (`tr`) alınır. |
| **max_links** (extract) | 500 | Satır 143, 223, 226 | `content_links_sample` ve `all_links_sample` için sayfa başına link üst sınırı. |
| **Boilerplate oranı** | 0.05 | Satır 243 | `is_boilerplate_heavy`: Kelime başına bu oranın üzerinde “cookie policy” vb. eşleşme varsa boilerplate ağır sayılır. |
| **_score (nav penalty)** | 5_000 | Satır 57 | `_score`: `nav`/`menu`/`sidebar` vb. bloklardan çıkarılan puan cezası. |
| **_score (link)** | `1 - ld * 2` | Satır 58 | Link yoğunluğu (`ld`) arttıkça skor düşer. |

**Not:** Spec’ten gelen `content_selectors` ile eşleşen bloklar artık link yoğunluğu yüzünden atlanmıyor (fihrist gibi link ağırlıklı sayfalar için).

---

## spider.py

| Sabit / eşik | Değer | Yer | Açıklama |
|--------------|--------|-----|----------|
| **max_pages** | 200 (varsayılan) | Satır 90, 94 | Tarama başına en fazla HTML sayfa; `-a max_pages=N` ile değiştirilebilir. |
| **VALIDATION_WINDOW** | 10 | Satır 38, 100, 212–214 | Son N sayfada title yoksa “title missing” sayılır. |
| **REPAIR_COOLDOWN** | 20 | Satır 39, 181 | İki spec repair arasında en az bu kadar sayfa geçmeli. |
| **Title var, text kısa** | 200 karakter | Satır 202 | Title varsa ama `extracted_text` bu uzunluktan kısaysa validation flag. |
| **Repair tetikleme** | 2+ flag | Satır 218 | Bu kadar veya daha fazla validation flag birikince spec repair denenir. |
| **REDIRECT_MAX_TIMES** | 5 | Satır 81 | Scrapy: Maksimum yönlendirme sayısı. |
| **CONCURRENT_REQUESTS** | 8 | Satır 83 | Aynı anda en fazla istek. |
| **DOWNLOAD_DELAY** | 0.25 s | Satır 84 | İstekler arası minimum bekleme. |

**NON_HTML_EXTENSIONS:** PDF, Office, arşiv, resim, video vb. uzantılar; bu URL’ler indirilmeden sadece asset kaydı üretilir.

---

## utils.py

| Sabit / eşik | Değer | Yer | Açıklama |
|--------------|--------|-----|----------|
| **max_links (diverse_link_sample)** | 300 | Satır 104, 144, 148, 153, 156 | Bir sayfadan takip edilecek link sayısı üst sınırı; path’e göre round-robin seçilir. |
| **AD_DOMAINS** | Sabit liste | Satır 11–35 | Bu domain’lere giden linkler takip edilmez / çıkarılmaz. |
| **JUNK_SCHEMES** | mailto, tel, javascript, vb. | Satır 37 | Bu scheme’li href’ler link sayılmaz. |

---

## crawler/llm.py

| Sabit / eşik | Değer | Yer | Açıklama |
|--------------|--------|-----|----------|
| **MODEL** | "gpt-4o-mini" | Satır 15 | Spec üretim/onarım için kullanılan model. |
| **max_tokens** | 800 | Satır 107 | LLM yanıtı için token üst sınırı. |
| **temperature** | 0 | Satır 106 | Deterministik yanıt. |
| **href_sample (LLM)** | 300 | Satır 126, 155 | LLM’e verilen link listesinin uzunluğu. |

---

## report.py / inspect_output.py

| Sabit | Değer | Açıklama |
|-------|--------|----------|
| **“short” text** | 200 karakter | Özette “short (&lt;200)” sayacı. |

---

## Özet tablo (sayısal eşikler)

| Ne | Değer | Dosya |
|----|--------|-------|
| Çıkarılan metin max uzunluk | 50_000 | extract.py |
| LLM’e HTML parçası | 40_000 byte | extract.py |
| Sayfa başına link (çıktı) | 500 | extract.py |
| Sayfa başına takip linki | 300 | utils.py |
| Sayfa başına tablo | 10 | extract.py |
| Tablo başına satır | 50 | extract.py |
| Auto-detect min metin | 100 | extract.py |
| Boilerplate oranı | 0.05 | extract.py |
| Validation: kısa metin | 200 | spider.py |
| Validation penceresi | 10 sayfa | spider.py |
| Repair cooldown | 20 sayfa | spider.py |
| Repair: min flag sayısı | 2 | spider.py |
| Max sayfa (varsayılan) | 200 | spider.py |

İhtiyaca göre bu değerleri sabitlerden config/env/CLI’ye taşıyabilirsiniz.
