FROM node:20-alpine AS base
RUN apk add --no-cache libc6-compat
WORKDIR /app

FROM base AS deps
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV HA_ADDON_MODE=true
ENV NEXT_PUBLIC_HA_ADDON_MODE=true
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM ghcr.io/home-assistant/base:latest AS runner

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

COPY openreef/nginx.conf /etc/nginx/http.d/default.conf
COPY openreef/run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
