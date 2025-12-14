
window.addEventListener('load', ()=>{
  const form = q("exportForm");
  if(!form) return;
  // Clear all fields on load (no hidden defaults)
  form.querySelectorAll('input, textarea, select').forEach(el=>{
    if(el.tagName.toLowerCase()==='select'){
      el.selectedIndex = 0;
    }else if(el.type==='checkbox' || el.type==='radio'){
      el.checked = false;
    }else{
      el.value = '';
    }
    el.setAttribute('autocomplete','off');
  });
});


async function postJSON(url, data){
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(data)
  });
  const j = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(j.error || ("HTTP " + res.status));
  return j;
}
function q(id){ return document.getElementById(id); }
function setStatus(msg){ q("status").textContent = msg || ""; }

function showProgress(show){
  const wrap = q("progressWrap");
  if(!wrap) return;
  wrap.style.display = show ? "block" : "none";
}

function renderProgress(p){
  const fill = q("progressFill");
  const line = q("progressLine");
  const sub = q("progressSub");

  if(!fill || !line || !sub) return;

  const total = Number(p.chunks_total || 0);
  const done = Number(p.chunks_done || 0);
  const transfers = Number(p.transfers_fetched || 0);
  const eta = (p.eta_seconds === null || p.eta_seconds === undefined) ? null : Number(p.eta_seconds);
  const range = p.current_range || "";
  const phase = p.phase || "";
  const state = p.state || "idle";

  // percent
  if(total > 0){
    const pct = Math.max(0, Math.min(100, Math.floor((done/total) * 100)));
    fill.classList.remove("indeterminate");
    fill.style.width = pct + "%";
    line.textContent = `${phase}  •  ${pct}%  (${done}/${total} chunks)`;
  }else{
    fill.classList.add("indeterminate");
    fill.style.width = "40%";
    line.textContent = phase || "Working…";
  }

  const etaTxt = (eta === null) ? "ETA: …" : `ETA: ~${eta}s`;
  const transfersTxt = `Transfers: ${transfers.toLocaleString()}`;
  const rangeTxt = range ? `Blocks: ${range}` : "";
  sub.textContent = [etaTxt, transfersTxt, rangeTxt].filter(Boolean).join("  •  ");

  // show/hide based on state
  if(state === "running"){
    showProgress(true);
  }
}

function startProgressPolling(){
  showProgress(true);
  let stopped = false;
  const tick = async ()=>{
    if(stopped) return;
    try{
      const res = await fetch("/api/progress", {cache:"no-store"});
      const p = await res.json();
      if(p && p.ok) renderProgress(p);
    }catch(e){
      // ignore polling errors; export request might still be running
    }
  };
  tick();
  const id = setInterval(tick, 650);
  return ()=>{ stopped = true; clearInterval(id); showProgress(false); };
}

function setSummary(summary){
  const wrap = q("summary");
  const grid = q("summaryGrid");
  grid.innerHTML = "";
  const entries = [
    ["asset", summary.asset_type],
    ["contract", summary.contract],
    ["holders", summary.holders_returned + " / " + summary.n_requested],
    ["transfers scanned", summary.transfers_scanned],
    ["blocks", summary.start_block + " → " + summary.end_block],
    ["time", summary.start_time + " → " + summary.end_time],
    ["runtime", summary.runtime_ms + " ms"],
  ];
  if(summary.decimals !== null && summary.decimals !== undefined){
    entries.push(["decimals", summary.decimals]);
  }
  if(summary.min_balance_raw){
    entries.push(["min raw", summary.min_balance_raw]);
  }
  for(const [k,v] of entries){
    const div = document.createElement("div");
    div.className = "kv";
    div.innerHTML = `<span>${k}</span><span>${String(v)}</span>`;
    grid.appendChild(div);
  }
  wrap.style.display = "block";
}
function setPreview(rows){
  const pre = q("previewPre");
  pre.textContent = JSON.stringify(rows, null, 2);
  q("preview").style.display = "block";
}

function collectCex(){
  return Array.from(document.querySelectorAll(".cexBox"))
    .filter(b=>b.checked)
    .map(b=>b.value);
}

let lastTxtContent = "";
let lastFilename = "holders.txt";

async function downloadText(filename, content){
  const res = await fetch("/download", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({filename, content})
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 2000);
}

async function copyList(){
  if(!lastTxtContent) return;
  await navigator.clipboard.writeText(lastTxtContent);
  setStatus("Copied to clipboard ✅");
}

