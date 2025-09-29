FROM alpine:latest
RUN apk add --no-cache dcron sqlite
COPY ./src/scripts/cleanup.sh /usr/local/bin/cleanup.sh
RUN chmod +x /usr/local/bin/cleanup.sh
RUN echo "*/5 * * * * /usr/local/bin/cleanup.sh >> /var/log/cron.log 2>&1" > /etc/crontabs/root
RUN touch /var/log/cron.log
CMD crond -f -L /var/log/cron.log