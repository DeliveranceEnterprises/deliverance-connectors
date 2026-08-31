#!/bin/bash
# Deja la Raspberry como "puente" hacia la red de la oficina via Tailscale.
# No hay que tocar la tablet del robot para nada, esto solo va en la Raspberry.
set -e

echo "== 1. Instalando Tailscale =="
curl -fsSL https://tailscale.com/install.sh | sh

echo "== 2. Activando reenvio de trafico (necesario para hacer de puente) =="
if ! grep -q "^net.ipv4.ip_forward = 1" /etc/sysctl.conf; then
  echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.conf
fi
sudo sysctl -p

echo "== 3. Detectando la red local de la oficina =="
SUBNET=$(ip -4 route list scope link | awk '{print $1}' | head -n1)
echo "Red detectada: $SUBNET"

if [ -z "$SUBNET" ]; then
  echo "No se pudo detectar la red automaticamente. Mira la IP de la Raspberry con 'ip a' y revisala manualmente."
  exit 1
fi

echo "== 4. Conectando a Tailscale, anunciando esa red =="
sudo tailscale up --advertise-routes="$SUBNET" --hostname=raspberry-oficina

echo ""
echo "Listo. Si ha salido un enlace arriba, abrelo en el navegador para iniciar sesion (una sola vez)."
echo "Despues, pide que se apruebe la ruta '$SUBNET' en admin.tailscale.com (Machines > esta Raspberry > Edit route settings)."
