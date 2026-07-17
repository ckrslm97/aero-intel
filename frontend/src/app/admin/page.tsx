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
      .catch(() => setError("Yönetim durumu yüklenemedi."));
  }, []);

  if (error) {
    return <p className="text-sm text-critical">{error}</p>;
  }
  if (!status) {
    return <p className="text-sm text-muted-foreground">Sistem durumu yükleniyor…</p>;
  }

  const totalArticles = status.articles_by_status.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="flex flex-col gap-8">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <p className="text-xs font-medium text-muted-foreground">Veritabanı</p>
          </CardHeader>
          <CardContent className="flex items-center gap-2">
            {status.database_ok ? (
              <CheckCircle2 className="size-5 text-good" />
            ) : (
              <XCircle className="size-5 text-critical" />
            )}
            <span className="text-sm font-medium">{status.database_ok ? "Sağlıklı" : "Erişilemiyor"}</span>
          </CardContent>
        </Card>
        <StatCard label="LLM sağlayıcı" value={status.llm_provider} />
        <StatCard label="Kaynaklar" value={status.sources_count} />
        <StatCard label="Çıkarılan varlıklar" value={status.entities_count} />
        <StatCard label="Toplam haber" value={totalArticles} />
        <StatCard label="Yayınlanan sayılar" value={status.editions_count} />
        <StatCard label="Aktif abone" value={status.subscribers_count} />
        <StatCard
          label="Son sayı"
          value={status.latest_edition_date ?? "—"}
        />
      </section>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Duruma göre haberler
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
            E-posta gönderimleri
          </h2>
          <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
            {status.email_deliveries_by_status.length === 0 && (
              <p className="p-3 text-sm text-muted-foreground">Henüz gönderim yok.</p>
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
          Zamanlanmış görevler
        </h2>
        <div className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
          {status.scheduler_jobs.map((job) => (
            <div key={job.id} className="flex items-center justify-between p-3 text-sm">
              <span className="font-medium">{job.id}</span>
              <span className="text-muted-foreground">
                sonraki çalışma:{" "}
                {job.next_run_time
                  ? new Date(job.next_run_time).toLocaleString("tr-TR", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })
                  : "zamanlanmadı"}
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
          <h1 className="text-2xl font-semibold tracking-tight">Yönetim paneli</h1>
          <p className="text-sm text-muted-foreground">
            Tarayıcı durumu, veri güncelliği ve sistem sağlığı.
          </p>
        </div>
        {user && (
          <button
            onClick={logout}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent"
          >
            Çıkış yap ({user.email})
          </button>
        )}
      </div>

      {loading && <p className="text-sm text-muted-foreground">Oturum kontrol ediliyor…</p>}

      {!loading && !user && (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-12 text-center">
          <Lock className="size-8 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Giriş gerekli</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            Yönetim paneli yalnızca yönetici hesaplarına açıktır.
          </p>
          <Link
            href="/login"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Giriş yap
          </Link>
        </div>
      )}

      {!loading && user && user.role !== "admin" && (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-12 text-center">
          <ShieldAlert className="size-8 text-critical" />
          <h2 className="text-lg font-semibold">Erişim reddedildi</h2>
          <p className="max-w-md text-sm text-muted-foreground">
            {user.email} ({user.role}) olarak giriş yaptınız. Bu bölüm yönetici rolü gerektirir.
          </p>
        </div>
      )}

      {!loading && user && user.role === "admin" && <AdminDashboard />}
    </div>
  );
}
