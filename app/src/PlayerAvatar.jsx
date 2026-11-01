import { useEffect, useState } from "react";
import { initials, safePlayerPhoto } from "./mediaIdentity.js";

/** Privacy-safe avatar. A broken remote asset never leaves a blank photograph. */
export default function PlayerAvatar({ name, src, large = false }) {
  const valid = safePlayerPhoto(src);
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [valid]);
  return (
    <span className={"edge-player-avatar" + (large ? " edge-player-avatar-large" : "")} aria-label={name ? `Foto de ${name}` : "Jugador"}>
      {valid && !broken
        ? <img src={valid} alt="" loading="lazy" decoding="async" onError={() => setBroken(true)}/>
        : <span aria-hidden="true">{initials(name)}</span>}
    </span>
  );
}
