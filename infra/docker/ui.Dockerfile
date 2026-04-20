FROM node:20-alpine

WORKDIR /app

COPY apps/ui/package.json /app/package.json
RUN npm install

COPY apps/ui /app

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

