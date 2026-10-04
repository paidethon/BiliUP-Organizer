// CSV export must neutralize spreadsheet formula injection (T14).

import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";

describe("toCsv formula-injection guard", () => {
  it("prefixes risky leading characters with a quote", () => {
    const csv = toCsv([["=cmd()", "+1", "-2", "@x", "\tT"]]);
    for (const cell of ["'=cmd()", "'+1", "'-2", "'@x", "'\tT"]) {
      expect(csv).toContain(cell);
    }
  });

  it("leaves safe text untouched and quotes commas via proper joining", () => {
    expect(toCsv([["正常标题", 12]])).toBe("\uFEFF正常标题,12\r\n");
  });

  it("renders null as empty cell", () => {
    expect(toCsv([[null, undefined]])).toBe("\uFEFF,\r\n");
  });

  it("includes BOM and header row", () => {
    const csv = toCsv([["a", 1]], ["列A", "列B"]);
    expect(csv.startsWith("\uFEFF列A,列B\r\n")).toBe(true);
    expect(csv.endsWith("a,1\r\n")).toBe(true);
  });
});
