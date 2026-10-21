export function formatNumber(value: number, maximumFractionDigits = 0): string {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits, minimumFractionDigits: 0 }).format(value);
}

export function formatKwh(energyWh: number, digits = 3): string {
  return `${formatNumber(energyWh / 1000, digits)} kWh`;
}

export function formatEuroCentsPerKwh(cents: number): string {
  const whole = formatNumber(Math.floor(cents / 100));
  const fraction = String(cents % 100).padStart(2, "0");
  return `€${whole}.${fraction}/kWh`;
}

export function formatEuroCents(cents: number): string {
  const whole = formatNumber(Math.floor(cents / 100));
  const fraction = String(cents % 100).padStart(2, "0");
  return `€${whole}.${fraction}`;
}

export function formatKgFromDg(deciGrams: number | null | undefined, gas: "CO2" | "CO2e" | string = "CO2"): string {
  if (deciGrams == null) return "—";
  return `${formatNumber(deciGrams / 10000, 2)} kg ${gas === "CO2e" ? "CO₂e" : "CO₂"}`;
}

export function formatFactor(value: number, unit: string): string {
  return `${formatNumber(value, 1)} ${unit}`;
}

export function formatScore(value: number): string { return value.toFixed(4); }

export const STATUS_LABELS: Record<string, string> = {
  Offer: "Ready for wallet",
  Pending: "Pending confirmation",
  Done: "Recorded on chain",
  Fail: "Failed",
};

export function parseKwhToWh(input: string): number {
  const normalized = input.trim();
  if (!/^\d+(?:\.\d{1,3})?$/.test(normalized)) throw new Error("Energy must be a positive number with up to 3 decimal places.");
  const [whole, decimal = ""] = normalized.split(".");
  const wh = BigInt(whole) * 1000n + BigInt((decimal + "000").slice(0, 3));
  if (wh <= 0n || wh > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Enter a valid positive energy quantity.");
  return Number(wh);
}

export function parseEuroToCents(input: string): number {
  const normalized = input.trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) throw new Error("Price must use euros with up to 2 decimal places.");
  const [whole, decimal = ""] = normalized.split(".");
  const cents = BigInt(whole) * 100n + BigInt((decimal + "00").slice(0, 2));
  if (cents > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("Enter a lower price.");
  return Number(cents);
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

export function comparisonLabel(status: string): string {
  if (status === "baseline_unavailable") return "Emissions difference not available for this region";
  if (status === "basis_mismatch") return "Emissions difference not available for this factor basis";
  return "Estimated difference vs. TR grid baseline";
}

