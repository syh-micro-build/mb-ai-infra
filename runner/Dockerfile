FROM python:3.12-slim-trixie@sha256:ddb0207ae1f0356c2b724d740769b0c5f5f51cc54a0525178f721825f78fe74c

ARG VCS_REF=local
LABEL org.opencontainers.image.title="mb-ai-infra-runner" \
      org.opencontainers.image.source="https://github.com/syh-micro-build/mb-ai-infra" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/runner \
    ANSIBLE_CONFIG=/workspace/ansible.cfg \
    ANSIBLE_COLLECTIONS_PATH=/opt/runner/collections \
    ANSIBLE_LOCAL_TEMP=/tmp/ansible/local \
    ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/ansible/cp \
    ANSIBLE_HOST_KEY_CHECKING=True

# These are controller dependencies. None of this image is copied to a managed node.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates openssh-client curl libnss-wrapper \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 runner \
    && useradd --uid 65532 --gid 65532 --home-dir /home/runner --no-create-home runner \
    && mkdir -p /opt/runner/ansible /run/infra-ssh /workspace /reports /home/runner \
    && find /usr/lib -name libnss_wrapper.so -exec ln -s '{}' /opt/runner/libnss_wrapper.so \; \
    && test -e /opt/runner/libnss_wrapper.so

COPY requirements-runner.txt /opt/runner/requirements-runner.txt
COPY ansible/requirements.yml /opt/runner/ansible/requirements.yml
RUN python -m pip install --no-cache-dir -r /opt/runner/requirements-runner.txt \
    && env -u ANSIBLE_CONFIG ansible-galaxy collection install \
       -r /opt/runner/ansible/requirements.yml -p /opt/runner/collections \
    && cd /opt/runner \
    && sha256sum requirements-runner.txt ansible/requirements.yml > toolchain.sha256

COPY VERSION /opt/runner/VERSION
COPY --chmod=755 runner/entrypoint.sh /usr/local/bin/infra-entrypoint
COPY runner/dispatch.py /opt/runner/dispatch.py

USER 65532:65532
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/infra-entrypoint"]
CMD ["version"]
