# WDC Robot: Agent Core de InOrbit ejecutándose en el propio robot

Integración del robot de reparto WDC con InOrbit usando el **Agent SDK**, con
todo el software corriendo físicamente dentro de la tablet que el robot lleva
montada. Sin servidores intermedios.

Estado: **operativo y validado contra el robot real**.

---

## 1. El requisito, y por qué condiciona todo el diseño

El requisito del proyecto es que el código que lee los datos del robot se
ejecute **en el propio robot**, accediendo a la información de forma interna.
Una integración que se conecta a un servidor externo para obtener los datos es
un *conector*, no un *agente*, y no necesita ejecutarse en el robot.

Esto descarta el patrón que usan el resto de integraciones de la flota (Keenon,
Allybot, Autoxing), que funcionan con **Edge SDK**: un proceso nuestro corre en
un servidor y habla con la nube del fabricante. Aquí se usa **Agent SDK**: el
Agent Core oficial de InOrbit, sin modificar, instalado dentro del robot.

La ventaja de fondo del Agent SDK es que no hay que escribir un adaptador por
cada modelo de robot: descubre por sí solo la posición, el láser, el mapa y la
batería siempre que estén publicados como topics ROS estándar.

## 2. El problema que hubo que resolver

El ordenador que gobierna el chasis del WDC está **aislado de red**: solo se
puede llegar a él por cable desde la tablet del propio robot, y usa un protocolo
propietario, no ROS. Tampoco sirve el acceso remoto de la nube del fabricante:
solo expone HTTP, con los puertos de ROS cerrados.

Es decir, no había ningún sitio donde instalar el Agent Core que tuviera acceso
al ROS real del robot.

**La solución** salió de analizar la app del fabricante: esa app publica un
servidor WebSocket **dentro de la propia tablet**, en el puerto 9015, con la
telemetría del robot en JSON y sin autenticación. Con eso, la tablet deja de ser
un obstáculo y pasa a ser el sitio donde montarlo todo.

```
Chasis (aislado)
   │  cable, protocolo propietario
   ▼
App del fabricante (en la tablet)
   │  WebSocket local :9015
   ▼
wdc_bridge_node.py  (en la misma tablet)
   │  topics ROS estándar
   ▼
InOrbit Agent Core  (en la misma tablet)
   │  MQTT saliente
   ▼
InOrbit Cloud
```

## 3. Qué hay montado dentro de la tablet

| Capa | Para qué |
|---|---|
| Termux | Terminal Linux real sobre Android, sin rootear el aparato |
| proot-distro + Ubuntu 20.04 | Un Ubuntu de verdad, para que el instalador oficial de InOrbit funcione sin modificarlo |
| ROS Noetic | Instalado con `apt` estándar. Soporte oficial en ARM |
| InOrbit Agent Core | Instalador oficial, sin ningún parche |
| `wdc_bridge_node.py` | Nuestro puente: lee el WebSocket local y publica los topics ROS |

La tablet es ARM de 64 bits (`arm64-v8a`), aunque la app del fabricante sea de
32. Usar Termux de 64 bits evita tener que compilar dependencias pesadas
(`numpy`, `opencv`), porque existen binarios ya preparados.

## 4. Funcionalidades

Todo lo siguiente está probado contra el robot real, no en simulación.

| Funcionalidad | Detalle |
|---|---|
| Telemetría | Posición, batería, láser y estado interno, cada 2 segundos |
| Mapa | Se pide al robot en vivo, con su resolución y origen reales |
| Estado operativo | Idle / Mission / Charging / Error, integrado en el panel estándar de InOrbit |
| Misiones | Cada acción queda registrada con su estado y progreso real por distancia |
| Acciones remotas | Parar, ir a cargar, y navegar a los puntos de reparto y al de origen |
| Vídeo | No disponible. Ver limitaciones |

Las coordenadas de los puntos de navegación no están inventadas ni medidas a
ojo: se leyeron de la propia base de datos de la app del fabricante, que es la
misma que usa su pantalla de reparto.

## 5. Puesta en marcha

### Aplicaciones necesarias en la tablet

Hacen falta tres apps, y **las tres tienen que venir del mismo origen** (las
versiones de F-Droid y de GitHub usan firmas distintas y no se pueden mezclar,
da error de instalación):

- Termux (variante `arm64-v8a`)
- Termux:Boot, para que todo arranque solo al encender
- Termux:API

Se descargan de las *releases* oficiales de GitHub del proyecto Termux. Conviene
verificar el `sha256` de cada APK contra el fichero de checksums que publican en
la misma release.

> Si se cambia de versión de Termux (por ejemplo de 32 a 64 bits), hay que
> **desinstalar antes**. Actualizar encima no sustituye los datos internos y el
> sistema sigue comportándose como la versión antigua.

### Instalación

Los scripts de `vpn_setup/` cubren el proceso:

| Script | Para qué |
|---|---|
| `termux_setup_inorbit.sh` | Prepara Ubuntu, ROS e instala el Agent Core |
| `agent_core_on_tablet.md` | El procedimiento explicado paso a paso |
| `start-deliverance.sh` | Arranque automático al encender (va en `~/.termux/boot/`) |
| `reboot_watchdog.sh` | Recuperación de último recurso (ver más abajo) |
| `setup_tailscale_raspberry.sh` | Acceso remoto a la red de la instalación |
| `test_termux_local_api.py` | Comprobar que la API local del robot responde |

