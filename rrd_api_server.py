#!/usr/bin/env python3
"""
RRD Web API Server
他サーバからHTTPでRRDデータを取得するためのWebAPIサーバ

依存パッケージ:
    pip install fastapi uvicorn rrdtool

起動方法:
    uvicorn rrd_api_server:app --host 0.0.0.0 --port [port number]

    # オプション: RRDファイルのディレクトリを環境変数で指定
    RRD_BASE_DIR=/var/lib/rrd uvicorn rrd_api_server:app --host 0.0.0.0 --port [port number]
"""

import os
import subprocess
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────
RRD_BASE_DIR = Path(os.environ.get("RRD_BASE_DIR", "/var/www/ysl/html/rrd"))

app = FastAPI(
    title="RRD Web API",
    description="RRDファイルから時系列データをHTTPで提供するAPI",
    version="1.0.0",
)


# ──────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────

def resolve_rrd_path(filename: str) -> Path:
    """
    ファイル名を受け取り、絶対パスを返す。
    ディレクトリトラバーサル攻撃を防ぐためパスを検証する。
    """
    # 拡張子を強制
    if not filename.endswith(".rrd"):
        filename = filename + ".rrd"

    path = (RRD_BASE_DIR / filename).resolve()

    # base_dir 外へのアクセスを禁止
    if not str(path).startswith(str(RRD_BASE_DIR.resolve())):
        raise HTTPException(status_code=400, detail="不正なファイルパスです")

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"RRDファイルが見つかりません: {filename}")

    return path


def parse_datetime(value: str) -> int:
    """
    ISO 8601形式 (YYYY-MM-DDTHH:MM:SS または YYYY-MM-DD) を
    Unixタイムスタンプ(int)に変換する。
    """
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(value, fmt).timestamp())
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail=f"日時フォーマットが不正です: '{value}'。例: '2026-01-01' または '2026-01-01T00:00:00'"
    )


def run_rrdtool_fetch(rrd_path: Path, cf: str, start_ts: int, end_ts: int) -> dict:
    """
    rrdtool fetch を実行し、結果を辞書で返す。
    """
    cmd = [
        "rrdtool", "fetch", str(rrd_path),
        cf,
        "--start", str(start_ts),
        "--end",   str(end_ts),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="rrdtool がインストールされていません")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="rrdtool の実行がタイムアウトしました")

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"rrdtool エラー: {result.stderr.strip()}"
        )

    return parse_fetch_output(result.stdout, start_ts)


