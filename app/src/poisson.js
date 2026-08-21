// Motor Poisson en cliente: reconstruye cualquier mercado desde el xG (lambdas).

export function pois(k, l) {
  let p = Math.exp(-l);
  for (let i = 1; i <= k; i++) p *= l / i;
  return p;
}

export function matrix(lh, la, mg = 10) {
  const m = [];
  for (let x = 0; x <= mg; x++) {
    m[x] = [];
    for (let y = 0; y <= mg; y++) m[x][y] = pois(x, lh) * pois(y, la);
  }
  let s = 0;
  m.forEach((r) => r.forEach((v) => (s += v)));
  return m.map((r) => r.map((v) => v / s));
}

export function oneXtwo(m) {
  let h = 0, d = 0, a = 0;
  for (let x = 0; x < m.length; x++)
    for (let y = 0; y < m.length; y++) {
      if (x > y) h += m[x][y];
      else if (x === y) d += m[x][y];
      else a += m[x][y];
    }
  return { 1: h, X: d, 2: a };
}

export function over(m, line) {
  let s = 0;
  for (let x = 0; x < m.length; x++)
    for (let y = 0; y < m.length; y++) if (x + y > line) s += m[x][y];
  return s;
}

export function btts(m) {
  let s = 0;
  for (let x = 1; x < m.length; x++)
    for (let y = 1; y < m.length; y++) s += m[x][y];
  return s;
}

export function ah(m, line, side) {
  const f = Math.abs((line * 2) % 1);
  if (Math.abs(f - 0.5) < 1e-9) {
    const a = ah(m, line - 0.25, side), b = ah(m, line + 0.25, side);
    return { win: (a.win + b.win) / 2, push: (a.push + b.push) / 2, lose: (a.lose + b.lose) / 2 };
  }
  let w = 0, p = 0, l = 0;
  for (let x = 0; x < m.length; x++)
    for (let y = 0; y < m.length; y++) {
      const marg = side === "home" ? x - y : y - x;
      const adj = marg + line;
      if (adj > 1e-9) w += m[x][y];
      else if (adj < -1e-9) l += m[x][y];
      else p += m[x][y];
    }
  return { win: w, push: p, lose: l };
}

export function topScores(m, n) {
  const a = [];
  for (let x = 0; x < m.length; x++)
    for (let y = 0; y < m.length; y++) a.push([x, y, m[x][y]]);
  a.sort((p, q) => q[2] - p[2]);
  return a.slice(0, n);
}

export function kelly(p, o) {
  const b = o - 1;
  if (b <= 0) return 0;
  return Math.max(0, (b * p - (1 - p)) / b);
}

export function entropy(pr) {
  return -[pr[1], pr.X, pr[2]].reduce((s, x) => s + (x > 0 ? x * Math.log(x) : 0), 0);
}
