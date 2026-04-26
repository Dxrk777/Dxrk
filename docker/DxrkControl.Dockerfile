FROM node:22-bullseye-slim
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     python3 \
     python3-venv \
     python3-pip \
     git \
     curl \
     build-essential \
     g++ \
     make \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /dxrk
COPY . /dxrk
WORKDIR /dxrk/DxrkControl
RUN npm install -g pnpm
RUN CI=true pnpm install
RUN CI=true pnpm build

CMD ["bash"]