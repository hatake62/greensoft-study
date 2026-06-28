# greensoft-study

複数言語で同じ内容の軽量なHTTPサーバーを実装し、Docker/Kubernetes上で動かして比較するためのサンプルです。
各アプリケーションは `0.0.0.0:8080` で待ち受け、`GET /` に対して言語ごとの簡単なメッセージを返します。

## 構成

| 言語 | 実装 | Dockerfile | Kubernetes Deployment | レスポンス |
| --- | --- | --- | --- | --- |
| Rust | `src/main.rs` | `Dockerfile` | `deployment.yaml` | `Hello from Rust!` |
| Go | `kepler-test-go/main.go` | `kepler-test-go/Dockerfile` | `kepler-test-go/deployment-go.yaml` | `Hello from Go!` |
| Java | `kepler-test-java/src/main/java/com/example/Application.java` | `kepler-test-java/Dockerfile` | `kepler-test-java/deployment-java.yaml` | `Hello from Java Spring Boot!` |
| Node.js | `kepler-test-node/app.js` | `kepler-test-node/Dockerfile` | `kepler-test-node/deployment-node.yaml` | `Hello from Node.js!` |
| Python | `kepler-test-python/server.py` | `kepler-test-python/Dockerfile` | `kepler-test-python/deployment-python.yaml` | `Hello from Python!` |

## 実装方法

### Rust

`src/main.rs` では標準ライブラリの `TcpListener` を使っています。外部HTTPフレームワークは使わず、TCP接続を受け取ったらHTTPレスポンス文字列を直接書き込む実装です。

`Cargo.toml` に外部依存はありません。コンテナはマルチステージビルドで、`rust:1.75` でリリースビルドしたバイナリだけを `debian:bookworm-slim` にコピーします。

### Go

`kepler-test-go/main.go` では標準ライブラリの `net/http` を使っています。`/` にハンドラを登録し、`http.ListenAndServe(":8080", nil)` でHTTPサーバーを起動します。

Dockerfileは `golang:1.21-alpine` でビルドし、生成した実行ファイルだけを `alpine:latest` にコピーするマルチステージ構成です。

### Java

`kepler-test-java/src/main/java/com/example/Application.java` はSpring Bootアプリケーションです。`@RestController` と `@GetMapping("/")` を使ってルートパスにレスポンスを返します。

`pom.xml` では `spring-boot-starter-web` を利用しています。DockerfileはMavenでjarを作成し、`eclipse-temurin:21-jre-jammy` 上で `java -jar app.jar` を実行します。

### Node.js

`kepler-test-node/app.js` ではNode.js標準の `http` モジュールを使っています。リクエストを受け取るたびに `text/plain` の200レスポンスを返します。

Dockerfileは `node:20-slim` を使い、`app.js` だけをコピーして `node app.js` で起動します。

### Python

`kepler-test-python/server.py` では標準ライブラリの `http.server` を使っています。`BaseHTTPRequestHandler` を継承した `SimpleHandler` が `GET` リクエストに応答します。

Dockerfileは `python:3.11-slim` を使い、`server.py` をコピーして `python server.py` で起動します。

## ローカル実行

各アプリケーションは同じ `8080` ポートを使うため、同時に複数起動する場合はポートの衝突に注意してください。

### Rust

```bash
cargo run
curl http://localhost:8080/
```

### Go

```bash
cd kepler-test-go
go run .
curl http://localhost:8080/
```

### Java

```bash
cd kepler-test-java
mvn spring-boot:run
curl http://localhost:8080/
```

### Node.js

```bash
cd kepler-test-node
node app.js
curl http://localhost:8080/
```

### Python

```bash
cd kepler-test-python
python server.py
curl http://localhost:8080/
```

## Dockerで実行

### Rust

```bash
docker build -t rust-idle-image:latest .
docker run --rm -p 8080:8080 rust-idle-image:latest
curl http://localhost:8080/
```

### Go

```bash
docker build -t go-idle-image:latest kepler-test-go
docker run --rm -p 8080:8080 go-idle-image:latest
curl http://localhost:8080/
```

### Java

```bash
docker build -t java-idle-image:latest kepler-test-java
docker run --rm -p 8080:8080 java-idle-image:latest
curl http://localhost:8080/
```

### Node.js

```bash
docker build -t node-idle-image:latest kepler-test-node
docker run --rm -p 8080:8080 node-idle-image:latest
curl http://localhost:8080/
```

### Python

```bash
docker build -t python-idle-image:latest kepler-test-python
docker run --rm -p 8080:8080 python-idle-image:latest
curl http://localhost:8080/
```

## Kubernetesで実行

事前に、Deployment内の `image` と同じ名前でコンテナイメージをビルドし、利用するKubernetesクラスタから参照できる状態にしてください。
ローカルKubernetesで使う場合は、Docker Desktop、kind、minikubeなど利用環境に合わせてイメージの読み込み方法が変わります。

Deploymentを適用します。

```bash
kubectl apply -f deployment.yaml
kubectl apply -f kepler-test-go/deployment-go.yaml
kubectl apply -f kepler-test-java/deployment-java.yaml
kubectl apply -f kepler-test-node/deployment-node.yaml
kubectl apply -f kepler-test-python/deployment-python.yaml
```

Podの状態を確認します。

```bash
kubectl get pods
kubectl get deployments
```

Serviceは含まれていないため、動作確認は `kubectl port-forward` で行います。例としてRustのDeploymentを確認する場合は次の通りです。

```bash
kubectl port-forward deployment/rust-idle-app 8080:8080
curl http://localhost:8080/
```

他の言語を確認する場合はDeployment名を差し替えます。

```bash
kubectl port-forward deployment/go-idle-app 8080:8080
kubectl port-forward deployment/java-idle-app 8080:8080
kubectl port-forward deployment/node-idle-app 8080:8080
kubectl port-forward deployment/python-idle-app 8080:8080
```

## リソース設定

Kubernetes DeploymentではCPUとメモリの `requests` / `limits` を設定しています。

| 言語 | requests.cpu | requests.memory | limits.cpu | limits.memory |
| --- | --- | --- | --- | --- |
| Rust | `100m` | `64Mi` | `200m` | `128Mi` |
| Go | `100m` | `64Mi` | `200m` | `128Mi` |
| Node.js | `100m` | `64Mi` | `200m` | `128Mi` |
| Python | `100m` | `64Mi` | `200m` | `128Mi` |
| Java | `100m` | `256Mi` | `200m` | `256Mi` |

JavaはSpring Bootの起動に必要なメモリを考慮し、他の言語より大きいメモリ設定になっています。

## 削除

Kubernetes上に作成したDeploymentを削除する場合は次のコマンドを実行します。

```bash
kubectl delete -f deployment.yaml
kubectl delete -f kepler-test-go/deployment-go.yaml
kubectl delete -f kepler-test-java/deployment-java.yaml
kubectl delete -f kepler-test-node/deployment-node.yaml
kubectl delete -f kepler-test-python/deployment-python.yaml
```
