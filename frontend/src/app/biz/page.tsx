import { Star } from "lucide-react";

const THY_RED = "#c70a20";

export default function BizPage() {
  return (
    <div
      className="-mx-4 -my-6 flex min-h-[80vh] flex-col items-center justify-center gap-4 rounded-none px-8 py-24 text-center text-white md:-mx-8 md:-my-8"
      style={{
        background: `radial-gradient(circle at 50% 0%, ${THY_RED}22 0%, #0a0a0a 60%)`,
      }}
    >
      <span
        className="flex size-14 items-center justify-center rounded-full"
        style={{ backgroundColor: THY_RED }}
      >
        <Star className="size-7 fill-white text-white" />
      </span>
      <h1 className="text-4xl font-semibold tracking-tight">BİZ</h1>
      <p className="max-w-md text-sm text-white/60">
        Türk Hava Yolları için özel istihbarat masası — kurumsal haberler, filo,
        Miles&amp;Smiles, rakip karşılaştırmaları ve yönetici brifingleri.
        Bu özel bölüm sırada bekliyor.
      </p>
    </div>
  );
}
