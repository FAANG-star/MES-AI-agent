/**
 * Two clocks, kept apart on purpose.
 *
 * The **factory's** time zone decides what "today" and "this week" mean. The
 * shift calendar, the maintenance plan and the production history are all
 * dated in the factory's days, so an answer about "today" must use the
 * factory's today — whoever asks, wherever they are. At 22:00 on Sunday in New
 * York, a factory in Tokyo is already running Monday's shifts; answering with
 * Sunday's rows would be wrong, however local it felt.
 *
 * The **viewer's** time zone decides how times are *shown*. A manager in
 * Shanghai reads clocks in Shanghai time, and is told plainly whenever their
 * calendar day and the factory's differ.
 *
 * Everything here is display arithmetic on instants and calendar labels. None
 * of it touches a factory figure.
 */

export const ZONE_STORAGE_KEY = "mes-copilot-timezone";
export const ZONE_EVENT = "mes-copilot-timezone";

export function isValidZone(zone: string | null | undefined): zone is string {
  if (!zone) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** The zone the viewer's device is set to, or UTC if it cannot say. */
export function deviceZone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return isValidZone(zone) ? zone : "UTC";
  } catch {
    return "UTC";
  }
}

/** A stored choice wins if it is still a real zone; otherwise the device's. */
export function resolveViewerZone(stored: string | null | undefined, device: string): string {
  return isValidZone(stored) ? stored : device;
}

/** Every IANA zone this runtime knows, UTC included. */
export function allZones(): string[] {
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    return zones.includes("UTC") ? zones : ["UTC", ...zones];
  } catch {
    return ["UTC", "Asia/Shanghai", "Asia/Tokyo", "Europe/London", "America/New_York"];
  }
}

export interface WallClock {
  /** ISO calendar date in that zone: "2026-09-14" */
  date: string;
  /** 24-hour wall time: "00:30" */
  time: string;
  /** Offset from UTC: "GMT+9", "GMT+5:30", "GMT" */
  offset: string;
}

/** What a clock on the wall in `zone` reads at `instant`. */
export function wallClock(instant: Date, zone: string): WallClock {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "shortOffset",
  }).formatToParts(instant);

  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";

  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    time: `${get("hour")}:${get("minute")}`,
    offset: get("timeZoneName"),
  };
}

/** Minutes east of UTC for `zone` at `instant` (DST-aware). */
export function offsetMinutes(instant: Date, zone: string): number {
  const match = /GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?/.exec(wallClock(instant, zone).offset);
  if (!match || !match[1]) return 0;
  const minutes = Number(match[2]) * 60 + Number(match[3] ?? 0);
  return match[1] === "-" ? -minutes : minutes;
}

/**
 * How the viewer's clock relates to the factory's, in words:
 * "same time as the factory", "1 h behind the factory",
 * "3 h 30 min ahead of the factory".
 */
export function relativeToFactory(instant: Date, viewer: string, factory: string): string {
  const difference = offsetMinutes(instant, viewer) - offsetMinutes(instant, factory);
  if (difference === 0) return "same time as the factory";
  const absolute = Math.abs(difference);
  const hours = Math.floor(absolute / 60);
  const minutes = absolute % 60;
  const span = [hours ? `${hours} h` : "", minutes ? `${minutes} min` : ""].filter(Boolean).join(" ");
  return difference < 0 ? `${span} behind the factory` : `${span} ahead of the factory`;
}

/** "America/Argentina/Buenos_Aires" → "Buenos Aires" */
export function zoneCity(zone: string): string {
  return (zone.split("/").pop() ?? zone).replaceAll("_", " ");
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * "2026-09-14" → "Mon 14 Sep". A calendar label, read without any zone, so it
 * cannot drift by a day depending on where it is rendered.
 */
export function formatDay(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const utc = new Date(Date.UTC(year, month - 1, day));
  return `${WEEKDAYS[utc.getUTCDay()]} ${day} ${MONTHS[month - 1]}`;
}
