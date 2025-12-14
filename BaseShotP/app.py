import os, time, json, csv
import concurrent.futures
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Set

from flask import Flask, render_template, request, jsonify, make_response
import requests
from dotenv import load_dotenv

# Load .env before reading environment variables
load_dotenv()

APP_VERSION = "v4.0"
DEFAULT_SCAN_BLOCKS = 80000  # kept for compatibility, but NOT used as an implicit default range

BASE_RPC_URL = os.getenv("BASE_RPC_URL", "").strip()

CURRENT_RPC_TIMEOUT = 60
CURRENT_CHUNK_SIZE = 2000
CURRENT_WORKERS = 1


TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_ADDR = "0x0000000000000000000000000000000000000000"
DEAD_ADDR = "0x000000000000000000000000000000000000dead"

app = Flask(__name__)

# ------------------------------
# Progress + Cancel (pure in-memory)
# ------------------------------
# NOTE: This does not change snapshot/sorting/filtering logic.
PROGRESS = {
    "state": "idle",            # idle|running|done|error|cancelled
    "phase": "",               # human readable status
    "started_ms": 0,
    "updated_ms": 0,
    "chunks_done": 0,
    "chunks_total": 0,
    "current_range": "",
    "transfers_fetched": 0,
    "eta_seconds": None,
    "error": "",
}

CANCEL_REQUESTED = False


class Cancelled(RuntimeError):
    pass


def _progress_reset():
    global CANCEL_REQUESTED
    CANCEL_REQUESTED = False
    PROGRESS.update({
        "state": "idle",
        "phase": "",
        "started_ms": 0,
        "updated_ms": 0,
        "chunks_done": 0,
        "chunks_total": 0,
        "current_range": "",
        "transfers_fetched": 0,
        "eta_seconds": None,
        "error": "",
    })


def _progress_start(phase: str):
    now = _now_ms()
    PROGRESS.update({
        "state": "running",
        "phase": phase,
        "started_ms": now,
        "updated_ms": now,
        "chunks_done": 0,
        "chunks_total": 0,
        "current_range": "",
        "transfers_fetched": 0,
        "eta_seconds": None,
        "error": "",
    })


def _progress_set(**kwargs):
    PROGRESS.update(kwargs)
    PROGRESS["updated_ms"] = _now_ms()


def _progress_finish(state: str, phase: str = ""):
    PROGRESS["state"] = state
    if phase:
        PROGRESS["phase"] = phase
    PROGRESS["updated_ms"] = _now_ms()


def _check_cancel():
    if CANCEL_REQUESTED:
        raise Cancelled("Cancelled by user")

def _rpc(method: str, params: list, timeout: Optional[int]=None):
    _check_cancel()
    if not BASE_RPC_URL:
        raise RuntimeError("BASE_RPC_URL is not set in .env")
    payload = {"jsonrpc":"2.0","id":1,"method":method,"params":params}
    r = requests.post(BASE_RPC_URL, json=payload, timeout=(timeout if timeout is not None else CURRENT_RPC_TIMEOUT))
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]

def _hex_to_int(h: str) -> int:
    return int(h, 16)

def _int_to_hex(i: int) -> str:
    return hex(i)

def _topic_addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()

def _now_ms():
    return int(time.time() * 1000)


def _get_code_at(contract: str, block_number: int) -> str:
    return _rpc("eth_getCode", [contract, _int_to_hex(block_number)])

def _find_deployment_block(contract: str, hi_block: int) -> int:
    """RPC-only: binary search for first block where contract code exists."""
    _progress_set(phase="Detecting deployment block (RPC)", current_range=f"0 → {hi_block}")
    lo, hi = 0, hi_block
    # quick checks
    if _get_code_at(contract, hi) in ("0x", "0x0", None):
        raise RuntimeError("Contract code not found at end block; is the address correct on Base?")
    if _get_code_at(contract, 0) not in ("0x", "0x0", None):
        return 0
    while lo + 1 < hi:
        _check_cancel()
        mid = (lo + hi)//2
        code = _get_code_at(contract, mid)
        if code in ("0x", "0x0", None):
            lo = mid
        else:
            hi = mid
        _progress_set(phase="Detecting deployment block (RPC)", current_range=f"{lo} → {hi}")
    return hi

