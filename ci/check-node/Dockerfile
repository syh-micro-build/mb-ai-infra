# Isolated systemd/Docker SSH fixture for planning on an existing Ubuntu host.
# This image is never deployed; applications are represented by HTTP fixtures.
ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401
FROM ${UBUNTU_IMAGE}
ENV container=docker
# Keep apt indexes so read-only plans can resolve candidates without apt updates.
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod 0755 /usr/sbin/policy-rc.d \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       systemd systemd-sysv dbus openssh-server sudo ca-certificates curl iproute2 \
       python3 python3-apt openssl iptables \
    && mkdir -p /etc/apt/keyrings \
    && curl --fail --silent --show-error https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && printf 'deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
       "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       docker-ce docker-ce-cli containerd.io docker-compose-plugin \
    && rm /usr/sbin/policy-rc.d \
    && useradd --create-home --shell /usr/local/bin/test-login-shell deploy \
    && printf 'deploy ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/deploy \
    && chmod 0440 /etc/sudoers.d/deploy \
    && mkdir -p /etc/docker /opt/sub2api /opt/mb-ai-docs \
    && printf '{"storage-driver":"vfs"}\n' > /etc/docker/daemon.json \
    && printf 'application-owned\n' > /opt/sub2api/sentinel \
    && printf 'application-owned\n' > /opt/mb-ai-docs/sentinel \
    && systemctl enable ssh docker
COPY --chmod=755 entrypoint.sh /usr/local/bin/test-systemd
COPY --chmod=755 login-shell.sh /usr/local/bin/test-login-shell
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["bash", "/usr/local/bin/test-systemd"]
