FROM node:18-alpine
WORKDIR /app
RUN npm install -g npm@9
COPY package*.json .
COPY packages ./packages
COPY translations ./translations
COPY . .
RUN mkdir -p themes extensions public media config
RUN npm install
RUN npm run compile:db
RUN npm run compile
RUN npm run build

EXPOSE 80
CMD ["npm", "run", "start"]