import { describe, expect, it } from "vitest";

import { HOME_EYEBROW, HOME_TAGLINE, HOME_TITLE } from "./home";

describe("home page copy", () => {
  it("points authors at paste import for v0.2", () => {
    expect(HOME_TITLE).toBe("Local Novel Studio");
    expect(HOME_EYEBROW).toContain("v0.2.0");
    expect(HOME_TAGLINE).toMatch(/粘贴正文或上传 TXT/);
    expect(HOME_TAGLINE).not.toMatch(/checksum|Snapshot|Milvus/);
  });
});
