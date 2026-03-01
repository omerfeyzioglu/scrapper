# Web Scraper — Project Context & Session Summary

> Bu doküman, projenin hedeflerini, yapısını, bu oturumda yapılan değişiklikleri ve güncel takıldığımız konuyu özetler. Başka bir agent veya geliştirici hızlıca bağlamı anlayabilsin diye hazırlanmıştır.

---

## 1. Proje Hedefleri

- **Genel amaçlı, site-bağımsız** bir web crawler/scraper: Tek bir siteye özel hardcode yok; farklı domain'lerde çalışacak şekilde tasarlandı.
- **Çıktı:** JSONL formatında yapılandırılmış veri (URL, title, date, extracted_text, tables, links).
- **Görselleştirme:** `report.py` ile HTML rapor; `inspect_output.py` ile terminal özeti.
- **LLM entegrasyonu:** Yeni domain'lerde extraction spec (CSS selector'lar) otomatik üretilir; başarısızlıkta onarım denenir.

---

## 2. Mimari Özet

```
scrapy runspider crawler/spider.py -a site=https://example.com -a max_pages=200 -O out.jsonl
```

| Modül | Rol |
|-------|-----|
| **spider.py** | Scrapy spider; BFS ile aynı-domain link takibi, PDF/Office skip, spec yükleme/üretim/onarım tetikleme |
| **extract.py** | HTML parsing; spec'teki CSS selector'larla içerik seçimi, metin/tablo/link çıkarma |
| **llm.py** | OpenAI gpt-4o-mini ile spec üretimi (`generate_spec`) ve onarımı (`repair_spec`) |
| **spec_store.py** | Domain bazlı spec cache: `spec_cache/<domain>.json` |
| **utils.py** | Domain helpers, reklam/junk filtreleme, `diverse_link_sample` (path stratification) |
| **report.py** | JSONL → HTML rapor (kartlar, arama, özet) |
| **inspect_output.py** | JSONL → terminal özeti |

### Spec Yapısı

```json
{
  "domain": "www.example.com",
  "content_selectors": [".html-content", "article"],
  "drop_selectors": ["nav", ".ads"],
  "fields": {
    "title_selector": "h1::text",
    "date_selector": "#date",
    "table_selector": "table"
  }
}
```

### LLM Kullanımı

