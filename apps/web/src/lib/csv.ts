// CSV export with formula-injection guard: cells starting with = + - @ (or
// tab/CR) are prefixed with a single quote so spreadsheet apps treat them as
// text instead of executing formulas (T14).

const RISKY = /^[=+\-@\t\r]|^"/;

function safeCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  if (RISKY.test(text)) return `'${text}`;
  return text;
}

export function toCsv(rows: Array<Array<string | number | null | undefined>>, header?: string[]): string {
  const lines: string[] = [];
  if (header) lines.push(header.map(safeCell).join(","));
  for (const row of rows) lines.push(row.map(safeCell).join(","));
  // UTF-8 BOM so Excel opens Chinese labels correctly; CRLF line endings with
  // a trailing terminator per RFC 4180
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}

export function downloadText(filename: string, text: string, mime = "text/csv;charset=utf-8"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.replace(/[\\/:*?"<>|]/g, "_");
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
