import { useEffect, useState } from "react";

/*
 * Which section the reader is currently in.
 *
 * The three parts of a report are one continuous document rather than three tab panels, so
 * the rail has to follow the scroll instead of being told what is showing. This is a scroll
 * listener rather than an IntersectionObserver on purpose: the question is not "which
 * sections are visible" (usually two, sometimes three) but "which one has most recently
 * passed under the rail", and that is a comparison of tops against one line, which an
 * observer makes harder rather than easier.
 */
export function useSpy(ids: readonly string[], offset: number): string {
  const key = ids.join(",");
  const [active, setActive] = useState<string>(ids[0] ?? "");

  useEffect(() => {
    const list = key ? key.split(",") : [];
    if (list.length === 0) return;

    const pick = () => {
      let current = list[0] as string;
      for (const id of list) {
        const el = document.getElementById(id);
        // A section claims the rail once its heading has reached the underside of it.
        if (el && el.getBoundingClientRect().top - offset <= 1) current = id;
      }
      // At the very bottom the last section may be too short to ever cross the line, so it
      // would otherwise be unreachable however far you scrolled.
      const atEnd =
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
      if (atEnd) current = list[list.length - 1] as string;
      setActive(current);
    };

    pick();
    window.addEventListener("scroll", pick, { passive: true });
    window.addEventListener("resize", pick);
    return () => {
      window.removeEventListener("scroll", pick);
      window.removeEventListener("resize", pick);
    };
  }, [key, offset]);

  return active;
}
