# Scrapper — Proje Durum Belgesi

> Son güncelleme: 2026-03-02  
> Bu belge projeye yeni bir Antigravity oturumundan devam edebilmek için yazılmıştır.

---

## Amaç

LLM destekli genel amaçlı web scraper. Herhangi bir siteye verilen URL'den başlayarak BFS ile geziyor, her farklı sayfa tipi (URL prefix'i) için OpenAI API kullanarak CSS selector spec'i otomatik üretiyor ve içerikleri JSONL formatında çıktılıyor.

**Hedef:** Her sitede, her sayfa tipinde maksimum doğrulukla veri çıkarmak.

---

## Proje Yapısı

```
scrapper/
├── crawler/
│   ├── spider.py       # Ana Scrapy spider — BFS, spec yönetimi, validation
│   ├── extract.py      # HTML → veri (title, date, metin, tablolar, linkler)
│   ├── llm.py          # OpenAI API — spec üretme ve onarma
│   ├── spec_store.py   # Spec'leri disk'te saklama/yükleme
│   └── utils.py        # URL yardımcıları, link örnekleme
├── spec_cache/         # Domain+prefix bazlı spec JSON dosyaları (git-ignored)
├── docs/               # Belgeler
├── report.py           # JSONL → HTML rapor
├── inspect_output.py   # Terminal özet analiz
├── .env                # OPENAI_API_KEY (git-ignored)
├── .env.example        # Şablon
├── .gitignore
└── requirements.txt    # scrapy, openai, python-dotenv
```

---

## Temel Veri Akışı

```
scrapy runspider crawler/spider.py -a site=URL [-a max_pages=N] -O out.jsonl

URL
 └─ BFS (spider.py)
      ├─ path_prefix(url) → "ekonomi" / "" / "eskiler" / ...
      ├─ spec_store.load_spec(domain, prefix)
      │    └─ MISS → llm.generate_spec() → spec_store.save_spec()
      ├─ extract.extract_page(html, spec)
      │    ├─ drop_selectors → gürültüyü sil
      │    ├─ content_selectors → TÜM eşleşen blokları topla (liste sayfaları dahil)
      │    ├─ title_selector, date_selector, table_selector
      │    └─ auto_detect_block() fallback (selector eşleşmezse)
      ├─ _validate() → kalite kontrolü, bozuksa _maybe_repair()
      └─ yield {"type":"html", "title":..., "date":..., "extracted_text":..., ...}
```

### JSONL Kayıt Tipleri

| type | Ne zaman |
|---|---|
| `html` | Normal sayfa — title, date, extracted_text, tables, links |
| `asset` | PDF/resim/video linki — HTTP isteği yapılmadan emit |
| `external_redirect` | Farklı domain'e yönlendirme |

---

## Spec Sistemi

### Disk Formatı (`spec_cache/<domain>.json`)

```json
{
  "domain": "www.ntv.com.tr",
  "specs": {
    "":         { "content_selectors": [...], "fields": {...} },
    "ekonomi":  { "content_selectors": [...], "fields": {...} },
    "teknoloji":{ "content_selectors": [...], "fields": {...} }
  }
}
```

- Anahtar: URL'nin ilk path segment'ı (`path_prefix(url)`)
- Eski tek-spec formatı backward-compat ile `""` prefix'ine migrate ediliyor

### Spec Üretim Akışı

1. Yeni prefix görüldüğünde `llm.generate_spec(domain, prefix, url, html_snippet, hrefs)` çağrılır
2. OpenAI API HTML snippet (~40KB) + 300 href görerek spec JSON üretir
3. Spec disk'e kaydedilir, sonraki run'larda cache'den yüklenir

### Validation & Repair

- Her prefix için bağımsız rolling window (son 10 sayfa title var mı?)
- 2+ kalite flag'i → `_maybe_repair()` tetiklenir (cooldown: 20 sayfa)
- Repair olan URL `_retry_urls`'e eklenir, spider kapanırken loglanır

---

## Bu Oturumda Yapılan Değişiklikler

### 1. Per-Page Spec Mimarisi (Ana Özellik)
- **`spec_store.py`** — `{domain: single_spec}` → `{domain: {prefix: spec}}` formatına geçildi
- **`spider.py`** — `self.spec` kaldırıldı, `_get_spec(url)` / `_set_spec(url, spec)` / `_ensure_spec()` eklendi
- **`llm.py`** — `generate_spec` ve `repair_spec` fonksiyonlarına `prefix` parametresi eklendi
- **`utils.py`** — `_path_prefix` → `path_prefix` (public)

