# --- ステージ1: ビルド用 ---
# コンパイルに必要なツールが入った重いイメージを使います
FROM rust:1.75 as builder
WORKDIR /usr/src/app
COPY . .
# 最適化（リリースモード）でビルドを実行
RUN cargo build --release

# --- ステージ2: 実行用 ---
# 実行時はコンパイラなどは不要なので、超軽量なOSイメージを使います
FROM debian:bookworm-slim
# ステージ1で作った実行ファイルだけをコピーしてきます
COPY --from=builder /usr/src/app/target/release/idle-server /usr/local/bin/idle-server

EXPOSE 8080
CMD ["idle-server"]