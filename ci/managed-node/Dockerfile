# Isolated SSH target for bootstrap-zero testing, never a production image.
ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401
FROM ${UBUNTU_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server sudo ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && test ! -x /usr/bin/python3 \
    && useradd --create-home --shell /bin/bash deploy \
    && printf 'deploy ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/deploy \
    && chmod 0440 /etc/sudoers.d/deploy \
    && mkdir -p /run/sshd /opt/sub2api /opt/mb-ai-docs \
    && printf 'application-owned\n' > /opt/sub2api/sentinel \
    && printf 'application-owned\n' > /opt/mb-ai-docs/sentinel
COPY entrypoint.sh /usr/local/bin/test-sshd
ENTRYPOINT ["bash", "/usr/local/bin/test-sshd"]
