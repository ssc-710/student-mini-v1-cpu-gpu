/* student-mini release report: hash router, panorama interaction and lazily rendered detail views.
   Routes: #/  #/node/<id>  #/records/<platform>/<operator>  #/case/<platform>/<case>  #/record/<platform>/<ordinal>
   Every view is a history entry, so the browser / mouse Back button returns to the previous view. */
(function () {
  'use strict';
  const G = JSON.parse(document.getElementById('graph').textContent);
  let D = null;
  const data = () => D || (D = JSON.parse(document.getElementById('data').textContent));
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const byId = id => document.getElementById(id);
  const N = G.nodes;
  const X = G.data;
  const pano = $('#pano'), detail = $('#detail'), svg = $('#pano-svg');
  const baseTitle = document.title;
  const esc = s => String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const PLATFORM = { cpu: 'CPU', gpu: 'GPU', accelerator: '加速器' };
  const ETYPE = { data: '数据依赖', gate: '验收门检查', loop: '迭代 / 回环', shared: '共享产物 / 工具', hold: '阻塞 HOLD' };

  // ------------------------------------------------------------------ formatting
  function num(v, d) {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'number') {
      if (Number.isInteger(v)) return Math.abs(v) >= 10000 ? v.toLocaleString('en-US') : String(v);
      return d === undefined ? (Math.abs(v) >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 1 }) : v.toPrecision(5)) : v.toFixed(d);
    }
    return esc(v);
  }
  function dur(s) {
    if (typeof s !== 'number') return '—';
    if (s < 90) return s.toFixed(0) + ' s';
    if (s < 5400) return (s / 60).toFixed(0) + ' min';
    return (s / 3600).toFixed(1) + ' h';
  }
  function bytes(b) {
    b = Number(b);
    if (!isFinite(b)) return '—';
    if (b >= 1e9) return (b / 1e9).toFixed(2) + ' GB';
    if (b >= 1e6) return (b / 1e6).toFixed(1) + ' MB';
    if (b >= 1e3) return (b / 1e3).toFixed(1) + ' kB';
    return b + ' B';
  }
  const gib = b => (typeof b === 'number' ? (b / 2 ** 30).toFixed(2) + ' GiB' : '—');
  function local(iso) {
    if (!iso) return '—';
    const t = new Date(iso);
    if (isNaN(t)) return esc(iso);
    const z = new Date(t.getTime() + 8 * 3600e3);
    return z.toISOString().slice(5, 16).replace('T', ' ');
  }
  function stc(s) {
    s = String(s || '');
    if (s === 'PASS' || s === 'COMPLETE' || /STAGE_PASS|SIGNOFF_PASS|_PASS$/.test(s)) return 'pass';
    if (s === 'NOT_MET' || s === 'FAIL' || /REJECTED|NOT MET|NOT_ACHIEVED|NOT ACHIEVED/.test(s)) return 'fail';
    if (s === 'INFO' || s === 'NA' || s === '') return 'info';
    return 'hold';
  }
  const pill = s => `<span class="st ${stc(s)}">${esc(s === 'NOT_MET' ? 'NOT MET' : s)}</span>`;
  const short = h => (h ? `<span class="mono" title="${esc(h)}">${esc(String(h).slice(0, 12))}…</span>` : '—');
  const title = id => (N[id] ? N[id].title : id);
  const link = (id, text) => `<a href="#/node/${encodeURIComponent(id)}">${esc(text === undefined ? title(id) : text)}</a>`;
  const flink = p => `<a href="${esc(p)}" class="mono">${esc(p)}</a>`;
  function table(head, rows, opts) {
    opts = opts || {};
    const h = head.map(c => `<th${/^(#|bytes|字节|时长|峰值|WNS|hold|DRC|天线|mW|cycles|seed|次数|值)/.test(c) ? ' class="num"' : ''}>${esc(c)}</th>`).join('');
    const body = rows.length ? rows.map(r => '<tr>' + r.map(c => `<td>${c === undefined || c === null ? '—' : c}</td>`).join('') + '</tr>').join('')
      : `<tr><td colspan="${head.length}" class="muted">${esc(opts.empty || '无数据')}</td></tr>`;
    return `<div class="tw"><table${opts.id ? ` id="${opts.id}"` : ''}><thead><tr>${h}</tr></thead><tbody>${body}</tbody></table></div>`;
  }
  const json = v => `<pre>${esc(JSON.stringify(v, null, 2).replace(/\[\s*((?:-?[\d.eE+-]+|"[^"\[\]{}]*"|true|false|null)(?:,\s*(?:-?[\d.eE+-]+|"[^"\[\]{}]*"|true|false|null))*)\s*\]/g, (m, inner) => '[' + inner.replace(/,\s+/g, ', ') + ']'))}</pre>`;

  // ------------------------------------------------------------------ panorama interaction
  if (svg) {
    const edges = $$('.edge', svg);
    const linked = id => {
      const ids = new Set([id]);
      let p = N[id] && N[id].parent;
      while (p) { ids.add(p); p = N[p] && N[p].parent; }
      (N[id] && N[id].children || []).forEach(c => ids.add(c));
      return ids;
    };
    $$('.nd', svg).forEach(nd => {
      nd.addEventListener('mouseenter', () => {
        const ids = linked(nd.dataset.id);
        svg.classList.add('focus');
        nd.classList.add('on');
        edges.forEach(e => {
          if (ids.has(e.dataset.from) || ids.has(e.dataset.to)) {
            e.classList.add('on');
            $$(`.nd[data-id="${CSS.escape(e.dataset.from)}"], .nd[data-id="${CSS.escape(e.dataset.to)}"]`, svg).forEach(n => n.classList.add('on'));
          }
        });
      });
      nd.addEventListener('mouseleave', () => {
        svg.classList.remove('focus');
        $$('.on', svg).forEach(n => n.classList.remove('on'));
      });
    });
    edges.forEach(e => {
      e.addEventListener('mouseenter', () => { svg.classList.add('focus'); e.classList.add('on'); });
      e.addEventListener('mouseleave', () => { svg.classList.remove('focus'); e.classList.remove('on'); });
      e.addEventListener('click', () => { location.hash = '#/node/' + encodeURIComponent(e.dataset.to); });
    });
    $$('.legend', svg).forEach(l => {
      const toggle = () => { svg.classList.toggle('hide-' + l.dataset.type); l.classList.toggle('off'); };
      l.addEventListener('click', toggle);
      l.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } });
    });
  }

  // ------------------------------------------------------------------ theme toggle (per-viewer convenience)
  const themeBtn = $('#theme');
  const themes = ['auto', 'light', 'dark'];
  function applyTheme(t) {
    if (t === 'auto') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t);
    if (themeBtn) themeBtn.textContent = { auto: '◐ 自动', light: '☀ 浅色', dark: '☾ 深色' }[t];
  }
  let theme = 'auto';
  try { theme = localStorage.getItem('student-mini-report-theme') || 'auto'; } catch (e) { /* storage unavailable */ }
  applyTheme(theme);
  if (themeBtn) themeBtn.addEventListener('click', () => {
    theme = themes[(themes.indexOf(theme) + 1) % themes.length];
    applyTheme(theme);
    try { localStorage.setItem('student-mini-report-theme', theme); } catch (e) { /* ignore */ }
  });

  // ------------------------------------------------------------------ router
  let moved = false;
  function route() {
    const h = location.hash.replace(/^#/, '') || '/';
    const parts = h.split('/').filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return showPano();
    let out;
    try {
      if (parts[0] === 'node') out = nodeView(parts.slice(1).join('/'));
      else if (parts[0] === 'records') out = recordsView(parts[1], parts[2]);
      else if (parts[0] === 'case') out = caseView(parts[1], parts.slice(2).join('/'));
      else if (parts[0] === 'record') out = recordView(parts[1], Number(parts[2]));
      else out = { title: '未知视图', html: `<p>没有这个视图：<code>${esc(h)}</code></p>` };
    } catch (err) {
      out = { title: '渲染失败', html: `<p class="FAIL">渲染失败：${esc(err && err.message)}</p><pre>${esc(err && err.stack)}</pre>` };
    }
    showDetail(out);
  }
  function showPano() {
    detail.hidden = true;
    detail.innerHTML = '';
    pano.hidden = false;
    document.body.classList.add('on-pano');
    document.title = baseTitle;
  }
  function showDetail(view) {
    pano.hidden = true;
    document.body.classList.remove('on-pano');
    const crumbs = (view.crumbs || []).map(c => (c[0] ? `<a href="${esc(c[0])}">${esc(c[1])}</a>` : esc(c[1]))).join(' › ');
    detail.innerHTML = `<div class="topbar"><a href="#/" data-back>← 后退</a><a href="#/">⌂ 全景</a><span class="crumbs"><a href="#/">全景</a>${crumbs ? ' › ' + crumbs : ''}</span></div>${view.html}`;
    detail.hidden = false;
    document.title = (view.title || '详情') + ' · ' + baseTitle;
    window.scrollTo(0, 0);
    const back = $('[data-back]', detail);
    back.addEventListener('click', ev => { if (moved) { ev.preventDefault(); history.back(); } });
    (view.after || []).forEach(f => f());
  }
  window.addEventListener('hashchange', () => { moved = true; route(); });

  // ------------------------------------------------------------------ node views
  function crumbsOf(id) {
    const chain = [];
    let p = N[id] && N[id].parent;
    if (N[id] && !N[id].is_module && N[id].module && N[id].module !== p) chain.unshift(N[id].module);
    while (p) { chain.unshift(p); p = N[p] && N[p].parent; }
    const seen = new Set();
    return chain.filter(c => !seen.has(c) && seen.add(c)).map(c => ['#/node/' + encodeURIComponent(c), title(c)]).concat([[null, title(id)]]);
  }
  function list(items) {
    return items && items.length ? '<ul>' + items.map(i => `<li>${/^(data|physical|power|sources)\/|\.json$|\.csv$|\.md$|\.py$|\.sha256$/.test(i) ? flink(i) : esc(i)}</li>`).join('') + '</ul>' : '<p class="muted">—</p>';
  }
  function nodeView(id) {
    if (id === 'why') return whyView();
    if (id === 'contents') return contentsView();
    if (id === 'disclosures') return { title: 'HOLD 与披露', crumbs: [[null, 'HOLD 与披露']], html: '<h1>HOLD 与披露事项</h1>' + viewHtml({ type: 'disclosures' }) };
    const n = N[id];
    if (!n) return { title: '未知', html: `<p>没有节点 <code>${esc(id)}</code></p>` };
    viewAfter = [];
    const heading = n.name && n.name !== n.title ? (n.name.startsWith(n.title) ? n.name : `${n.name} · ${n.title}`) : n.title;
    let h = `<h1>${n.n ? esc(n.n) + ' · ' : ''}${esc(heading)} ${pill(n.status)}</h1>`;
    h += `<p class="muted">${esc({ module: '模块', step: '步骤', gate: '验收门', hold: '阻塞项', info: '说明' }[n.kind] || n.kind)}${n.lane ? ' · 泳道 ' + esc(laneLabel(n.lane)) : ''} · id <code>${esc(id)}</code></p>`;
    if (n.kpi && n.kpi.length) h += '<div class="kpis">' + n.kpi.map(k => `<span>${esc(k)}</span>`).join('') + '</div>';
    h += '<div class="cards">';
    h += `<div class="card" style="grid-column:1/-1"><h4>做了什么</h4><p>${esc(n.desc || '—')}</p></div>`;
    if (n.inputs) h += `<div class="card"><h4>输入</h4>${list(n.inputs)}</div>`;
    if (n.outputs) h += `<div class="card"><h4>输出</h4>${list(n.outputs)}</div>`;
    if (n.files) h += `<div class="card"><h4>包内文件（相对链接）</h4>${list(n.files)}</div>`;
    h += '</div>';
    if (n.children && n.children.length) {
      h += `<h2>${n.is_module ? '子模块' : '子步骤'}（${n.children.length}）</h2><div class="cards">` + n.children.map(c => {
        const m = N[c];
        return `<a class="card" href="#/node/${encodeURIComponent(c)}"><b>${esc(m.title)} ${pill(m.status)}</b><small>${esc((m.kpi || []).join(' · '))}</small></a>`;
      }).join('') + '</div>';
    }
    if (n.attempts) h += attemptsHtml(n.attempts);
    h += relatedHtml(id);
    (n.views || []).forEach(v => { h += viewHtml(v); });
    if (n.notes && n.notes.length) {
      h += `<h2>开发记录摘录（${esc(G.notes_path)}）</h2>` + n.notes.map(b => `<blockquote>${esc(b.text)}<div class="src">${esc(G.notes_path)} ${esc(b.lines)}</div></blockquote>`).join('');
    }
    if (n.guard && n.guard.length) h += guardHtml(n.guard, n.is_module ? '本模块全部受限运行记录' : '受限运行记录（2 vCPU / 8 GiB 护栏）');
    else if (!n.is_module) h += `<h2>受限运行记录</h2><p class="muted">本步骤没有绑定护栏记录（${n.attempts ? '见上方尝试表' : '该步骤不在护栏中运行或证据中无法匹配'}）。</p>`;
    const after = [];
    if (n.evidence && n.evidence.length) { h += evidenceHtml(n.evidence, 'ev-' + id); after.push(() => bindEvidence('ev-' + id, n.evidence)); }
    return { title: n.title, crumbs: crumbsOf(id).slice(0, -1).concat([[null, n.title]]), html: h, after: after.concat(viewAfter) };
  }
  let viewAfter = [];
  function laneLabel(l) { const x = (G.lanes || []).find(a => a.id === l); return x ? x.label : l; }
  function relatedHtml(id) {
    const ins = G.edges.filter(e => e.to === id && e.from !== id), outs = G.edges.filter(e => e.from === id && e.to !== id), self = G.edges.filter(e => e.from === id && e.to === id);
    const row = (e, other, dir) => `<li><span class="etype ${e.type}"></span>${esc(ETYPE[e.type])} ${dir} ${link(other)}${e.label ? ' — ' + esc(e.label) : ''}${e.count_value !== null && e.count_value !== undefined ? ` <b>×${esc(e.count_value)}</b> ${esc(e.unit || '')}` : ''}</li>`;
    let h = '<h2>相关步骤</h2><div class="cards">';
    const n = N[id];
    const up = [];
    if (n.parent) up.push(`上级：${link(n.parent)}`);
    if (n.module && n.module !== id && n.module !== n.parent) up.push(`模块：${link(n.module)}`);
    if (up.length) h += `<div class="card"><h4>层级</h4><p>${up.join('<br>')}</p></div>`;
    if (ins.length) h += `<div class="card"><h4>上游（指向本步骤）</h4><ul class="rel">${ins.map(e => row(e, e.from, '←')).join('')}</ul></div>`;
    if (outs.length) h += `<div class="card"><h4>下游（本步骤指向）</h4><ul class="rel">${outs.map(e => row(e, e.to, '→')).join('')}</ul></div>`;
    if (self.length) h += `<div class="card"><h4>自身迭代</h4><ul class="rel">${self.map(e => `<li><span class="etype loop"></span>${esc(e.label || '迭代')} <b>×${esc(e.count_value === null || e.count_value === undefined ? '?' : e.count_value)}</b> ${esc(e.unit || '')}</li>`).join('')}</ul></div>`;
    if (!up.length && !ins.length && !outs.length && !self.length) h += '<p class="muted">无连线。</p>';
    return h + '</div>';
  }
  function outcomeText(o) { const t = o ? [o.status, o.stage, o.reason].filter(Boolean).join(': ') : ''; return t ? esc(t) : '—'; }
  function attemptsHtml(rows) {
    let total = 0;
    rows.forEach(r => { total += r.elapsed || 0; });
    let h = `<h2>迭代与尝试（${rows.length} 次，累计 ${dur(total)}）</h2>`;
    h += table(['#', '尝试', '状态', '开始 (+08:00)', '时长', '峰值', '退出码', '结论（证据）', 'guard 记录 / 运行目录'], rows.map((r, i) => [
      i + 1, `<span style="white-space:nowrap">${esc(r.label)}</span>`, pill(r.status), local(r.created_at), dur(r.elapsed) + (r.elapsed_basis && r.elapsed_basis !== 'guard record' ? `<br><small class="muted">${esc(r.elapsed_basis)}</small>` : ''),
      gib(r.peak), num(r.exit_code),
      esc(r.result || '') + (r.completion_reason ? `<br><small class="muted">completion: ${esc(r.completion_status)} — ${esc(r.completion_reason)}</small>` : '') +
        (r.outcome && outcomeText(r.outcome) !== '—' ? `<br><small class="muted">日志：${outcomeText(r.outcome)}</small>` : '') + (r.mem ? `<br><small class="muted">memory.events max ${num(r.mem.max)} · oom ${num(r.mem.oom)} · oom_kill ${num(r.mem.oom_kill)}</small>` : ''),
      `<span class="mono">${esc(r.guard || '—')}</span>${r.guard_kind === 'log' ? ' <small class="muted">（仅日志，无 guard 记录）</small>' : ''}${r.guard_sha256 ? '<br>SHA-256 ' + short(r.guard_sha256) : ''}${r.work ? `<br><small class="mono">${esc(r.work)}</small>` : ''}`
    ]));
    rows.forEach(r => { (r.notes || []).forEach(b => { h += `<blockquote><b>${esc(r.label)}</b>：${esc(b.text)}<div class="src">${esc(G.notes_path)} ${esc(b.lines)}</div></blockquote>`; }); });
    return h;
  }
  function guardHtml(names, heading) {
    const rows = names.map(n => G.guards[n]).filter(Boolean);
    let total = 0, pass = 0, first = null, last = null;
    rows.forEach(r => {
      total += r.elapsed || 0; if (r.status === 'PASS') pass++;
      if (r.start) { first = first === null ? r.start : Math.min(first, r.start); last = last === null ? r.start + (r.elapsed || 0) : Math.max(last, r.start + (r.elapsed || 0)); }
    });
    let h = `<h2>${esc(heading)}（${rows.length} 条：PASS ${pass} · 其他 ${rows.length - pass}）</h2>`;
    h += `<p class="note">累计受限运行时间 ${dur(total)}${first !== null ? `；墙钟跨度 ${dur(last - first)}（${local(new Date(first * 1000).toISOString())} → ${local(new Date(last * 1000).toISOString())}）；并行任务使累计时间可以大于跨度` : ''}。记录目录：<code>${esc(G.env_dir)}</code>；“包内”表示记录同时复制到了 data/resources/。</p>`;
    h += table(['记录', '状态', '开始 (+08:00)', '时长', '峰值', '退出码', '子进程结果 / 原因', '脚本', '包内', 'SHA-256'], rows.map(r => [
      `<span class="mono">${esc(r.name)}</span>${r.kind === 'log' ? '<br><small class="muted">仅日志，无 guard 记录</small>' : ''}`, pill(r.status), r.kind === 'log' ? `<small class="muted">日志 ${local(r.log_mtime)}</small>` : local(r.created_at),
      dur(r.elapsed), gib(r.peak), num(r.exit_code), outcomeText(r.outcome) + (r.mem && (r.mem.max || r.mem.oom_kill) ? `<br><small class="muted">memory.max ${num(r.mem.max)} · oom_kill ${num(r.mem.oom_kill)}</small>` : ''),
      `<span class="mono">${esc(r.script || '')}</span>`, r.in_package ? flink('data/resources/' + r.name.split('/').pop()) : '—', short(r.sha256)
    ]));
    return h;
  }
  // ---- evidence browser
  function evidenceRows(prefixes) {
    const ev = X.evidence;
    if (!ev) return [];
    return ev.files.filter(f => !prefixes || prefixes.some(p => f[0].startsWith(p)));
  }
  function evidenceHtml(prefixes, key) {
    const rows = evidenceRows(prefixes);
    return `<h2>证据文件（evidence-index.json，${rows.length} 个${prefixes ? '，前缀 ' + prefixes.map(p => `<code>${esc(p)}</code>`).join(' ') : ''}）</h2>
      <p class="note">SHA-256 为包内文件；“源 SHA-256”为压缩前源字节（verify_release.py 复核两者）。别名指向内容相同、只打包一次的文件。</p>
      <div class="filter"><input id="${key}-q" placeholder="筛选路径" size="40"><span class="muted" id="${key}-n"></span></div><div id="${key}-t"></div>`;
  }
  function bindEvidence(key, prefixes) {
    const all = evidenceRows(prefixes);
    let limit = 300;
    const draw = () => {
      const q = (byId(key + '-q') || {}).value || '';
      const rows = all.filter(f => f[0].toLowerCase().includes(q.toLowerCase()));
      byId(key + '-n').textContent = `${rows.length} 个匹配` + (rows.length > limit ? `，显示前 ${limit}` : '');
      byId(key + '-t').innerHTML = table(['路径', '字节', 'SHA-256', '源 SHA-256', '源字节', '别名指向'], rows.slice(0, limit).map(f => [
        flink(f[0]), num(f[1]), short(f[2]), short(f[3]), num(f[4]), f[5] ? flink(f[5]) : '—'])) +
        (rows.length > limit ? '<button class="more">显示更多</button>' : '');
      const more = byId(key + '-t').querySelector('.more');
      if (more) more.addEventListener('click', () => { limit += 1000; draw(); });
    };
    byId(key + '-q').addEventListener('input', () => { limit = 300; draw(); });
    draw();
  }

  // ------------------------------------------------------------------ data views (declared in the graph file)
  function phys(impl) { return (X.physical || {})[impl]; }
  function powerRows(impl) {
    const p = phys(impl);
    return p && p.power && p.power.records ? p.power.records : [];
  }
  const mw = r => (r.total_mw !== undefined && r.total_mw !== null ? r.total_mw : (r.power_w || 0) * 1000);
  function viewHtml(v) {
    const t = v.type;
    const T = v.title ? `<h3>${esc(v.title)}</h3>` : '';
    switch (t) {
      case 'json':
        return (T || '<h3>数据</h3>') + (v.data === null || v.data === undefined ? `<p class="muted">该数据不在本包中（${esc(v.src)}）。</p>` : json(v.data));
      case 'baselines': {
        const b = (X.summary.baselines || []);
        return '<h2>baseline 汇总（data/summary/baselines.csv）</h2>' + table(['平台', '算子', '状态', '记录', '通过', 'case', '平均 cycles', '物理实现', '功耗（seed 均值）', '功耗 seed 数'],
          b.map(r => [`<a href="#/records/${r.platform}/${r.operator}">${esc(PLATFORM[r.platform] || r.platform)}</a>`, esc(r.operator.toUpperCase()), pill(r.status), num(r.records), num(r.passed), `${r.cases_passed}/${r.cases}`, num(r.mean_cycles), esc(r.physical), esc(r.power), num(r.power_seeds)])) +
          `<p class="note">CSV：${flink('data/summary/baselines.csv')} · ${flink('data/summary/cases.csv')} · ${flink('data/summary/power_per_seed.csv')}</p>`;
      }
      case 'records_index':
        return '<h2>逐条记录入口</h2><p>' + (X.summary.baselines || []).map(r => `<a href="#/records/${r.platform}/${r.operator}">${esc(PLATFORM[r.platform] || r.platform)} ${esc(r.operator.toUpperCase())}</a>`).join(' · ') + '</p>';
      case 'records':
        return `<h2>${esc(PLATFORM[v.platform] || v.platform)} 全部 case</h2><p>` + ['p1', 'p2', 'p3'].map(op => `<a href="#/records/${v.platform}/${op}">${op.toUpperCase()} 的 case 与逐 seed 记录 →</a>`).join(' · ') +
          `</p><p class="note">原始数据：${flink('data/records/' + v.platform + '.jsonl')} · ${flink('data/arrays/' + v.platform + '.npz')} · ${flink('data/summary/cases.csv')}</p>`;
      case 'case_matrix': {
        const cases = (data().cases || {})[Object.keys(data().cases || {})[0]] || [];
        return '<h2>展开 case 列表（每个 case × seed 1–10）</h2>' + table(['case', '算子', '场景', '期望状态'], cases.map(c => [esc(c.case_id), esc(c.operator), esc(c.scenario), esc(c.expected_status)]));
      }
      case 'physical_table':
        return '<h2>物理实现与签核</h2>' + table(['实现', 'route 状态', '频率 MHz', 'WNS ns', 'hold WNS ns', 'DRC', '天线 nets', '功耗状态', '功耗 seed 数'],
          Object.entries(X.physical || {}).map(([k, p]) => { const m = (p.route || {}).metrics || {}; return [link(k.startsWith('accelerator') ? 'phys.acc.' + k.split('-')[1] : 'phys.' + k + '.top', k), pill((p.route || {}).status), num((p.frequency_hz || 0) / 1e6), num(m.wns_ns, 3), num(m.hold_wns_ns, 3), num(m.drc), num(m.antenna_nets), pill((p.power || {}).status), num(((p.power || {}).records || []).length)]; }));
      case 'physical': {
        const p = phys(v.impl);
        if (!p) return `<p class="muted">本包没有 ${esc(v.impl)} 的物理实现。</p>`;
        const r = p.route || {}, m = r.metrics || {};
        let h = `<h2>${esc(v.impl)} 物理签核（data/summary/physical.json）</h2>` + table(['项目', '值'], [
          ['状态', pill(r.status)], ['时钟', num(m.clock_period_ns) + ' ns / ' + num((p.frequency_hz || 0) / 1e6) + ' MHz'], ['setup WNS', num(m.wns_ns, 4) + ' ns'],
          ['hold WNS', num(m.hold_wns_ns, 4) + ' ns'], ['DRC', num(m.drc)], ['天线 nets / pins', num(m.antenna_nets) + ' / ' + num(m.antenna_pins)],
          ['结果目录', `<span class="mono">${esc(r.result_directory || '—')}</span>`]]);
        if (r.macro_audit) h += '<h3>宏审计</h3>' + json(r.macro_audit);
        if (r.report_metrics) h += '<h3>ORFS 报告指标</h3>' + json(r.report_metrics);
        if (r.macro_pin_access) h += `<p>宏 pin 访问：<code>${esc(r.macro_pin_access)}</code></p>`;
        if (r.rom_banks) h += `<p>ROM bank：${num(r.rom_banks_passed)}/${r.rom_banks.length} PASS → ${link('phys.cpu.rombank')}</p>`;
        return h;
      }
      case 'stages': {
        const s = v.data || {};
        const max = Math.max(1, ...Object.values(s).filter(x => typeof x === 'number'));
        const sum = Object.values(s).filter(x => typeof x === 'number').reduce((a, b) => a + b, 0);
        return `<h2>ORFS 阶段耗时（${esc(v.src)}）</h2><div class="bars">` + Object.entries(s).map(([k, x]) => `<span class="mono">${esc(k)}</span><div class="b" style="width:${(100 * x / max).toFixed(1)}%"></div><span>${dur(x)}</span>`).join('') +
          `</div><p class="note">ORFS 阶段合计 ${dur(sum)}；整个受限运行 ${dur(v.elapsed_value)}${typeof v.elapsed_value === 'number' ? `，其余 ${dur(v.elapsed_value - sum)} 为独立进程的天线修复轮次、finish 与审计（由运行总时长减去阶段时长得出）` : ''}。</p>`;
      }
      case 'antenna': {
        const rows = v.data || [];
        return `<h2>${esc(v.title || '天线修复轮次')}</h2>` + (rows.length ? table(['轮', '模式', '修复前 nets', '修复后 nets', 'DRC 后', '插入二极管', '峰值', '接受', '日志'], rows.map(r => [num(r.round), esc(r.mode || 'default'), num(r.antenna_nets_before), num(r.antenna_nets_after), num(r.drc_after), num(r.diodes_inserted), gib(r.peak_rss_bytes), r.accepted ? '<span class="PASS">是</span>' : '<span class="HOLD">否</span>', `<span class="mono">${esc(r.log || '')}</span>`]))
          : `<p class="muted">无数据（${esc(v.src)}）</p>`);
      }
      case 'rom_banks': {
        const r = (phys('cpu') || {}).route || {};
        return '<h2>25 个 ROM bank 逐块验收</h2>' + table(['bank', '设计', '状态', 'DRC', '天线 nets', 'WNS ns', 'hold WNS ns', 'completion'], (r.rom_banks || []).map(b => [num(b.bank), `<span class="mono">${esc(b.design)}</span>`, pill(b.status), num(b.drc), num(b.antenna_nets), num(b.wns_ns, 3), num(b.hold_wns_ns, 3), flink(`physical/cpu/rom-bank-${String(b.bank).padStart(2, '0')}/completion.json`)]));
      }
      case 'power': {
        const p = phys(v.impl);
        if (!p || !p.power) return `<p class="muted">本包没有 ${esc(v.impl)} 的功耗。</p>`;
        const rows = powerRows(v.impl);
        const mean = rows.length ? rows.reduce((a, r) => a + mw(r), 0) / rows.length : null;
        const corner = p.power.corner || {};
        return `<h2>${esc(v.impl)} 逐 seed 功耗（${pill(p.power.status)}，均值 ${num(mean, 3)} mW）</h2><p class="note">工艺角 ${esc(corner.process || '')} ${esc(corner.voltage_v || '')} V ${esc(corner.temperature_c || '')} °C · ${num((p.power.frequency_hz || 0) / 1e6)} MHz · 窗口：${esc(p.power.window || '')}${p.power.boundary ? ' · 边界：' + esc(p.power.boundary) : ''}</p>` +
          table(['算子', 'case', 'seed', '总功耗 mW', '动态 mW', '漏电 mW', '能量 J', '窗口 ns', '标注率 %', '未标注 pins', '活动 SHA-256', '网表 SHA-256', 'SPEF SHA-256'], rows.map(r => [esc(r.operator), esc(r.case_id), num(r.seed), num(mw(r), 3), num(r.dynamic_mw, 3), num(r.leakage_mw, 5), num(r.energy_j), num((r.end_ns || 0) - (r.begin_ns || 0)), num(r.annotation_percent, 3), num(r.unannotated_pins), short(r.activity_sha256), short(r.netlist_sha256), short(r.spef_sha256)]));
      }
      case 'nano': {
        const s = ((X.nano || {})[v.platform] || {}).sessions || [];
        return `<h2>${esc(PLATFORM[v.platform] || v.platform)} NanoChat 会话（12 个冻结测试问题）</h2>` + table(['#', '问题', '领域', '期望回答', '状态', 'token 数', '后端', '会话 SHA-256', '会话文件'], s.map(r => [num(r.index), esc(r.question), esc(r.domain), esc(r.expected_text), pill(r.status), num((r.tokens || []).length), esc(r.backend), short(r.session_sha256), `<small class="mono">${esc(r.session || '')}</small>`])) +
          `<p class="note">逐 token 与 PTQ 参考 ${flink('data/nano/sessions.json')} 比对。</p>`;
      }
      case 'resources': {
        const rows = (X.resources || []).slice();
        if (v.sort === 'peak') rows.sort((a, b) => (b.memory_peak_bytes || 0) - (a.memory_peak_bytes || 0));
        return `<h2>本包引用的受限运行（data/resources，${rows.length} 条）</h2>` + table(['记录', '状态', 'CPU', '内存上限', '峰值', 'memory.max', 'oom_kill', '时长', '退出码'], rows.map(r => [flink('data/resources/' + r.record), pill(r.status), num(r.cpu_limit), gib(r.memory_limit_bytes), gib(r.memory_peak_bytes), num((r.memory_events || {}).max), num((r.memory_events || {}).oom_kill), dur(r.elapsed_seconds), num(r.exit_code)]));
      }
      case 'disclosures': {
        let rows = X.summary.disclosures || [];
        if (v.kind) rows = rows.filter(d => d.kind === v.kind);
        if (v.match) rows = rows.filter(d => (d.text || '').includes(v.match));
        return `<h2>HOLD 与披露（release.json disclosures${v.kind ? ' · ' + esc(v.kind) : ''}，${rows.length} 项）</h2>` + table(['类别', '对象', '状态', '说明'], rows.map(d => [esc(d.kind), esc(d.item), pill(d.status || 'INFO'), esc(d.text)]));
      }
      case 'candidates': {
        const c = X.candidates || {};
        return `<h2>四层候选（data/candidates.json，${(c.candidates || []).length} 个）</h2><p class="note">${esc(c.description || '')}</p>` + table(['平台', '算子', '层', '状态', 'PROMOTE', '父 baseline'], (c.candidates || []).map(x => [esc(x.platform), esc(x.operator), esc(x.layer), pill(x.status), x.promote ? '是' : '否', esc(x.parent)]));
      }
      case 'tools': {
        const b = ((X.spec || {}).tools || {}).binaries || [];
        return `<h2>工具二进制（SPEC.json tools.binaries，${b.length} 个）</h2>` + table(['路径', '版本输出', '当前 SHA-256', '与记录一致', '绑定的运行数'], b.map(x => [`<span class="mono">${esc(x.path)}</span>`, esc(x.version), short(x.current), x.matches ? '<span class="PASS">是</span>' : '<span class="FAIL">否</span>', num(x.bound_by_count)]));
      }
      case 'flow_files': {
        const f = ((X.spec || {}).tools || {}).flow_and_pdk_files || [];
        return `<h2>流程与 PDK 文件（SPEC.json tools.flow_and_pdk_files，${f.length} 个）</h2>` + table(['路径', '当前 SHA-256', '与记录一致', '绑定的运行数'], f.map(x => [`<span class="mono">${esc(x.path)}</span>`, short(x.current), x.matches ? '<span class="PASS">是</span>' : '<span class="FAIL">否</span>', num(x.bound_by_count)]));
      }
      case 'measurements': {
        const m = X.measure || {};
        const dep = m.dependencies || {};
        const runs = (m.runs || {}).directories || {};
        return `<h2>软件依赖与磁盘（data/resources/resource-measurements.json）</h2><pre>${esc(m.method || '')}</pre>` +
          table(['依赖树', '字节'], Object.entries(dep.trees || {}).map(([k, x]) => [esc(k), bytes(x)]).concat([['APT 包合计', bytes((dep.apt || {}).total_bytes)], ['<b>依赖合计</b>', '<b>' + bytes(dep.total_bytes) + '</b>']])) +
          `<h3>证据运行目录（${Object.keys(runs).length} 个，合计 ${bytes((m.runs || {}).total_bytes)}）</h3>` + table(['目录', '字节'], Object.entries(runs).sort((a, b) => b[1] - a[1]).slice(0, 40).map(([k, x]) => [`<span class="mono">${esc(k)}</span>`, bytes(x)]));
      }
      case 'model_card': {
        const m = X.model_card || {};
        const cls = (m.parameters || {}).classes || {};
        return `<h2>NanoChat 模型卡（${flink('data/nano/model-card.json')}，${pill(m.status)}）</h2>` + table(['权重类别', '张量数', '元素', '字节'], Object.entries(cls).map(([k, x]) => [esc(k), num(x.tensors), num(x.elements), num(x.bytes)]).concat([['<b>合计参数</b>', '', '<b>' + num((m.parameters || {}).total) + '</b>', '']])) +
          '<h3>部署（checkpoint / 导出 SHA）</h3>' + json(m.deployment) + '<h3>模型形状</h3>' + json(m.model_shape);
      }
      case 'omitted': {
        const o = (X.evidence || {}).omitted || [];
        return `<h2>未打包的证据（${o.length} 个，SHA-256 仍在 evidence-index.json 与 profile.json 中）</h2>` + table(['路径', '字节', 'SHA-256', '原因'], o.map(x => [`<span class="mono">${esc(x.path)}</span>`, num(x.bytes), short(x.sha256), esc(x.reason)]));
      }
      case 'evidence_all': {
        viewAfter = [() => bindEvidence('ev-all', null)];
        return evidenceHtml(null, 'ev-all');
      }
      case 'packaging_runs': {
        const r = X.packaging_runs || [];
        return `<h2>本计划的装配记录（package-report.json，${r.length} 次；本次装配的记录在报告写入之后产生）</h2>` + table(['package-report.json', '状态', 'ZIP 字节', '解压字节', '干净解压清单', '校验器退出码 / 问题数', '失败原因'], r.map(x => [`<span class="mono">${esc(x.path)}</span>`, pill(x.status), num(x.zip_bytes), num(x.expanded_bytes), x.clean_unzip_manifest_ok ? '<span class="PASS">一致</span>' : '—', `${num(x.verifier_exit)} / ${num(x.problems)}`, esc((x.failures || []).join('; ') || '—')]));
      }
      case 'package_contents': {
        const c = X.package_contents || [];
        return `<h2>包内容（渲染时测得，report.html / release.json / MANIFEST 除外，合计 ${bytes(X.package_bytes)}）</h2>` + table(['目录 / 文件', '文件数', '字节'], c.map(x => [flink(x.path), num(x.files), bytes(x.bytes)]));
      }
      case 'gates': {
        const g = X.summary.gates || {};
        return '<h2>发布门（release.json gates）</h2>' + table(['门', '结果'], Object.entries(g).map(([k, ok]) => [`<span class="mono">${esc(k)}</span>`, ok ? '<span class="PASS">PASS</span>' : '<span class="FAIL">NOT MET</span>']));
      }
      case 'gpu_components': {
        const r = (phys('gpu') || {}).route || {};
        return '<h2>GPU 分块与顶层（block + top；时序以全芯片 STA 为准）</h2>' + table(['组件', '角色', '状态', 'DRC', '天线 nets', 'budget setup ns', 'budget hold ns'], (r.components || []).map(c => [esc(c.design), esc(c.role), pill(c.status), num(c.drc), num(c.antenna_nets), num(c.budget_setup_ws_ns, 3), num(c.budget_hold_ws_ns, 3)]), { empty: '本包没有 GPU 分块数据' });
      }
      case 'fullchip_sta': {
        const s = ((phys('gpu') || {}).route || {}).fullchip_sta;
        return '<h2>GPU 全芯片 STA 签核</h2>' + (s ? json(s) : '<p class="muted">本包没有全芯片 STA 数据。</p>');
      }
      case 'partition': {
        const s = ((phys('gpu') || {}).route || {}).partition;
        return '<h2>GPU 冻结分割</h2>' + (s ? json(s) : '<p class="muted">本包没有分割数据。</p>');
      }
      default:
        return `<p class="muted">未知视图类型 ${esc(t)}</p>`;
    }
  }

  // ------------------------------------------------------------------ panels: time and contents
  function whyView() {
    const t = G.time || {};
    let h = `<h1>为什么用了这么久？</h1><div class="kpis"><span>开始 ${local(t.start)}（SPEC implementation_started_at）</span><span>本次装配 ${local(t.end)}</span><span>历时 <b>${dur(t.elapsed)}</b>（${(t.elapsed / 86400).toFixed(1)} 天）</span><span>目标 ${dur(t.deadline)} ${pill('NOT_MET')}</span></div>`;
    h += '<p>一小时目标从实施开始计时，包含修改、训练、运行、验证和打包（task.md §1、§5）。下面的数字全部来自护栏记录（每个受限任务一条，含失败尝试）、运行目录的 completion.json / heartbeat.json 与开发记录 NOTES.md。</p>';
    h += '<h2>主要耗时（受限运行累计，含失败尝试）</h2>' + table(['环节', '累计', '次数', '依据', ''], (t.sinks || []).map(s => [esc(s.label), dur(s.seconds), num(s.count), '<small>' + (s.basis || []).map(esc).join('<br>') + '</small>', link(s.node, '详情 →')]));
    h += '<h2>根因</h2><ol>' + (t.causes || []).map(c => `<li>${esc(c.text)} — ${link(c.node, '证据 →')}</li>`).join('') + '</ol>';
    h += '<h2>各模块的受限运行</h2>' + table(['模块', '记录数', '累计', '墙钟跨度', 'PASS', '其他'], G.modules.map(m => {
      const rows = (t.modules[m] || []).map(n => G.guards[n]).filter(Boolean);
      const starts = rows.filter(r => r.start);
      const span = starts.length ? Math.max(...starts.map(r => r.start + (r.elapsed || 0))) - Math.min(...starts.map(r => r.start)) : null;
      return [link(m), num(rows.length), dur(rows.reduce((a, r) => a + (r.elapsed || 0), 0)), dur(span), num(rows.filter(r => r.status === 'PASS').length), num(rows.filter(r => r.status !== 'PASS').length)];
    }));
    h += `<p class="note">护栏目录共 ${num(G.env_records_total)} 条记录；以上只统计流程图各步骤绑定（与本课程相关）的记录，GPU 课程的记录不计入。探索性运行（在护栏外的 8 线程开发机上）没有护栏记录，只在 NOTES.md 中描述，其耗时无法从证据中统计。</p>`;
    const all = [];
    G.modules.forEach(m => (t.modules[m] || []).forEach(n => { if (G.guards[n]) all.push([m, G.guards[n]]); }));
    all.sort((a, b) => (a[1].start || 9e12) - (b[1].start || 9e12));
    h += `<h2>全部相关受限运行（按时间，${all.length} 条）</h2>` + table(['开始 (+08:00)', '模块', '记录', '状态', '时长', '峰值', '结果'], all.map(([m, r]) => [r.kind === 'log' ? '<small class="muted">仅日志</small>' : local(r.created_at), `<span style="white-space:nowrap">${link(m, N[m].short || N[m].title)}</span>`, `<span class="mono">${esc(r.name)}</span>`, pill(r.status), dur(r.elapsed), gib(r.peak), outcomeText(r.outcome)]));
    return { title: '为什么用了这么久', crumbs: [[null, '时间分析']], html: h };
  }
  function contentsView() {
    let h = `<h1>包里有什么 · 达成了什么 ${pill(X.summary.status)}</h1>`;
    const c = X.summary.course || {};
    h += `<p>课程 <b>${esc(c.name || '三平台')}</b>（spec route ${esc(c.spec_route || '—')}）· 平台 ${esc((c.platforms || []).join(', '))} · 物理实现 ${esc((c.implementations || []).join(', '))}</p>`;
    if (c.excluded_platforms) h += table(['不包含的平台', '说明'], Object.entries(c.excluded_platforms).map(([k, v]) => [esc(k), esc(v)]));
    h += viewHtml({ type: 'baselines' }) + viewHtml({ type: 'gates' }) + viewHtml({ type: 'package_contents' }) + viewHtml({ type: 'packaging_runs' });
    h += '<h2>入口文件</h2><ul>' + ['README.md', 'SPEC.json', 'release.json', 'evidence-index.json', 'MANIFEST.sha256', 'verify_release.py', 'data/summary/baselines.csv', 'data/summary/cases.csv', 'data/summary/power_per_seed.csv', 'data/summary/physical.json', 'data/nano/sessions.json', 'data/candidates.json'].map(f => `<li>${flink(f)}</li>`).join('') + '</ul>';
    (X.sections || []).filter(s => /边界|课程/.test(s.title)).forEach(s => { h += `<h3>${esc(s.title)}</h3>` + (s.text ? `<p>${esc(s.text)}</p>` : '') + (s.rows ? table(s.rows[0].map(String), s.rows.slice(1).map(r => r.map(x => esc(x)))) : ''); });
    h += viewHtml({ type: 'disclosures' });
    return { title: '包内容', crumbs: [[null, '包内容']], html: h };
  }

  // ------------------------------------------------------------------ records drill-down (golden / actual / delta)
  function recordsView(platform, op) {
    const cases = ((data().cases || {})[platform] || []).filter(c => !op || c.operator === op);
    const b = (X.summary.baselines || []).find(x => x.platform === platform && x.operator === op);
    let h = `<h1>${esc(PLATFORM[platform] || platform)} · ${esc((op || '').toUpperCase())} ${b ? pill(b.status) : ''}</h1>`;
    if (b) h += `<div class="kpis"><span>记录 ${b.passed}/${b.records} PASS</span><span>case ${b.cases_passed}/${b.cases}</span><span>平均 ${num(b.mean_cycles)} cycles</span><span>功耗 ${esc(b.power)}（${b.power_seeds} seed 均值）</span><span>物理实现 ${esc(b.physical)}</span></div>`;
    h += `<p class="note">每个 case 执行 seed 1–10；任一 seed 失败则 case 失败。原始数据 ${flink('data/records/' + platform + '.jsonl')} · ${flink('data/arrays/' + platform + '.npz')} · ${flink('data/summary/cases.csv')}</p>`;
    h += '<div class="filter"><input id="cq" placeholder="筛选 case / 场景" size="30"><select id="cs"><option value="">全部状态</option><option>PASS</option><option>HOLD</option><option>FAIL</option></select></div>';
    h += table(['case', '场景', '期望状态', '状态', '失败 seed', 'max |Δ|', 'MAE', 'RMSE', 'bit mismatch', 'cycles 均值'], cases.map(c => [
      `<a href="#/case/${platform}/${encodeURIComponent(c.case_id)}">${esc(c.case_id)}</a>`, esc(c.scenario), esc(c.expected_status), pill(c.status), esc((c.failed_seeds || []).join(',') || '—'),
      num(c.max_absolute_delta), num(c.mean_absolute_error), num(c.rmse), num(c.bit_mismatch_count), num(c.cycles_mean)]), { id: 'ct' });
    const filter = () => {
      const q = $('#cq').value.toLowerCase(), s = $('#cs').value;
      $$('#ct tbody tr').forEach(tr => { const txt = tr.textContent.toLowerCase(); tr.style.display = (txt.includes(q) && (!s || txt.includes(s.toLowerCase()))) ? '' : 'none'; });
    };
    return { title: `${platform} ${op}`, crumbs: [['#/node/base.gate', 'Baseline'], [null, `${PLATFORM[platform] || platform} ${(op || '').toUpperCase()}`]], html: h,
      after: [() => { $('#cq').addEventListener('input', filter); $('#cs').addEventListener('change', filter); }] };
  }
  function caseView(platform, caseId) {
    const recs = (data().records[platform] || []).filter(r => r.case === caseId).sort((a, b) => a.seed - b.seed);
    const c = ((data().cases || {})[platform] || []).find(x => x.case_id === caseId) || {};
    let h = `<h1>${esc(PLATFORM[platform] || platform)} · ${esc(caseId)} ${pill(c.status)}</h1><p class="muted">场景 ${esc(c.scenario)} · 期望状态 ${esc(c.expected_status)}</p>`;
    h += table(['seed', '状态', '期望 / 实际状态', 'max |Δ|', 'MAE', 'RMSE', 'bit mismatch', 'cycles', ''], recs.map(r => [num(r.seed), pill(r.status), `${esc(r.expected_status)} / ${esc(r.actual_status)}`, num(r.max_abs), num(r.mae), num(r.rmse), num(r.mismatch), num(r.cycles), `<a href="#/record/${platform}/${r.ordinal}">输入 · golden · actual · Δ →</a>`]));
    return { title: caseId, crumbs: [['#/node/base.gate', 'Baseline'], [`#/records/${platform}/${c.operator || ''}`, `${PLATFORM[platform] || platform} ${(c.operator || '').toUpperCase()}`], [null, caseId]], html: h };
  }
  function recordView(platform, ordinal) {
    const r = (data().records[platform] || []).find(x => x.ordinal === ordinal);
    if (!r) return { title: '记录', html: '<p>没有这条记录。</p>' };
    const hex = v => (typeof v === 'number' ? '0x' + v.toString(16).padStart(4, '0') : '—');
    const rows = (r.golden_bits || []).map((g, i) => [num(i), `<span class="mono">${hex(g)}</span>`, num(r.golden[i]), `<span class="mono">${r.actual_bits ? hex(r.actual_bits[i]) : '—'}</span>`, r.actual ? num(r.actual[i]) : '—', r.delta ? num(r.delta[i]) : '—']);
    let h = `<h1>${esc(PLATFORM[platform] || platform)} · ${esc(r.case)} · seed ${r.seed} ${pill(r.status)}</h1>`;
    h += `<p>记录 ordinal ${r.ordinal} · 期望状态 ${esc(r.expected_status)}，实际 ${esc(r.actual_status)} · 来源 <code>${esc(r.source)}</code>${r.main ? ' · 协议 case：比对的是协议运行，主执行另存于 main_execution' : ''}</p>`;
    h += '<h2>输入</h2>' + json(data().inputs[r.ordinal]);
    h += '<h2>golden vs actual（逐元素）</h2>' + table(['#', 'golden 位', 'golden 值', 'actual 位', 'actual 值', 'signed Δ'], rows, { empty: '错误状态 case：没有输出载荷' });
    h += '<h2>期望事件 → 证据</h2>';
    const ev = r.events;
    h += ev ? table(['期望事件', '状态', '证据'], (ev.expected_events || []).map(e => [esc(e), ev.actual_events[e] ? '<span class="PASS">已确认</span>' : '<span class="HOLD">缺失</span>', esc(ev.actual_events[e] || '—')])) : '<p class="muted">无事件记录</p>';
    h += '<h2>计数器</h2>' + json(r.counters);
    return { title: `${r.case} seed ${r.seed}`, crumbs: [['#/node/base.gate', 'Baseline'], [`#/case/${platform}/${encodeURIComponent(r.case)}`, r.case], [null, 'seed ' + r.seed]], html: h };
  }

  route();
})();
