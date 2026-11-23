# Lotery — Statistical analysis for the Belgian National Lottery

Modern web app that analyses the **official** results of the Belgian National Lottery
(Lotto and EuroMillions), generates 4 complementary grids, and measures honestly what
each method is (or isn't) worth.

- 📥 **Verifiable data**: the official results API, plus a cross-check against the
  Loterie Nationale's statistics file. Nothing is invented.
- 📊 **Statistics engine**: frequencies (year / 30 / 60 / 90 draws), gaps, moving averages,
  pairs and triplets, distributions. Each one is compared with its theoretical value under chance.
- 🎯 **4 grids**: historical frequencies, recent trends, hybrid, anti-sharing. Each grid has a
  **statistical** score, an **anti-sharing** score and an adjustable overall score.
- 🛡️ **Anti-sharing model** calibrated on the real number of Belgian winners per rank
  (out-of-sample R² of 0.76 for Lotto).
- 🧪 **Walk-forward backtest** with no data leakage, compared against a random strategy.
- ⭐ History of generated grids, favourites, "analyse my grid".

> ⚠️ Every combination has exactly the same probability of being drawn. The tool does not
> increase your chances of winning. At most, it can reduce the risk of *sharing* a prize.
> Play responsibly.

The full scoping document (rules, sources, methods, evaluation, results) is in
[`docs/CADRAGE.md`](docs/CADRAGE.md).

## Deployment on a VPS (Docker)

```bash
git clone https://github.com/sseggio/lotery.git && cd lotery
```

```bash
cp .env.example .env   # set BASIC_AUTH_USER / BASIC_AUTH_PASSWORD
```

```bash
docker compose up -d --build
```

On first start, the app downloads the history from the official source (about 30 s). It then
syncs automatically after each draw.

The port is bound to `127.0.0.1:8000`: put a reverse proxy with HTTPS in front. For example,
with Caddy:

```
lotery.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Data lives in the `lotery-data` volume (a single SQLite file). Backup:

```bash
docker run --rm -v lotery_lotery-data:/data -v "$PWD":/backup alpine cp /data/lotery.db /backup/
```

## Deployment behind an existing Traefik

```bash
cp .env.example .env   # DOMAIN, TRAEFIK_NETWORK, TRAEFIK_SUBNET, BASIC_AUTH_*
```

```bash
docker compose -f docker-compose.traefik.yml up -d --build
```

No port is opened on the host. Traefik handles HTTPS like it does for the other sites.

## GitLab CI/CD

`.gitlab-ci.yml` chains the following jobs:
- **tests** (pytest, frontend build, npm audit);
- **Docker image** pushed to the GitLab registry (tagged with the commit SHA and `latest`);
- **SSH deployment** on the VPS (`docker compose pull && up -d`), followed by a public health check.

Deployment only runs on the default branch. The required CI/CD variables are listed at the top of the file.
The `.env` file (secrets) stays on the server. To roll back, re-run the `deploy:production` job of an earlier pipeline.

## Local development

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
```

```bash
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Vite serves the UI on http://localhost:5173 and proxies `/api` to port 8000.

Tests:

```bash
cd backend && python -m pytest -q
```

## Structure

```
backend/app/
  games.py           official rules (Lotto, EuroMillions), exact probabilities per rank
  ingest/            official API, xlsx cross-check, incremental sync
  db.py              SQLite (draws, ranks, sync log, generations, favourites)
  engine/            statistics, strategies, popularity model, generator, backtest
  services.py        use cases + engine cache
  main.py            FastAPI API, security, scheduler, frontend serving
frontend/src/        React + TypeScript + Tailwind + Recharts
docs/CADRAGE.md      scoping and methodology
.claude/agents/      review agents: security-auditor, ui-challenger
```

## Configuration (`.env`)

| Variable | Default | Role |
|---|---|---|
| `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` | empty | protects the whole site (recommended) |
| `HISTORY_START_YEAR` | 2016 | first year downloaded |
| `SYNC_MIN_INTERVAL_S` | 60 | minimum delay between two manual refreshes |

## Security (VPS)

- Set `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` in `.env`. Without them, the site is open, and a warning is logged at startup.
- Set `ALLOWED_HOSTS=your-domain` to reject any other `Host` header.
- Keep the port bound to `127.0.0.1` and put an HTTPS reverse proxy in front (Caddy does it automatically, with HSTS).
- Set `FORWARDED_ALLOW_IPS` to the reverse proxy's IP so the client IP used for rate limiting is reliable.
- POSTs are limited to 40 per minute per IP. Manual refreshes are limited to one per minute. Backtests only accept a fixed list of parameters.
