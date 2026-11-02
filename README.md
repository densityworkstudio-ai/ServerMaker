# ServerMaker

ServerMaker is a Python dashboard and supervised Paper server
configuration for **DensitySMP** (Minecraft 1.21.11, Paper build 132).

## Install and run

This environment already includes the OpenJDK 21 JDK. `install.sh` verifies the
runtime/compiler, installs the Python dependency, fetches Paper only from the
official Paper API, and validates its published SHA-256 checksum. It preserves
an existing Paper jar, server directory, plugins, and worlds.

```bash
./install.sh
./start.sh
```

The dashboard listens on port 8080. Open the forwarded port in your workspace;
no login is required. Anyone who can reach the dashboard can control the server
and edit its files, so only expose it on a trusted network. Set `SERVERMAKER_HOST`
or `SERVERMAKER_PORT` before starting to change the bind address or port.

`./stop.sh` gracefully saves and stops the server before shutting down the
panel. The server-specific `servers/DensitySMP/start.sh` and `stop.sh` delegate
to the same panel, avoiding a second unmanaged Java process. Paper console output
is also saved to `data/logs/console.log`; Paper's own logs remain in the server
directory. Backups are stored in `data/backups/`.

The dashboard includes process controls, live console, server status and
resource metrics, player status, a constrained server-file editor, plugin JAR
uploads, world backups, and server settings. The supervisor restarts a crashed
server after a delay; it never removes world files. The Java heap is initialized
to the largest whole-GiB size that leaves 2 GiB available for the host, capped
at 8 GiB. You can lower it in the dashboard.

## Public access and uptime

The panel tests the external Minecraft status endpoint before showing a join
address. An outbound public IP is not treated as an inbound address. This
workspace has no systemd process manager and runs inside an ephemeral Codespace
container. The `deployment/servermaker.service` unit is provided for a host with
systemd, but it is not active here. Codespaces can sleep or be stopped, so this
environment cannot provide guaranteed 24/7 hosting. A Playit tunnel also needs
an authorized Playit account/agent setup; no unauthenticated tunnel is claimed.