def _get_latest_block() -> int:
    return _hex_to_int(_rpc("eth_blockNumber", []))

def _get_block_timestamp(n: int) -> int:
    b = _rpc("eth_getBlockByNumber", [_int_to_hex(n), False])
    return _hex_to_int(b["timestamp"])

def _date_to_ts(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

def _find_block_by_ts(target_ts: int, lo: int, hi: int) -> int:
    while lo < hi:
        mid = (lo + hi) // 2
        ts = _get_block_timestamp(mid)
        if ts < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo

def _block_range_from_dates(start_date: Optional[str], end_date: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not start_date and not end_date:
        return None, None
    latest = _get_latest_block()
    genesis = 0
    st_block = None
    ed_block = None
    if start_date:
        st_ts = _date_to_ts(start_date)
        st_block = _find_block_by_ts(st_ts, genesis, latest)
    if end_date:
        ed_ts = _date_to_ts(end_date) + 24*3600 - 1
        ed_block = _find_block_by_ts(ed_ts, genesis, latest)
    return st_block, ed_block

def _is_contract(addr: str) -> bool:
    code = _rpc("eth_getCode", [addr, "latest"])
    return code not in ("0x", "0x0")

def _get_erc20_decimals(contract: str) -> Optional[int]:
    try:
        res = _rpc("eth_call", [{"to": contract, "data": "0x313ce567"}, "latest"])
        if not res or res == "0x":
            return None
        return int(res, 16)
    except Exception:
        return None

def _parse_amount_tokens(amount_str: str) -> Optional[float]:
    if not amount_str:
        return None
    try:
        return float(amount_str)
    except Exception:
        return None

def _to_raw_units(tokens: float, decimals: int) -> int:
    return int(tokens * (10 ** decimals))

def _chunked_block_ranges(start_block: int, end_block: int, step: int = 2000):
    s = start_block
    while s <= end_block:
        e = min(end_block, s + step - 1)
        yield s, e
        s = e + 1


def _get_logs(contract: str, start_block: int, end_block: int, chunk_size: int, workers: int):
    logs: List[dict] = []
    # Build initial ranges
    ranges = list(_chunked_block_ranges(start_block, end_block, step=chunk_size))
    # We'll use a queue that can grow if we need to split ranges due to RPC limitations.
    q: List[Tuple[int,int]] = ranges[:]
    total_planned = len(q)
    done = 0
    _progress_set(chunks_total=total_planned, chunks_done=0, transfers_fetched=0, current_range=f"{start_block} → {end_block}")

    t0 = time.time()

    def fetch_range(s: int, e: int) -> List[dict]:
        _check_cancel()
        params = [{
            "fromBlock": _int_to_hex(s),
            "toBlock": _int_to_hex(e),
            "address": contract,
            "topics": [TOPIC_TRANSFER]
        }]
        try:
            return _rpc("eth_getLogs", params) or []
        except Exception as ex:
            # If the node returns too many results or times out, split range and retry.
            msg = str(ex).lower()
            if e - s > 50 and ("too many" in msg or "limit" in msg or "timeout" in msg or "response" in msg):
                mid = (s + e)//2
                # indicate that we're splitting; caller will handle re-queue
                raise RuntimeError(f"SPLIT:{s}:{mid}:{mid+1}:{e}")
            raise

    # Concurrency: fetch up to `workers` ranges in parallel.
    workers = max(1, int(workers or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        inflight: Dict[concurrent.futures.Future, Tuple[int,int]] = {}

        def submit_one():
            nonlocal total_planned
            if not q:
                return
            s,e = q.pop(0)
            fut = pool.submit(fetch_range, s, e)
            inflight[fut] = (s,e)

        # prime
        for _ in range(min(workers, len(q))):
            submit_one()

        while inflight:
            _check_cancel()
            done_futs, _ = concurrent.futures.wait(inflight.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done_futs:
                s,e = inflight.pop(fut)
                try:
                    chunk_logs = fut.result()
                    logs.extend(chunk_logs)
                    done += 1
                    total_planned = max(total_planned, done + len(q) + len(inflight))
                    elapsed = max(0.001, time.time() - t0)
                    rate = done / elapsed
                    eta = int((total_planned - done) / rate) if rate > 0 else None
                    _progress_set(
                        phase=f"Fetching Transfer logs (chunk {done}/{total_planned})",
                        current_range=f"{s} → {e}",
                        chunks_done=done,
                        chunks_total=total_planned,
                        transfers_fetched=len(logs),
                        eta_seconds=eta
                    )
                except Exception as ex:
                    msg = str(ex)
                    if msg.startswith("SPLIT:"):
                        _, a,b,c,d = msg.split(":")
                        a,b,c,d = int(a),int(b),int(c),int(d)
                        # Re-queue split ranges (front of queue) to keep progress meaningful
                        q.insert(0, (c,d))
                        q.insert(0, (a,b))
                        total_planned = max(total_planned, done + len(q) + len(inflight))
                        _progress_set(
                            phase="Fetching Transfer logs (splitting range)",
                            current_range=f"{a} → {d}",
                            chunks_done=done,
                            chunks_total=total_planned,
                            transfers_fetched=len(logs),
                        )
                    else:
                        raise

                # Keep pipeline full
                while len(inflight) < workers and q:
                    submit_one()

    return logs


def _get_erc20_decimals(contract: str) -> Optional[int]:
    try:
        res = _rpc("eth_call", [{"to": contract, "data": "0x313ce567"}, "latest"])
        if not res or res == "0x":
            return None
        return int(res, 16)
    except Exception:
        return None

def _parse_amount_tokens(amount_str: str) -> Optional[float]:
    if not amount_str:
        return None
    try:
        return float(amount_str)
    except Exception:
        return None

def _to_raw_units(tokens: float, decimals: int) -> int:
    return int(tokens * (10 ** decimals))

def _chunked_block_ranges(start_block: int, end_block: int, step: int = 2000):
    s = start_block
    while s <= end_block:
        e = min(end_block, s + step - 1)
        yield s, e
        s = e + 1

def _get_logs_serial(contract: str, start_block: int, end_block: int):
    logs = []
    ranges = list(_chunked_block_ranges(start_block, end_block, step=2000))
    total = len(ranges)
    _progress_set(chunks_total=total, chunks_done=0, transfers_fetched=0, current_range=f"{start_block} → {end_block}")

    t0 = time.time()
    for i, (s, e) in enumerate(ranges, start=1):
        _check_cancel()
        _progress_set(phase=f"Fetching Transfer logs (chunk {i}/{total})", current_range=f"{s} → {e}", chunks_done=i-1)
        params = [{
            "fromBlock": _int_to_hex(s),
            "toBlock": _int_to_hex(e),
            "address": contract,
            "topics": [TOPIC_TRANSFER]
        }]
        part = _rpc("eth_getLogs", params)
        logs.extend(part)
        # Update ETA based on average chunk time so far.
        elapsed = max(0.001, time.time() - t0)
        avg = elapsed / i
        remaining = max(0, total - i)
        eta = int(avg * remaining)
        _progress_set(chunks_done=i, transfers_fetched=len(logs), eta_seconds=eta)
    return logs

def _summarize_blocks(start_block: int, end_block: int) -> dict:
    ts_start = _get_block_timestamp(start_block)
    ts_end = _get_block_timestamp(end_block)
    return {
        "start_block": start_block,
        "end_block": end_block,
        "start_time": datetime.fromtimestamp(ts_start, tz=timezone.utc).isoformat(),
        "end_time": datetime.fromtimestamp(ts_end, tz=timezone.utc).isoformat(),
    }

def _compute_erc20_snapshot(transfers: List[dict]):
    balances: Dict[str,int] = {}
    last_recv_block: Dict[str,int] = {}
    first_recv_block: Dict[str,int] = {}
    for lg in transfers:
        topics = lg.get("topics", [])
        if len(topics) < 3:
            continue
        frm = _topic_addr(topics[1])
        to = _topic_addr(topics[2])
        val = _hex_to_int(lg.get("data","0x0"))
        blk = _hex_to_int(lg.get("blockNumber","0x0"))
        if frm != ZERO_ADDR:
            balances[frm] = balances.get(frm,0) - val
        if to != ZERO_ADDR:
            balances[to] = balances.get(to,0) + val
            last_recv_block[to] = max(last_recv_block.get(to,0), blk)
            first_recv_block[to] = min(first_recv_block.get(to,10**18), blk)
    return balances, {"last": last_recv_block, "first": first_recv_block}

def _compute_erc721_snapshot(transfers: List[dict]):
    token_owner: Dict[int,str] = {}
    last_recv_block: Dict[str,int] = {}
    first_recv_block: Dict[str,int] = {}
    for lg in transfers:
        topics = lg.get("topics", [])
        if len(topics) < 4:
            continue
        to = _topic_addr(topics[2])
        token_id = _hex_to_int(topics[3])
        blk = _hex_to_int(lg.get("blockNumber","0x0"))
        token_owner[token_id] = to
        if to != ZERO_ADDR:
            last_recv_block[to] = max(last_recv_block.get(to,0), blk)
            first_recv_block[to] = min(first_recv_block.get(to,10**18), blk)
    counts: Dict[str,int] = {}
    for _, owner in token_owner.items():
        if owner == ZERO_ADDR:
            continue
        counts[owner] = counts.get(owner,0) + 1
    return counts, {"last": last_recv_block, "first": first_recv_block}

def _filter_addresses(addrs: List[str], exclude_zero_dead: bool, exclude_contracts: bool, exclude_set: Set[str]) -> List[str]:
    out = []
    for a in addrs:
        al = a.lower()
        if al in exclude_set:
            continue
        if exclude_zero_dead and al in (ZERO_ADDR, DEAD_ADDR):
            continue
        if exclude_contracts:
            try:
                if _is_contract(al):
                    continue
            except Exception:
                pass
        out.append(al)
    return out

def _rank(address_values: Dict[str,int], meta_blocks: Dict[str,Dict[str,int]], sort_mode: str):
    items = list(address_values.items())
    if sort_mode == "latest":
        items.sort(key=lambda kv: (meta_blocks["last"].get(kv[0],0), kv[1]), reverse=True)
    elif sort_mode == "oldest":
        items.sort(key=lambda kv: (meta_blocks["first"].get(kv[0],10**18), kv[1]))
    else:
        items.sort(key=lambda kv: kv[1], reverse=True)
    return items

def _make_txt(addrs: List[str]) -> bytes:
    return ("\n".join(addrs) + ("\n" if addrs else "")).encode("utf-8")

def _make_csv(rows: List[dict]) -> bytes:
    import io
    buf = io.StringIO()
    if not rows:
        buf.write("address,value\n")
        return buf.getvalue().encode("utf-8")
    fieldnames = list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")

@app.route("/", methods=["GET"])
def index():
    mode = request.args.get("mode","normal")
    if mode not in ("normal","pro"):
        mode = "normal"
    return render_template("index.html", mode=mode, version=APP_VERSION)


@app.route("/api/progress", methods=["GET"])
def api_progress():
    # Lightweight polling endpoint for UI.
    return jsonify({"ok": True, **PROGRESS})


@app.route("/api/cancel", methods=["POST"])
def api_cancel():
    global CANCEL_REQUESTED
    CANCEL_REQUESTED = True
    _progress_set(phase="Cancelling…", state="running")
    return jsonify({"ok": True, "message": "Cancel requested"})

@app.route("/api/export", methods=["POST"])
def export_api():
    _progress_reset()
    _progress_start("Validating input")
    t0 = _now_ms()
    payload = request.get_json(force=True, silent=True) or {}
    asset = (payload.get("asset_type") or "erc721").lower()
    contract = (payload.get("contract_address") or "").strip().lower()
    # No hidden defaults: N must be provided explicitly.
    if payload.get("n") in (None, "", "null"):
        return jsonify({"ok": False, "error": "N is required (how many addresses)."}), 400
    n = int(payload.get("n"))
    token_id = payload.get("token_id")
    sort_mode = payload.get("sort_mode") or "top"
    exclude_zero_dead = bool(payload.get("exclude_zero_dead", True))
    exclude_contracts = bool(payload.get("exclude_contracts", False))
    exclude_addresses = payload.get("exclude_addresses") or ""
    exclude_cex = payload.get("exclude_cex") or []
    snapshot_block = payload.get("snapshot_block")
    min_balance_tokens = payload.get("min_balance_tokens")
    min_nft = int(payload.get("min_nft") or 0)
    out_format = (payload.get("format") or "txt").lower()

    # Performance knobs (optional; no hidden UI defaults)
    global CURRENT_RPC_TIMEOUT, CURRENT_CHUNK_SIZE, CURRENT_WORKERS
    if payload.get("rpc_timeout") not in (None, "", "null"):
        CURRENT_RPC_TIMEOUT = int(payload.get("rpc_timeout"))
    else:
        CURRENT_RPC_TIMEOUT = 60
    if payload.get("chunk_size") not in (None, "", "null"):
        CURRENT_CHUNK_SIZE = int(payload.get("chunk_size"))
    else:
        CURRENT_CHUNK_SIZE = 2000
    if payload.get("workers") not in (None, "", "null"):
        CURRENT_WORKERS = int(payload.get("workers"))
    else:
        CURRENT_WORKERS = 1


    if not contract or not contract.startswith("0x") or len(contract) != 42:
        return jsonify({"ok": False, "error": "Invalid contract address"}), 400

    # No hidden defaults: block/date range must be explicitly provided.
    start_block = None
    end_block = None

    # Explicit block range takes precedence over derived date range.
    if payload.get("start_block") not in (None, "", "null"):
        start_block = int(payload["start_block"])
    if payload.get("end_block") not in (None, "", "null"):
        end_block = int(payload["end_block"])

    start_date = payload.get("start_date")
    if start_date == "YYYY-MM-DD":
        start_date = None
    end_date = payload.get("end_date")
    if end_date == "YYYY-MM-DD":
        end_date = None
    if (start_date or end_date) and (start_block is None and end_block is None):
        _progress_set(phase="Resolving date range → blocks")
        sd, ed = _block_range_from_dates(start_date, end_date)
        start_block = sd if sd is not None else start_block
        end_block = ed if ed is not None else end_block

    if snapshot_block not in (None, "", "null"):
        end_block = int(snapshot_block)

    
    auto_deploy_start = bool(payload.get("auto_deploy_start", False))

    # If user requested it, auto-detect deployment block (RPC) as start block.
    # This preserves 'no hidden defaults' because it only runs when the checkbox is enabled.
    if auto_deploy_start and start_block is None and (not start_date):
        # Need an end block boundary to search within; use resolved end_block.
        if end_block is None:
            return jsonify({"ok": False, "error": "End range is required when using auto-start from deployment block. Provide end block/date or snapshot block."}), 400
        try:
            start_block = _find_deployment_block(contract, int(end_block))
        except Cancelled as e:
            _progress_finish("cancelled", "Cancelled")
            return jsonify({"ok": False, "error": str(e)}), 499
        except Exception as e:
            return jsonify({"ok": False, "error": f"Failed to detect deployment block: {e}"}), 400

    if start_block is None or end_block is None:
        return jsonify({
            "ok": False,
            "error": "Range is required. Provide start+end blocks, OR start/end dates, OR snapshot block (as end) plus a start block/date. No range is assumed automatically."
        }), 400

    if end_block < start_block:
        return jsonify({"ok": False, "error": "end_block must be >= start_block"}), 400

    exclude_set = set(a.strip().lower() for a in exclude_addresses.splitlines() if a.strip())
    # Preset buckets (empty by default; user can paste real addresses)
    CEX = {"coinbase": set(), "binance": set(), "okx": set(), "kraken": set()}
    for k in exclude_cex:
        if k in CEX:
            exclude_set |= CEX[k]

    try:
        _progress_set(phase="Fetching Transfer logs", current_range=f"{start_block} → {end_block}")
        transfers = _get_logs(contract, start_block, end_block, CURRENT_CHUNK_SIZE, CURRENT_WORKERS)
    except Cancelled as e:
        _progress_finish("cancelled", "Cancelled")
        return jsonify({"ok": False, "error": str(e)}), 499
    except Exception as e:
        _progress_finish("error", "Error")
        return jsonify({"ok": False, "error": f"RPC getLogs failed: {e}"}), 500

    transfers_scanned = len(transfers)

    decimals = None
    min_raw = 0

    _progress_set(phase="Computing snapshot")
    if asset == "erc20":
        decimals = _get_erc20_decimals(contract) or 18
        if min_balance_tokens:
            amt = _parse_amount_tokens(str(min_balance_tokens))
            if amt is not None:
                min_raw = _to_raw_units(amt, decimals)
        balances, meta = _compute_erc20_snapshot(transfers)
        values = {a:v for a,v in balances.items() if v and v > 0 and v >= min_raw}
        ranked = _rank(values, meta, sort_mode)
        rows = []
        addrs = []
        for a,v in ranked:
            addrs.append(a)
            rows.append({"address": a, "raw_balance": str(v)})
            if len(addrs) >= n: break
    else:
        counts, meta = _compute_erc721_snapshot(transfers)
        if token_id not in (None, "", "null"):
            try:
                tid = int(token_id)
            except Exception:
                return jsonify({"ok": False, "error": "Token ID must be integer"}), 400
            owner = None
            for lg in transfers:
                topics = lg.get("topics", [])
                if len(topics) >= 4 and _hex_to_int(topics[3]) == tid:
                    owner = _topic_addr(topics[2])
            counts = {owner: 1} if owner and owner != ZERO_ADDR else {}
        values = {a:c for a,c in counts.items() if c and c >= max(1, min_nft)}
        ranked = _rank(values, meta, sort_mode)
        rows = []
        addrs = []
        for a,c in ranked:
            addrs.append(a)
            rows.append({"address": a, "nft_count": str(c)})
            if len(addrs) >= n: break

    _progress_set(phase="Applying filters")
    _progress_set(phase="Applying filters")
    addrs = _filter_addresses(addrs, exclude_zero_dead, exclude_contracts, exclude_set)
    addrset = set(addrs)
    rows = [r for r in rows if r["address"].lower() in addrset]

    summary = _summarize_blocks(start_block, end_block)
    summary.update({
        "asset_type": asset,
        "contract": contract,
        "n_requested": n,
        "holders_returned": len(addrs),
        "transfers_scanned": transfers_scanned,
        "decimals": decimals,
        "min_balance_raw": str(min_raw) if asset == "erc20" else None,
        "runtime_ms": _now_ms() - t0,
    })

    _progress_set(phase="Preparing export file")
    _progress_set(phase="Building export file")
    if out_format == "json":
        content = json.dumps({"summary": summary, "rows": rows}, indent=2).encode("utf-8")
        fname = "holders.json"
    elif out_format == "csv":
        content = _make_csv(rows)
        fname = "holders.csv"
    else:
        content = _make_txt(addrs)
        fname = "holders.txt"

    _progress_finish("done", "Done")
    _progress_finish("done", "Done")

    # For mobile copy/share, return txt content if possible
    txt_content = _make_txt(addrs).decode("utf-8") if addrs else ""
    _progress_finish("done", "Done")
    return jsonify({"ok": True, "summary": summary, "rows": rows[:50], "filename": fname, "content": content.decode("utf-8", errors="ignore"), "txt": txt_content})

@app.route("/download", methods=["POST"])
def download():
    payload = request.get_json(force=True, silent=True) or {}
    content = (payload.get("content") or "").encode("utf-8")
    filename = payload.get("filename") or "holders.txt"
    resp = make_response(content)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(Exception)
def handle_exception(e):
    # For API requests, return JSON so the frontend can display a real error
    if request.path.startswith("/api/"):
        msg = str(e) or e.__class__.__name__
        return jsonify({"ok": False, "error": msg}), 500
    # For non-API routes, re-raise so Flask serves its normal error page
    raise e

if __name__ == "__main__":
    # threaded=True lets the UI poll /api/progress while /api/export is running.
    app.run(host="127.0.0.1", port=int(os.getenv("PORT","8000")), debug=False, threaded=True)
