
## Function region

`vercel.json` pins the API to `fra1`. It defaulted to `iad1` (Washington), while
Neon runs in `eu-central-1` (Frankfurt), so every database round trip crossed the
Atlantic. With NullPool (required for the pooled connection) each request also
pays a fresh TCP+TLS handshake, so that latency was multiplied: measured 2.8s for
a `/articles` request whose SQL takes 0.2ms in Postgres.
