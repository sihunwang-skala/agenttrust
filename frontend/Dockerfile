FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV VITE_API_PROXY=http://backend:8000
CMD ["npx", "vite", "--host", "0.0.0.0"]
