import { describe, expect, it } from "vitest";

import { HOME_EYEBROW, HOME_TAGLINE, HOME_TITLE } from "./home";

describe("home page copy", () => {
  it("renders the v0.1 foundation shell, not novel features", () => {
    expect(HOME_TITLE).toBe("Local Novel Studio");
    expect(HOME_EYEBROW).toContain("v0.1.0");
    expect(HOME_TAGLINE).toMatch(/本地优先/);
    expect(HOME_TAGLINE).not.toMatch(/Reader|Import|Memory/);
  });
});
