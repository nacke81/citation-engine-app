// Public by design: the publishable key only lets a signed-in user reach their own rows (row-level security).
// Citation Engine shares the People CRM Supabase project (same sign-in). Tests can override with window.CE_CONFIG.
const o = (typeof window !== "undefined" && window.CE_CONFIG) || {};
export const SUPABASE_URL = o.url || "https://nwqpdknxazfeaxdxexry.supabase.co";
export const SUPABASE_KEY = o.key || "sb_publishable_pQfd836lWG23J6nIlUsGVA_gRhh94KW";
