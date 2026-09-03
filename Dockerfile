# Base identity: python:3.13-alpine
FROM python@sha256:71397d15c4c450526972669d41cad5bf89fd463c0027cc93af15891215f6c56b AS builder
ARG SOURCE_COMMIT=0000000000000000000000000000000000000000
ARG BASE_IMAGE_DIGEST=sha256:71397d15c4c450526972669d41cad5bf89fd463c0027cc93af15891215f6c56b
ARG CONTAINER_LOCK_SHA256=b60c17e3a8ffedb5fa6c885888973c6dfbf76d7a0843b09c4906b81c7cecbbf8
ARG CONTAINER_APK_LOCK_SHA256=cc56945541167178a2907030428e8db085264701561b9312ba75a2e4d402c3a7
ARG CONTAINER_BUILDER_LOCK_SHA256=9116ec93dee871b6244c3cc93c456338537fe2d11aaa838aa40bf79513238c9e
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
FROM python@sha256:71397d15c4c450526972669d41cad5bf89fd463c0027cc93af15891215f6c56b
ARG SOURCE_COMMIT=0000000000000000000000000000000000000000
ARG BASE_IMAGE_DIGEST=sha256:71397d15c4c450526972669d41cad5bf89fd463c0027cc93af15891215f6c56b
ARG CONTAINER_LOCK_SHA256=b60c17e3a8ffedb5fa6c885888973c6dfbf76d7a0843b09c4906b81c7cecbbf8
ARG CONTAINER_APK_LOCK_SHA256=cc56945541167178a2907030428e8db085264701561b9312ba75a2e4d402c3a7
ARG CONTAINER_BUILDER_LOCK_SHA256=9116ec93dee871b6244c3cc93c456338537fe2d11aaa838aa40bf79513238c9e
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
    rm -rf /app/dist && \
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
