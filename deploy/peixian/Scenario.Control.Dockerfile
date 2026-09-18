# Reuse the verified local dependency layer; no network downloads at build time.
FROM sha256:72410e707f63f8cc58242d8a36f00815173947bf47290e3ff7b623633f4134a5
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
COPY packages/peixian-console/dist /app/static
