# Higher Ed Intelligence Agent (v1 automation)

You asked for: a weekly automated generator that updates `data/latest.json` and keeps an archive.

This repo includes:
- `higher-ed-intel/` (static site)
- `higher-ed-intel/generator/` (Python generator)
- `.github/workflows/weekly.yml` (GitHub Actions scheduler)

## How it works
1) Pulls RSS feeds (open/public sources)
2) Tags/categorizes items via keyword rules
3) Writes:
   - `higher-ed-intel/data/latest.json` (overwritten weekly)
   - `higher-ed-intel/data/archive/YYYY-MM-DD.json` (weekly archive; Monday date)
   - `higher-ed-intel/data/rss.xml` (RSS feed for your own page)

## Quick start locally
From repo root:

    python -m venv .venv
    source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r higher-ed-intel/generator/requirements.txt
    python higher-ed-intel/generator/generate_weekly_brief.py

Then upload `higher-ed-intel/` to your server (merder.org).

## GitHub Actions
If you put this repo on GitHub, Actions will run weekly and commit updated JSON automatically.

## Paywalls
This approach uses RSS metadata (headline + snippet). It does NOT scrape paywalled full text.
That keeps the automation simple and avoids licensing issues.