def parse_fetch_output(raw: str, start_ts: int) -> dict:
    """
    rrdtool fetch の標準出力をパースして辞書に変換する。

    出力例:
        ds_name1  ds_name2

        1735689600: 1.23 4.56
        1735689900: nan 7.89
        ...
    """
    lines = raw.strip().splitlines()
    if not lines:
        raise HTTPException(status_code=500, detail="rrdtool から出力がありません")

    # 1行目: データソース名
    ds_names = lines[0].split()

    # 3行目以降: タイムスタンプ + 値
    records = []
    for line in lines[2:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        # タイムスタンプは "1735689600:" のようにコロン付き
        ts = int(parts[0].rstrip(":"))
        values = {}
        for i, ds in enumerate(ds_names):
            raw_val = parts[i + 1] if i + 1 < len(parts) else "nan"
            try:
                f = float(raw_val)
                # NaN / inf はJSONに含められないので None に変換
                values[ds] = None if (f != f or f == float("inf") or f == float("-inf")) else f
            except ValueError:
                values[ds] = None
        records.append({
            "timestamp": ts,
            "datetime":  datetime.fromtimestamp(ts).isoformat(),
            "values":    values,
        })

    return {
        "ds_names": ds_names,
        "records":  records,
        "count":    len(records),
    }


def get_rrd_info(rrd_path: Path) -> dict:
    """rrdtool info でファイル情報を取得する。"""
    cmd = ["rrdtool", "info", str(rrd_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="rrdtool がインストールされていません")

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"rrdtool エラー: {result.stderr.strip()}")

    # 簡易パース: key = value 形式
    info = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip().strip('"')
    return info


# ──────────────────────────────────────────────
# エンドポイント
# ──────────────────────────────────────────────

@app.get("/", summary="APIの説明")
def root():
    return {
        "name": "RRD Web API",
        "version": "1.0.0",
        "endpoints": {
            "GET /fetch/{filename}": "指定期間のデータを取得",
            "GET /info/{filename}":  "RRDファイルの情報を取得",
            "GET /list":             "利用可能なRRDファイル一覧",
            "GET /health":           "ヘルスチェック",
        },
        "example": "/fetch/tb2n4?start=2026-01-01&end=2026-01-07&cf=AVERAGE",
    }


@app.get("/health", summary="ヘルスチェック")
def health():
    """サーバの稼働状態を返す。"""
    rrdtool_ok = subprocess.run(
        ["rrdtool", "--version"], capture_output=True
    ).returncode == 0

    return {
        "status":       "ok" if rrdtool_ok else "degraded",
        "rrdtool":      "available" if rrdtool_ok else "not found",
        "rrd_base_dir": str(RRD_BASE_DIR),
        "server_time":  datetime.now().isoformat(),
    }


@app.get("/list", summary="RRDファイル一覧")
def list_rrd_files():
    """
    RRD_BASE_DIR 内の .rrd ファイル一覧を返す。
    """
    if not RRD_BASE_DIR.exists():
        raise HTTPException(status_code=500, detail=f"RRDディレクトリが存在しません: {RRD_BASE_DIR}")

    files = [
        {
            "filename": p.name,
            "size_bytes": p.stat().st_size,
            "modified":   datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        }
        for p in sorted(RRD_BASE_DIR.glob("*.rrd"))
    ]
    return {"rrd_base_dir": str(RRD_BASE_DIR), "files": files, "count": len(files)}


@app.get("/info/{filename}", summary="RRDファイル情報")
def rrd_info(filename: str):
    """
    指定したRRDファイルのメタ情報（データソース名・RRA設定など）を返す。

    - **filename**: RRDファイル名（.rrd 拡張子は省略可）
    """
    rrd_path = resolve_rrd_path(filename)
    info = get_rrd_info(rrd_path)
    return {"filename": rrd_path.name, "info": info}


@app.get("/fetch/{filename}", summary="時系列データ取得")
def fetch_rrd(
    filename: str,
    start: str = Query(..., description="開始日時 (例: 2026-01-01 または 2026-01-01T00:00:00)"),
    end:   str = Query(..., description="終了日時 (例: 2026-01-07 または 2026-01-07T23:59:59)"),
    cf:    str = Query("AVERAGE", description="集計関数: AVERAGE / MAX / MIN / LAST"),
):
    """
    指定した日時範囲のRRDデータをJSON形式で返す。

    - **filename**: RRDファイル名（.rrd 拡張子は省略可）
    - **start**: 開始日時（ISO 8601形式）
    - **end**: 終了日時（ISO 8601形式）
    - **cf**: 集計関数（AVERAGE / MAX / MIN / LAST）
    """
    # バリデーション
    cf = cf.upper()
    if cf not in ("AVERAGE", "MAX", "MIN", "LAST"):
        raise HTTPException(status_code=400, detail="cf は AVERAGE / MAX / MIN / LAST のいずれかを指定してください")

    rrd_path  = resolve_rrd_path(filename)
    start_ts  = parse_datetime(start)
    end_ts    = parse_datetime(end)

    if start_ts >= end_ts:
        raise HTTPException(status_code=400, detail="start は end より前の日時を指定してください")

    data = run_rrdtool_fetch(rrd_path, cf, start_ts, end_ts)

    return {
        "filename":   rrd_path.name,
        "cf":         cf,
        "start":      datetime.fromtimestamp(start_ts).isoformat(),
        "end":        datetime.fromtimestamp(end_ts).isoformat(),
        "start_ts":   start_ts,
        "end_ts":     end_ts,
        **data,
    }
