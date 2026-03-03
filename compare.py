#!/usr/bin/env python3
"""Venice.ai Cost Comparison Tool — Compare Venice pay-as-you-go, DIEM staking,
Anthropic, OpenAI, and OpenRouter pricing for AI model access."""

import argparse
import csv
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone

# ─── Pricing Data ───────────────────────────────────────────────────────────

LAST_UPDATED = "2026-03-02"

# per 1M tokens (input, output) — from docs.venice.ai/overview/pricing
MODELS = {
    # ── Anthropic (Venice + direct) ──
    "claude-opus-4.6": {
        "display": "Claude Opus 4.6",
        "venice": (6.00, 30.00),
        "anthropic": (5.00, 25.00),
    },
    "claude-sonnet-4.6": {
        "display": "Claude Sonnet 4.6",
        "venice": (3.60, 18.00),
        "anthropic": (3.00, 15.00),
    },
    "claude-sonnet-4.5": {
        "display": "Claude Sonnet 4.5",
        "venice": (3.75, 18.75),
        "anthropic": (3.00, 15.00),
    },
    "claude-haiku-4.5": {
        "display": "Claude Haiku 4.5",
        "venice": None,
        "anthropic": (1.00, 5.00),
    },
    # ── OpenAI (Venice + direct) ──
    "gpt-4o": {
        "display": "GPT-4o",
        "venice": None,
        "openai": (2.50, 10.00),
    },
    "gpt-5.2": {
        "display": "GPT-5.2",
        "venice": (2.19, 17.50),
        "openai": (1.75, 14.00),
    },
    # ── Google (Venice + direct) ──
    "gemini-3-pro": {
        "display": "Gemini 3 Pro",
        "venice": (2.50, 15.00),
        "google": (1.25, 10.00),
    },
    "gemini-3-flash": {
        "display": "Gemini 3 Flash",
        "venice": (0.70, 3.75),
        "google": (0.15, 0.60),
    },
    # ── xAI (Venice only) ──
    "grok-4.1-fast": {
        "display": "Grok 4.1 Fast",
        "venice": (0.50, 1.25),
    },
    # ── Venice-only open models ──
    "deepseek-v3.2": {
        "display": "DeepSeek V3.2",
        "venice": (0.40, 1.00),
    },
    "qwen-3-coder-480b": {
        "display": "Qwen 3 Coder 480B",
        "venice": (0.75, 3.00),
    },
    "kimi-k2-thinking": {
        "display": "Kimi K2 Thinking",
        "venice": (0.75, 3.20),
    },
    "llama-3.3-70b": {
        "display": "Llama 3.3 70B",
        "venice": (0.70, 2.80),
    },
    "llama-3.2-3b": {
        "display": "Llama 3.2 3B",
        "venice": (0.15, 0.60),
    },
    "glm-4.7": {
        "display": "GLM 4.7",
        "venice": (0.55, 2.65),
    },
    "glm-4.7-flash": {
        "display": "GLM 4.7 Flash",
        "venice": (0.13, 0.50),
    },
    "minimax-m2.5": {
        "display": "MiniMax M2.5",
        "venice": (0.40, 1.60),
    },
    "venice-uncensored-1.1": {
        "display": "Venice Uncensored 1.1",
        "venice": (0.20, 0.90),
    },
}

OPENROUTER_FEE = 0.055  # 5.5% platform fee

# Venice DIEM network parameters
DIEM_DAILY_NETWORK = 18148  # total DIEM/day
VVV_PRICE_DEFAULT = 6.51  # USD per VVV token (fallback)
TOTAL_ACTIVE_STAKED_VVV = 100_000_000  # approximate, for allocation calc

# CoinGecko API (free demo key available at coingecko.com/en/api)
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_PRICE_PATH = "/simple/price?ids=venice-token&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true"
COINGECKO_CHART_PATH = "/coins/venice-token/market_chart?vs_currency=usd&days=30"


# ─── Live Data Fetching ────────────────────────────────────────────────────

def _coingecko_url(path, api_key=None):
    """Build CoinGecko URL, appending demo API key if provided."""
    url = COINGECKO_BASE + path
    if api_key:
        sep = "&" if "?" in url else "?"
        url += f"{sep}x_cg_demo_api_key={api_key}"
    return url


