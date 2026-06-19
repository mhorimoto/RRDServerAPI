# RRD Web API サーバ

他サーバからHTTPリクエストでRRDファイルの時系列データを取得できるWebAPIサーバです。

## 必要条件

- Python 3.8+
- rrdtool（システムパッケージ）
- pip パッケージ: fastapi, uvicorn, rrdtool

## インストール

```bash
# rrdtool本体 + 開発ライブラリ（AlmaLinux / RHEL / Rocky Linux）
sudo dnf install rrdtool rrdtool-devel

# EPELが必要な場合（rrdtoolが見つからないとき）
sudo dnf install epel-release
sudo dnf install rrdtool rrdtool-devel

# Pythonパッケージ
pip install fastapi uvicorn
```

## 起動

```bash
# デフォルト（RRDディレクトリ: /var/lib/rrd、ポート: 8080）
uvicorn rrd_api_server:app --host 0.0.0.0 --port 8080

# RRDディレクトリを変更する場合
RRD_BASE_DIR=/path/to/rrd uvicorn rrd_api_server:app --host 0.0.0.0 --port 8080

# 開発時（ホットリロード）
uvicorn rrd_api_server:app --host 0.0.0.0 --port 8080 --reload
```

## API エンドポイント

### `GET /fetch/{filename}`
指定期間のRRDデータを取得します。

**パラメータ:**

| パラメータ | 必須 | 説明 | 例 |
|------------|------|------|----|
| filename   | o   | RRDファイル名（.rrd省略可） | `tb2n4` |
| start      | o   | 開始日時（ISO 8601） | `2026-01-01` |
| end        | o   | 終了日時（ISO 8601） | `2026-01-07` |
| cf         | -    | 集計関数（デフォルト: AVERAGE） | `MAX` |

**例:**
```
GET /fetch/tb2n4?start=2026-01-01&end=2026-01-07&cf=AVERAGE
```

**レスポンス:**
```json
{
  "filename": "tb2n4.rrd",
  "cf": "AVERAGE",
  "start": "2026-01-01T00:00:00",
  "end": "2026-01-07T00:00:00",
  "start_ts": 1767225600,
  "end_ts": 1767744000,
  "ds_names": ["traffic_in", "traffic_out"],
  "records": [
    {
      "timestamp": 1767225600,
      "datetime": "2026-01-01T00:00:00",
      "values": {
        "traffic_in": 1234.56,
        "traffic_out": 789.01
      }
    }
  ],
  "count": 2016
}
```

---

### `GET /info/{filename}`
RRDファイルのメタ情報を取得します。

```
GET /info/tb2n4
```

---

### `GET /list`
利用可能なRRDファイルの一覧を取得します。

```
GET /list
```

---

### `GET /health`
サーバとrrdtoolの稼働状態を確認します。

```
GET /health
```

## クライアント側からの呼び出し例

### curl
```bash
curl "http://rrdserver:8080/fetch/tb2n4?start=2026-01-01&end=2026-01-07"
```

### Python (requests)
```python
import requests

resp = requests.get("http://rrdserver:8080/fetch/tb2n4", params={
    "start": "2026-01-01",
    "end":   "2026-01-07T23:59:59",
    "cf":    "AVERAGE",
})
data = resp.json()
for record in data["records"]:
    print(record["datetime"], record["values"])
```

### JavaScript (fetch)
```javascript
const resp = await fetch(
  "http://rrdserver:8080/fetch/tb2n4?start=2026-01-01&end=2026-01-07"
);
const data = await resp.json();
console.log(data.records);
```

## スワッガーUI（自動生成ドキュメント）

起動後、ブラウザで以下にアクセスするとインタラクティブなAPIドキュメントが使えます。

```
http://rrdserver:8080/docs
```

## systemd サービス登録（本番環境）

`/etc/systemd/system/rrd-api.service`:

```ini
[Unit]
Description=RRD Web API Server
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/rrd-api
Environment=RRD_BASE_DIR=/var/lib/rrd
ExecStart=/usr/local/bin/uvicorn rrd_api_server:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now rrd-api
```
