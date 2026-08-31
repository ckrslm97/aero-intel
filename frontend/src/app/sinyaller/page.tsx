import { SignalsClient } from "@/components/sinyaller/signals-client";

export const metadata = {
  title: "Sinyaller — Erken Uyarı Merkezi — AeroIntel",
  description:
    "Kokpit sinyal panosu, kampanya uyarıları, Risk Radarı, rakip ve stratejik olaylar, ağ sinyalleri ve haber momentumu tek listede: şiddete, sonra tazeliğe göre sıralı erken uyarı merkezi.",
};

export default function SinyallerPage() {
  return <SignalsClient />;
}
