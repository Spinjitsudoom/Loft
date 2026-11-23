#!/bin/sh
# Started as root (the usual way, and how ZimaOS and CasaOS start apps): make /data Loft's, then run
# Loft as PUID:PGID (1000:1000 unless set). App platforms create the folder mounted at /data as
# root, where Loft couldn't otherwise save its library. Your books in /books are never touched.
# Started as another user already (compose `user:`, podman --userns=keep-id): just run Loft.
set -e
if [ "$(id -u)" = 0 ]; then
  uid="${PUID:-1000}"
  gid="${PGID:-1000}"
  case "$uid$gid" in *[!0-9]*) echo "PUID and PGID must be numbers" >&2; exit 1 ;; esac
  mkdir -p /data
  # Only when it isn't theirs yet: a big library has a lot of covers and page images to go through.
  if [ "$(stat -c %u:%g /data)" != "$uid:$gid" ]; then
    echo "Making /data belong to $uid:$gid"
    chown -R "$uid:$gid" /data
  fi
  exec setpriv --reuid="$uid" --regid="$gid" --clear-groups -- "$@"
fi
exec "$@"
