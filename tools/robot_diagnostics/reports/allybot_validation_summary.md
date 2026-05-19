# Allybot Read-Only Validation Summary

This report is sanitized for team review. It does not include API keys, passwords, tokens, real IP addresses, WebSocket URLs, full manufacturer fleet IDs, or raw robot outputs.

| robot_id | proveedor | fuente fabricante | InOrbit | mapa | pose | datos recibidos | estado validacion | observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| allybot-cleaner-1 | Allybot | OK | OK | DELIVERANCE | OK | bateria, agua limpia/sucia, work_status, ws_connected, key-values | full_flow_ok | Validado en modo read-only, sin acciones de control. |
| allybot-cleaner-2 | Allybot | parcial | no visible/no registrado con ese robot_id | get_active_map falla con OPERATION FAILURE 513 | no vista en ventana de prueba | estado y bateria desde Allybot | source_partial | Pendiente confirmar si debe existir en InOrbit y si tiene mapa activo valido. |

## Que No Se Ha Probado Por Seguridad

- `start_task`
- `pause_task`
- `resume_task`
- `stop_task`
- navegacion
- modificaciones de mapas/locations
- `inorbit apply`
- `inorbit delete`

## Proximos Pasos

- Confirmar `allybot-cleaner-2` con el jefe/equipo.
- Confirmar si `allybot-cleaner-2` debe darse de alta o ser visible en InOrbit.
- Pedir credenciales y mapeos para Keenon.
- Pedir credenciales y mapeos para AutoXing.
- Implementar checks read-only con fixtures antes de llamar APIs reales.
