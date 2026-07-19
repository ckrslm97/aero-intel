"use client";

import { useState } from "react";

import { TailIcon } from "@/components/tail-icon";

/** The carrier's real logo, on its brand-coloured square, from a public
 * airline-logo CDN. Verified for all ten carriers we show (1.7-5.7KB each).
 *
 * Falls back to our own drawn tail fin if the image doesn't load: the CDN is
 * outside our control, and a chip must never render empty. The images are
 * lazy and same-sized, so a failure costs nothing but the fallback.
 */
const LOGO_BASE = "https://pics.avs.io/al_square/128/128";

export function AirlineLogo({
  code,
  name,
  className = "size-4",
}: {
  code: string;
  name?: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <TailIcon code={code} className={className} />;
  }

  return (
    /* eslint-disable-next-line @next/next/no-img-element --
       next/image would route this through the optimizer for no gain: these are
       already tiny (1.7-5.7KB), fixed-size, third-party PNGs. */
    <img
      src={`${LOGO_BASE}/${code}.png`}
      alt={name ? `${name} logosu` : code}
      width={16}
      height={16}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={`${className} rounded-[3px] object-contain`}
    />
  );
}
