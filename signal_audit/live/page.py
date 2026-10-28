"""The landing page at `/`: what this is, how to connect, what it refuses, and live counts from /stats."""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>signal-audit live</title>
<style>
:root { --bg: #fbfaf7; --fg: #1d1d1b; --muted: #6b6a66; --line: #e4e1da; --card: #ffffff; --accent: #2f5d50;
        --no: #9a3b2e; --code: #f1efe9; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #141413; --fg: #ecebe6; --muted: #9c9a93; --line: #2c2b28; --card: #1c1c1a; --accent: #7fb8a4;
          --no: #e08a7a; --code: #23231f; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 ui-sans-serif, system-ui, -apple-system,
       "Segoe UI", sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 40px 16px 64px; }
h1 { font-size: 28px; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 17px; margin: 36px 0 10px; }
p { margin: 0 0 12px; }
.lead { color: var(--muted); font-size: 17px; }
code, pre { font: 13.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; margin: 0;
      white-space: pre-wrap; word-break: break-all; }
.connect { position: relative; }
button { position: absolute; top: 8px; right: 8px; font: 13px system-ui, sans-serif; padding: 4px 10px;
         border-radius: 6px; border: 1px solid var(--line); background: var(--card); color: var(--fg); cursor: pointer; }
table { width: 100%; border-collapse: collapse; font-size: 14.5px; }
td, th { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 500; font-size: 13px; }
td.no { color: var(--no); white-space: nowrap; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.tile b { display: block; font-size: 22px; font-variant-numeric: tabular-nums; }
.tile span { color: var(--muted); font-size: 13px; }
.layers { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 560px) { .layers { grid-template-columns: 1fr; } }
footer { margin-top: 40px; color: var(--muted); font-size: 13.5px; }
a { color: var(--accent); }
</style>
</head>
<body>
<main>
<h1>signal-audit, live</h1>
<p class="lead">An MCP server that lets any AI agent test a trading signal under rules it cannot bend.
Each session gets its own sandbox, with two synthetic data sets whose answer is known in advance.</p>

<h2>Connect</h2>
<div class="connect"><pre id="cmd">claude mcp add --transport http signal-audit {{MCP_URL}}</pre>
<button onclick="navigator.clipboard.writeText(document.getElementById('cmd').innerText)">Copy</button></div>
<p style="margin-top:10px">Then ask your agent: <em>"Use signal-audit to test whether the A/A+ short labels in
data/planted.csv.gz beat an honest baseline, then do the same for data/null.csv.gz."</em>
The audit should find the planted edge and find nothing in the null world.</p>

<h2>Two layers between an agent and the answer</h2>
<div class="layers">
<div class="tile"><span>The gate</span><p style="margin:4px 0 0">Default-deny on what a call is. Only listed actions
run. It also enforces the per-session budgets.</p></div>
<div class="tile"><span>The rules</span><p style="margin:4px 0 0">Register before scoring, score once, freeze once,
and stay inside your sandbox. This is the same code the local server runs.</p></div>
</div>

<h2>What it refuses</h2>
<table>
<tr><th>Shortcut an agent might take</th><th>Refused by</th></tr>
<tr><td>Score a trial that was never registered</td><td class="no">the rules</td></tr>
<tr><td>Score the same trial again, hoping for a different answer</td><td class="no">the rules</td></tr>
<tr><td>Edit the frozen spec after seeing the result</td><td class="no">the gate</td></tr>
<tr><td>Forge a lock with fresh hashes</td><td class="no">the gate</td></tr>
<tr><td>Rewrite the trial ledger</td><td class="no">the gate</td></tr>
<tr><td>Re-freeze over the old lock</td><td class="no">the rules</td></tr>
<tr><td>Score a new spec under the old lock (swap the data)</td><td class="no">the rules</td></tr>
<tr><td>Read the raw rows before registering (peek at the outcome)</td><td class="no">the gate</td></tr>
<tr><td>Write a script into the sandbox</td><td class="no">the gate</td></tr>
<tr><td>Read another session's ledger (a path outside the sandbox)</td><td class="no">the rules</td></tr>
<tr><td>Ask for 10 million bootstrap draws</td><td class="no">the gate</td></tr>
</table>
<p style="margin-top:10px;color:var(--muted);font-size:14px">Every call, allowed or refused, goes into your
session's hash-chained gate log. The log is kept outside the sandbox, and <code>read_gate_log</code> shows it.</p>

<h2>Since this instance started</h2>
<div class="grid" id="stats">
<div class="tile"><b id="s-sessions">–</b><span>sessions open</span></div>
<div class="tile"><b id="s-calls">–</b><span>tool calls</span></div>
<div class="tile"><b id="s-gate">–</b><span>refused by the gate</span></div>
<div class="tile"><b id="s-rules">–</b><span>refused by the rules</span></div>
<div class="tile"><b id="s-scored">–</b><span>trials scored</span></div>
</div>

<footer>
<p>This runs on a free instance. It sleeps after 15 idle minutes, and the first request wakes it in about a minute.
A sandbox is deleted after 30 idle minutes. Nothing is kept, and no tool can reach the network.</p>
<p>Source and case study: <a href="https://github.com/jarvisss007/signal-audit">github.com/jarvisss007/signal-audit</a>
· v{{VERSION}} · <a href="/stats">/stats</a> · <a href="/health">/health</a></p>
</footer>
</main>
<script>
async function load() {
  try {
    const s = await (await fetch('/stats')).json();
    const scored = Object.keys(s).filter(k => k.startsWith('verdict ')).reduce((a, k) => a + s[k], 0);
    const set = (id, v) => document.getElementById(id).textContent = (v || 0).toLocaleString();
    set('s-sessions', s.sessions_open); set('s-calls', s.calls); set('s-gate', s.refused_by_gate);
    set('s-rules', s.refused_by_rules); set('s-scored', scored);
  } catch (e) {}
}
load(); setInterval(load, 15000);
</script>
</body>
</html>
"""
