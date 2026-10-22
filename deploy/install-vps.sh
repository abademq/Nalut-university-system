#!/usr/bin/env bash
# Install (or update) the platform on an Ubuntu server that already runs Nginx
# for another site, without touching that site.
#
#   sudo bash deploy/install-vps.sh <domain> [email]
#   sudo bash deploy/install-vps.sh <domain> [email] --reset-demo   # recreate demo data
#
# What it does:
#   - runs the app as its own system user "nus", listening on 127.0.0.1 only
#   - keeps code in /opt/nus, data in /var/lib/nus, secrets in /etc/nus/nus.env
#   - adds ONE new Nginx site file for <domain>; it validates the whole Nginx
#     config before reloading and removes its own file again if validation fails
#   - requests a Let's Encrypt certificate for <domain> only
# Running it again updates the code and keeps the data and secrets.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
RESET=""
for a in "$@"; do [ "$a" = "--reset-demo" ] && RESET=1; done
[ "$EMAIL" = "--reset-demo" ] && EMAIL=""
PORT="${NUS_PORT:-8010}"

APP_DIR=/opt/nus
DATA_DIR=/var/lib/nus
ENV_FILE=/etc/nus/nus.env
SERVICE=nus
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mXX  %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run with sudo (as root)."
[ -n "$DOMAIN" ] || die "Usage: sudo bash deploy/install-vps.sh <domain> [email]"
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "Invalid domain: $DOMAIN"
[ -f "$SRC_DIR/backend/app/main.py" ] || die "Run this script from inside the project folder."
command -v nginx >/dev/null || die "Nginx is not installed."

# The port must be free unless it is already ours.
if ss -ltn "sport = :$PORT" | grep -q LISTEN && ! systemctl is-active --quiet "$SERVICE"; then
  die "Port $PORT is already used by another program. Re-run with: NUS_PORT=8020 sudo -E bash $0 $DOMAIN $EMAIL"
fi

say "Installing system packages (python3-venv, certbot)"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip rsync certbot python3-certbot-nginx >/dev/null

say "Creating user and folders"
id -u nus >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin nus
mkdir -p "$APP_DIR" "$DATA_DIR/files" "$DATA_DIR/backups" /etc/nus
chown -R nus:nus "$DATA_DIR"
chmod 750 "$DATA_DIR"

say "Copying the code to $APP_DIR"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  rsync -a --delete --exclude .git --exclude .venv --exclude 'backend/data' --exclude '__pycache__' "$SRC_DIR/" "$APP_DIR/"
fi
git -c safe.directory='*' -C "$SRC_DIR" log -1 --format='%h %cd' --date=short > "$APP_DIR/VERSION" 2>/dev/null || echo unknown > "$APP_DIR/VERSION"

