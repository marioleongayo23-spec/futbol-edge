// Cliente Supabase + hook de sesión. Login por enlace mágico (email), sin
// contraseñas. Si faltan las claves (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY),
// la app corre en modo abierto para poder probarla antes de configurar Supabase.

import { createClient } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

const URL = import.meta.env.VITE_SUPABASE_URL;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
// Email autorizado (solo tú). Si se define, solo esa cuenta entra.
export const ALLOWED_EMAIL = import.meta.env.VITE_ALLOWED_EMAIL || "";

export const authEnabled = Boolean(URL && KEY);
export const supabase = authEnabled ? createClient(URL, KEY) : null;

export function useSession() {
  const [session, setSession] = useState(null);
  const [ready, setReady] = useState(!authEnabled);
  useEffect(() => {
    if (!authEnabled) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);
  return { session, ready };
}

export async function sendMagicLink(email) {
  return supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.origin },
  });
}

export async function signOut() {
  if (supabase) await supabase.auth.signOut();
}
