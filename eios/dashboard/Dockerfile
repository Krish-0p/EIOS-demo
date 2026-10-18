FROM oven/bun:1.3.11-alpine AS build
WORKDIR /app
COPY dashboard/package.json dashboard/bun.lock ./
RUN bun install --frozen-lockfile
COPY dashboard/ ./
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN bun run build

FROM oven/bun:1.3.11-alpine
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY dashboard/serve.ts ./serve.ts
EXPOSE 5173
CMD ["bun", "run", "serve.ts"]
