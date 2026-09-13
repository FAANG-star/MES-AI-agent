import { describe, expect, it } from "vitest";

import {
  formatDay,
  isValidZone,
  offsetMinutes,
  relativeToFactory,
  resolveViewerZone,
  wallClock,
  zoneCity,
} from "@/lib/timezone";

// 15:30 UTC on Sunday 13 September 2026: already Monday in Tokyo, still
// Sunday in Shanghai. The instant this whole feature exists to handle.
const MIDNIGHT_IN_TOKYO = new Date("2026-09-13T15:30:00Z");

describe("reading a clock in a given zone", () => {
  it("gives the same instant a different wall time and date per zone", () => {
    expect(wallClock(MIDNIGHT_IN_TOKYO, "Asia/Tokyo")).toMatchObject({ date: "2026-09-14", time: "00:30" });
    expect(wallClock(MIDNIGHT_IN_TOKYO, "Asia/Shanghai")).toMatchObject({ date: "2026-09-13", time: "23:30" });
    expect(wallClock(MIDNIGHT_IN_TOKYO, "America/New_York")).toMatchObject({ date: "2026-09-13", time: "11:30" });
  });

  it("does not depend on the zone of the machine running it", () => {
    // The explicit zone is the only one that matters; the test runner's own
    // TZ must not leak into what a factory clock reads.
    expect(wallClock(MIDNIGHT_IN_TOKYO, "UTC")).toMatchObject({ date: "2026-09-13", time: "15:30" });
  });

  it("reports offsets, including half hours and daylight saving", () => {
    expect(offsetMinutes(MIDNIGHT_IN_TOKYO, "Asia/Tokyo")).toBe(540);
    expect(offsetMinutes(MIDNIGHT_IN_TOKYO, "Asia/Kolkata")).toBe(330);
    expect(offsetMinutes(MIDNIGHT_IN_TOKYO, "UTC")).toBe(0);
    // New York is on daylight time in September (UTC−4) and standard in January (UTC−5).
    expect(offsetMinutes(MIDNIGHT_IN_TOKYO, "America/New_York")).toBe(-240);
    expect(offsetMinutes(new Date("2026-01-15T12:00:00Z"), "America/New_York")).toBe(-300);
  });
});

describe("saying how the viewer's clock relates to the factory's", () => {
  it("says so when they match", () => {
    expect(relativeToFactory(MIDNIGHT_IN_TOKYO, "Asia/Tokyo", "Asia/Tokyo")).toBe("same time as the factory");
  });

  it("says behind or ahead, in hours and minutes", () => {
    expect(relativeToFactory(MIDNIGHT_IN_TOKYO, "Asia/Shanghai", "Asia/Tokyo")).toBe("1 h behind the factory");
    expect(relativeToFactory(MIDNIGHT_IN_TOKYO, "Asia/Kolkata", "Asia/Tokyo")).toBe("3 h 30 min behind the factory");
    expect(relativeToFactory(MIDNIGHT_IN_TOKYO, "Asia/Tokyo", "Asia/Shanghai")).toBe("1 h ahead of the factory");
  });
});

describe("choosing the viewer's zone", () => {
  it("accepts real IANA zones only", () => {
    expect(isValidZone("Asia/Shanghai")).toBe(true);
    expect(isValidZone("UTC")).toBe(true);
    expect(isValidZone("China")).toBe(false);
    expect(isValidZone("")).toBe(false);
    expect(isValidZone(null)).toBe(false);
  });

  it("uses a stored choice, or falls back to the device when there is none or it is broken", () => {
    expect(resolveViewerZone("Asia/Shanghai", "Europe/Berlin")).toBe("Asia/Shanghai");
    expect(resolveViewerZone(null, "Europe/Berlin")).toBe("Europe/Berlin");
    expect(resolveViewerZone("Mars/Olympus", "Europe/Berlin")).toBe("Europe/Berlin");
  });
});

describe("labels", () => {
  it("names a zone by its city", () => {
    expect(zoneCity("Asia/Shanghai")).toBe("Shanghai");
    expect(zoneCity("America/Argentina/Buenos_Aires")).toBe("Buenos Aires");
    expect(zoneCity("UTC")).toBe("UTC");
  });

  it("writes a calendar day without letting a zone shift it", () => {
    expect(formatDay("2026-09-14")).toBe("Mon 14 Sep");
    expect(formatDay("2026-09-13")).toBe("Sun 13 Sep");
    expect(formatDay("2026-01-01")).toBe("Thu 1 Jan");
  });
});
