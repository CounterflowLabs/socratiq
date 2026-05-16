FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
EXPOSE 3000
# BACKEND_URL is read at request time by the API proxy route handler
# (src/app/api/[...path]/route.ts). Override at deploy with `-e BACKEND_URL=...`.
ENV BACKEND_URL=http://backend:8000
CMD ["npx", "next", "start", "--port", "3000"]
