#!/usr/bin/env bash
# Installation sur une instance Lightsail Ubuntu 24.04 (à lancer avec sudo depuis le dossier du projet).
#   sudo bash deploy/install.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update
apt-get install -y python3-venv nginx sqlite3 certbot python3-certbot-nginx

id copro >/dev/null 2>&1 || useradd --system --home /srv/copro --shell /usr/sbin/nologin copro
mkdir -p /srv/copro/app /srv/copro/data
cp -r "$SRC"/. /srv/copro/app/
rm -rf /srv/copro/app/data

python3 -m venv /srv/copro/venv
/srv/copro/venv/bin/pip install --upgrade pip
/srv/copro/venv/bin/pip install -r /srv/copro/app/requirements.txt

if [ ! -f /etc/copro.env ]; then
  cp /srv/copro/app/deploy/copro.env.example /etc/copro.env
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET/" /etc/copro.env
  echo ">>> Complétez /etc/copro.env (domaine, bucket, clés AWS), puis relancez ce script."
fi
chown root:copro /etc/copro.env
chmod 640 /etc/copro.env
chown -R copro:copro /srv/copro
chmod +x /srv/copro/app/deploy/backup.sh

cp /srv/copro/app/deploy/copro.service /etc/systemd/system/copro.service
cp /srv/copro/app/deploy/nginx.conf /etc/nginx/sites-available/copro
ln -sf /etc/nginx/sites-available/copro /etc/nginx/sites-enabled/copro
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable --now copro
nginx -t && systemctl reload nginx

# Sauvegarde chaque nuit à 3h15
{ crontab -u copro -l 2>/dev/null | grep -v backup.sh || true; echo "15 3 * * * /srv/copro/app/deploy/backup.sh >> /srv/copro/data/backup.log 2>&1"; } | crontab -u copro -

echo "Installation terminée. Étapes suivantes :"
echo "  1. sudo certbot --nginx -d votre-domaine.fr"
echo "  2. Créer le premier administrateur :"
echo "     sudo -u copro bash -c 'set -a; source /etc/copro.env; cd /srv/copro/app; /srv/copro/venv/bin/flask --app app add-admin'"
