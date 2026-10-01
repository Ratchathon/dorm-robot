#!/usr/bin/env bash
# Run ONCE on the Raspberry Pi:   bash setup_pi.sh
# After this the robot starts by itself every time the Pi powers on,
# and the cockpit is at  http://meterbot.local:5000  (no IP address needed).
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
NAME="${1:-meterbot}"

echo "==> ติดตั้งแพ็กเกจ"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-picamera2 python3-opencv python3-pip avahi-daemon
pip install -r requirements.txt --break-system-packages -q

echo "==> ปิดโปรแกรมกล้องของ Arducam (แย่งกล้อง)"
sudo systemctl disable --now camera-streamer 2>/dev/null || true

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> สร้างไฟล์ .env แล้ว (แก้ CLOUD_URL และ DEVICE_KEY ภายหลังด้วย: nano $HERE/.env)"
fi

echo "==> ตั้งชื่อเครื่องเป็น $NAME (เปิดได้ที่ http://$NAME.local:5000)"
sudo hostnamectl set-hostname "$NAME"
sudo sed -i "s/^127.0.1.1.*/127.0.1.1\t$NAME/" /etc/hosts
sudo systemctl restart avahi-daemon

echo "==> ให้หุ่นเริ่มทำงานเองทุกครั้งที่เปิดเครื่อง"
sudo tee /etc/systemd/system/meterbot.service >/dev/null <<UNIT
[Unit]
Description=Teleoperated Cleaning Robot (cockpit + drive bridge)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$HERE
ExecStart=/usr/bin/python3 $HERE/server.py
Restart=always
RestartSec=2
User=$USER

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now meterbot.service

IP="$(hostname -I | awk '{print $1}')"
echo
echo "เสร็จแล้ว เปิดหน้าควบคุมได้ที่:"
echo "   http://$NAME.local:5000"
echo "   http://$IP:5000   (สำรอง ถ้าเครื่องไหนเปิดชื่อ .local ไม่ได้)"
echo "ดู log: journalctl -u meterbot -f    รีสตาร์ท: sudo systemctl restart meterbot"
