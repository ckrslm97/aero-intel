# Kubernetes manifests

Scaffolded, not wired to a live cluster. These assume a **managed Postgres and
Redis** (RDS/Cloud SQL/etc) rather than running stateful databases in-cluster
— point `DATABASE_URL`/`REDIS_URL` in `secret.yaml` at them.

Apply order:

```bash
kubectl apply -f namespace.yaml
kubectl apply -f secret.yaml       # edit the placeholder values first
kubectl apply -f backend-deployment.yaml
kubectl apply -f backend-service.yaml
kubectl apply -f frontend-deployment.yaml
kubectl apply -f frontend-service.yaml
kubectl apply -f ingress.yaml
```

Build and push the images first (`aerointel-backend`, `aerointel-frontend`)
to a registry the cluster can pull from, and update the `image:` fields.
PDF export (Playwright/Chromium) isn't in the base backend image -- see
`backend/Dockerfile` for how to add it if a cluster deployment needs PDFs.
