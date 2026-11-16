# Backup/restauração do PostgreSQL (10.3): pg_dump/pg_restore 16 + rclone (pasta
# compartilhada SMB e SharePoint) + redis-cli (marca o resultado para os alertas).
FROM rclone/rclone:1.69.3 AS rclone

FROM postgres:16
RUN apt-get update \
 && apt-get install -y --no-install-recommends redis-tools ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone
COPY backup.sh restore.sh /usr/local/bin/
RUN sed -i 's/\r$//' /usr/local/bin/backup.sh /usr/local/bin/restore.sh \
 && chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/restore.sh
ENTRYPOINT []
CMD ["backup.sh"]
