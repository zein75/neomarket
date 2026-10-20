FROM node:22.14.0-alpine AS base
WORKDIR /workspace
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable && corepack prepare pnpm@9.15.5 --activate

FROM base AS deps
COPY . .
RUN pnpm install --frozen-lockfile

FROM deps AS builder
RUN pnpm --filter @neomarket/seller build

FROM node:22.14.0-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/seller/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/seller/.next/static ./apps/seller/.next/static
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/seller/public ./apps/seller/public
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 CMD wget -q -O - http://127.0.0.1:3000/api/health || exit 1
CMD ["node", "apps/seller/server.js"]
