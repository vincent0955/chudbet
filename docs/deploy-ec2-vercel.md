# Chudbet Deployment Runbook (EC2 + Docker Compose + Vercel)

This runbook deploys the current application with always-on services at low cost:
- EC2 hosts `postgres`, `backend`, `worker`, and `caddy`.
- Vercel hosts the frontend.

## 1) Provision cloud prerequisites

1. Create an Ubuntu EC2 instance (start small, e.g. `t4g.small` or `t3.small`).
2. Attach a static Elastic IP.
3. Open inbound ports:
   - `22` (restricted to your IP)
   - `80`, `443` (public)
4. Create/choose an S3 bucket for DB backups (optional but recommended).
5. Point DNS `api.example.com` to the EC2 Elastic IP.

## 2) Prepare EC2 host

Install Docker, compose plugin, AWS CLI, and git. Then clone this repo to `/opt/chudbet`.

```bash
cd /opt/chudbet
cp .env.prod.example .env.prod
```

Edit `.env.prod`:
- set `API_DOMAIN` and `ACME_EMAIL`
- set strong `POSTGRES_PASSWORD`
- set `CHUDBET_CORS_ORIGINS` to your Vercel URL(s)
- optionally set `S3_BACKUP_BUCKET`

## 3) Start backend stack

```bash
cd /opt/chudbet
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

Backend should be reachable:

```bash
curl -f https://api.example.com/health
```

## 4) Deploy frontend on Vercel

1. Import `frontend/` as a Vercel project.
2. Set framework to Vite (or use `frontend/vercel.json` defaults).
3. Set env vars in Vercel:
   - `VITE_API_URL=https://api.example.com`
   - `VITE_ACCOUNT_ID=1` (or your desired demo account)
4. Deploy.

## 5) Backup automation (S3)

Grant the EC2 instance role `s3:PutObject` for your backup bucket path.

Install systemd units:

```bash
sudo cp /opt/chudbet/infra/ops/chudbet-db-backup.service /etc/systemd/system/
sudo cp /opt/chudbet/infra/ops/chudbet-db-backup.timer /etc/systemd/system/
sudo chmod +x /opt/chudbet/infra/ops/backup_postgres_to_s3.sh
sudo systemctl daemon-reload
sudo systemctl enable --now chudbet-db-backup.timer
sudo systemctl list-timers | grep chudbet-db-backup
```

Manual backup test:

```bash
sudo systemctl start chudbet-db-backup.service
journalctl -u chudbet-db-backup.service -n 100 --no-pager
```

## 6) CloudWatch log shipping

1. Install CloudWatch agent on EC2.
2. Copy config:
   - `/opt/chudbet/infra/ops/cloudwatch-agent-config.json`
3. Start agent with that config and verify log group `/chudbet/docker` receives entries.

## 7) Smoke tests

Run after each deploy:
- `GET /health` returns `{\"status\":\"ok\"}`
- frontend loads without CORS errors
- place a small test parlay end-to-end
- confirm worker activity in logs:
  - `docker compose -f docker-compose.prod.yml --env-file .env.prod logs worker --tail=200`

## 8) Rollback

If deploy is unhealthy:
1. Revert to previous commit on EC2.
2. Rebuild/restart:
   - `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`
3. Re-check `/health` and key user flows.
