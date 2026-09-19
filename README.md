# gnome-scale-duel

App GTK4 / libadwaita para comparar dos (o mas) niveles de escalado
de un monitor en GNOME/Wayland, en duelos directos, hasta encontrar
el que mejor se ve. A diferencia del artefacto web original (que
simulaba el escalado con `transform: scale()` en CSS), esta app
aplica el escalado **de verdad** en tu pantalla llamando a la interfaz
DBus real de Mutter: `org.gnome.Mutter.DisplayConfig`.

## Como funciona

1. Lee los monitores conectados y sus modos via `GetCurrentState`.
2. Arma una lista de escalas candidatas (pasos de 0.25 dentro del
   rango que soporta el modo actual del monitor).
3. Arma un bracket de eliminacion directa con las escalas que
   marques.
4. Para cada duelo, aplica el escalado en modo `ApplyMode.TEST`
   (temporal: si no confirmas, Mutter lo revierte solo).
5. Al terminar el bracket, si elegis "dejar aplicado el ganador",
   lo confirma en modo `ApplyMode.PERSISTENT`; si no, restaura el
   escalado que tenias antes de abrir la app.

## Requisitos

```bash
sudo pacman -S python-gobject gtk4 libadwaita   # Arch
```

La app **tiene que correr dentro de tu sesion grafica real de GNOME**
(necesita `DBUS_SESSION_BUS_ADDRESS` apuntando al bus de sesion donde
vive Mutter). No funciona desde un contenedor, una VM headless, o una
sesion sin GNOME Shell activo.

## Uso

```bash
python3 scale_duel.py
```

## Tests

Los tests cubren la logica del bracket de eliminacion y el armado de
escalas candidatas -- son puros (sin GTK ni DBus), asi que corren en
cualquier lado:

```bash
python3 -m pytest test_scale_duel.py -v
# o sin pytest instalado:
python3 -c "
import test_scale_duel as t
for f in [x for x in dir(t) if x.startswith('test_')]:
    getattr(t, f)()
    print('PASS', f)
"
```

Lo que **no** esta cubierto por tests automaticos (requiere tu sesion
grafica real): la conexion DBus a Mutter, `GetCurrentState`,
`ApplyMonitorsConfig` en modo TEST/PERSISTENT, y el flujo completo de
la UI. Eso hay que probarlo a mano corriendo la app.

## Estado / limitaciones conocidas

- Probado solo en el codigo (sintaxis + tests de logica pura). Nunca
  se corrio contra un Mutter real todavia.
- Asume que Mutter revierte solo un TEST no confirmado (comportamiento
  documentado de la interfaz, pero no verificado en este equipo).
- Solo cambia el `scale` del monitor elegido; si tenes mas de un
  monitor, el resto queda con su layout actual sin tocar.
- No maneja `transform` (rotacion) mas alla de preservar el actual.