El instalador de InOrbit **no está en el repo**: se descarga con la clave
privada de la cuenta, y por eso no se versiona. Se obtiene desde el panel de
InOrbit al dar de alta el robot.

## 6. Que siga funcionando sin que nadie lo vigile

Un despliegue que solo funciona mientras alguien mira no sirve. Hay tres capas
de recuperación, cada una cubriendo el fallo de la anterior:

1. **Bucles de reinicio.** Si `roscore`, el puente o el agente se paran, se
   relanzan solos. Cubre incluso que el propio agente de InOrbit se reinicie a
   sí mismo, algo que hace y que dejó el robot 38 horas desconectado antes de
   detectarse.
2. **Exención de batería de Android.** Termux y la app del fabricante quedan
   excluidas de la optimización de energía, para que el sistema no las cierre.
3. **Vigilante con reinicio.** Si Android llega a matar Termux entero, un job
   del propio sistema operativo (que sobrevive a eso) comprueba cada 15 minutos
   si los procesos siguen vivos y, si no, reinicia la tablet.

La cadena completa está probada de verdad: se mató el proceso de Termux a
propósito, el vigilante lo detectó y forzó el reinicio a los 12,8 minutos, y
todo volvió solo, con datos llegando a InOrbit en menos de 10 segundos.

## 7. Operación y resolución de problemas

**Ver y manejar la pantalla de la tablet en remoto.** Es la herramienta de
diagnóstico más útil, y evita tener que desplazarse hasta el robot:

```bash
# Activar ADB por red (no sobrevive a un reinicio, hay que repetirlo)
su -c 'setprop service.adb.tcp.port 5555'; su -c 'stop adbd'; su -c 'start adbd'

# Desde el ordenador
adb connect <ip-tablet>:5555
scrcpy                      # pantalla en vivo y control con ratón
```

**Problemas frecuentes:**

| Síntoma | Causa y solución |
|---|---|
| El robot no obedece una orden de ir a un punto | Tiene una tarea previa sin cerrar. Pulsar **Stop** y repetir |
| Sigue sin moverse, y en la tablet pone "Line controller busy" | Pulsar **Return Point** en la pantalla de la tablet |
| Acaba de cargar y no sale del cargador | **Stop** lo desacopla; después ya acepta destinos |
| La app del fabricante no responde ni se ve | Cerrarla del todo y reabrirla: `am force-stop com.sirui.wdc_robot` y luego `am start -n com.sirui.wdc_robot/.MainActivity`. Traerla al frente no basta |
| InOrbit muestra batería 0% y Error | Suele ser falso: son los valores que se publican mientras la API local está caída. Comprobar la batería real antes de alarmarse |

## 8. Limitaciones conocidas

- **Sin vídeo en directo.** El robot tiene cámara física (aparece en los
  registros de calibración del chasis), pero no expone la imagen: solo el
  resultado ya procesado de su sistema de visión. La app de la tablet ni
  siquiera pide permiso de cámara. Para teleoperación haría falta acceso al
  ordenador del chasis o montar una cámara aparte.
- **Los puntos C, D y E no son navegables.** Están fuera de la zona escaneada
  del mapa actual: no existe camino libre hasta ellos, y el robot ni siquiera
  se mueve al intentarlo (desde InOrbit y desde su propia app). Hay que volver
  a grabarlos con el mapa actual. A, B y el punto de origen funcionan bien.
- **Solo se registran las misiones lanzadas desde InOrbit.** Si se manda una
  tarea desde la pantalla de la tablet, el puente no se entera: el robot no
  informa de las tareas que le llegan por otros canales.
- **El robot necesita liberar la tarea anterior** antes de aceptar un destino
  nuevo. Se intentó automatizar el Stop previo, pero desestabilizaba la app del
  fabricante y se descartó. El enfoque correcto sería enviarlo solo cuando el
  robot rechace la orden.

## 9. Estructura del repositorio

```
wdc_robot_sdk/
├── src/wdc_bridge_node.py       El puente. Es la pieza central
├── cac/                          Configuración de InOrbit (acciones, misiones)
├── vpn_setup/                    Instalación, arranque y recuperación
├── deliverance_wdc_agent_app/    App Android propia (ver abajo)
└── CLAUDE.md                     Detalle técnico y registro de hallazgos
```

Los binarios de terceros (APKs de Termux, app y SDK del fabricante) **no se
versionan**: pesan cientos de megas y se obtienen de su origen oficial.

## 10. App propia de Deliverance (aparcada)

`deliverance_wdc_agent_app/` es una app Android que se conecta **directamente al
ordenador del chasis**, sin pasar por la app del fabricante, usando el SDK
oficial del propio fabricante. Compila y funciona; solo falta decidir y
programar a dónde envía los datos.

Se aparcó al priorizar la integración con InOrbit, con la idea de que la
telemetría hacia nuestra propia plataforma llegue después reutilizando el
conector que ya sincroniza InOrbit con la plataforma. Se retomará más adelante.

Para compilarla hacen falta las librerías del SDK del fabricante en
`app/libs/`, que tampoco se versionan por ser binarios propietarios.