- **Ne zaman:** Spec cache'te yoksa (ilk domain ziyareti) veya validation 2+ flag üretince (repair).
- **Ne veriliyor:** Domain, örnek URL, HTML snippet (~40 KB), aynı-domain link listesi (300'e kadar).
- **Ne isteniyor:** Yukarıdaki şemaya uyan tek bir JSON spec (CSS selector seti).
- **Önemli:** LLM "sayfa yapısını anlama" değil, **bu HTML'e uygun selector seti üretme** için kullanılıyor. Domain başına tek spec; tüm sayfalarda aynı spec kullanılır.

---

## 3. Bu Oturumda Yapılan Değişiklikler

### 3.1. Link Density Düzeltmesi (extract.py)

**Sorun:** Resmi Gazete fihrist sayfası `.html-content` içinde "T.C. Merkez Bankasınca Belirlenen Devlet İç Borçlanma Senetlerinin Günlük Değerleri" linki vardı; fakat `content_selectors` ile eşleşen bloklar `link_density > 0.7` olduğunda atlanıyordu. Fihrist neredeyse tamamen link olduğu için bu blok hiç kullanılmıyordu.

**Çözüm:** Spec'ten gelen `content_selectors` ile eşleşen bloklar için link_density kontrolü kaldırıldı. Artık fihrist gibi link-ağır sayfalar da doğru çıkarılıyor.

**Dosya:** `crawler/extract.py` — `_best_content_block` içindeki `if _link_density(candidate) > 0.7: continue` satırı silindi.

### 3.2. Validation'dan Link Density Kaldırılması (spider.py)

**Sorun:** `_validate()` içinde `link_density > 0.35` flag'i vardı. Fihrist gibi sayfalar yüksek link density ile doğru çıkarılıyordu ama validation bunu "hatalı" sayıp gereksiz spec repair tetikliyordu.

**Çözüm:** `link_density` validation flag'i tamamen kaldırıldı.

**Dosya:** `crawler/spider.py` — `_validate()` fonksiyonundan ilgili blok silindi.

### 3.3. Scraping Limitlerinin Gevşetilmesi

Çıktı kalitesini ve kapsamını artırmak için aşağıdaki değerler güncellendi:

| Limit | Eski | Yeni | Dosya |
|-------|------|------|-------|
| extracted_text max | 15_000 | 50_000 | extract.py |
| LLM HTML snippet | 20 KB | 40 KB | extract.py |
| Sayfa başına tablo | 2 | 10 | extract.py |
| Tablo başına satır | 3 | 50 | extract.py |
| content_links / all_links | 200 | 500 | extract.py |
| Takip edilen link (sayfa başına) | 150 | 300 | utils.py |
| LLM'e verilen link örneği | 150 | 300 | llm.py |

**Dosyalar:** `crawler/extract.py`, `crawler/utils.py`, `crawler/llm.py`

### 3.4. report.py Python Uyumluluğu

**Sorun:** `str | None` sözdizimi Python 3.9 altında çalışmıyordu.

**Çözüm:** `from __future__ import annotations` eklendi; `Optional[str]` kullanıldı.

**Dosya:** `report.py`

### 3.5. PDF/Asset Skip (Önceki Oturumdan)

PDF, Office, arşiv, resim, video vb. uzantılı URL'ler indirilmiyor; sadece asset kaydı emit ediliyor. Bu sayede Resmi Gazete crawl'ı ~22 GB'dan ~955 KB'a düştü.

**Dosya:** `crawler/spider.py` — `NON_HTML_EXTENSIONS`, `_non_html_content_type`, `_enqueue_links` içinde asset emit.

### 3.6. Dokümantasyon

- **docs/MANUAL_LIMITS.md:** Tüm sabit limitler ve eşikler listelendi.
- **docs/PROJECT_CONTEXT.md:** Bu dosya.

---

## 4. Önemli Bulgular

### 4.1. Resmi Gazete Örneği

- **Ana sayfa / fihrist:** `.html-content`, `.html-title`, `#spanGazeteTarih`, `#gunluk-akis` mevcut; spec iyi çalışıyor.
- **Makale sayfaları (eskiler/*.htm):** Word export HTML (`.Section1`, `.MsoNormal`); spec selector'ları yok; title/date boş; `_auto_detect_block` ile içerik yine de çıkarılıyor.
- **İlan sayfaları (ilanlar/*.htm):** Bazılarında `.html-title` var (örn. "MERKEZ BANKASI", "ÇEŞİTLİ İLANLAR"); title geliyor.
- **Merkez Bankası DİBS (ilanlar/.../YYYYMMDD-5.htm):** Tablo verisi HTML metni değil, **19 adet JPG görselinde**. Word'den HTML export edilirken tablolar resme dönüştürülmüş. Scraping ile bu veriye ulaşılamaz; OCR veya alternatif kaynak gerekir.

### 4.2. Merkez Bankası URL Kalıbı

```
https://www.resmigazete.gov.tr/ilanlar/eskiilanlar/YYYY/MM/YYYYMMDD-5.htm
```

Örnek: `.../2026/03/20260301-5.htm` (1 Mart 2026)

### 4.3. Çıktı Yapısı (JSONL)

Her satır bir kayıt:

- **type:** `"html"` | `"asset"` | `"external_redirect"`
- **url, final_url, status**
- **html için:** title, date, extracted_text, tables, content_links_sample, all_links_sample

JSONL'dan veri bulma: `jq -r 'select(.type=="html" and .title=="MERKEZ BANKASI") | .url' out.jsonl`

### 4.4. report.py HTML Raporu

- JSONL → HTML; her kayıt bir kart.
- Search bar ile filtreleme.
- Özet: tip sayıları, ortalama metin uzunluğu, titled/dated sayıları.
- Collapsible: extracted_text, tablolar, link örnekleri.

---

## 5. Mevcut Kısıtlar (Objektif)

| Kısıt | Açıklama |
|-------|----------|
| Tek spec / domain | Farklı sayfa tipleri (index, makale, ilan) aynı spec ile işleniyor; bazı sayfalarda title/date boş kalıyor. |
| Resim tabanlı içerik | Tablo/veri resimde ise (Merkez Bankası DİBS) scraping ile alınamıyor. |
| JS ile yüklenen içerik | Scrapy JS çalıştırmıyor; SPA vb. için içerik gelmez. |
| Spec kaynağı | Spec ilk açılan sayfaya göre üretiliyor; diğer sayfa tipleri LLM'e gösterilmiyor. |

---

## 6. **Güncel Takıldığımız Konu: Çoklu Sayfa Tipi**

### Problem

Bir domain içinde farklı sayfa tipleri var (ör. Resmi Gazete: ana sayfa, fihrist, makale, ilan). **Tek spec** tüm sayfalara uygulanıyor. Spec ilk sayfa tipine (ör. ana sayfa) göre üretildiği için:

- Ana sayfa / fihrist → iyi çalışıyor
- Makale sayfaları → `.html-content` vb. yok; title/date boş; sadece `_auto_detect_block` ile metin geliyor
- İlan sayfaları → kısmen çalışıyor

### Önerilen Best Practice'ler (Tartışıldı, Henüz Uygulanmadı)

1. **Path/URL pattern → spec map:** URL path'ine göre farklı spec seçimi (örn. `/ilanlar/` → ilan spec, `/eskiler/` → makale spec).
2. **Birden fazla temsilci sayfa ile spec:** İlk crawl'da 2–3 farklı sayfa tipi açılıp her biri için ayrı spec üretmek; sonra path'e göre eşleme.
3. **Fallback zinciri:** Önce path'e uygun spec dene; yoksa default spec.
4. **Spec formatı genişletme:** `spec_by_path` gibi bir yapı ile `{ "/ilanlar": {...}, "/eskiler": {...} }` şeklinde birden fazla spec saklamak.

### Beklenen Sonuç

- Her sayfa tipi kendi selector setine kavuşacak.
- Makale sayfalarında title/date dolu gelecek.
- Site-spesifik hardcode yerine, path pattern + LLM ile üretilen çoklu spec kullanılacak.

---

## 7. Dosya Yapısı Özeti

```
scrapper/
├── crawler/
│   ├── spider.py      # Scrapy spider
│   ├── extract.py     # HTML extraction
│   ├── llm.py         # LLM spec gen/repair
│   ├── spec_store.py  # Spec cache
│   └── utils.py       # Helpers
├── spec_cache/        # Domain bazlı spec JSON'ları
├── docs/
│   ├── MANUAL_LIMITS.md   # Limit/sabit listesi
│   └── PROJECT_CONTEXT.md # Bu dosya
├── report.py          # JSONL → HTML rapor
├── inspect_output.py  # JSONL → terminal özet
├── requirements.txt
└── out_*.jsonl        # Crawl çıktıları
```

### Ortam

- **Venv:** `/Users/omer/Desktop/venvs/scrapper/`
- **API:** `OPENAI_API_KEY` LLM için gerekli.

---

## 8. Hızlı Referans Komutları

```bash
# Crawl
scrapy runspider crawler/spider.py -a site=https://www.resmigazete.gov.tr -a max_pages=100 -O out.jsonl

# Rapor
python report.py out.jsonl

# Terminal özet
python inspect_output.py out.jsonl

# URL listesi
jq -r '.url // empty' out.jsonl

# Merkez Bankası sayfaları
jq -r 'select(.type=="html" and (.url | contains("ilanlar") and endswith("-5.htm"))) | .url' out.jsonl
```

---

*Son güncelleme: Bu oturum özeti. Güncel kod ve limitler için `docs/MANUAL_LIMITS.md` ve ilgili kaynak dosyalara bakınız.*
