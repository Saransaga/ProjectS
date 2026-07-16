#!/bin/bash
# Creates a read-only Postgres role for the new FastAPI backend (api/), so
# that service can never write to the trading DB even if a query were
# misused — a real DB-level guarantee, not just an app-level flag (same
# "belt and suspenders" spirit as dashboard.py's conn.set_session(readonly=True),
# but that one still logs in as the privileged POSTGRES_USER underneath).
#
# Mounted into docker-entrypoint-initdb.d/ alongside init.sql — Postgres runs
# every file in that directory in lexical order on first init of a fresh data
# directory ("init.sql" < "readonly_role.sh"), so this only runs automatically
# on a brand-new deployment. On an already-initialized database, apply it
# manually (safe to rerun, see README.md):
#   docker compose exec -T postgres bash -c '/docker-entrypoint-initdb.d/readonly_role.sh'
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${POSTGRES_READONLY_USER}') THEN
          CREATE ROLE ${POSTGRES_READONLY_USER} LOGIN PASSWORD '${POSTGRES_READONLY_PASSWORD}';
       END IF;
    END
    \$\$;
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO ${POSTGRES_READONLY_USER};
    GRANT USAGE ON SCHEMA public TO ${POSTGRES_READONLY_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${POSTGRES_READONLY_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${POSTGRES_READONLY_USER};
EOSQL
