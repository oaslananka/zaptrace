# Base identity: python:3.13-alpine
FROM python@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a AS builder
ARG SOURCE_COMMIT=0000000000000000000000000000000000000000
ARG BASE_IMAGE_DIGEST=sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a
ARG CONTAINER_LOCK_SHA256=10b7d1a10b5771439b2252dbf75881020965ebec681a1e1d49031e5fac5f5087
ARG CONTAINER_APK_LOCK_SHA256=12b81d7fcc1ec53d74a0fa111683a26d073235715fec0c7e5d7f6608f820a48d
ARG CONTAINER_BUILDER_LOCK_SHA256=309fc4d1d751e3ba5d1908082e2cd89fdafd1c8d11bfd3accba91d0957c93153
WORKDIR /build
RUN apk add --no-cache build-base cargo patchelf rust
COPY requirements/container-builder.txt /build/requirements/container-builder.txt
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: \
      -r /build/requirements/container-builder.txt
COPY requirements/container-runtime.txt /build/requirements/container-runtime.txt
COPY requirements/container-apk.txt /build/requirements/container-apk.txt
COPY . .
RUN maturin build --release --locked --out dist --manifest-path zaptrace_core/Cargo.toml
RUN set -eux; \
    apk info -vv | LC_ALL=C sort > /build/builder-apk-packages.txt; \
    WHEEL="$(find /build/dist -name '*.whl' -print -quit)"; \
    WHEEL_VERSION="$(basename "$WHEEL" | cut -d- -f2)"; \
    WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"; \
    printf 'zaptrace-eda==%s --hash=sha256:%s\n' "$WHEEL_VERSION" "$WHEEL_SHA256" \
      > /build/zaptrace-wheel-requirement.txt; \
    python scripts/ci_container_reproducibility.py write-provenance \
      --source-commit "$SOURCE_COMMIT" \
      --base-digest "$BASE_IMAGE_DIGEST" \
      --manifest /build/requirements/container-runtime.txt \
      --expected-manifest-sha256 "$CONTAINER_LOCK_SHA256" \
      --apk-manifest /build/requirements/container-apk.txt \
      --expected-apk-manifest-sha256 "$CONTAINER_APK_LOCK_SHA256" \
      --builder-dependency-manifest /build/requirements/container-builder.txt \
      --expected-builder-dependency-manifest-sha256 "$CONTAINER_BUILDER_LOCK_SHA256" \
      --builder-manifest /build/builder-apk-packages.txt \
      --wheel "$WHEEL" \
      --output /build/container-build-provenance.json

# Base identity: python:3.13-alpine
FROM python@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a
ARG SOURCE_COMMIT=0000000000000000000000000000000000000000
ARG BASE_IMAGE_DIGEST=sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a
ARG CONTAINER_LOCK_SHA256=10b7d1a10b5771439b2252dbf75881020965ebec681a1e1d49031e5fac5f5087
ARG CONTAINER_APK_LOCK_SHA256=12b81d7fcc1ec53d74a0fa111683a26d073235715fec0c7e5d7f6608f820a48d
ARG CONTAINER_BUILDER_LOCK_SHA256=309fc4d1d751e3ba5d1908082e2cd89fdafd1c8d11bfd3accba91d0957c93153
LABEL org.opencontainers.image.revision="$SOURCE_COMMIT" \
      io.zaptrace.base.digest="$BASE_IMAGE_DIGEST" \
      io.zaptrace.dependencies.python.sha256="$CONTAINER_LOCK_SHA256" \
      io.zaptrace.dependencies.alpine.sha256="$CONTAINER_APK_LOCK_SHA256" \
      io.zaptrace.dependencies.builder-python.sha256="$CONTAINER_BUILDER_LOCK_SHA256" \
      io.zaptrace.provenance.path="/usr/share/zaptrace/container-build-provenance.json"
WORKDIR /app
COPY requirements/container-runtime.txt /app/requirements/container-runtime.txt
COPY requirements/container-apk.txt /app/requirements/container-apk.txt
# ngspice is version-locked to the exact package observed for the pinned Alpine base.
RUN apk add --no-cache $(cat /app/requirements/container-apk.txt)
COPY --from=builder /build/dist/*.whl /app/dist/
COPY --from=builder /build/container-build-provenance.json /usr/share/zaptrace/container-build-provenance.json
COPY --from=builder /build/builder-apk-packages.txt /usr/share/zaptrace/builder-apk-packages.txt
COPY --from=builder /build/zaptrace-wheel-requirement.txt /app/requirements/zaptrace-wheel.txt
# Both the runtime set and locally built wheel are exact, hash-verified requirements.
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: \
      -r /app/requirements/container-runtime.txt && \
    pip install --no-cache-dir --require-hashes --only-binary=:all: --no-index \
      --find-links=/app/dist -r /app/requirements/zaptrace-wheel.txt && \
    pip check && \
    rm -rf /app/dist /usr/local/lib/python3.13/site-packages/pip \
      /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
      /usr/local/lib/python3.13/ensurepip && \
    rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 && \
    mkdir -p /workspace && \
    addgroup -S -g 1001 appgroup && \
    adduser -S -D -H -u 1001 -G appgroup appuser && \
    chown -R appuser:appgroup /workspace
VOLUME ["/workspace"]
WORKDIR /workspace
USER appuser:appgroup
# This image supports CLI, REST, and MCP entrypoints. A single image-level
# probe would be incorrect; deployment manifests define protocol-specific checks.
HEALTHCHECK NONE
ENTRYPOINT ["zaptrace"]
CMD ["--help"]
