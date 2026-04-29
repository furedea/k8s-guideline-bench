# Dockerfile for the k8s-guideline-bench agent execution environment.
#
# The host (src/agent_execution/agent_runner.py) prepares the editable
# worktree on macOS and bind-mounts it into the container at /work, so the
# image carries no entrypoint — the host invokes `bash -lc <agent_command>`
# directly. The in-image Kubernetes clone is kept for the rare case where
# an agent needs `git log`/`git show` against history not in the worktree.
#
# Build:
#   docker build -t k8s-bench-agent -f docker/Dockerfile .

# syntax=docker/dockerfile:1.7
FROM golang:1.26-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        make \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# opencode CLI (Go implementation). The installer treats VERSION literally
# as a release tag, so passing "latest" looks up `vlatest` and fails. Leave
# OPENCODE_VERSION empty to take the installer's default (current latest);
# set it to a release tag like "1.1.14" via --build-arg to pin.
ARG OPENCODE_VERSION=
ENV OPENCODE_INSTALL=/usr/local/opencode
RUN set -eux; \
    install_env="OPENCODE_INSTALL=${OPENCODE_INSTALL}"; \
    if [ -n "${OPENCODE_VERSION}" ]; then \
        install_env="${install_env} VERSION=${OPENCODE_VERSION}"; \
    fi; \
    curl -fsSL https://opencode.ai/install | env ${install_env} bash; \
    ln -s "${OPENCODE_INSTALL}/bin/opencode" /usr/local/bin/opencode

ARG KUBERNETES_REPO_URL=https://github.com/kubernetes/kubernetes.git

ENV KUBERNETES_CLONE_PATH=/k8s \
    WORKTREE_PATH=/work \
    GOCACHE=/tmp/go-build \
    GOMODCACHE=/tmp/go-mod \
    GOFLAGS=-mod=vendor

# Blobless clone: all commits and trees are present so any reachable base_sha
# resolves, but blobs fetch on demand when a worktree checks them out. Keeps
# the image ~1/4 the size of a full clone.
RUN git clone --filter=blob:none "${KUBERNETES_REPO_URL}" "${KUBERNETES_CLONE_PATH}"

WORKDIR /work

CMD ["bash"]
