
(function () {
  const el = document.getElementById("typed");
  if (!el) return;

  const mode = window.__MODE__ || "normal";
  const lines = mode === "pro" ? [
    "export --mode pro --asset ERC-20|ERC-721 --contract 0x... --n 1000",
    "pro: sort=latest/oldest, snapshot_block=exact, exclude_contracts=1",
    "pro: min_balance(tokens), min_nft(count), export=txt|csv|json"
  ] : [
    "export --mode normal --asset ERC-20|ERC-721 --contract 0x... --n 1000",
    "normal: set a date range or start block if holders are missing",
    "ready. paste contract and hit EXECUTE"
  ];

  let line = 0, i = 0, deleting = false;
  const typeSpeed = 45;
  const delSpeed  = 22;
  const holdTime  = 1200;
  const nextTime  = 600;

  function tick() {
    const text = lines[line];
    if (!deleting) {
      i++;
      el.textContent = text.slice(0, i);
      if (i >= text.length) {
        deleting = true;
        return setTimeout(tick, holdTime);
      }
      return setTimeout(tick, typeSpeed);
    } else {
      i--;
      el.textContent = text.slice(0, Math.max(0,i));
      if (i <= 0) {
        deleting = false;
        line = (line + 1) % lines.length;
        return setTimeout(tick, nextTime);
      }
      return setTimeout(tick, delSpeed);
    }
  }
  tick();
})();
