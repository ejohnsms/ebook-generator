FROM ghcr.io/prefix-dev/pixi:latest

# Install system dependencies required by Kokoro TTS
RUN apt-get update && apt-get install -y \
    espeak-ng \
    pkg-config \
    libcairo2-dev \
    libpango1.0-dev \
    libpng-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
    libglib2.0-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy pixi project files
COPY pixi.toml pixi.lock* ./

# Install dependencies via pixi
RUN pixi install --locked || pixi install

# Copy source code
COPY code/ /workspace/code/

# Create output directories
RUN mkdir -p stories prompts images compiled progress audio

# Default command
ENTRYPOINT ["pixi", "run"]
CMD ["ebook-gen", "--help"]
