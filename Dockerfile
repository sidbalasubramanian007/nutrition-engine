# API image for Render (or any container host). Build from the repo root:
#   docker build --platform linux/amd64 -t nutrition-engine-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Runtime dependencies only (requirements-dev.txt adds pytest and isn't installed)
COPY requirements.txt .
RUN pip install -r requirements.txt

# App modules, plus the schema, data and setup script so `python scripts/setup_db.py --with-all`
# can also be run from the container. See .dockerignore for what's left out (.env, venv, web/, tests).
COPY api/ api/
COPY optimizer.py solver.py calculator.py db.py schema.sql food_data.csv trader_joes_macros.json ./
COPY data/ data/
COPY scripts/setup_db.py scripts/

# Fail the build if either MILP solver can't run here: HiGHS (highspy) and PuLP's bundled CBC
RUN python -c "import pulp, highspy; \
p = pulp.LpProblem('check', pulp.LpMinimize); x = p.add_variable('x', 0, 3, cat='Integer'); p += x; p += x >= 1; \
[p.solve(s) for s in (pulp.HiGHS(msg=False), pulp.PULP_CBC_CMD(msg=False))]; \
assert pulp.value(x) == 1, 'solver check failed'; print('HiGHS and CBC OK')"

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# Render sets $PORT; it defaults to 8000 elsewhere
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
