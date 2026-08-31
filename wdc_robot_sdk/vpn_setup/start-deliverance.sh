#!/data/data/com.termux/files/usr/bin/bash
# Arranca automaticamente al encender la tablet: sshd, roscore, el bridge
# de Deliverance, y el Agent Core de InOrbit, todo dentro de Ubuntu (proot-distro).
#
# Este archivo va copiado en la tablet en ~/.termux/boot/start-deliverance.sh
# (necesita Termux:Boot instalado y abierto una vez para que Android lo
# ejecute automaticamente en cada arranque).
termux-wake-lock

sshd

# Vigilante de la app de fabrica (com.sirui.wdc_robot): esa app cierra o
# pierde el primer plano por su cuenta de vez en cuando, y con ella se cae
# su API local del puerto 9015 -- confirmado en vivo 2026-08-28 como la
# causa real de que no llegaran datos a InOrbit (no era un bug de red/ROS,
# ver CLAUDE.md). Este vigilante la reabre solo, sin depender de nada
# externo a la propia tablet.
nohup setsid bash ~/wdc_watchdog.sh > ~/wdc_watchdog_out.log 2>&1 < /dev/null &

sleep 5

# ROS_HOSTNAME/ROS_IP con la IP real de la tablet (no localhost/127.0.0.1):
# confirmado en vivo 2026-08-28 que bajo PRoot conviene usar la IP real de
# la interfaz wifi para que publishers y subscribers ROS se resuelvan igual
# entre sesiones proot distintas (mismo patron que ya usaba el contenedor
# Docker viejo, que resolvia su propio hostname a una IP real, no loopback).
#
# TODO EN BUCLE, no "lanza una vez": confirmado en vivo 2026-08-31 que el
# agente de InOrbit se puede parar solo ("Agent finishing to force system
# restart" en su propio log, un reinicio interno que InOrbit espera que
# relance un supervisor externo -- INORBIT_ENABLE_WATCHDOG esta a "no" en
# nuestro agent.env.sh). Sin este bucle, si el agente se para por su cuenta
# en cualquier momento, se queda parado hasta el siguiente reinicio fisico
# de la tablet (la vez que paso, estuvo 2 dias desconectado sin que nadie
# se diera cuenta). El mismo bucle se aplica a roscore y al bridge por si
# acaso, aunque solo se ha visto pararse solo al agente hasta ahora.
nohup setsid bash -c 'while true; do proot-distro login ubuntu -- bash -c "source /opt/ros/noetic/setup.bash && export ROS_HOSTNAME=192.168.3.102 && export ROS_IP=192.168.3.102 && roscore"; sleep 3; done' > ~/roscore.log 2>&1 < /dev/null &
sleep 8

nohup setsid bash -c 'while true; do proot-distro login ubuntu -- bash -c "source /opt/ros/noetic/setup.bash && export ROS_HOSTNAME=192.168.3.102 && export ROS_IP=192.168.3.102 && export WDC_LOCAL_API_HOST=192.168.3.102 && cd /root/wdc_bridge && python3 wdc_bridge_node.py"; sleep 3; done' > ~/bridge.log 2>&1 < /dev/null &
sleep 3

nohup setsid bash -c 'while true; do proot-distro login ubuntu -- bash -c "source /opt/ros/noetic/setup.bash && export ROS_HOSTNAME=192.168.3.102 && export ROS_IP=192.168.3.102 && cd /root/.inorbit/dist && ./scripts/start.sh"; sleep 3; done' > ~/inorbit_launch.log 2>&1 < /dev/null &

# Vigilante de ultimo recurso (reinicio real de la tablet si Termux entero
# muere, ver reboot_watchdog.sh) via Android JobScheduler -- se reprograma
# en cada arranque por si el flag --persisted no sobrevive en este Android,
# aunque en teoria no haria falta repetirlo.
termux-job-scheduler --job-id 1 --script ~/reboot_watchdog.sh --period-ms 900000 --persisted true