### 2. max_pages Opsiyonel
- Parametre verilmezse sonsuz crawl (önceden default 200'dü)
- `_over_limit()` artık `None` kontrolü yapıyor

### 3. .env Desteği
- `crawler/llm.py`'de `load_dotenv()` eklendi
- `.env` ve `spec_cache/` `.gitignore`'a eklendi
- `.env.example` şablon olarak GitHub'a gidiyor

### 4. Liste Sayfaları için Multi-Block Extraction
- **`extract.py`** — `_best_content_block()` → `_collect_content_blocks()` değiştirildi
- Eski davranış: content_selectors ile eşleşen en yüksek skorlu **tek blok** alınıyordu
- Yeni davranış: **tüm eşleşen bloklar** toplandı, metinleri `\n\n` ile birleştirildi
- Makale sitelerinde fark yok (zaten tek blok), liste sitelerinde (quotes, ürünler) tüm itemlar geliyor

### 5. _flush_retries → closed() Hook'a Taşındı
- Eski: `parse()` her çağrıldığında `_flush_retries()` çalışıyordu → concurrent sorun
- Yeni: Spider kapanırken `closed()` hook'u retry URL'leri logluyor

---

## Bilinen Sorunlar / Eksikler

### 🔴 Kritik

| Sorun | Etki | Açıklama |
|---|---|---|
| Tarih-bazlı prefix patlaması | LLM maliyet | `resmigazete.gov.tr/28.02.2026/` → her tarih ayrı prefix, ayrı LLM çağrısı |
| Spec tek sayfadan üretiliyor | Kalite | Atipik bir sayfa gösterilirse tüm prefix yanlış spec alır |

### 🟡 Orta

| Sorun | Etki | Açıklama |
|---|---|---|
| Tables/links sadece `blocks[0]`'dan | Eksik veri | Multi-block fix sonrası tables ve content_links ilk bloktan geliyor |
| LLM HTML snippet 40KB ile kısıtlı | Kalite | Büyük sayfalarda sayfa sonu yapısı LLM'e görünmüyor |
| TEXT_LIMIT = 50.000 karakter | Eksik veri | Büyük listelerde metin kesilebilir |
| Validation window 10 sayfa | Geç tespit | Az sayfalı prefixlerde hiç dolmuyor |

### 🟢 Minor

| Sorun | Etki | Açıklama |
|---|---|---|
| `visited` seti her run'da sıfırlanıyor | Tekrar crawl | Dünkü URL'ler bugün tekrar taranır |
| Concurrent spec üretimi | Race condition | Aynı prefix için 8 paralel request varsa 8 LLM çağrısı gidebilir |

---

## Kullanım

```bash
# .env dosyasını doldur
echo 'OPENAI_API_KEY=sk-...' > .env

# Limitli crawl
scrapy runspider crawler/spider.py \
  -a site=https://www.ntv.com.tr \
  -a max_pages=50 \
  -O out.jsonl

# Limitsiz crawl
scrapy runspider crawler/spider.py \
  -a site=https://www.resmigazete.gov.tr \
  -O out_resmi.jsonl

# HTML rapor
python report.py out.jsonl

# Terminal özet
python inspect_output.py out.jsonl
```

---

## Test Edilen Siteler

| Site | Durum | Notlar |
|---|---|---|
| `quotes.toscrape.com` | ✅ İyi | 5 prefix, author sayfaları mükemmel (doğum tarihi dahil) |
| `www.ntv.com.tr` | ✅ İyi | 30 prefix, title %100, metin %99 |
| `www.resmigazete.gov.tr` | ⚠️ Kısmi | eskiler title boş, ilanlar bazı sayfalar görsel-tablo |
| `www.transfermarkt.com.tr` | ❌ Bot koruması | Cloudflare 403, bu scraper ile erişilemiyor |

---

## Sonraki Adımlar (Öncelik Sırası)

1. **Tables/links tüm bloklar** — `extract_tables` ve `extract_links` tüm `blocks`'ı kapsasın
2. **Tarih prefix'i çözümü** — tarih-formatı segment'larını normalize et ya da maliyet cap'i dön
3. **Concurrent spec race condition** — prefix bazlı lock mekanizması
4. **Spec birden fazla sayfa ile üretim** — ilk 3 sayfayı göster, daha robust spec
