FROM docker.io/library/ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /sandbox /opt/lab-private \
    && printf 'This is a fake secret for the filesystem exercise.\n' > /opt/lab-private/example.txt \
    && chown -R 1000:1000 /sandbox /opt/lab-private
USER 1000:1000
WORKDIR /sandbox
CMD ["sleep", "infinity"]
