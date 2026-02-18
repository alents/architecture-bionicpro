FROM nginx:1.25-alpine

# Удаляем дефолтный конфиг
RUN rm /etc/nginx/conf.d/default.conf

# Копируем наш конфиг
COPY nginx.conf /etc/nginx/conf.d/cdn.conf

# Создаём директорию для кеша
RUN mkdir -p /var/cache/nginx/reports && \
    chown -R nginx:nginx /var/cache/nginx

EXPOSE 80