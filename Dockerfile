FROM python:3.12-slim

ARG REQUIREMENTS=prod

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgdal-dev \
    gdal-bin \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala GDAL con la versión exacta que tiene el sistema
RUN pip install GDAL==$(gdal-config --version)

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/${REQUIREMENTS}.txt

COPY . .