#!/usr/bin/env bash
# Botni Google Cloud (Ubuntu) serveriga o'rnatadi yoki yangilaydi.
#
# Birinchi marta (SSH oynasida):
#   wget -qO setup.sh https://raw.githubusercontent.com/wwtf339-wq/jarvis-dashboard/claude/telegram-expense-tracking-bot-kmd0y7/expense-bot/deploy_gcp.sh
#   sudo bash setup.sh
#
# Keyin kod yangilanganda xuddi shu ikki buyruqni qayta bering:
# .env va baza (expenses.db) saqlanib qoladi, faqat kod yangilanadi.
set -euo pipefail

REPO=https://github.com/wwtf339-wq/jarvis-dashboard.git
BRANCH=claude/telegram-expense-tracking-bot-kmd0y7
SRC=/opt/src
APP=/opt/expense-bot

[ "$(id -u)" = 0 ] || { echo "sudo bilan ishga tushiring: sudo bash $0"; exit 1; }

echo "== 1/6 Paketlar o'rnatilmoqda"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3-venv sqlite3 >/dev/null

echo "== 2/6 Swap (e2-micro'da RAM atigi 1 GB)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/6 Kod yuklanmoqda"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch -q origin "$BRANCH"
  git -C "$SRC" reset -q --hard FETCH_HEAD
else
  git clone -q -b "$BRANCH" "$REPO" "$SRC"
fi
mkdir -p "$APP"
# GitHub'da .env va .db yo'q, shuning uchun ular ustidan yozilmaydi
cp -r "$SRC/expense-bot/." "$APP/"

echo "== 4/6 Python kutubxonalari"
[ -d "$APP/.venv" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

echo "== 5/6 Sozlamalar (.env)"
if [ ! -f "$APP/.env" ]; then
  read -rp "Telegram bot tokeni: " TOKEN < /dev/tty
  read -rp "Gemini API kaliti: " GKEY < /dev/tty
  read -rp "Xo'jayin Telegram ID (bir nechta bo'lsa vergul bilan): " OWNERS < /dev/tty
  sed -e "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TOKEN|" \
      -e "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=$GKEY|" \
      -e "s|^OWNER_IDS=.*|OWNER_IDS=$OWNERS|" \
      "$APP/.env.example" > "$APP/.env"
else
  echo "   .env bor, tegilmadi (o'zgartirish: sudo nano $APP/.env)"
fi
chmod 600 "$APP/.env"

echo "== 6/6 Xizmat ishga tushirilmoqda"
cp "$APP/expense-bot.service" /etc/systemd/system/expense-bot.service
systemctl daemon-reload
systemctl enable -q expense-bot
systemctl restart expense-bot
sleep 5
if systemctl is-active -q expense-bot; then
  echo
  echo "TAYYOR: bot ishlayapti. Telegram'da /start bosing."
  echo "Loglar:   sudo journalctl -u expense-bot -f"
  echo "Kalitlar: sudo nano $APP/.env && sudo systemctl restart expense-bot"
else
  echo "Bot ishga tushmadi. Oxirgi loglar:"
  journalctl -u expense-bot -n 30 --no-pager
  exit 1
fi
