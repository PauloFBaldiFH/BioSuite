#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" == 0 ]] || { echo 'Administrador necessário.' >&2; exit 1; }
if command -v cloudflared >/dev/null; then cloudflared --version; exit 0; fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o "$work/key.gpg"
gpg --show-keys "$work/key.gpg" >/dev/null
install -d -m 755 /etc/apt/keyrings
install -m 644 "$work/key.gpg" /etc/apt/keyrings/biosuite-cloudflare.gpg
[[ ! -e /etc/apt/sources.list.d/biosuite-cloudflared.list ]] || { echo 'A fonte já existe; revise-a antes de continuar.' >&2; exit 1; }
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/biosuite-cloudflare.gpg] https://pkg.cloudflare.com/cloudflared any main' >/etc/apt/sources.list.d/biosuite-cloudflared.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y cloudflared
cloudflared --version
