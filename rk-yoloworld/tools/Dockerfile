FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc-aarch64-linux-gnu g++-aarch64-linux-gnu cmake \
    python3 git ca-certificates pkg-config xz-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /project
CMD ["bash", "tools/build_linux.sh"]
