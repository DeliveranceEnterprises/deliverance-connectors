#!/data/data/com.termux/files/usr/bin/bash
# Corre esto DENTRO de Termux, en la tablet del WDC (Android 7.1).
# Deja un Ubuntu real montado con proot-distro y arranca el Agent Core real
# de InOrbit dentro, sin tocar la app de produccion del robot para nada.
#
# Aprendido en las pruebas de simulacion del 2026-08-27/28 (mismo mecanismo,
# PRoot, solo que aqui es Termux+proot-distro en vez de nuestra copia manual
# con Ubuntu Base + qemu-arm-static -- en la tablet real no hace falta qemu,
# el procesador ya es ARM nativo):
#   - Hay que arreglar un gancho roto de libc6 (notify-reboot-required) o
#     falla en cascada la instalacion de paquetes.
#   - Hace falta lsb-release para que el instalador de InOrbit detecte Ubuntu.
#   - numpy==1.19.0 necesita compilar desde el codigo fuente (no hay wheel
#     lista para armv7/py3.8), y con eso hace falta Cython VIEJO (<3), la
#     version nueva de Cython rompe la compilacion de un numpy tan antiguo.
#   - Puede hacer falta PROOT_NO_SECCOMP=1 si roscore u otras cosas dan un
#     error "Bad address" al arrancar.

set -e

echo "=== 1. Instalando proot-distro ==="
pkg update -y
pkg install -y proot-distro

echo "=== 2. Instalando Ubuntu (focal, para que encaje con ROS Noetic) ==="
proot-distro install ubuntu

echo "=== 3. Arreglando el gancho roto de libc6 antes de nada ==="
proot-distro login ubuntu -- bash -c "
mkdir -p /usr/share/update-notifier
printf '#!/bin/sh\nexit 0\n' > /usr/share/update-notifier/notify-reboot-required
chmod +x /usr/share/update-notifier/notify-reboot-required
"

echo "=== 4. Dependencias base dentro del Ubuntu ==="
proot-distro login ubuntu -- bash -c "
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y sudo curl gnupg lsb-release python3-virtualenv python3-dev python3.8-venv build-essential cmake pkg-config
"

echo "=== 5. Instalando ROS Noetic ==="
proot-distro login ubuntu -- bash -c "
export DEBIAN_FRONTEND=noninteractive
curl -sL https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | apt-key add -
echo 'deb http://packages.ros.org/ros/ubuntu focal main' > /etc/apt/sources.list.d/ros-latest.list
apt-get update
apt-get install -y ros-noetic-ros-base
"

echo "=== 6. Descargando el instalador real de InOrbit ==="
proot-distro login ubuntu -- bash -c "
curl -fsSL https://space.inorbit.ai/liftoff/<INORBIT_INSTALL_KEY> -o /root/inorbit_installer.sh
"

echo "=== Listo. Para lanzar el instalador de verdad (interactivo, hay que estar delante): ==="
echo "proot-distro login ubuntu"
echo "  source /opt/ros/noetic/setup.bash"
echo "  bash /root/inorbit_installer.sh"
echo ""
echo "Si al arrancar roscore da un error 'Bad address', reintentar con:"
echo "  PROOT_NO_SECCOMP=1 proot-distro login ubuntu"