say "Installing Python requirements (a few minutes the first time)"
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q -r "$APP_DIR/backend/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
  say "Generating secrets in $ENV_FILE"
  SECRET=$("$APP_DIR/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")
  FERNET=$("$APP_DIR/.venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  cat > "$ENV_FILE" <<ENV
# Demo deployment. APP_ENV=demo keeps the demo-account buttons on the login page.
APP_ENV=demo
SECRET_KEY=$SECRET
DATA_ENCRYPTION_KEY=$FERNET
COOKIE_SECURE=true
DATABASE_URL=sqlite:///$DATA_DIR/nus.db
STORAGE_DIR=$DATA_DIR/files
WEB_DIR=$APP_DIR/web
RUN_WORKER=true
PYTHONDONTWRITEBYTECODE=1
ENV
fi
chown root:nus "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "Preparing the database"
run_as_nus() { sudo -u nus bash -c "set -a; . $ENV_FILE; set +a; cd $APP_DIR/backend; $*"; }
if [ -n "$RESET" ]; then
  run_as_nus "$APP_DIR/.venv/bin/python -m app.seed --reset"
else
  run_as_nus "$APP_DIR/.venv/bin/python -m app.seed"
fi

say "Installing the background service ($SERVICE)"
cat > /etc/systemd/system/$SERVICE.service <<UNIT
[Unit]
Description=University platform (FastAPI)
After=network.target

[Service]
User=nus
Group=nus
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --quiet $SERVICE
systemctl restart $SERVICE

for i in $(seq 1 20); do
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || die "The service did not start. See: journalctl -u $SERVICE -n 50"

say "Adding the Nginx site for $DOMAIN (the existing site is not modified)"
# "zz-" so the file loads after existing sites and never becomes the default server.
SITE=/etc/nginx/sites-available/zz-$DOMAIN
LISTEN6=""
ss -ltn | grep -q '\[::\]:80 ' && LISTEN6="listen [::]:80;"
if [ ! -f "$SITE" ]; then
  cat > "$SITE" <<NGINX
server {
    listen 80;
    $LISTEN6
    server_name $DOMAIN;

    client_max_body_size 30m;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
NGINX
  ln -sf "$SITE" /etc/nginx/sites-enabled/zz-$DOMAIN
  if ! nginx -t 2>/tmp/nus-nginx-test.log; then
    rm -f /etc/nginx/sites-enabled/zz-$DOMAIN "$SITE"
    cat /tmp/nus-nginx-test.log
    die "Nginx rejected the new config; it was removed and nothing was reloaded."
  fi
  systemctl reload nginx
fi

HTTPS_OK=""
say "Checking that $DOMAIN points to this server"
SERVER_IP=$(curl -4 -fsS https://api.ipify.org || true)
DOMAIN_IP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)
if [ -n "$SERVER_IP" ] && [ "$SERVER_IP" = "$DOMAIN_IP" ]; then
  say "Requesting the HTTPS certificate for $DOMAIN"
  if [ -n "$EMAIL" ]; then CERT_MAIL=(-m "$EMAIL"); else CERT_MAIL=(--register-unsafely-without-email); fi
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect "${CERT_MAIL[@]}"; then
    HTTPS_OK=1
  else
    warn "Certificate request failed. Fix the reason above, then run: sudo certbot --nginx -d $DOMAIN --redirect"
  fi
else
  warn "$DOMAIN resolves to '${DOMAIN_IP:-nothing}' but this server is '${SERVER_IP:-unknown}'."
  warn "Add an A record for $DOMAIN -> $SERVER_IP, wait a few minutes, then run: sudo certbot --nginx -d $DOMAIN --redirect"
fi

say "Installing the SMS check (sudo nus-sms-check [phone])"
cat > /usr/local/sbin/nus-sms-check <<CHECK
#!/usr/bin/env bash
# Checks the SMS settings in $ENV_FILE and optionally sends one test code: nus-sms-check [phone]
exec sudo -u nus bash -c 'set -a; . $ENV_FILE; set +a; cd $APP_DIR/backend; exec $APP_DIR/.venv/bin/python -m app.sms_check "\$@"' nus-sms-check "\$@"
CHECK
chmod 755 /usr/local/sbin/nus-sms-check

say "Daily backup (03:30, keeps 14 days)"
cat > /etc/cron.d/nus-backup <<CRON
30 3 * * * nus $APP_DIR/.venv/bin/python -c "import sqlite3,datetime; d='$DATA_DIR/backups/nus-'+datetime.date.today().isoformat()+'.db'; s=sqlite3.connect('$DATA_DIR/nus.db'); t=sqlite3.connect(d); s.backup(t); t.close()" && tar -czf $DATA_DIR/backups/files-\$(date +\%F).tgz -C $DATA_DIR files && find $DATA_DIR/backups -mtime +14 -delete
CRON

if [ -n "$HTTPS_OK" ]; then
  say "Done: https://$DOMAIN"
else
  warn "Installed, but HTTPS is not active yet (see above). Login sessions and the camera need HTTPS."
fi
echo "  Version        : $(cat "$APP_DIR/VERSION")"
echo "  Service status : systemctl status $SERVICE"
echo "  Live logs      : journalctl -u $SERVICE -f"
echo "  Update later   : git pull && sudo bash deploy/install-vps.sh $DOMAIN"
