# syntax=docker/dockerfile:1.7

FROM node:20-alpine

WORKDIR /app

COPY apps/ui/package.json apps/ui/package-lock.json /app/
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY VERSION /app/VERSION
COPY apps/ui /app

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
