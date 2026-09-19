# Contexto para retomar en terminal local (claude CLI)

## Que es esto
App GTK4/libadwaita para comparar niveles de escalado de pantalla en
GNOME/Wayland en duelos directos (bracket de eliminacion, misma
mecanica que un artefacto web previo llamado "Prueba de escalado"),
pero aplicando el escalado de verdad via DBus contra
`org.gnome.Mutter.DisplayConfig` en lugar de un zoom CSS simulado.

## Por que se armo en dos partes
Esta sesion corrio en la nube (Claude Code / Cowork) con un puente
`remote-devices` a esta PC ("mars", Arch Linux). Ese puente da una
terminal (`device_bash`) que vive en una **VM aislada de Cowork
dentro del equipo**, sin `DBUS_SESSION_BUS_ADDRESS` ni
`XDG_SESSION_TYPE` -- o sea, sin acceso al bus de sesion real de
GNOME/Mutter. Por eso todo el codigo se escribio y se validaron los
tests de logica pura ahi, pero **nunca se probo contra un Mutter
real**. Para eso hace falta correr esto en una terminal normal de tu
sesion grafica (la que tiene el DBUS_SESSION_BUS_ADDRESS de verdad).

## Estado actual (al momento de escribir esto)
- `scale_duel.py`: app completa. Sin correr nunca contra GTK4 real
  (el entorno de desarrollo no tenia los typelibs de Gtk4/Adwaita
  instalados, solo PyGObject base).
- `test_scale_duel.py`: 8 tests de logica pura (bracket de
  eliminacion + armado de escalas candidatas), con un stub manual de
  `gi`/`Gtk`/`Adw`/`Gio`/`GLib` para poder importar el modulo sin
  GTK instalado. Los 8 pasan.
- README.md: documentacion de uso y limitaciones conocidas.
- Git: recien inicializado, sin commits todavia (o con el primer
  commit si esto se corrio despues del `git commit` de mas abajo).

## Lo que falta probar (con tu sesion grafica real)
1. `sudo pacman -S python-gobject gtk4 libadwaita` si falta algo.
2. `python3 scale_duel.py` y ver si:
   - Conecta bien a DBus y lista tus monitores reales.
   - `GetCurrentState` devuelve el formato de tupla que el codigo
     espera (la firma de Mutter puede variar levemente entre
     versiones -- si explota al parsear, mandame el traceback).
   - `ApplyMonitorsConfig` en modo TEST (valor 2) realmente cambia
     la escala en pantalla y se revierte solo si no confirmas.
   - El modo PERSISTENT (valor 1) deja el cambio guardado de verdad
     (sobrevive a `gnome-shell --replace` o a un logout/login).
3. Revisar si con mas de un monitor conectado el layout del resto no
   se rompe (el codigo intenta preservar x/y/transform/primary de
   cada uno, pero no se probo con multi-monitor).
4. UX: el flujo de "elegir A o B" deja aplicado el elegido y sigue
   con el siguiente duelo -- confirmar que se sienta bien en la
   practica (podria valer la pena un breve delay o un toast de "se
   aplico" mas visible).

## Como seguir
Abri una terminal en tu sesion de GNOME, `cd
/home/eibu/git/gnome-scale-duel`, y arrancá ahi una sesion de
`claude` (CLI local) pegandole este archivo como contexto, o
simplemente decile "segui con gnome-scale-duel, lee CONTEXT.md".
Correr la app, mandarme (a esa sesion local) los errores/tracebacks
que salgan, e iterar desde ahi -- esa sesion si va a poder correr y
debuguear en caliente porque tiene tu bus de sesion real.
