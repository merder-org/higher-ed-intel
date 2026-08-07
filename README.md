# Higher Ed Intelligence Agent (v1 automation)

This repository generates a Monday / Thursday intelligence brief and keeps an archive.

This repo includes:
- `higher-ed-intel/` (static site)
- `higher-ed-intel/generator/` (Python generator)
- `.github/workflows/weekly.yml` (GitHub Actions scheduler)

## How it works
1) Pulls RSS feeds from open/public higher-education sources
2) Tags and scores items, removes roundup/poll noise, clusters overlapping stories, and limits source concentration
3) Produces one strongest LinkedIn opportunity rather than several templated drafts
4) Writes:
   - `higher-ed-intel/data/latest.json` (overwritten weekly)
   - `higher-ed-intel/data/archive/YYYY-MM-DD.json` (dated archive for each cycle)
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
