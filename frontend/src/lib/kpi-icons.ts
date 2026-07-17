import {
  ArrowLeftRight,
  CalendarCheck,
  Droplet,
  Fuel,
  Gauge,
  Package,
  Percent,
  Plane,
  PlaneTakeoff,
  Receipt,
  Route,
  ShoppingBag,
  Ticket,
  TrendingUp,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

/** metric_key -> icon, purely a presentation concern so it stays on the frontend
 * rather than in the backend's KPI_DISPLAY (which only knows label/direction). */
export const KPI_ICONS: Record<string, LucideIcon> = {
  flights_airborne: Plane, // in flight right now
  flights_today: CalendarCheck,
  passengers_ytd: Users,
  load_factor: Gauge,
  fuel_price: Fuel,
  oil_price: Droplet,
  fx_usd_try: ArrowLeftRight,
  departures: PlaneTakeoff, // takeoffs over the year
  total_aviation_revenue_ytd: Wallet,
  passenger_revenue_ytd: Ticket,
  ancillary_revenue_ytd: ShoppingBag,
  rask: TrendingUp,
  cask: Receipt,
  yield_per_rpk: Percent,
  ask: Package,
  rpk: Route,
};
