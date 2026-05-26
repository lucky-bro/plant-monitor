FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build-time env: Next.js inlines these into the bundle.
# BACKEND_URL is used by next.config.ts rewrites (server-side proxy).
# NEXT_PUBLIC_API_URL is what client-side fetch uses (rewritten to BACKEND_URL).
ENV BACKEND_URL=http://plant-backend:8000
ENV NEXT_PUBLIC_API_URL=/api
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
