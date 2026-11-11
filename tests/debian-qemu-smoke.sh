#!/usr/bin/env bash
# Executar apenas no container Debian descartável criado pelo workflow.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${BIOSUITE_DEBIAN_VM_SMOKE:-}" == 1 && "$EUID" == 0 ]] || {
    echo 'Harness reservado ao container descartável da CI.' >&2; exit 2;
}
release=${1:-}
case "$release" in 12) codename=bookworm ;; 13) codename=trixie ;; *) exit 2 ;; esac
work=$(mktemp -d /tmp/biosuite-qemu-XXXXXXXX)
vm_pid=''
cleanup() {
    code=$?
    trap - EXIT
    if [[ "$code" != 0 && -f "$work/serial.log" ]]; then
        python3 - "$work/serial.log" <<'PY'
from collections import deque
from pathlib import Path
import sys
with Path(sys.argv[1]).open(errors='replace') as stream:
    text = ''.join(deque(stream, maxlen=35))[-8000:]
print('::error title=Boot Debian QEMU::' + text.replace('%','%25').replace('\r','%0D').replace('\n','%0A'))
PY
    fi
    if [[ -n "$vm_pid" ]]; then
        kill "$vm_pid" 2>/dev/null || true
        wait "$vm_pid" 2>/dev/null || true
    fi
    rm -rf -- "$work"
    exit "$code"
}
trap cleanup EXIT

# O host QEMU usa somente pacotes Debian; não depende dos mirrors Ubuntu do runner.
apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o APT::Update::Error-Mode=any update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    qemu-system-x86 qemu-utils seabios cloud-image-utils openssh-client curl ca-certificates python3

base="https://cloud.debian.org/images/cloud/$codename/latest"
curl --fail --silent --show-error --location --retry 3 --max-time 120 "$base/SHA512SUMS" -o "$work/SHA512SUMS"
filename=$(python3 - "$work" "$release" <<'PY'
from pathlib import Path
import re,sys
work=Path(sys.argv[1]);release=sys.argv[2]
entries=[]
for line in (work/'SHA512SUMS').read_text().splitlines():
    parts=line.split()
    if len(parts)!=2 or not re.fullmatch(r'[0-9a-fA-F]{128}',parts[0]):continue
    name=parts[1].removeprefix('*').removeprefix('./')
    if re.fullmatch(rf'debian-{release}-generic-amd64(?:-\d{{8}}-\d+)?\.qcow2',name):entries.append((name,parts[0]))
if not entries:raise SystemExit('Imagem generic amd64 ausente no checksum oficial.')
name,checksum=sorted(entries)[-1]
(work/'image.sha512').write_text(checksum+'  '+str(work/'image.qcow2')+'\n')
print(name)
PY
)
curl --fail --silent --show-error --location --retry 3 --max-time 600 "$base/$filename" -o "$work/image.qcow2"
sha512sum -c "$work/image.sha512"
echo "::notice title=Debian QEMU::Imagem oficial $filename conferida por SHA-512."
qemu-img resize "$work/image.qcow2" +50G
ssh-keygen -q -t ed25519 -N '' -f "$work/client"
ssh-keygen -q -t ed25519 -N '' -f "$work/server"
python3 - "$work" "$release" <<'PY'
from pathlib import Path
import json,sys
work=Path(sys.argv[1])
config={'disable_root':False,'ssh_pwauth':False,
        'users':[{'name':'root','ssh_authorized_keys':[(work/'client.pub').read_text().strip()]}],
        'ssh_keys':{'ed25519_private':(work/'server').read_text(),'ed25519_public':(work/'server.pub').read_text().strip()},
        'write_files':[{'path':'/etc/biosuite-ci-disposable','permissions':'0600','content':'CI descartável BioSuite\n'}]}
(work/'user-data').write_text('#cloud-config\n'+json.dumps(config))
(work/'meta-data').write_text('instance-id: biosuite-debian-'+sys.argv[2]+'\nlocal-hostname: biosuite-ci\n')
(work/'known_hosts').write_text('[127.0.0.1]:2222 '+(work/'server.pub').read_text())
for name in ('user-data','client','server','known_hosts'):(work/name).chmod(0o600)
PY
cloud-localds "$work/seed.img" "$work/user-data" "$work/meta-data"
install -d -m 700 /root/.ssh
cat > /root/.ssh/config <<EOF
Host debian
    HostName 127.0.0.1
    Port 2222
    User root
    IdentityFile $work/client
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    UserKnownHostsFile $work/known_hosts
    BatchMode yes
    ConnectTimeout 5
EOF
chmod 600 /root/.ssh/config
if [[ -c /dev/kvm ]]; then
    acceleration=(-accel kvm -cpu host)
else
    acceleration=(-accel tcg,thread=multi -cpu max)
fi
qemu-system-x86_64 "${acceleration[@]}" -m 4096 -smp 2 \
    -drive "file=$work/image.qcow2,format=qcow2,if=virtio" \
    -drive "file=$work/seed.img,format=raw,if=virtio" \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22 -device virtio-net-pci,netdev=net0 \
    -object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0 \
    -display none -monitor none -serial "file:$work/serial.log" &
vm_pid=$!
ready=0
for attempt in $(seq 1 120); do
    kill -0 "$vm_pid" || { echo 'QEMU terminou antes do boot.' >&2; exit 1; }
    if ssh debian 'test -f /var/lib/cloud/instance/boot-finished && test -f /etc/biosuite-ci-disposable' 2>/dev/null; then
        ready=1; break
    fi
    sleep 3
done
[[ "$ready" == 1 ]] || { echo 'Guest não concluiu cloud-init/SSH.' >&2; exit 1; }
ssh debian ". /etc/os-release; test \"\$ID:\$VERSION_ID\" = debian:$release; test \"\$(cat /proc/1/comm)\" = systemd; mkdir -p /src"
tar -C /src --exclude=.git --exclude=.venv --exclude=node_modules --exclude=__pycache__ --exclude=.wrangler -cf - . | ssh debian 'tar -C /src -xf -'
cd /src
echo "::notice title=Debian QEMU::Guest Debian $release pronto com systemd como PID 1."
python3 tests/debian-vm-smoke.py
