-- Target schema for Neon Postgres. GitHub JSON uses the same logical model until Neon MCP write tools are exposed.
create table if not exists properties (
  id text primary key,
  ward text,
  address text,
  land_sqm numeric,
  building_sqm numeric,
  layout text,
  built text,
  station text,
  created_at timestamptz default now()
);

create table if not exists listings (
  id text primary key,
  property_id text references properties(id),
  source text not null,
  url text not null,
  title text,
  first_seen date not null,
  last_seen date not null,
  status text not null default 'active',
  unique(source, url)
);

create table if not exists price_snapshots (
  listing_id text references listings(id),
  observed_on date not null,
  price_man numeric not null,
  observed_at timestamptz not null,
  primary key (listing_id, observed_on)
);

create index if not exists price_snapshots_listing_date_idx on price_snapshots(listing_id, observed_on);
create index if not exists listings_property_idx on listings(property_id);
create index if not exists listings_status_idx on listings(status);
