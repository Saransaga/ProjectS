FROM python:3.12-slim

WORKDIR /app

# TA-Lib's Python wheel wraps the C library — it isn't on PyPI as a binary
# wheel for most platforms, so build the C lib from source first.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential wget \
    && wget -q https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz \
    && tar -xzf ta-lib-0.4.0-src.tar.gz \
    && cd ta-lib \
    && ./configure --prefix=/usr \
    && make -s \
    && make install \
    && cd .. \
    && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz \
    && apt-get purge -y --auto-remove wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ingestion/ ./ingestion/
COPY dashboard.py .

CMD ["python", "-m", "ingestion.main"]
