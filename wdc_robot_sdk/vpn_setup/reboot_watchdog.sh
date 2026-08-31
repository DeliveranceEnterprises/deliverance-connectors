#!/data/data/com.termux/files/usr/bin/bash
# Vigilante de ultimo recurso: si Android mata Termux ENTERO (no solo un
# script corriendo dentro), los bucles de auto-reinicio de
# start-deliverance.sh mueren con el, y no queda nada vivo dentro de Termux
# capaz de arreglarlo por su cuenta.
#
# Este script se ejecuta via `termux-job-scheduler` (Android JobScheduler),
# que SI sobrevive a que Android mate la app -- si Termux estaba muerto,
# Android arranca un proceso nuevo de Termux solo para correr este script,
# asi que el propio hecho de que esto se ejecute ya implica que Termux esta
# vivo en ESTE momento, aunque no lo estuviera hace un segundo.
#
# Si al ejecutarse detecta que los procesos criticos NO estan corriendo (la
# senal de que se cayeron y nadie los relanzo -- confirmado en vivo
# 2026-08-31, ver CLAUDE.md), fuerza un reinicio real de la tablet, que
# sabemos que se recupera solo via Termux:Boot (confirmado 2026-08-29).
if ! pgrep -f roscore > /dev/null || ! pgrep -f wdc_bridge_node.py > /dev/null || ! pgrep -f 'inorbit.py' > /dev/null; then
    echo "$(date +%s) proceso critico caido, forzando reinicio" >> ~/reboot_watchdog.log
    su -c reboot
fi
