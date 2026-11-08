#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" == 0 ]] || { echo 'É necessário administrador.' >&2; exit 1; }
if command -v docker >/dev/null; then
    docker compose version && exit 0
    echo 'Docker já existe e não será substituído. Instale o plugin Compose compatível com essa instalação.' >&2
    exit 1
fi
[[ "$(cat /proc/1/comm)" == systemd ]] || { echo 'Ative systemd antes de preparar Docker.' >&2; exit 1; }
. /etc/os-release
case "$ID:$VERSION_ID" in ubuntu:22.04|ubuntu:24.04|debian:12|debian:13) ;; *) exit 1 ;; esac
[[ ! -e /etc/apt/sources.list.d/biosuite-docker.sources ]] || { echo 'A fonte APT já existe; revise a configuração antes de continuar.' >&2; exit 1; }
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o "$work/key.asc"
fingerprint=$(gpg --show-keys --with-colons "$work/key.asc" | awk -F: '$1=="fpr" {print $10; exit}')
[[ "$fingerprint" == 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]] || { echo 'A chave Docker não corresponde ao fingerprint esperado.' >&2; exit 1; }
install -d -m 755 /etc/apt/keyrings
install -m 644 "$work/key.asc" /etc/apt/keyrings/biosuite-docker.asc
cat >/etc/apt/sources.list.d/biosuite-docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $VERSION_CODENAME
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/biosuite-docker.asc
EOF
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
