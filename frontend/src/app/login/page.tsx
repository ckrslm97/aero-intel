"use client";

import { Plane } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(email, password);
      await refresh();
      router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-6 py-16">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="flex size-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Plane className="size-5" />
        </span>
        <h1 className="text-xl font-semibold tracking-tight">Sign in to AeroIntel</h1>
        <p className="text-sm text-muted-foreground">
          Admin and editor access to the intelligence portal.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <Input
          type="email"
          placeholder="Email"
          autoFocus
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          type="password"
          placeholder="Password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-critical">{error}</p>}
        <Button type="submit" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
