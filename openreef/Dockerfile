FROM node:20-alpine AS base
RUN apk add --no-cache libc6-compat git
WORKDIR /app

FROM base AS source
ARG OPENREEF_REPOSITORY="https://github.com/TheCarpyVikings/OpenReef.git"
ARG OPENREEF_REF="main"
COPY config.yaml /tmp/openreef-addon-config.yaml
RUN echo "OpenReef source cache key:" \
    && sha256sum /tmp/openreef-addon-config.yaml \
    && git clone --depth 1 --branch "${OPENREEF_REF}" "${OPENREEF_REPOSITORY}" /src \
    && git -C /src rev-parse HEAD > /src/.openreef-source-revision

FROM base AS deps
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY --from=source /src/package.json /src/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY --from=source /src ./
ENV HA_ADDON_MODE=true
ENV NEXT_PUBLIC_HA_ADDON_MODE=true
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM ghcr.io/home-assistant/base:latest AS runner

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
    nodejs \
    nginx \
    && mkdir -p /run/nginx /data

WORKDIR /app

ENV HA_ADDON_MODE=true
ENV NEXT_PUBLIC_HA_ADDON_MODE=true
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV OPENREEF_DATA_DIR=/data

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

COPY nginx.conf /etc/nginx/http.d/default.conf
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
