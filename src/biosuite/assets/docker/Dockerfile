# syntax=docker/dockerfile:1
FROM debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates git python3 python3-venv python3-dev build-essential libpq-dev \
    libxml2-dev libxslt1-dev zlib1g-dev libffi-dev libssl-dev util-linux && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1000 --user-group --home-dir /data --shell /bin/bash galaxy && mkdir /galaxy /data && chown galaxy:galaxy /galaxy /data
WORKDIR /galaxy
COPY --chmod=0444 build-config.json /tmp/build-config.yml
RUN --mount=type=secret,id=proxy_ca,mode=0444 --mount=type=cache,target=/data/.cache/pip,uid=1000,gid=1000 \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca GIT_SSL_CAINFO=/run/secrets/proxy_ca; fi; \
    runuser -u galaxy -- git clone --depth 1 --branch v26.1.2 https://github.com/galaxyproject/galaxy.git /galaxy && \
    test "$(runuser -u galaxy -- git rev-parse HEAD)" = 391641a4e121216de4764ffd12b8c666859460ea && \
    runuser -u galaxy -- git switch -c release_26.1 && \
    runuser -u galaxy -- env GALAXY_CONFIG_FILE=/tmp/build-config.yml GALAXY_INSTALL_PREBUILT_CLIENT=1 \
      GALAXY_WHEELS_INDEX_URL=https://pypi.org/simple sh scripts/common_startup.sh
COPY entrypoint.py /usr/local/bin/biosuite-entrypoint
ENTRYPOINT ["python3", "/usr/local/bin/biosuite-entrypoint"]
