# Build from the repository root: docker build -f deploy/peixian/Managed.Dockerfile .
FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS build
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git python3 build-essential unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY package.json bun.lock ./
COPY patches/ ./patches/
# Workspace manifests and local tarballs are the dependency-layer inputs.
COPY packages/app/package.json packages/app/
COPY packages/cli/package.json packages/cli/
COPY packages/client/package.json packages/client/
COPY packages/codemode/package.json packages/codemode/
COPY packages/console/app/package.json packages/console/app/
COPY packages/console/core/package.json packages/console/core/
COPY packages/console/function/package.json packages/console/function/
COPY packages/console/mail/package.json packages/console/mail/
COPY packages/console/resource/package.json packages/console/resource/
COPY packages/console/support/package.json packages/console/support/
COPY packages/core/package.json packages/core/
COPY packages/desktop/package.json packages/desktop/
COPY packages/effect-drizzle-sqlite/package.json packages/effect-drizzle-sqlite/
COPY packages/effect-sqlite-node/package.json packages/effect-sqlite-node/
COPY packages/enterprise/package.json packages/enterprise/
COPY packages/function/package.json packages/function/
COPY packages/http-recorder/package.json packages/http-recorder/
COPY packages/httpapi-codegen/package.json packages/httpapi-codegen/
COPY packages/llm/package.json packages/llm/
COPY packages/opencode/package.json packages/opencode/
COPY packages/peixian-console/package.json packages/peixian-console/
COPY packages/plugin/package.json packages/plugin/
COPY packages/protocol/package.json packages/protocol/
COPY packages/schema/package.json packages/schema/
COPY packages/script/package.json packages/script/
COPY packages/sdk-next/package.json packages/sdk-next/
COPY packages/sdk/js/package.json packages/sdk/js/
COPY packages/server/package.json packages/server/
COPY packages/session-ui/package.json packages/session-ui/
COPY packages/slack/package.json packages/slack/
COPY packages/stats/app/package.json packages/stats/app/
COPY packages/stats/core/package.json packages/stats/core/
COPY packages/stats/server/package.json packages/stats/server/
COPY packages/storybook/package.json packages/storybook/
COPY packages/tui/package.json packages/tui/
COPY packages/ui/package.json packages/ui/
COPY packages/web/package.json packages/web/
COPY packages/app/vendor/opencode-ai-client-1.17.13-v2.tgz packages/app/vendor/
ENV HUSKY=0 OPENCODE_VERSION=1.18.30 OPENCODE_CHANNEL=latest
RUN bun install --frozen-lockfile --ignore-scripts
COPY packages/ ./packages/
COPY .github/TEAM_MEMBERS ./.github/TEAM_MEMBERS
RUN bun run --cwd packages/core fix-node-pty
WORKDIR /src/packages/opencode
ENV MODELS_DEV_API_JSON=/src/packages/opencode/test/tool/fixtures/models-api.json
RUN bun run script/build.ts --single --skip-install --skip-embed-web-ui \
    && test "$(./dist/opencode-linux-x64/bin/opencode --version)" = "1.18.30"

FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git python3 ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 opencode && useradd -u 10001 -g 10001 -d /home/opencode -m opencode \
    && mkdir -p /workspace /files /managed /opt/peixian \
    && chown 10001:10001 /workspace /files /home/opencode
COPY --from=build /src/packages/opencode/dist/opencode-linux-x64/bin/opencode /usr/local/bin/opencode
COPY deploy/peixian/managed-entrypoint.sh /opt/peixian/managed-entrypoint.sh
RUN chmod 0555 /opt/peixian/managed-entrypoint.sh
ENV HOME=/home/opencode \
    XDG_CONFIG_HOME=/home/opencode/.config \
    XDG_DATA_HOME=/home/opencode/.local/share \
    XDG_CACHE_HOME=/home/opencode/.cache \
    XDG_STATE_HOME=/home/opencode/.local/state \
    PEIXIAN_MANAGED_ROOT=/managed \
    OPENCODE_DISABLE_PROJECT_CONFIG=true \
    OPENCODE_DISABLE_MODELS_FETCH=true \
    OPENCODE_DISABLE_DEFAULT_PLUGINS=true \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    OPENCODE_DISABLE_EXTERNAL_SKILLS=true \
    OPENCODE_DISABLE_LSP_DOWNLOAD=true \
    OPENCODE_PURE=true \
    OPENCODE_AUTO_SHARE=false \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
USER 10001:10001
EXPOSE 4096
ENTRYPOINT ["/opt/peixian/managed-entrypoint.sh"]
