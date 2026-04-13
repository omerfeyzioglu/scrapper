# Scrapper

Lightweight domain crawler built with Scrapy.

It crawls same-domain pages, extracts structured content, and writes JSONL output.  
The extractor uses a cached per-domain spec and can generate/repair specs with OpenAI.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` from `.env.example` and set your key:

```bash
cp .env.example .env
```

## Run

```bash
scrapy runspider crawler/spider.py -a site=https://example.com -a max_pages=200 -O out.jsonl
```

## View Output

```bash
python inspect_output.py out.jsonl
python report.py out.jsonl
```

## Project Layout

- `crawler/spider.py` — crawling and emit logic
- `crawler/extract.py` — HTML extraction
- `crawler/llm.py` — spec generation/repair
- `crawler/spec_store.py` — spec cache persistence
- `spec_cache/` — cached domain specs
- `report.py` — JSONL to HTML report
- `inspect_output.py` — terminal summary
