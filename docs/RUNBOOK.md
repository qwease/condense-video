# Condense Video Backend - Operations Runbook

This runbook covers deployment procedures, monitoring, troubleshooting, and maintenance for the Condense Video Backend service.

## Table of Contents

- [System Architecture](#system-architecture)
- [Deployment Procedures](#deployment-procedures)
- [Monitoring and Health Checks](#monitoring-and-health-checks)
- [Common Issues and Fixes](#common-issues-and-fixes)
- [Rollback Procedures](#rollback-procedures)
- [Maintenance Tasks](#maintenance-tasks)
- [Scaling Guidelines](#scaling-guidelines)
- [Disaster Recovery](#disaster-recovery)

## System Architecture

### Service Components

| Component | Purpose | Ports |
|-----------|---------|-------|
| **FastAPI** | REST API for video processing | 8000 |
| **Celery Worker** | Background task processing | N/A |
| **Redis** | Message broker & result backend | 6379 |
| **MinIO** | Object storage (optional) | 9000, 9001 |
| **Flower** | Celery monitoring dashboard | 5555 |

### Data Flow

```
Client Request → FastAPI → Celery Task Queue → Workers → DashScope AI
                                                    ↓
                                                Redis (Status)
                                                    ↓
                                                WebSocket (Progress)
```

## Deployment Procedures

### Docker Compose Deployment (Recommended)

#### Initial Deployment

```bash
# 1. Clone repository
git clone <repo-url>
cd condense-video

# 2. Create environment file
cp .env.example .env
# Edit .env with production values

# 3. Set required environment variables
export DASHSCOPE_API_KEY="sk-xxxxx"
export MINIO_ROOT_USER="admin"
export MINIO_ROOT_PASSWORD="secure-password"

# 4. Build and start services
cd docker
docker-compose build
docker-compose up -d

# 5. Verify services are healthy
docker-compose ps
curl http://localhost:8000/health
```

#### Service Status Verification

```bash
# Check all containers
docker-compose ps

# Expected output: All services should show "Up (healthy)"
NAME              STATUS                     PORTS
docker-api-1      Up (healthy)               0.0.0.0:58000->8000/tcp
docker-worker-1   Up (healthy)               -
docker-flower-1   Up (healthy)               0.0.0.0:5555->5555/tcp
docker-redis-1    Up (healthy)               0.0.0.0:6379->6379/tcp
docker-minio-1    Up (healthy)               0.0.0.0:9000-9001->9000-9001/tcp
```

### Production Deployment with Systemd

#### API Service

Create `/etc/systemd/system/condense-api.service`:

```ini
[Unit]
Description=Condense Video API
After=network.target

[Service]
Type=notify
User=condense
Group=condense
WorkingDirectory=/opt/condense-video
Environment="PATH=/opt/condense-video/venv/bin"
EnvironmentFile=/opt/condense-video/.env
ExecStart=/opt/condense-video/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Celery Worker Service

Create `/etc/systemd/system/condense-worker.service`:

```ini
[Unit]
Description=Condense Video Celery Worker
After=network.target redis.service

[Service]
Type=forking
User=condense
Group=condense
WorkingDirectory=/opt/condense-video
Environment="PATH=/opt/condense-video/venv/bin"
EnvironmentFile=/opt/condense-video/.env
ExecStart=/opt/condense-video/venv/bin/celery -A tasks.celery_app worker \
    --loglevel=info --concurrency=4 --pidfile=/var/run/condense-worker.pid
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Enable and Start Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable condense-api condense-worker
sudo systemctl start condense-api condense-worker

# Check status
sudo systemctl status condense-api
sudo systemctl status condense-worker
```

## Monitoring and Health Checks

### Health Check Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | API health check |
| `GET /api/v1/tasks/{task_id}` | Task status check |
| `GET http://localhost:5555` | Flower monitoring dashboard |

### Monitoring Commands

```bash
# API Health
curl http://localhost:8000/health
# Expected: {"status":"healthy","version":"2.0.0"}

# Celery Worker Status
celery -A tasks.celery_app inspect active
celery -A tasks.celery_app inspect stats

# Redis Status
redis-cli ping
redis-cli info stats

# Flower Dashboard
# Open browser: http://localhost:5555
```

### Log Monitoring

```bash
# Docker Compose logs
docker-compose logs -f api
docker-compose logs -f worker

# Systemd service logs
journalctl -u condense-api -f
journalctl -u condense-worker -f

# Application logs
tail -f logs/api.log
tail -f logs/worker.log
```

### Metrics to Monitor

| Metric | Tool | Alert Threshold |
|--------|------|-----------------|
| API Response Time | Prometheus | > 5s |
| Task Queue Length | Flower | > 100 |
| Worker CPU Usage | htop | > 80% |
| Redis Memory | redis-cli | > 2GB |
| Disk Space | df | > 85% full |

## Common Issues and Fixes

### Issue: API Returns 502 Bad Gateway

**Symptoms**: API unresponsive, connection refused

**Diagnosis**:
```bash
docker-compose ps
curl http://localhost:8000/health
docker-compose logs api
```

**Causes & Fixes**:

1. **API container crashed**
   ```bash
   docker-compose restart api
   ```

2. **Port conflict**
   ```bash
   netstat -tulpn | grep 8000
   # Change port in docker-compose.yml if needed
   ```

3. **Redis connection failed**
   ```bash
   docker-compose restart redis
   ```

### Issue: Celery Workers Not Processing Tasks

**Symptoms**: Tasks stuck in "PENDING" state

**Diagnosis**:
```bash
# Check worker status
celery -A tasks.celery_app inspect active

# Check queue length
celery -A tasks.celery_app inspect active_queues

# View worker logs
docker-compose logs worker
```

**Causes & Fixes**:

1. **Worker not connected to broker**
   ```bash
   # Check CELERY_BROKER_URL in .env
   echo $CELERY_BROKER_URL
   # Should match redis URL
   docker-compose restart worker
   ```

2. **Worker out of memory**
   ```bash
   # Check container stats
   docker stats docker-worker-1
   # Increase worker memory limit in docker-compose.yml
   ```

3. **Task execution error**
   ```bash
   # Check for errors in logs
   docker-compose logs worker | grep ERROR
   # Common issue: Missing DASHSCOPE_API_KEY
   ```

### Issue: OCR/TTS API Rate Limiting

**Symptoms**: Tasks failing with rate limit errors

**Diagnosis**:
```bash
docker-compose logs worker | grep "rate limit"
```

**Fix**:
```bash
# Reduce concurrency in .env
OCR_CONCURRENCY=2        # Default: 5
TTS_CONCURRENCY=1        # Default: 3
CLASSIFICATION_CONCURRENCY=5  # Default: 10

# Restart workers
docker-compose restart worker
```

### Issue: Video Processing Timeout

**Symptoms**: Large videos fail to process

**Fix**:
```bash
# Increase timeout in .env
TASK_TIMEOUT=14400    # 4 hours (default: 7200)

# For very long videos, adjust worker prefork settings
WORKER_PREFETCH_MULTIPLIER=1
```

### Issue: High Memory Usage

**Symptoms**: OOM kills, system sluggish

**Diagnosis**:
```bash
docker stats
free -h
```

**Fix**:
```bash
# Reduce worker concurrency
WORKER_CONCURRENCY=1

# Add memory limits in docker-compose.yml
services:
  worker:
    deploy:
      resources:
        limits:
          memory: 2G
```

### Issue: MinIO Connection Errors

**Symptoms**: File upload/download failures

**Diagnosis**:
```bash
curl http://localhost:9000/minio/health/live
docker-compose logs minio
```

**Fix**:
```bash
# Restart MinIO
docker-compose restart minio

# Verify credentials in .env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=condense-video
```

## Rollback Procedures

### Docker Compose Rollback

```bash
# 1. Stop current services
docker-compose down

# 2. Checkout previous version
git checkout <previous-commit>

# 3. Rebuild with previous version
docker-compose build
docker-compose up -d

# 4. Verify rollback
curl http://localhost:8000/health
```

### Database/Data Rollback

Redis is stateless for this application. To clear task state:

```bash
# WARNING: This clears all task history
redis-cli FLUSHDB

# To clear specific task data
redis-cli DEL "task:{task_id}"
```

## Maintenance Tasks

### Daily Tasks

- [ ] Check service health: `curl http://localhost:8000/health`
- [ ] Review Flower dashboard for stuck tasks
- [ ] Check disk space: `df -h`
- [ ] Review error logs: `docker-compose logs --since 24h | grep ERROR`

### Weekly Tasks

- [ ] Clean up old task data (Redis TTL auto-clears after 30 days)
- [ ] Review and rotate logs
- [ ] Check for dependency updates: `pip list --outdated`

### Monthly Tasks

- [ ] Review and update DashScope API usage
- [ ] Test backup and restore procedures
- [ ] Review performance metrics
- [ ] Security audit: check for leaked credentials

### Log Rotation

Configure logrotate for application logs:

Create `/etc/logrotate.d/condense-video`:

```
/opt/condense-video/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 condense condense
    sharedscripts
    postrotate
        docker-compose exec api kill -USR1 $(cat /tmp/api.pid)
    endscript
}
```

## Scaling Guidelines

### Horizontal Scaling - Workers

```bash
# Update docker-compose.yml
services:
  worker:
    deploy:
      replicas: 4    # Increase worker count

# Or scale with command
docker-compose up -d --scale worker=4
```

### Horizontal Scaling - API

```bash
# Add load balancer (nginx/traefik) in front of multiple API instances
docker-compose up -d --scale api=3

# Example nginx upstream config:
upstream api_backend {
    least_conn;
    server api-1:8000;
    server api-2:8000;
    server api-3:8000;
}
```

### Vertical Scaling - Resources

```bash
# Add resource limits in docker-compose.yml
services:
  worker:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

### Performance Tuning

| Component | Setting | Effect |
|-----------|---------|--------|
| Worker Concurrency | `WORKER_CONCURRENCY=4` | More parallel tasks |
| Task Prefetch | `WORKER_PREFETCH_MULTIPLIER=2` | Reduce idle time |
| OCR Concurrency | `OCR_CONCURRENCY=10` | Faster OCR processing |
| API Workers | `API_WORKERS=4` | More API capacity |

## Disaster Recovery

### Backup Strategy

**What to Backup**:
- Environment configuration (`.env`)
- MinIO data (if using object storage)
- Redis data (optional - mainly cache)

**Backup Commands**:

```bash
# Backup environment
cp .env .env.backup.$(date +%Y%m%d)

# Backup MinIO data
docker exec docker-minio-1 mc mirror /data /backup/minio-$(date +%Y%m%d)

# Backup Redis (optional)
docker exec docker-redis-1 redis-cli --rdb /data/dump.rdb
docker cp docker-redis-1:/data/dump.rdb ./redis-backup-$(date +%Y%m%d).rdb
```

### Recovery Procedure

```bash
# 1. Restore environment
cp .env.backup.YYYYMMDD .env

# 2. Restore MinIO data
docker exec docker-minio-1 mc mirror /backup/minio-YYYYMMDD /data

# 3. Restart services
docker-compose down
docker-compose up -d

# 4. Verify recovery
curl http://localhost:8000/health
```

### Emergency Contacts

| Role | Contact |
|------|---------|
| System Administrator | admin@example.com |
| DevOps Engineer | devops@example.com |
| DashScope Support | Alibaba Cloud Console |

## Security Checklist

- [ ] Change default MinIO credentials
- [ ] Use strong passwords for all services
- [ ] Enable HTTPS/TLS for production
- [ ] Restrict API access with firewall rules
- [ ] Rotate API keys regularly
- [ ] Enable audit logging
- [ ] Scan images for vulnerabilities
- [ ] Keep dependencies updated

## Quick Reference Commands

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# View logs
docker-compose logs -f

# Restart specific service
docker-compose restart api

# Rebuild after code changes
docker-compose build && docker-compose up -d

# Execute command in container
docker-compose exec api bash

# Check service health
curl http://localhost:8000/health

# View Celery tasks
celery -A tasks.celery_app inspect active

# Redis CLI
docker-compose exec redis redis-cli

# MinIO CLI
docker-compose exec minio mc ls /data
```
