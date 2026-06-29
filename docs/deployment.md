# Deployment Guide

This document describes the intended deployment path for Smart-MQTT++.

## Current Status

The current system is a research prototype that runs locally with:
- FastAPI backend
- React frontend
- MQTT broker
- InfluxDB
- Local JSON metadata stores

Docker-based deployment is planned as the next step.

## Target Local Deployment

The target local deployment should run with:

```bash
docker compose up --build

Expected services:

backend
frontend
mqtt broker
influxdb
Required Environment Variables

Suggested .env.example:

MQTT_BROKER=mosquitto
MQTT_PORT=1883

INFLUX_URL=http://influxdb:8086
INFLUX_BUCKET=smartHub
INFLUX_ORG=smartmqtt
INFLUX_TOKEN=change_me

EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DEVICE=cpu

ID_THRESH=0.90
MIN_POINTS=10
DUPE_CHECK_DELAY=60
GROUP_TAG_THRESH=0.85

DATA_DIR=./backend/data
Deployment Goals

A deployable Smart-MQTT++ setup should provide:

One-command local startup.
Persistent InfluxDB volume.
Configurable MQTT broker.
Configurable backend environment.
Frontend connected through environment-based API URLs.
Health check endpoint.
Demo publisher script.
Benchmark script.
Future Production Considerations

Before external production use, the system should add:

API authentication.
MQTT authentication.
Restricted CORS.
HTTPS reverse proxy.
Structured logging.
Metadata database.
Backup and restore process.
Monitoring and metrics.
