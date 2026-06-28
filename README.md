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
| Java | `100m` | `384Mi` | `200m` | `384Mi` |

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

## Java GC・ヒープサイズ実験プロトタイプ

卒業研究用のMVPとして、Java Spring Bootアプリケーションを対象に、GC方式・ヒープサイズ・負荷条件を変えながら、スループット、P95レイテンシ、Kepler由来の消費電力、エネルギー効率をCSVに保存するスクリプトを追加しています。

### 実験条件の変更

実験条件は `experiments/matrix.yaml` で管理します。

```yaml
gc:
  - G1GC
  - SerialGC
  - ZGC
heap:
  - 256m
  - 512m
  - 1g
load_level:
  - 10
  - 30
  - 50
sla_ms:
  - 300
  - 500
```

値を増減すると、`gc x heap x load_level x sla_ms` の全組み合わせが実行されます。

### dry-run の実行

Kubernetes、k6、Prometheus がない環境でも、ダミーデータでCSV生成まで確認できます。

```bash
python experiments/run_experiment.py --dry-run
```

結果は `results/experiment_results.csv` に追記されます。繰り返し実行すると行が追加されるため、最初から作り直したい場合はCSVを削除してから再実行してください。

### 実環境での実行

事前に Java のDeploymentを作成し、k6 と Prometheus/Kepler が利用できる状態にします。

```bash
kubectl apply -f kepler-test-java/deployment-java.yaml
```

Prometheusをローカルから参照できるようにします。PrometheusのService名やnamespaceは環境に合わせて変更してください。

```bash
kubectl port-forward -n monitoring service/prometheus-server 9090:80
```

別ターミナルで実験を実行します。`--port-forward` を付けると、各条件でJava Deploymentを再起動したあとにスクリプトが `kubectl port-forward` を張り直します。

```bash
python experiments/run_experiment.py \
  --namespace default \
  --deployment java-idle-app \
  --container java-container \
  --target-url http://localhost:8080/ \
  --prometheus-url http://localhost:9090 \
  --port-forward
```

既に別ターミナルで `kubectl port-forward deployment/java-idle-app 8080:8080` を実行している場合は、`--port-forward` を省略できます。ただし、Deploymentの再起動で接続が切れる場合は張り直しが必要です。

スクリプトは `JAVA_TOOL_OPTIONS` にGC方式と `-Xms/-Xmx` を設定し、Deploymentを再起動してからk6を実行します。ヒープサイズに合わせてKubernetesのメモリ request/limit も更新します。k6の各HTTPリクエストのタイムアウトは `--http-timeout` で変更でき、デフォルトは `5s` です。

実行前に `--target-url` と `--prometheus-url` へ接続できるかを確認します。PrometheusのKepler向けPromQLは `prometheus/queries.py` の定数で変更できます。

### CSVの項目

`results/experiment_results.csv` には次の列を保存します。

| 列 | 意味 |
| --- | --- |
| `gc` | GC方式。`G1GC`、`SerialGC`、`ZGC` |
| `heap` | JVMヒープサイズ |
| `load_level` | k6の仮想ユーザー数 |
| `throughput` | k6から得たリクエスト数/秒 |
| `power_watt` | Prometheus/Keplerから得た平均消費電力 |
| `energy_efficiency` | `throughput / power_watt` |
| `p95_latency_ms` | k6から得たP95レイテンシ |
| `sla_ms` | 判定対象のSLA |
| `sla_ok` | `p95_latency_ms <= sla_ms` の結果 |

### 最適設定の確認

SLAごとに、SLAを満たす行の中で `energy_efficiency` が最も高い設定を表示します。

```bash
python analysis/select_best_config.py results/experiment_results.csv
```

### パレートフロント画像の作成

P95レイテンシを横軸、エネルギー効率を縦軸にした散布図を作成します。

```bash
python analysis/pareto_front.py results/experiment_results.csv
```

出力先は `results/pareto_front.png` です。matplotlib がない環境では、必要なエラー内容を表示します。
