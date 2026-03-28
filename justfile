venv_path := justfile_directory() / ".venv"
set dotenv-load := true
os := os()
devcontainer := if env_var_or_default("USER", "nobody") == "vscode" {"true"} else {"false"}
serve_host := if env_var_or_default("CODESPACES", "false") == "true" { "0.0.0.0" } else { "localhost" }

@default:
    just --list

# Completely bootstrap a development environment
bootstrap:
    #!/usr/bin/env bash
    set -eu -o pipefail

    # if our .env isn't there, this is probably a checkout;
    # we want to generate it instead.
    scripts/ensure_env.sh

    docker compose up --wait

    scripts/get_local_docker_ports.sh
    scripts/get_web_port.sh

    # we run this again to get the new environment locked in
    docker compose up --wait

    # initialize our DB; this has to be in a separate task to reload the environment
    unset NOM_DB_PORT
    just migrate
    just seed

# Serve locally
serve:
    uv run manage.py runserver {{ serve_host }}:$DEV_SERVER_PORT

# Run the background task worker
worker:
    uv run celery -A nomnom worker -l INFO

# Format code with ruff
format:
    uv run ruff format .

# Lint code with ruff
lint:
    uv run ruff check .

# Fix linting issues automatically
lint-fix:
    uv run ruff check --fix .

# Run tests
test:
    uv run pytest -v

# Run tests every time a file changes
guard:
    uv run pytest -v --looponfail

# Run all quality checks
check: lint test

build-stack:
    docker compose -f docker-compose.yml -f docker-compose.dev.yml build

stack:
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# Run a shell in the full docker stack
stack-shell:
    docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm web python manage.py shell

# Open the mailcatcher web interface
stack-mailcatcher:
    open http://$(docker compose port mailcatcher 1080)

# Flush the development database
resetdb:
    docker compose down -v

startdb:
    docker compose up -d db redis

# Re-run all DB migrations against the database
migrate:
    uv run manage.py migrate

collectstatic:
    uv run manage.py collectstatic --noinput

initdb: startdb migrate

# initialize the database with production and development seed data
seed:
    #!/usr/bin/env bash
    set -eu -o pipefail
    shopt -s nullglob
    for seed_file in {{ justfile_directory() }}/seed/all/*.json; do
        uv run manage.py loaddata $seed_file
    done
    for seed_file in {{ justfile_directory() }}/seed/dev/*.json; do
        uv run manage.py loaddata $seed_file
    done

    uv run manage.py seed_all --full yugo-awards "The Yugo Awards"

# update dependencies
update: update-precommit update-gha update-uv


# refresh nomnom, only
refresh-nomnom:
    # This is useful when you're working on nomnom itself,
    # when we might have a source dependency on nomnom, but we want to bump the shipped
    # version, possibly to a beta.
    uv sync --no-sources --dev --prerelease=if-necessary-or-explicit --refresh -P nomnom-hugoawards

@update-uv:
    uv sync --upgrade

@update-precommit:
    uvx --with pre-commit-uv pre-commit autoupdate -j3

@update-gha:
    uvx gha-update

@db_data:
    mkdir -p "{{ justfile_directory() }}/data/"

# dump database to file
@pg_dump file='db.dump': db_data
    docker compose run \
        --no-deps \
        --rm \
        --volume "{{ justfile_directory() }}/data/:/_data/" \
        db pg_dump \
            --dbname "${DATABASE_URL:=postgres://postgres@db/nominate}" \
            --file /_data/{{ file }} \
            --format=c \
            --verbose

export file='export.json': db_data
    docker compose run \
        --no-deps \
        --rm \
        --entrypoint "bash" \
        --volume "{{ justfile_directory() }}/data/:/_data/" \
        web -c \
        'python manage.py dumpdata \
            --indent 4 \
            --natural-foreign \
            --natural-primary \
            -o /_data/{{ file }} \
            base nominate canonicalize advise hugopacket convention_admin lacon_v_app'

# restore database dump from file
@pg_restore file='db.dump': db_data
    docker compose run \
        --no-deps \
        --rm \
        --volume "{{ justfile_directory() }}/data/:/_data/" \
        db pg_restore \
            --clean \
            --dbname "${DATABASE_URL:=postgres://postgres@db/nominate}" \
            --if-exists \
            --no-owner \
            --verbose \
            /_data/{{ file }}
