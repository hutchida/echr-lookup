"use client";

import { useEffect } from "react";

/**
 * Marks the element named by the URL hash as highlighted (`data-highlighted="true"`), scrolls it into
 * view, and follows hash changes. The CSS `:target` styling already works without JS; this adds the
 * scroll and the marker the demo and the capture specs look for.
 */
export function HighlightTarget() {
  useEffect(() => {
    let current: HTMLElement | null = null;
    const apply = () => {
      current?.removeAttribute("data-highlighted");
      current = null;
      const id = decodeURIComponent(window.location.hash.slice(1));
      const el = id ? document.getElementById(id) : null;
      if (!el) return;
      el.setAttribute("data-highlighted", "true");
      el.scrollIntoView({ block: "center" });
      current = el;
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => {
      window.removeEventListener("hashchange", apply);
      current?.removeAttribute("data-highlighted");
    };
  }, []);
  return null;
}
