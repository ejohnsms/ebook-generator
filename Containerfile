# One image per pipeline stage, built by `./ebook-gen build`:
#
#   container build --build-arg PIXI_ENV=text --build-arg PIPELINE_STAGE=text -t ebook-gen-text .
#
# PIXI_ENV is the pixi environment to install (text, images, compile, audio,
# dev). PIPELINE_STAGE limits which pipeline steps the image runs; it's empty
# for dev, which runs tests and the TUI. pixi only installs packages here; at
# run time the shell hook activates the environment directly.
FROM ghcr.io/prefix-dev/pixi:0.81.0

ARG PIXI_ENV
ARG PIPELINE_STAGE=""

# The environment lives outside /workspace, where ./ebook-gen mounts the repo.
WORKDIR /opt/ebook-gen
COPY pixi.toml ./
RUN pixi install -e ${PIXI_ENV} \
    && pixi shell-hook -e ${PIXI_ENV} -s bash > /opt/ebook-gen/activate.sh \
    && echo 'exec "$@"' >> /opt/ebook-gen/activate.sh \
    && rm -rf /root/.cache/rattler /root/.cache/uv

# Fallback copy of the code; ./ebook-gen mounts the working tree over it.
COPY code/ /workspace/code/
WORKDIR /workspace

ENV PYTHONPATH=/workspace/code \
    EBOOK_GEN_BACKEND=remote \
    EBOOK_GEN_STAGE=${PIPELINE_STAGE} \
    HF_HOME=/hf

ENTRYPOINT ["/bin/bash", "/opt/ebook-gen/activate.sh"]
CMD ["python", "-m", "ebook_gen.cli", "--help"]
