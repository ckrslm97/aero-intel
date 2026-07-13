"use client";

import { CheckCircle2, Lock, ShieldAlert, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { API_BASE_URL } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { AdminStatusOut } from "@/lib/types";

function StatCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tracking-tight">{value}</p>
      </CardContent>
    </Card>
  );
}

function AdminDashboard() {
  const [status, setStatus] = useState<AdminStatusOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    fetch(`${API_BASE_URL}/admin/status`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then(setStatus)
      .catch(() => setError("Could not load admin status."));
  }, []);

  if (error) {
    return <p className="text-sm text-critical">{error}</p>;
  }
  if (!status) {
    return <p className="text-sm text-muted-foreground">Loading system status…</p>;
  }

  const totalArticles = status.articles_by_status.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="flex flex-col gap-8">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <p className="text-xs font-medium text-muted-foreground">Database</p>
          </CardHeader>
          <CardContent className="flex items-center gap-2">
            {status.database_ok ? (
              <CheckCircle2 className="size-5 text-good" />
            ) : (
              <XCircle className="size-5 text-critical" />
            )}
            <span className="text-sm font-medium">{status.database_ok ? "Healthy" : "Unreachable"}</span>
          </CardContent>
        </Card>
        <StatCard label="LLM provider" value={status.llm_provider} />
        <StatCard label="Sources" value={status.sources_count} />
        <StatCard label="Entities extracted" value={status.entities_count} />
        <StatCard label="Total articles" value={totalArticles} />
        <StatCard label="Editions published" value={status.editions_count} />
        <StatCard label="Active subscribers" value={status.subscribers_count} />
        <StatCard
          label="Latest edition"
          value={status.latest_edition_date ?? "—"}
        />
      </section>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Articles by status
          </h2>
          <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {status.articles_by_status.map((s) => (
              <div key={s.status} className="flex items-center justify-between p-3 text-sm">
                <Badge variant="secondary" className="uppercase">{s.status}</Badge>
                <span className="font-medium tabular-nums">{s.count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Email deliveries
          </h2>
          <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {status.email_deliveries_by_status.length === 0 && (
              <p className="p-3 text-sm text-muted-foreground">No deliveries yet.</p>
            )}
            {status.email_deliveries_by_status.map((s) => (
              <div key={s.status} className="flex items-center justify-between p-3 text-sm">
                <Badge variant="secondary" className="uppercase">{s.status}</Badge>
                <span className="font-medium tabular-nums">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Scheduled jobs
        </h2>
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {status.scheduler_jobs.map((job) => (
            <div key={job.id} className="flex items-center justify-between p-3 text-sm">
              <span className="font-medium">{job.id}</span>
              <span className="text-muted-foreground">
                next run:{" "}
                {job.next_run_time
                  ? new Date(job.next_run_time).toLocaleString("en-GB", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })
                  : "not scheduled"}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function AdminPage() {
  const { user, loading, logout } = useAuth();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Admin panel</h1>
          <p className="text-sm text-muted-foreground">
            Crawler status, data freshness, and system health.
          </p>
        </div>
        {user && (
          <button
            onClick={logout}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent"
          >
            Sign out ({user.email})
          </button>
        )}
      </div>

      {loading && <p className="text-sm text-muted-foreground">Checking session…</p>}

      {!loading && !user && (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-12 text-center">
          <Lock className="size-8 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Sign in required</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            The admin panel is restricted to admin accounts.
          </p>
          <Link
            href="/login"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Sign in
          </Link>
        </div>
      )}

      {!loading && user && user.role !== "admin" && (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-12 text-center">
          <ShieldAlert className="size-8 text-critical" />
          <h2 className="text-lg font-semibold">Access denied</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            Signed in as {user.email} ({user.role}). This section requires the admin role.
          </p>
        </div>
      )}

      {!loading && user && user.role === "admin" && <AdminDashboard />}
    </div>
  );
}
