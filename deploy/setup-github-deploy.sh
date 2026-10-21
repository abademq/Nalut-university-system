#!/usr/bin/env bash
# One-time setup for the "deploy" button in GitHub Actions.
#
#   sudo bash deploy/setup-github-deploy.sh <domain>
#
# Creates a user "nus-deploy" whose SSH key can do exactly one thing: run
# /usr/local/sbin/nus-update with a commit id. The key cannot open a shell,
# forward ports or run any other command. The private key is printed once for
# the GitHub secret and then deleted from this server.
set -euo pipefail

DOMAIN="${1:-}"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME=nus-deploy

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo "Usage: sudo bash $0 <domain>"; exit 1; }
git -C "$SRC_DIR" rev-parse HEAD >/dev/null

mkdir -p /etc/nus
printf 'DOMAIN=%s\nSRC_DIR=%s\n' "$DOMAIN" "$SRC_DIR" > /etc/nus/deploy.conf
chmod 644 /etc/nus/deploy.conf
install -o root -g root -m 755 "$SRC_DIR/deploy/nus-update" /usr/local/sbin/nus-update

id -u "$USER_NAME" >/dev/null 2>&1 || useradd --create-home --shell /bin/sh "$USER_NAME"
passwd -l "$USER_NAME" >/dev/null

echo "$USER_NAME ALL=(root) NOPASSWD: /usr/local/sbin/nus-update" > /etc/sudoers.d/nus-deploy
chmod 440 /etc/sudoers.d/nus-deploy
visudo -cf /etc/sudoers.d/nus-deploy >/dev/null

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "github-deploy@$DOMAIN" -f "$TMP/key"
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
install -d -o "$USER_NAME" -g "$USER_NAME" -m 700 "$HOME_DIR/.ssh"
# restrict = no shell, no forwarding; the command ignores whatever the client asks to run
echo "restrict,command=\"sudo /usr/local/sbin/nus-update \\\"\$SSH_ORIGINAL_COMMAND\\\"\" $(cat "$TMP/key.pub")" \
  > "$HOME_DIR/.ssh/authorized_keys"
chown "$USER_NAME:$USER_NAME" "$HOME_DIR/.ssh/authorized_keys"
chmod 600 "$HOME_DIR/.ssh/authorized_keys"

PORT=$(sshd -T 2>/dev/null | awk '$1=="port"{print $2; exit}')
HOSTKEY=$(cat /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $1" "$2}')
if [ "${PORT:-22}" = "22" ]; then KH="$DOMAIN $HOSTKEY"; else KH="[$DOMAIN]:$PORT $HOSTKEY"; fi

cat <<EOF

Done. Add these 4 secrets in GitHub:
  repository -> Settings -> Secrets and variables -> Actions -> New repository secret

  DEPLOY_HOST         $DOMAIN
  DEPLOY_PORT         ${PORT:-22}
  DEPLOY_KNOWN_HOSTS  $KH
  DEPLOY_KEY          (everything between the two lines below, including BEGIN and END)
----------------------------------------------------------------------
$(cat "$TMP/key")
----------------------------------------------------------------------
The private key is now deleted from this server; it exists only in what you copy.
If the domain goes through a proxy (e.g. Cloudflare), set DEPLOY_HOST to the server IP
and use that IP instead of the domain in DEPLOY_KNOWN_HOSTS.
EOF
