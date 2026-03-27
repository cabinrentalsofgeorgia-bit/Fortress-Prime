"use client";

import { useEffect } from "react";

const BODY_CLASSES = ["html", "front", "not-logged-in", "no-sidebars", "page-node"];

export function LegacyBodyClasses() {
  useEffect(() => {
    document.body.classList.add(...BODY_CLASSES);

    return () => {
      document.body.classList.remove(...BODY_CLASSES);
    };
  }, []);

  return null;
}
