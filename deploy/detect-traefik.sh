#!/bin/sh
# Detects the settings of an existing Traefik (running in Docker) and prints the
# lines to put in lotery's .env. Read-only: it changes nothing on the server.
# Usage: sh detect-traefik.sh   (as a user allowed to run docker, or with sudo)
set -u

T=$(docker ps --format '{{.Names}} {{.Image}}' | awk 'tolower($2) ~ /traefik/ {print $1; exit}')
if [ -z "$T" ]; then
  echo "No running Traefik container found (docker ps)."; exit 1
fi
echo "Traefik container : $T ($(docker inspect -f '{{.Config.Image}}' "$T"))"

# 1. Values actually used by the sites already behind Traefik (most reliable).
LABELS=$(docker ps -q | xargs docker inspect -f '{{range $k, $v := .Config.Labels}}{{$k}}={{$v}}{{"\n"}}{{end}}' 2>/dev/null)
EP=$(printf '%s\n' "$LABELS" | sed -n 's/^traefik\.http\.routers\.[^.]*\.entrypoints=//p' | tr ',' '\n' | sort | uniq -c | sort -rn | awk '{print $2}' | grep -iv '^web$\|^http$' | head -1)
CR=$(printf '%s\n' "$LABELS" | sed -n 's/^traefik\.http\.routers\.[^.]*\.tls\.certresolver=//p' | sort | uniq -c | sort -rn | awk 'NR==1{print $2}')
NET=$(printf '%s\n' "$LABELS" | sed -n 's/^traefik\.docker\.network=//p' | sort | uniq -c | sort -rn | awk 'NR==1{print $2}')

# 2. Fallback: Traefik's own command line (static configuration).
ARGS=$(docker inspect -f '{{range .Config.Cmd}}{{.}}{{"\n"}}{{end}}{{range .Args}}{{.}}{{"\n"}}{{end}}' "$T")
[ -z "$EP" ] && EP=$(printf '%s\n' "$ARGS" | sed -n 's/^--entrypoints\.\([^.]*\)\.address=.*:443$/\1/Ip' | head -1)
[ -z "$CR" ] && CR=$(printf '%s\n' "$ARGS" | sed -n 's/^--certificatesresolvers\.\([^.]*\)\..*/\1/Ip' | head -1)

# 3. Network: the one given in labels, else the Traefik network shared with the
#    most other containers (that is where the sites live).
if [ -z "$NET" ]; then
  best=0
  for n in $(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$T"); do
    case "$n" in bridge|host|none) continue ;; esac
    c=$(docker network inspect -f '{{range $id, $x := .Containers}}{{$x.Name}}{{"\n"}}{{end}}' "$n" | grep -cv "^$T\$\|^\$")
    echo "  network $n: $c other container(s)"
    if [ "$c" -gt "$best" ] || [ -z "$NET" ]; then best=$c; NET=$n; fi
  done
fi
SUBNET=""
[ -n "$NET" ] && SUBNET=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$NET" 2>/dev/null | tr ' ' '\n' | grep -v ':' | head -1)

if [ -z "$CR" ]; then
  echo "WARNING: no certificate resolver found (Traefik may use a static config file)."
  echo "Mounted files of $T:"; docker inspect -f '{{range .Mounts}}  {{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' "$T"
fi

echo
echo "# ---- lines for /opt/lotery/.env ----"
echo "TRAEFIK_NETWORK=${NET:-??? (not found)}"
echo "TRAEFIK_ENTRYPOINT=${EP:-websecure}"
echo "TRAEFIK_CERTRESOLVER=${CR:-??? (not found)}"
echo "TRAEFIK_SUBNET=${SUBNET:-??? (not found)}"
