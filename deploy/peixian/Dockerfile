FROM ghcr.io/anomalyco/opencode:1.18.30@sha256:412b37a894bb937a0d5d6a1860789b9fd7d34a109334bec98a3f6ecf812bb442

USER root
RUN apk add --no-cache bash ca-certificates git python3 \
    && apk add --no-cache --virtual .peixian-build-deps nodejs npm \
    && addgroup -g 10001 opencode \
    && adduser -D -u 10001 -G opencode -h /home/opencode opencode \
    && mkdir -p /workspace /opt/peixian/config-deps \
    && chown 10001:10001 /home/opencode /workspace

COPY config/package.json config/package-lock.json /opt/peixian/config-deps/
RUN npm ci --prefix /opt/peixian/config-deps --ignore-scripts --omit=dev --no-audit --no-fund \
    && apk del .peixian-build-deps \
    && rm -rf /root/.npm \
    && test "$(opencode --version)" = "1.18.30"

COPY config/opencode.json /opt/peixian/config/opencode.json
COPY entrypoint.sh healthcheck.py tcp-forward.py /opt/peixian/
RUN chmod 0555 /opt/peixian/entrypoint.sh /opt/peixian/healthcheck.py \
    && chmod -R a+rX /opt/peixian/config /opt/peixian/config-deps

ENV HOME=/home/opencode \
    XDG_CONFIG_HOME=/home/opencode/.config \
    XDG_DATA_HOME=/home/opencode/.local/share \
    XDG_CACHE_HOME=/home/opencode/.cache \
    XDG_STATE_HOME=/home/opencode/.local/state \
    OPENCODE_CONFIG_DIR=/home/opencode/.config/opencode \
    OPENCODE_PASSWORD_FILE=/run/secrets/opencode-password \
    OPENCODE_DISABLE_PROJECT_CONFIG=true \
    OPENCODE_DISABLE_MODELS_FETCH=true \
    OPENCODE_DISABLE_DEFAULT_PLUGINS=true \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    OPENCODE_DISABLE_EXTERNAL_SKILLS=true \
    OPENCODE_DISABLE_LSP_DOWNLOAD=true \
    OPENCODE_PURE=true \
    OPENCODE_AUTO_SHARE=false \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace
USER 10001:10001
EXPOSE 4096
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
    CMD ["python3", "/opt/peixian/healthcheck.py"]
ENTRYPOINT ["/opt/peixian/entrypoint.sh"]
CMD ["serve", "--hostname", "0.0.0.0", "--port", "4096"]
