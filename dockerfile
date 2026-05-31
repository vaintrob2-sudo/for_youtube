FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg curl cmake gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L https://github.com/quickjs-ng/quickjs/releases/download/v0.9.0/qjs-linux-x86_64 \
    -o /usr/local/bin/qjs && chmod +x /usr/local/bin/qjs

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]
