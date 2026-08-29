# Monetización — Fútbol Edge

Modelo **freemium por suscripción**. La app es abierta; las funciones de pago
se desbloquean por plan. El cobro es con **Stripe Payment Links** (sin backend
propio) y el plan del usuario vive en los **metadatos de Supabase**.

## Planes y precios

| Plan | Precio | Qué incluye |
|------|--------|-------------|
| **Free** | 0 € | Resultados, clasificación, probabilidades 1X2, previa IA, marcador/goles probables. |
| **Pro** | 12,99 €/mes · 99 €/año | + Value bets con edge, player props, Mi cartera (Kelly), CLV, alertas. |
| **VIP** | 29,99 €/mes · 249 €/año | + Quiniela optimizada, Datos y modelos (calibración/backtest), Champions y Segunda al completo, ranking de value global, exportar. |

El mapa feature→plan está en `src/plans.js` (`FEATURE_PLAN`). Cambiar precios o
qué desbloquea cada plan se hace **solo ahí**.

## Cómo se decide el plan de un usuario

`resolvePlan(session)` en `src/plans.js`:

1. Si el email = `VITE_ALLOWED_EMAIL` → **VIP** (tu cuenta, acceso total).
2. Si Supabase trae `app_metadata.plan` o `user_metadata.plan` (`pro`/`vip`) → ese.
3. Si no → `VITE_DEFAULT_PLAN` (por defecto `free`).

## Puesta en marcha del cobro (una vez)

### 1. Stripe Payment Links
En el panel de Stripe crea un **producto** por plan/ciclo (4 en total) y un
**Payment Link** para cada uno. Copia las 4 URLs a las variables de entorno de
Vercel (Project → Settings → Environment Variables):

```
VITE_STRIPE_PRO_MONTH=https://buy.stripe.com/...
VITE_STRIPE_PRO_YEAR=https://buy.stripe.com/...
VITE_STRIPE_VIP_MONTH=https://buy.stripe.com/...
VITE_STRIPE_VIP_YEAR=https://buy.stripe.com/...
```

La app añade a cada enlace `prefilled_email` y `client_reference_id` (el uid de
Supabase) para poder casar el pago con el usuario.

### 2. Webhook Stripe → Supabase (asignar el plan tras el cobro)
Crea una **Supabase Edge Function** suscrita al webhook de Stripe
(`checkout.session.completed` y `customer.subscription.deleted`). En el evento:

- `completed` → lee `client_reference_id` (uid) y el producto comprado, y
  actualiza el usuario:
  `supabase.auth.admin.updateUserById(uid, { app_metadata: { plan: "pro" } })`.
- `subscription.deleted` / impago → vuelve a `{ plan: "free" }`.

Con eso, en el siguiente refresco de sesión `resolvePlan` ya ve el plan nuevo y
el paywall se abre solo. No hay estado de pago en el frontend.

### 3. Variables de entorno (resumen)
```
# Login (ya existente)
VITE_SUPABASE_URL=...
VITE_SUPABASE_ANON_KEY=...
VITE_ALLOWED_EMAIL=tu@email        # tu cuenta = VIP
# Plan por defecto de visitantes (opcional)
VITE_DEFAULT_PLAN=free
# Pago
VITE_STRIPE_PRO_MONTH=...
VITE_STRIPE_PRO_YEAR=...
VITE_STRIPE_VIP_MONTH=...
VITE_STRIPE_VIP_YEAR=...
```

## Probar sin Stripe
Sin las `VITE_STRIPE_*`, los botones avisan de que el pago no está configurado
(no rompen). Para ver la app desbloqueada en local, pon `VITE_DEFAULT_PLAN=vip`
o usa tu `VITE_ALLOWED_EMAIL`.

## Proyección rápida
100 suscriptores a ~15 €/mes ≈ **18.000 €/año** de ingresos recurrentes; a un
múltiplo SaaS de 3-5× ARR, eso sitúa la valoración del producto en
**55.000-90.000 €** una vez con tracción.

> Fútbol Edge ofrece probabilidades y ventaja estadística, no certezas. Incluye
> aviso de juego responsable (+18). Revisa la normativa de publicidad de apuestas
> (DGOJ) antes de lanzar campañas de captación en España.
