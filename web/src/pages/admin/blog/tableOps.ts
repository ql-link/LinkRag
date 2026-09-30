/** 表格网格的纯函数操作：行 0 视为表头 */
export interface Grid {
  head: string[];
  rows: string[][];
}

const all = (g: Grid) => [g.head, ...g.rows];
const fromAll = (rows: string[][]): Grid => ({ head: rows[0] ?? [''], rows: rows.slice(1) });

export function setCell(g: Grid, r: number, c: number, v: string): Grid {
  return fromAll(all(g).map((row, i) => (i === r ? row.map((x, j) => (j === c ? v : x)) : row)));
}

export function insertRow(g: Grid, at: number): Grid {
  const rows = all(g);
  const at1 = Math.max(1, Math.min(at, rows.length)); // 不在表头上方插入
  return fromAll([...rows.slice(0, at1), Array<string>(g.head.length).fill(''), ...rows.slice(at1)]);
}

export function removeRow(g: Grid, r: number): Grid {
  if (r === 0 || g.rows.length <= 1) return g;
  return fromAll(all(g).filter((_, i) => i !== r));
}

export function insertCol(g: Grid, at: number): Grid {
  return fromAll(all(g).map((row) => [...row.slice(0, at), '', ...row.slice(at)]));
}

export function removeCol(g: Grid, c: number): Grid {
  if (g.head.length <= 1) return g;
  return fromAll(all(g).map((row) => row.filter((_, j) => j !== c)));
}
