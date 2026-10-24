#!/bin/sh
# Entrypoint for the litegm container image.
#
# Compose bind-mounts the host's ./data and ./.config over /app/data and
# /app/.config. Those mounts carry the host's ownership, so a directory that
# was created by root (for example by an earlier `docker run`, or by docker
# compose creating a missing bind source) makes SQLite fail as UID 10001 with
# "unable to open database file". When the container is allowed to start as
# root, take ownership of the writable paths, then drop to 10001 and exec the
# command. Without root (compose `user:` override) nothing is changed: the
# host must then pre-create ./data with matching ownership.

set -e

if [ "$(id -u)" = "0" ]; then
  for dir in /app/data /app/.pixi-cache /app/.config; do
    [ -d "$dir" ] && chown -R 10001:10001 "$dir" 2>/dev/null || true
  done
  exec setpriv --reuid=10001 --regid=10001 --clear-groups -- "$@"
fi

exec "$@"
