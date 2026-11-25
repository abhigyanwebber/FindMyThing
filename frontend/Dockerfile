# Build-verification / local-preview image. Production hosting is Azure Static Web Apps (deploys dist/).
# Build from frontend/:  docker build --build-arg VITE_API_BASE_URL=https://api.example.edu/api -t findmything-web .
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --include=dev
COPY . .
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
