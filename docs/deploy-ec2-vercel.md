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

## 9) CI/CD (GitHub Actions)

The pipeline in `.github/workflows/ci-cd.yml` runs on every push and pull request to `main`:

1. `backend-tests` — `pytest` (uses in-memory SQLite, no Postgres needed).
2. `frontend-tests` — ESLint, Vitest, and a type-checked build.
3. `e2e-tests` — Playwright E2E (with the report uploaded as an artifact on failure).
4. `deploy` — only on a push to `main`, and only after all three test jobs pass. It assumes an AWS role via **GitHub OIDC** (no long-lived AWS keys, no inbound SSH) and uses **AWS Systems Manager (SSM)** `send-command` to run the same steps you would by hand on the instance:

   ```bash
   cd /opt/chudbet
   git fetch --all
   git reset --hard origin/main
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
   docker image prune -f
   curl -fsS "https://$API_DOMAIN/health"
   ```

The frontend is **not** deployed here — Vercel's Git integration auto-deploys `frontend/` on pushes to `main` independently.

### Deploy mechanism: SSM + OIDC (no inbound SSH)

Because the deploy runs via SSM, **port 22 stays closed to the internet**. GitHub Actions never connects to the box directly; it tells SSM to run the script, and the on-box SSM agent executes it (as `root`).

One-time AWS setup:

1. **Let the instance be managed by SSM.** Attach an instance profile with the managed policy `AmazonSSMManagedInstanceCore` to the EC2 instance. (The SSM agent is preinstalled on Amazon Linux.) Confirm the instance appears under **Systems Manager → Fleet Manager / Managed instances** with a "Connected/Online" ping status.

2. **Create the GitHub OIDC identity provider in IAM** (once per AWS account):
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

3. **Create an IAM role** (e.g. `chudbet-github-deploy`) the workflow can assume. Trust policy (replace `<ACCOUNT_ID>` and the repo if it changes):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
       "Action": "sts:AssumeRoleWithWebIdentity",
       "Condition": {
         "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
         "StringLike": { "token.actions.githubusercontent.com:sub": "repo:vincent0955/chudbet:ref:refs/heads/main" }
       }
     }]
   }
   ```

4. **Attach a permissions policy** to that role allowing it to run a command on the one instance and read the result (replace `<REGION>`, `<ACCOUNT_ID>`, `<INSTANCE_ID>`):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "ssm:SendCommand",
         "Resource": [
           "arn:aws:ssm:<REGION>::document/AWS-RunShellScript",
           "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:instance/<INSTANCE_ID>"
         ]
       },
       {
         "Effect": "Allow",
         "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations", "ssm:ListCommands"],
         "Resource": "*"
       }
     ]
   }
   ```

### Required repository secrets

Set these under **Settings → Secrets and variables → Actions**:

- `AWS_DEPLOY_ROLE_ARN` — ARN of the IAM role from step 3 (e.g. `arn:aws:iam::123456789012:role/chudbet-github-deploy`).
- `AWS_REGION` — region the instance runs in (e.g. `us-east-1`).
- `EC2_INSTANCE_ID` — target instance id (e.g. `i-0abc123...`), found in the EC2 console.

Notes:
- SSM `AWS-RunShellScript` runs as `root` without a default `$HOME`; the workflow sets `HOME=/root` and passes `git -c safe.directory=/opt/chudbet` so git can operate in a tree that may be owned by `ec2-user`.
- `git reset --hard origin/main` discards any local commits on the server by design; `.env.prod` is untracked and therefore preserved.
- DB schema changes need no extra step — backend startup runs `Base.metadata.create_all` + `ensure_postgres_schema` (`backend/app/main.py`).
- The job prints the script's stdout/stderr from SSM and fails the build if the invocation status is not `Success` (so a failed `/health` check fails the deploy).
