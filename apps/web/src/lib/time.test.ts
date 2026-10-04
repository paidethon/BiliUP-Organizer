// T1/T2 (frontend side): display formatting is Shanghai-fixed regardless of
// host timezone, and week helpers are Monday-first. The node test runner runs
// in the host TZ by default, which is exactly the "viewer timezone varies"
// condition these tests must survive.

import { describe, expect, it } from "vitest";
import {
  addDays,
  formatDateShanghai,
  formatDateTimeShanghai,
  humanDuration,
  mondayOf,
  parseStamp,
  relativeTime,
  toISODate,
} from "./time";

describe("parseStamp", () => {
  it("treats naive stamps as UTC (storage convention)", () => {
    const d = parseStamp("2026-09-27 16:00:00")!;
    expect(d.toISOString()).toBe("2026-09-27T16:00:00.000Z");
  });

  it("parses ISO stamps with explicit offsets unchanged", () => {
    expect(parseStamp("2026-09-28T00:00:00+08:00")!.toISOString()).toBe(
      "2026-09-27T16:00:00.000Z"
    );
    expect(parseStamp("2026-09-27T16:00:00Z")!.toISOString()).toBe(
      "2026-09-27T16:00:00.000Z"
    );
  });

  it("returns null for garbage", () => {
    expect(parseStamp("not a date")).toBeNull();
    expect(parseStamp(null)).toBeNull();
  });
});

describe("Shanghai display formatting (T1)", () => {
  it("formats the same instant identically for every input offset", () => {
    // same absolute instant expressed three ways
    expect(formatDateTimeShanghai("2026-09-27 16:00:00")).toBe(
      formatDateTimeShanghai("2026-09-28T00:00:00+08:00")
    );
    // Shanghai absolute time for that instant is 2026-09-28 00:00
    expect(formatDateTimeShanghai("2026-09-27 16:00:00")).toMatch(
      /^2026-09-28 00:00/
    );
  });

  it("date-only formatting", () => {
    expect(formatDateShanghai("2026-09-27 16:00:00")).toBe("2026-09-28");
  });
});

describe("week helpers (T2)", () => {
  it("mondayOf is Monday-first", () => {
    // 2026-09-28 is a Monday; 2026-10-04 is its Sunday
    const monday = new Date(2026, 8, 28);
    const sunday = new Date(2026, 9, 4);
    expect(toISODate(mondayOf(monday))).toBe("2026-09-28");
    expect(toISODate(mondayOf(sunday))).toBe("2026-09-28");
  });

  it("addDays crosses month boundaries", () => {
    expect(toISODate(addDays(new Date(2026, 8, 30), 1))).toBe("2026-10-01");
  });
});

describe("humanDuration", () => {
  it("renders hours/minutes/seconds", () => {
    expect(humanDuration(3600)).toBe("1 小时 0 分钟");
    expect(humanDuration(300)).toBe("5 分钟");
    expect(humanDuration(42)).toBe("42 秒");
    expect(humanDuration(null)).toBe("0 秒");
  });
});

describe("relativeTime", () => {
  it("classifies past and future", () => {
    const now = Date.parse("2026-10-04T10:00:00Z");
    expect(relativeTime("2026-10-04 09:59:30", now)).toBe("刚刚");
    expect(relativeTime("2026-10-04 08:00:00", now)).toBe("2 小时前");
    expect(relativeTime("2026-10-04 11:00:00", now)).toBe("1 小时后");
  });
});
