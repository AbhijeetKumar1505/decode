FROM kalilinux/kali-rolling:latest

RUN apt-get update && apt-get install -y \
    nmap \
    curl \
    git \
    python3 \
    python3-pip \
    dirsearch \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/bin/bash"]
