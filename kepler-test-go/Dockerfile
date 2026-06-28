# --- ビルドステージ ---
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod ./
# 今回は外部ライブラリがないので go mod download は不要ですが、慣習として
COPY . .
RUN go build -o main .

# --- 実行ステージ ---
FROM alpine:latest
WORKDIR /root/
COPY --from=builder /app/main .
EXPOSE 8080
CMD ["./main"]