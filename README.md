# Storage (self-hosted)

PostgreSQL 15 + TimescaleDB and Redis 7, persisted to `/data` on the host.

## Start

```bash
docker compose up -d
```

## Verify

```bash
docker compose ps
docker compose exec postgres psql -U trading -d trading -c "\dx"
docker compose exec redis redis-cli ping
```

## Stop

```bash
docker compose down
```

Data lives on the host at `/data/postgres` and `/data/redis` and survives `docker compose down`.