def fetch_json(url, api_key=None, timeout=10):
    """Fetch JSON from a URL. Returns dict or None on failure."""
    try:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["x-cg-demo-api-key"] = api_key
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"  Warning: Failed to fetch {url.split('?')[0]}: {e}", file=sys.stderr)
        return None


def fetch_vvv_live(api_key=None):
    """Fetch current VVV price, market cap, 24h change from CoinGecko."""
    url = _coingecko_url(COINGECKO_PRICE_PATH, api_key)
    data = fetch_json(url, api_key)
    if data and "venice-token" in data:
        vt = data["venice-token"]
        return {
            "price": vt.get("usd"),
            "market_cap": vt.get("usd_market_cap"),
            "volume_24h": vt.get("usd_24h_vol"),
            "change_24h": vt.get("usd_24h_change"),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
    return None


def fetch_vvv_history(api_key=None):
    """Fetch 30-day VVV price history from CoinGecko, compute 7d/30d MA."""
    url = _coingecko_url(COINGECKO_CHART_PATH, api_key)
    data = fetch_json(url, api_key)
    if not data or "prices" not in data:
        return None

    prices = [p[1] for p in data["prices"]]
    if not prices:
        return None

    current = prices[-1]
    ma_7d = sum(prices[-7 * 24:]) / len(prices[-7 * 24:]) if len(prices) >= 7 else current
    ma_30d = sum(prices) / len(prices)

    return {
        "current": round(current, 4),
        "ma_7d": round(ma_7d, 4),
        "ma_30d": round(ma_30d, 4),
        "data_points": len(prices),
        "low_30d": round(min(prices), 4),
        "high_30d": round(max(prices), 4),
    }


def resolve_vvv_price(args, live_info=None, history=None):
    """Determine VVV price based on --price-mode and available data."""
    mode = getattr(args, "price_mode", "spot")

    if mode == "manual" or not live_info:
        return args.vvv_price

    if mode == "7d" and history:
        return history["ma_7d"]
    elif mode == "30d" and history:
        return history["ma_30d"]
    else:  # spot
        return live_info["price"] or args.vvv_price


# ─── Cost Calculation ───────────────────────────────────────────────────────

def calc_monthly_cost(price_per_m_in, price_per_m_out, input_mtok, output_mtok):
    """Calculate monthly cost given per-1M-token rates and monthly token volumes."""
    return input_mtok * price_per_m_in + output_mtok * price_per_m_out


def calc_openrouter(direct_in, direct_out):
    """OpenRouter = provider price + 5.5% fee."""
    return (direct_in * (1 + OPENROUTER_FEE), direct_out * (1 + OPENROUTER_FEE))


def compare_model(model_key, input_mtok, output_mtok):
    """Return dict of provider -> monthly cost for a given model and usage."""
    m = MODELS[model_key]
    results = {}

    if m.get("venice"):
        v_in, v_out = m["venice"]
        results["Venice Pay-Go"] = calc_monthly_cost(v_in, v_out, input_mtok, output_mtok)

    for provider_key, label in [("anthropic", "Anthropic Direct"),
                                ("openai", "OpenAI Direct"),
                                ("google", "Google Direct")]:
        if m.get(provider_key):
            d_in, d_out = m[provider_key]
            results[label] = calc_monthly_cost(d_in, d_out, input_mtok, output_mtok)
            or_in, or_out = calc_openrouter(d_in, d_out)
            results["OpenRouter"] = calc_monthly_cost(or_in, or_out, input_mtok, output_mtok)

    return results


def calc_staking(vvv_usd, vvv_appreciation=0.0, opportunity_cost_rate=0.10,
                 total_staked_vvv=TOTAL_ACTIVE_STAKED_VVV, vvv_price=VVV_PRICE_DEFAULT):
    """Calculate DIEM staking economics."""
    vvv_tokens = vvv_usd / vvv_price
    user_share = vvv_tokens / total_staked_vvv

    daily_diem = user_share * DIEM_DAILY_NETWORK
    daily_usd_value = daily_diem  # 1 DIEM = $1/day compute
    monthly_usd_value = daily_usd_value * 30
    annual_usd_value = daily_usd_value * 365

    annual_opportunity_cost = vvv_usd * opportunity_cost_rate
    annual_appreciation_value = vvv_usd * vvv_appreciation
    effective_annual_cost = annual_opportunity_cost - annual_appreciation_value
    effective_monthly_cost = effective_annual_cost / 12

    if annual_usd_value > 0:
        effective_cost_per_dollar_compute = effective_annual_cost / annual_usd_value
    else:
        effective_cost_per_dollar_compute = float('inf')

    return {
        "vvv_usd": vvv_usd,
        "vvv_tokens": vvv_tokens,
        "vvv_price": vvv_price,
        "user_share_pct": user_share * 100,
        "daily_diem": daily_diem,
        "daily_usd_value": daily_usd_value,
        "monthly_usd_value": monthly_usd_value,
        "annual_usd_value": annual_usd_value,
        "opportunity_cost_rate": opportunity_cost_rate,
        "vvv_appreciation": vvv_appreciation,
        "annual_opportunity_cost": annual_opportunity_cost,
        "annual_appreciation_value": annual_appreciation_value,
        "effective_annual_cost": effective_annual_cost,
        "effective_monthly_cost": effective_monthly_cost,
        "effective_cost_per_dollar_compute": effective_cost_per_dollar_compute,
    }


def calc_staking_vs_paygo(staking_info, model_key, input_mtok, output_mtok):
    """Compare staking effective cost against pay-as-you-go for a model."""
    m = MODELS[model_key]
    if not m.get("venice"):
        return None

    v_in, v_out = m["venice"]
    monthly_paygo = calc_monthly_cost(v_in, v_out, input_mtok, output_mtok)
    annual_paygo = monthly_paygo * 12

    monthly_compute_value = staking_info["monthly_usd_value"]
    can_cover = monthly_compute_value >= monthly_paygo

    if staking_info["daily_usd_value"] > 0:
        needed_daily = monthly_paygo / 30
        needed_share = needed_daily / DIEM_DAILY_NETWORK
        breakeven_vvv_usd = needed_share * staking_info["vvv_tokens"] / staking_info["user_share_pct"] * 100 * staking_info["vvv_price"]
    else:
        breakeven_vvv_usd = float('inf')

    return {
        "model": m["display"],
        "monthly_paygo": monthly_paygo,
        "annual_paygo": annual_paygo,
        "monthly_compute_value": monthly_compute_value,
        "can_cover_usage": can_cover,
        "effective_monthly_cost": staking_info["effective_monthly_cost"],
        "monthly_savings": monthly_paygo - staking_info["effective_monthly_cost"] if can_cover else None,
        "breakeven_vvv_usd": breakeven_vvv_usd,
    }


# ─── CSV Import ─────────────────────────────────────────────────────────────

def import_csv(filepath):
    """Parse a provider usage CSV and extract token volumes."""
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            norm = {k.lower().strip(): v.strip() for k, v in row.items()}
            model = (norm.get("model") or norm.get("model_id") or
                     norm.get("model name") or "unknown")
            input_tok = int(norm.get("input_tokens", 0) or norm.get("input tokens", 0) or
                           norm.get("prompt_tokens", 0) or 0)
            output_tok = int(norm.get("output_tokens", 0) or norm.get("output tokens", 0) or
                            norm.get("completion_tokens", 0) or 0)
            rows.append({"model": model, "input_tokens": input_tok, "output_tokens": output_tok})
    return rows


def aggregate_csv_usage(rows):
    """Aggregate imported CSV rows by model -> total input/output tokens."""
    agg = {}
    for r in rows:
        m = r["model"]
        if m not in agg:
            agg[m] = {"input_tokens": 0, "output_tokens": 0}
        agg[m]["input_tokens"] += r["input_tokens"]
        agg[m]["output_tokens"] += r["output_tokens"]
    return agg


# ─── Output Formatting ──────────────────────────────────────────────────────

def try_rich():
    """Try to import rich; return (Console, Table) or (None, None)."""
    try:
        from rich.console import Console
        from rich.table import Table
        return Console, Table
    except ImportError:
        return None, None


def format_usd(val):
    if val is None:
        return "—"
    if val < 0:
        return f"-${abs(val):,.2f}"
    return f"${val:,.2f}"


def print_live_data(live_info, history):
    """Print live VVV market data."""
    print(f"\n  ═══ Live VVV Market Data (CoinGecko) ═══\n")
    if live_info:
        print(f"  Spot Price:          {format_usd(live_info['price'])}")
        chg = live_info.get("change_24h")
        if chg is not None:
            print(f"  24h Change:          {chg:+.2f}%")
        print(f"  Market Cap:          {format_usd(live_info['market_cap'])}")
        print(f"  24h Volume:          {format_usd(live_info['volume_24h'])}")
        print(f"  Fetched:             {live_info['fetched_at']}")
    if history:
        print(f"\n  7-Day MA:            {format_usd(history['ma_7d'])}")
        print(f"  30-Day MA:           {format_usd(history['ma_30d'])}")
        print(f"  30-Day Range:        {format_usd(history['low_30d'])} – {format_usd(history['high_30d'])}")
    print()


def print_comparison_table(model_key, input_mtok, output_mtok, results, price_source=None):
    """Print comparison table, using rich if available."""
    m = MODELS[model_key]
    Console, Table = try_rich()

    print(f"\n  Model: {m['display']}")
    print(f"  Usage: {input_mtok}M input + {output_mtok}M output tokens/month")
    src = f"Prices as of: {LAST_UPDATED}"
    if price_source:
        src += f" | VVV price: {price_source}"
    print(f"  {src}\n")

    if Console and Table:
        console = Console()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Provider", style="bold")
        table.add_column("Monthly Cost", justify="right")
        table.add_column("Annual Cost", justify="right")
        table.add_column("vs Cheapest", justify="right")

        cheapest = min(results.values()) if results else 0
        for provider, monthly in sorted(results.items(), key=lambda x: x[1]):
            annual = monthly * 12
            diff = monthly - cheapest
            diff_str = "baseline" if diff == 0 else f"+{format_usd(diff)}/mo"
            table.add_row(provider, format_usd(monthly), format_usd(annual), diff_str)

        console.print(table)
    else:
        cheapest = min(results.values()) if results else 0
        print(f"  {'Provider':<22} {'Monthly':>12} {'Annual':>14} {'vs Cheapest':>14}")
        print(f"  {'─' * 22} {'─' * 12} {'─' * 14} {'─' * 14}")
        for provider, monthly in sorted(results.items(), key=lambda x: x[1]):
            annual = monthly * 12
            diff = monthly - cheapest
            diff_str = "baseline" if diff == 0 else f"+{format_usd(diff)}/mo"
            print(f"  {provider:<22} {format_usd(monthly):>12} {format_usd(annual):>14} {diff_str:>14}")
    print()


def print_staking_summary(info, price_source=None):
    """Print DIEM staking analysis."""
    Console, Table = try_rich()

    header = "Venice DIEM Staking Analysis"
    if price_source:
        header += f" (VVV: {price_source})"
    print(f"\n  ═══ {header} ═══\n")

    lines = [
        ("VVV Investment", format_usd(info["vvv_usd"])),
        ("VVV Price", format_usd(info["vvv_price"])),
        ("VVV Tokens", f"{info['vvv_tokens']:,.0f}"),
        ("Network Share", f"{info['user_share_pct']:.4f}%"),
        ("", ""),
        ("Daily DIEM Allocation", f"{info['daily_diem']:,.2f}"),
        ("Daily Compute Value", format_usd(info["daily_usd_value"])),
        ("Monthly Compute Value", format_usd(info["monthly_usd_value"])),
        ("Annual Compute Value", format_usd(info["annual_usd_value"])),
        ("", ""),
        ("Opportunity Cost Rate", f"{info['opportunity_cost_rate']:.0%}"),
        ("Expected VVV Appreciation", f"{info['vvv_appreciation']:+.0%}"),
        ("Annual Opportunity Cost", format_usd(info["annual_opportunity_cost"])),
        ("Annual Appreciation Value", format_usd(info["annual_appreciation_value"])),
        ("Effective Annual Cost", format_usd(info["effective_annual_cost"])),
        ("Effective Monthly Cost", format_usd(info["effective_monthly_cost"])),
    ]

    if info["effective_cost_per_dollar_compute"] != float('inf'):
        eff = info["effective_cost_per_dollar_compute"]
        if eff < 0:
            lines.append(("Cost per $1 Compute", f"{format_usd(eff)} (net gain)"))
        else:
            lines.append(("Cost per $1 Compute", format_usd(eff)))

    if Console and Table:
        console = Console()
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold")
        table.add_column(justify="right")
        for label, val in lines:
            if label == "":
                table.add_row("", "")
            else:
                table.add_row(label, val)
        console.print(table)
    else:
        for label, val in lines:
            if label == "":
                print()
            else:
                print(f"  {label:<28} {val:>16}")
    print()


def export_csv(filepath, model_key, input_mtok, output_mtok, results, staking_info=None):
    """Export comparison results to CSV."""
    m = MODELS[model_key]
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Model", "Input M Tokens/mo", "Output M Tokens/mo",
                         "Provider", "Monthly Cost", "Annual Cost"])
        for provider, monthly in sorted(results.items(), key=lambda x: x[1]):
            writer.writerow([m["display"], input_mtok, output_mtok,
                             provider, f"{monthly:.2f}", f"{monthly * 12:.2f}"])

        if staking_info:
            writer.writerow([])
            writer.writerow(["Staking Parameter", "Value"])
            for k, v in staking_info.items():
                writer.writerow([k, v])

    print(f"  Exported to {filepath}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def list_models():
    print("\n  Available models:\n")
    for key, m in MODELS.items():
        providers = []
        if m.get("venice"):
            v_in, v_out = m["venice"]
            providers.append(f"Venice ${v_in}/{v_out}")
        for pk, lbl in [("anthropic", "Anthropic"), ("openai", "OpenAI"), ("google", "Google")]:
            if m.get(pk):
                d_in, d_out = m[pk]
                providers.append(f"{lbl} ${d_in}/{d_out}")
        print(f"    {key:<24} {m['display']}")
        print(f"    {'':24} {', '.join(providers)}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Venice.ai Cost Comparison Tool — Compare Venice vs direct providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --quick --model claude-sonnet-4.6 --input-mtok 10 --output-mtok 5
  %(prog)s --live --staking --vvv-usd 10000 --model claude-sonnet-4.6
  %(prog)s --live --price-mode 7d --staking --vvv-usd 50000
  %(prog)s --quick --model claude-opus-4.6 --input-mtok 50 --output-mtok 20 --export out.csv
  %(prog)s --import-csv usage.csv
  %(prog)s --list-models
        """)

    # Modes
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true",
                      help="Quick comparison for a model + usage level")
    mode.add_argument("--staking", action="store_true",
                      help="DIEM staking ROI analysis")
    mode.add_argument("--import-csv", metavar="FILE",
                      help="Import historical usage CSV")
    mode.add_argument("--list-models", action="store_true",
                      help="List available models and pricing")

    # Live data
    parser.add_argument("--live", action="store_true",
                        help="Fetch live VVV price from CoinGecko (spot + 7d/30d MA)")
    parser.add_argument("--price-mode", choices=["spot", "7d", "30d", "manual"],
                        default="spot",
                        help="VVV price mode: spot (live), 7d MA, 30d MA, or manual (default: spot)")
    parser.add_argument("--cg-api-key", metavar="KEY",
                        help="CoinGecko demo API key (free at coingecko.com/en/api)")

    # Usage params
    parser.add_argument("--model", default="claude-sonnet-4.6",
                        help="Model key (default: claude-sonnet-4.6)")
    parser.add_argument("--input-mtok", type=float, default=10,
                        help="Monthly input tokens in millions (default: 10)")
    parser.add_argument("--output-mtok", type=float, default=5,
                        help="Monthly output tokens in millions (default: 5)")

    # Staking params
    parser.add_argument("--vvv-usd", type=float, default=10000,
                        help="USD value of VVV to stake (default: 10000)")
    parser.add_argument("--vvv-price", type=float, default=VVV_PRICE_DEFAULT,
                        help=f"VVV token price in USD (default: {VVV_PRICE_DEFAULT}, overridden by --live)")
    parser.add_argument("--vvv-appreciation", type=float, default=0.0,
                        help="Expected annual VVV price change, e.g. 0.2 for +20%% (default: 0)")
    parser.add_argument("--opportunity-cost", type=float, default=0.10,
                        help="Annual opportunity cost rate (default: 0.10)")
    parser.add_argument("--total-staked-vvv", type=float, default=TOTAL_ACTIVE_STAKED_VVV,
                        help=f"Total VVV staked network-wide (default: {TOTAL_ACTIVE_STAKED_VVV:,.0f})")

    # Export
    parser.add_argument("--export", metavar="FILE.csv",
                        help="Export results to CSV")

    args = parser.parse_args()

    # Default to --quick if no mode specified
    if not (args.quick or args.staking or args.import_csv or args.list_models):
        args.quick = True

    if args.list_models:
        list_models()
        return

    if args.model not in MODELS:
        print(f"  Error: Unknown model '{args.model}'")
        print(f"  Run with --list-models to see available options")
        sys.exit(1)

    # ── Fetch live data if requested ──
    live_info = None
    history = None
    price_source = None

    if args.live:
        cg_key = args.cg_api_key or os.environ.get("COINGECKO_API_KEY")
        print("  Fetching live VVV data from CoinGecko...")
        live_info = fetch_vvv_live(cg_key)
        history = fetch_vvv_history(cg_key)
        print_live_data(live_info, history)

        vvv_price = resolve_vvv_price(args, live_info, history)
        args.vvv_price = vvv_price
        price_source = f"{format_usd(vvv_price)} ({args.price_mode})"
    elif args.price_mode != "spot":
        print("  Note: --price-mode requires --live to fetch data. Using manual price.")
        price_source = f"{format_usd(args.vvv_price)} (manual)"
    else:
        price_source = f"{format_usd(args.vvv_price)} (manual)"

    if args.import_csv:
        print(f"\n  Importing usage data from: {args.import_csv}\n")
        rows = import_csv(args.import_csv)
        agg = aggregate_csv_usage(rows)
        for model_name, usage in agg.items():
            in_m = usage["input_tokens"] / 1_000_000
            out_m = usage["output_tokens"] / 1_000_000
            print(f"  {model_name}: {in_m:.1f}M input, {out_m:.1f}M output tokens")

            matched = None
            model_lower = model_name.lower()
            for key in MODELS:
                if key.replace("-", "") in model_lower.replace("-", "").replace(" ", ""):
                    matched = key
                    break

            if matched:
                results = compare_model(matched, in_m, out_m)
                if results:
                    print_comparison_table(matched, in_m, out_m, results, price_source)
            else:
                print(f"    (no matching model in pricing database)\n")
        return

    if args.quick:
        results = compare_model(args.model, args.input_mtok, args.output_mtok)
        if not results:
            print(f"  No pricing data available for {MODELS[args.model]['display']}")
            sys.exit(1)
        print_comparison_table(args.model, args.input_mtok, args.output_mtok, results, price_source)

        if args.export:
            export_csv(args.export, args.model, args.input_mtok, args.output_mtok, results)

    if args.staking:
        info = calc_staking(
            vvv_usd=args.vvv_usd,
            vvv_appreciation=args.vvv_appreciation,
            opportunity_cost_rate=args.opportunity_cost,
            total_staked_vvv=args.total_staked_vvv,
            vvv_price=args.vvv_price,
        )
        print_staking_summary(info, price_source)

        comparison = calc_staking_vs_paygo(info, args.model, args.input_mtok, args.output_mtok)
        if comparison:
            print(f"  ─── Staking vs Pay-As-You-Go: {comparison['model']} ───\n")
            print(f"  Monthly Pay-Go Cost:       {format_usd(comparison['monthly_paygo'])}")
            print(f"  Monthly Compute from Stake: {format_usd(comparison['monthly_compute_value'])}")
            covers = "Yes ✓" if comparison["can_cover_usage"] else "No ✗"
            print(f"  Stake Covers Usage:        {covers}")
            print(f"  Effective Monthly Cost:    {format_usd(comparison['effective_monthly_cost'])}")
            if comparison["monthly_savings"] is not None:
                print(f"  Monthly Savings vs PayGo:  {format_usd(comparison['monthly_savings'])}")
            if comparison["breakeven_vvv_usd"] < float('inf'):
                print(f"  Break-Even VVV Investment: {format_usd(comparison['breakeven_vvv_usd'])}")
            print()

        if args.export:
            results = compare_model(args.model, args.input_mtok, args.output_mtok)
            export_csv(args.export, args.model, args.input_mtok, args.output_mtok,
                       results or {}, staking_info=info)


if __name__ == "__main__":
    main()
