# Google login and synchronized favorites

Supabase project: `house-tracker` (`nswgzzvgmudtftvjogvt`)

## Already configured

- `public.listing_favorites` table
- Row Level Security enabled
- Per-user SELECT / INSERT / UPDATE / DELETE policies
- No table privileges for the anonymous role
- Dashboard Supabase URL and publishable key
- Guest favorites in localStorage
- Guest-to-account favorite migration after login
- Favorite buttons in desktop rows, mobile cards, price-drop cards, and listing details
- Favorites-only filter for the all-listings price chart

## Remaining Google provider setup

1. In Google Auth Platform, create an OAuth Client ID with application type **Web application**.
2. Add this Authorized JavaScript origin:

   `https://realestate-dashboard-sawamotokais-projects.vercel.app`

3. Add this Authorized redirect URI:

   `https://nswgzzvgmudtftvjogvt.supabase.co/auth/v1/callback`

4. In Supabase Dashboard → Authentication → Providers → Google, enable Google and paste the Client ID and Client Secret.
5. In Supabase Dashboard → Authentication → URL Configuration:
   - Site URL: `https://realestate-dashboard-sawamotokais-projects.vercel.app/`
   - Redirect URL: `https://realestate-dashboard-sawamotokais-projects.vercel.app/`

Use the exact production redirect above. Add wildcard preview URLs separately only when preview-deployment authentication is needed.

After those settings are saved, reload the dashboard. The Google login button detects the enabled provider automatically.
