# syntax=docker/dockerfile:1
#
# Multi-stage frontend image (FR-016): a Node build stage compiles the SPA with Vite, then a
# pinned nginx runtime serves the static bundle with SPA history-fallback. The Node toolchain
# never ships in the runtime.

############################
# Build stage — compile the SPA (Node toolchain; not shipped).
############################
FROM node:18.20.8-alpine@sha256:8d6421d663b4c28fd3ebc498332f249011d118945588d0a35cb9bc4b8ca09d9e AS build

WORKDIR /app

# API base URL is baked at build time (dev: http://api.localhost; prod overlay-configured).
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

############################
# Runtime stage — nginx serving the built bundle (pinned by patch + digest, Principle I).
############################
FROM nginx:1.30.3-alpine@sha256:92cf5e2f488744c90d3df4378dfa3f0842704950cfa1353975d5510c945b072f AS runtime

# SPA history-fallback config (replaces the default server block).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
