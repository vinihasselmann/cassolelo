# Imagem de produção do frontend: build do Vite servido por nginx (sem root).
# Build: docker build -t visualizador-bim-web frontend/

# --- estágio 1: build (tsc + vite) e cabeçalhos do nginx a partir de security-headers.ts
FROM node:24.11-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build \
 && node scripts/nginx-headers.mjs > /src/security-headers.conf

# --- estágio 2: nginx
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
