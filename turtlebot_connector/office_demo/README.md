# Oficina Demo - TurtleBot3 Gazebo, Nav2 & InOrbit

Este directorio contiene los archivos necesarios para simular el TurtleBot3 en un mundo de Gazebo basado en las dimensiones reales de la oficina, permitiendo que la navegación y las coordenadas en InOrbit tengan total coherencia métrica.

## Parámetros de Escala y Coordenadas
Para conseguir que Gazebo, Nav2 e InOrbit compartan una escala métrica coherente basada en el plano de referencia de la oficina (**Floorplan0**):
- **Superficie útil del PDF:** S = 55.50 m²
- **Resolución ajustada:** `0.0104908 m/px`
- **Dimensiones del plano/mundo:** `8.6444 m` (ancho) x `6.4203 m` (alto)
- **Origen de Nav2 (centrado):** `[-4.3222, -3.2102, 0.0]`
- **Punto de Spawn / Home del Robot:** `x = -2.0`, `y = -0.5` (zona libre de obstáculos en la oficina)

---

## Archivos del Demo

1. **`maps/office_map.yaml`**: Archivo de metadatos del mapa Nav2 actualizado con la resolución de `0.0104908` y el origen en `[-4.3222, -3.2102, 0.0]`.
2. **`maps/office_map.pgm`**: Imagen del mapa en formato PGM escalada y procesada a partir del plano real de la oficina.
3. **`worlds/office_world.world`**: Mundo de Gazebo con el suelo (`8.6444 x 6.4203 m`) y las paredes (exteriores e interiores) perfectamente alineadas con las dimensiones reales a escala.
4. **`config/fleet.ros2.office.local.yaml`**: Archivo de configuración de flota local (en el directorio `/config/` del host) que define las coordenadas reales de spawn y waypoints de navegación libres de obstáculos en el nuevo mapa de la oficina.

---

## Instrucciones Paso a Paso para Iniciar la Demo

Todas las instrucciones se ejecutan **dentro del contenedor Docker** `turtlebot-connector-ros2-gazebo` en la ruta `/workspace/turtlebot_connector`.

Si aún no has iniciado el contenedor en tu host:
```bash
docker start -ai turtlebot-connector-ros2-gazebo
```

### Paso 1: Lanzar el Servidor de Gazebo con el Mundo de la Oficina
En una **Terminal 1** dentro del contenedor:
```bash
# Definir variables de entorno para usar el mundo y la pose de spawn correctos
export WORLD_FILE="/workspace/turtlebot_connector/office_demo/worlds/office_world.world"
export TB3_X_POSE="-2.0"
export TB3_Y_POSE="-0.5"

# Configurar salidas gráficas para simular la cámara usando renderizado por software en VNC
export DISPLAY=:1
export XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1

# Ejecutar el script launcher de simulación
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_sim.sh
```

### Paso 2: (Opcional) Abrir el Cliente de Gazebo (VNC Desktop)
Si estás accediendo a través del escritorio VNC en `http://localhost:6080` y deseas confirmación visual del modelo en Gazebo, ejecuta esto en una **Terminal 2** dentro del contenedor (con el usuario `ubuntu`):
```bash
su - ubuntu
cd /workspace/turtlebot_connector
source /opt/ros/humble/setup.bash
export DISPLAY=:1
export XAUTHORITY=/home/ubuntu/.Xauthority
export LIBGL_ALWAYS_SOFTWARE=1
gzclient
```

### Paso 3: Iniciar Nav2 con el Mapa Escalado de la Oficina
En una **Terminal 3** dentro del contenedor:
```bash
# Lanzar Nav2 especificando el archivo yaml de nuestro mapa personalizado
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/launch_nav2.sh /workspace/turtlebot_connector/office_demo/maps/office_map.yaml
```

Una vez que Nav2 esté activo y escuchando, en otra terminal o utilizando el script auxiliar podemos inicializar la estimación de AMCL en el punto de spawn:
```bash
export INITIAL_X="-2.0"
export INITIAL_Y="-0.5"
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/set_initial_pose.sh
```
*(También se puede orientar manualmente el robot con el botón `2D Pose Estimate` de RViz en el escritorio VNC de la misma forma).*

### Paso 4: Ejecutar el Conector InOrbit
En una **Terminal 4** dentro del contenedor:
```bash
# Cargar el entorno e iniciar el conector con el archivo de flota específico de la oficina
/workspace/turtlebot_connector/docker/ros2_gazebo/scripts/run_connector_ros2.sh config/fleet.ros2.office.local.yaml
```

---

## Validación del Funcionamiento

### 1. Comprobar que el mundo de Gazebo responde al nombre correcto
Ejecuta esto para listar los tópicos de Gazebo y verificar que se publican bajo el espacio de nombres `office_world`:
```bash
gz topic -l
```
*(Deberías ver tópicos como `/gazebo/office_world/pose/info` y `/gazebo/office_world/world_stats`).*

### 2. Comprobar estadísticas de la simulación
Para monitorizar el estado de la física del mundo en tiempo real:
```bash
gz topic -e /gazebo/office_world/world_stats
```

### 3. Verificar estado de los elementos/modelos cargados
Para obtener el detalle geométrico o la pose del suelo o de las paredes exteriores:
```bash
gz model -w office_world -m office_floor -i
gz model -w office_world -m wall_top -p
```

---

## Modelado Especial de Obstáculos y Puertas Dinámicas

Para lograr la máxima coherencia entre el mapa visual de Nav2 y la física de Gazebo, hemos incorporado elementos clave del plano real:

### 1. Las Estanterías (Bookshelves)
* En el plano real (zona izquierda) hay estanterías dibujadas en cuadrícula.
* Físicamente en Gazebo se representan mediante el modelo `shelves_left` de dimensiones `0.50m x 3.60m x 1.50m` de color gris metálico oscuro. Esto permite que el robot colisione y detecte con su sensor LiDAR la presencia de estas estanterías tal y como están dibujadas.

### 2. La Puerta Interior Dinámica (Open / Closed State)
El paso entre la habitación superior izquierda y la habitación superior derecha está controlado por un marco de puerta de `0.90m`.
* **Modelo en Gazebo:** `door_internal` de dimensiones `0.05m x 0.90m x 2.00m` de color madera.
* **Simulación de Puerta Cerrada (por defecto):** El modelo está presente físicamente. Si mandas al robot a la habitación contigua (por ejemplo, a `charger`), el sensor LiDAR detectará que la puerta está cerrada (como una pared) y Nav2 abortará o planificará una ruta alternativa si existiese.
* **Simulación de Puerta Abierta:** Puedes abrir la puerta al instante de dos maneras:
  1. **Comentando el bloque XML** `<model name="door_internal">` en `office_demo/worlds/office_world.world`.
  2. **Girándola / abriéndola** en el propio XML cambiando la orientación a abierta (girada 90 grados):
     ```xml
     <pose>-0.5049 0.96 1.00 0 0 1.5708</pose>
     ```
  Al abrir la puerta, el sensor LiDAR detectará el paso libre y Nav2 permitirá al robot cruzar fluidamente entre ambas salas.