async function shareList(){
  if(!lastTxtContent) return;
  if(navigator.share){
    try{
      const file = new File([lastTxtContent], lastFilename, {type:"text/plain"});
      await navigator.share({title:lastFilename, text:"Holders list", files:[file]});
      setStatus("Shared ✅");
    }catch(e){
      setStatus("Share cancelled.");
    }
  }else{
    setStatus("Share not supported on this browser.");
  }
}

function toggleFields(){
  const asset = q("assetType").value;
  const mode = window.__MODE__ || "normal";
  if(mode === "pro"){
    const token = q("tokenIdWrap"); if(token) token.style.display = (asset === "erc721") ? "block" : "none";
    const mb = q("minBalWrap"); if(mb) mb.style.display = (asset === "erc20") ? "block" : "none";
    const mn = q("minNftWrap"); if(mn) mn.style.display = (asset === "erc721") ? "block" : "none";
  }
}

document.addEventListener("DOMContentLoaded", ()=>{
  // Hard clear all fields on page load to avoid browser autofill or stale values.
  // This matches the requirement: all inputs empty by default (placeholders only).
  document.querySelectorAll("input, textarea, select").forEach((el)=>{
    if(el.tagName.toLowerCase() === "select"){
      el.selectedIndex = 0; // select placeholder option
    }else if(el.type === "checkbox" || el.type === "radio"){
      el.checked = false;
    }else{
      el.value = "";
    }
    el.setAttribute("autocomplete","off");
  });

  toggleFields();
  q("assetType").addEventListener("change", toggleFields);

  q("copyBtn").addEventListener("click", copyList);
  q("shareBtn").addEventListener("click", shareList);

  const cancelBtn = q("cancelBtn");
  if(cancelBtn){
    cancelBtn.addEventListener("click", async ()=>{
      try{
        await fetch("/api/cancel", {method:"POST"});
        setStatus("Cancelling…");
      }catch(e){
        setStatus("Cancel request failed.");
      }
    });
  }

  q("exportForm").addEventListener("submit", async (e)=>{
    e.preventDefault();
    setStatus("Running… (large ranges can take time)");
    q("summary").style.display = "none";
    q("preview").style.display = "none";
    q("copyBtn").disabled = true;
    q("shareBtn").disabled = true;

    const mode = window.__MODE__ || "normal";
    const data = {
      asset_type: q("assetType").value,
      contract_address: q("contractAddress").value.trim(),
      n: q("n").value ? Number(q("n").value) : null,
      start_block: q("startBlock").value ? Number(q("startBlock").value) : null,
      end_block: q("endBlock").value ? Number(q("endBlock").value) : null,
      start_date: q("startDate").value.trim() || null,
      end_date: q("endDate").value.trim() || null,
      exclude_addresses: q("excludeAddresses").value || "",
      exclude_zero_dead: q("excludeZeroDead").checked
    };

    if(mode === "pro"){
      data.sort_mode = q("sortMode").value;
      data.auto_deploy_start = q("autoDeployStart") ? q("autoDeployStart").checked : false;
      data.token_id = q("tokenId").value.trim() || null;
      data.min_balance_tokens = q("minBalance").value.trim() || null;
      data.min_nft = q("minNft").value ? Number(q("minNft").value) : 0;
      data.exclude_contracts = q("excludeContracts").checked;
      data.exclude_cex = collectCex();
      data.snapshot_block = q("snapshotBlock").value ? Number(q("snapshotBlock").value) : null;
      data.format = q("format").value;
      data.chunk_size = q("chunkSize") && q("chunkSize").value ? Number(q("chunkSize").value) : null;
      data.workers = q("workers") && q("workers").value ? Number(q("workers").value) : null;
      data.rpc_timeout = q("rpcTimeout") && q("rpcTimeout").value ? Number(q("rpcTimeout").value) : null;
    } else {
      data.sort_mode = "top";
      data.format = "txt";
    }

    const stopPoll = startProgressPolling();
    try{
      if(!data.asset_type){
        throw new Error("Select asset type (ERC-20 or ERC-721).\n");
      }
      if(!data.n){
        throw new Error("N is required.");
      }
      const out = await postJSON("/api/export", data);
      setStatus(`Done. Holders: ${out.summary.holders_returned}. Downloading…`);
      setSummary(out.summary);
      setPreview(out.rows);

      lastTxtContent = out.txt || "";
      lastFilename = out.filename || "holders.txt";

      q("copyBtn").disabled = !navigator.clipboard;
      q("shareBtn").disabled = !navigator.share;

      await downloadText(lastFilename, lastTxtContent);
    }catch(err){
      setStatus("Error: " + err.message);
    }finally{
      stopPoll();
    }
  });
});
