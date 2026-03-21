# ABOUTME: Script to generate a report on businesses with >$10M turnover
# ABOUTME: across 7 northern Melbourne LGAs from CABEE data

import json
from pathlib import Path
from collections import defaultdict

DATA_FILE = Path(__file__).parent.parent / "data" / "northlink_cabee_extract.json"
OUTPUT_FILE = Path(__file__).parent.parent / "docs" / "north_melbourne_10m_business_report.md"

YEAR = "2025"

# SEIFA deciles for each LGA (from the 200k report)
SEIFA = {
    "Hume": 5,
    "Whittlesea": 7,
    "Merri-Bek": 9,
    "Darebin": 9,
    "Banyule": 10,
    "Nillumbik": 10,
    "Mitchell": 7,
}

LGA_ORDER = ["Hume", "Whittlesea", "Merri-Bek", "Darebin", "Banyule", "Nillumbik", "Mitchell"]


def load_data():
    with open(DATA_FILE) as f:
        return json.load(f)


def strip_industry_prefix(name):
    """Remove the letter prefix like 'E Construction' -> 'Construction'"""
    parts = name.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) == 1 and parts[0].isalpha():
        return parts[1]
    return name


def main():
    data = load_data()
    lines = []

    # --- Section 1: Overview ---
    total_all = 0
    total_10m = 0
    total_5m_10m = 0
    total_2m_5m = 0
    total_200k_2m = 0
    total_under_200k = 0

    lga_stats = {}
    for lga in LGA_ORDER:
        t = data["by_turnover"][lga][YEAR]
        lga_stats[lga] = t
        total_all += t["total"]
        total_10m += t["10m_plus"]
        total_5m_10m += t["5m_to_10m"]
        total_2m_5m += t["2m_to_5m"]
        total_200k_2m += t["200k_to_2m"]
        total_under_200k += t["zero_to_50k"] + t["50k_to_200k"]

    lines.append("# Businesses Over $10M Turnover: North Melbourne")
    lines.append("")
    lines.append("Focused analysis of businesses with annual turnover exceeding $10 million across 7 northern Melbourne LGAs.")
    lines.append("Source: ABS CABEE (Jul 2021 - Jun 2025), SEIFA 2021.")
    lines.append("")
    lines.append("These are enterprise-scale businesses - the largest employers, highest spenders, and most complex operations in the region.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. The $10M+ Market at a Glance")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|------:|")
    lines.append(f"| Total businesses in region | {total_all:,} |")
    lines.append(f"| Businesses with $10M+ turnover | {total_10m:,} |")
    pct = total_10m / total_all * 100 if total_all else 0
    lines.append(f"| Share of total | {pct:.1f}% |")
    lines.append(f"| Businesses $5M - $10M | {total_5m_10m:,} |")
    lines.append(f"| Businesses $2M - $5M | {total_2m_5m:,} |")
    lines.append(f"| Businesses $200K - $2M | {total_200k_2m:,} |")
    lines.append(f"| Businesses under $200K | {total_under_200k:,} |")
    lines.append("")

    # --- Section 2: By LGA ---
    lines.append("---")
    lines.append("")
    lines.append("## 2. $10M+ Businesses by LGA")
    lines.append("")
    lines.append("| LGA | Total Biz | $10M+ | % over $10M | $5M-$10M | $2M-$5M | $200K-$2M | Under $200K | SEIFA Decile |")
    lines.append("|-----|----------:|------:|------------:|---------:|--------:|----------:|------------:|:------------:|")

    for lga in LGA_ORDER:
        t = lga_stats[lga]
        under_200k = t["zero_to_50k"] + t["50k_to_200k"]
        pct = t["10m_plus"] / t["total"] * 100 if t["total"] else 0
        lines.append(
            f"| {lga} | {t['total']:,} | {t['10m_plus']:,} | {pct:.1f}% "
            f"| {t['5m_to_10m']:,} | {t['2m_to_5m']:,} | {t['200k_to_2m']:,} "
            f"| {under_200k:,} | {SEIFA[lga]} |"
        )

    lines.append(
        f"| **Total** | **{total_all:,}** | **{total_10m:,}** | **{total_10m/total_all*100:.1f}%** "
        f"| **{total_5m_10m:,}** | **{total_2m_5m:,}** | **{total_200k_2m:,}** "
        f"| **{total_under_200k:,}** | |"
    )
    lines.append("")

    # --- Section 3: By Industry ---
    lines.append("---")
    lines.append("")
    lines.append("## 3. $10M+ Businesses by Industry")
    lines.append("")

    # Aggregate industry data across all LGAs
    industry_agg = defaultdict(lambda: {
        "10m_plus": 0, "5m_to_10m": 0, "2m_to_5m": 0,
        "200k_to_2m": 0, "total": 0, "over_200k": 0,
    })

    for lga in LGA_ORDER:
        lga_industries = data["by_industry_turnover"][lga][YEAR]
        for ind_name, ind_data in lga_industries.items():
            clean = strip_industry_prefix(ind_name)
            for key in industry_agg[clean]:
                industry_agg[clean][key] += ind_data.get(key, 0)

    # Sort by 10m_plus descending
    sorted_industries = sorted(industry_agg.items(), key=lambda x: x[1]["10m_plus"], reverse=True)

    lines.append("| Industry | $10M+ | $5M-$10M | $2M-$5M | $200K-$2M | Total | % of all $10M+ |")
    lines.append("|----------|------:|---------:|--------:|----------:|------:|---------------:|")

    for ind_name, ind in sorted_industries:
        pct_of_10m = ind["10m_plus"] / total_10m * 100 if total_10m else 0
        lines.append(
            f"| {ind_name} | {ind['10m_plus']:,} | {ind['5m_to_10m']:,} "
            f"| {ind['2m_to_5m']:,} | {ind['200k_to_2m']:,} "
            f"| {ind['total']:,} | {pct_of_10m:.1f}% |"
        )

    lines.append("")

    # --- Section 4: Industry concentration ---
    lines.append("---")
    lines.append("")
    lines.append("## 4. Which Industries Have the Highest Enterprise Concentration?")
    lines.append("")
    lines.append("Industries ranked by the share of their businesses that exceed $10M turnover.")
    lines.append("Higher percentage = more enterprise-scale businesses relative to the industry's total.")
    lines.append("")
    lines.append("| Industry | $10M+ | Total | % over $10M | $5M+ | % over $5M |")
    lines.append("|----------|------:|------:|------------:|-----:|-----------:|")

    # Sort by % over 10m descending
    conc = []
    for ind_name, ind in sorted_industries:
        pct_10m = ind["10m_plus"] / ind["total"] * 100 if ind["total"] else 0
        over_5m = ind["10m_plus"] + ind["5m_to_10m"]
        pct_5m = over_5m / ind["total"] * 100 if ind["total"] else 0
        conc.append((ind_name, ind["10m_plus"], ind["total"], pct_10m, over_5m, pct_5m))

    conc.sort(key=lambda x: x[3], reverse=True)

    for ind_name, ten_m, tot, pct_10m, over_5m, pct_5m in conc:
        lines.append(
            f"| {ind_name} | {ten_m:,} | {tot:,} | {pct_10m:.1f}% | {over_5m:,} | {pct_5m:.1f}% |"
        )

    lines.append("")

    # --- Section 5: Top industries per LGA ---
    lines.append("---")
    lines.append("")
    lines.append("## 5. Top 5 Industries per LGA (by $10M+ count)")
    lines.append("")

    for lga in LGA_ORDER:
        lines.append(f"### {lga}")
        lines.append("")
        lines.append("| Rank | Industry | $10M+ | $5M-$10M | $2M-$5M | Total |")
        lines.append("|:----:|----------|------:|---------:|--------:|------:|")

        lga_industries = data["by_industry_turnover"][lga][YEAR]
        ind_list = []
        for ind_name, ind_data in lga_industries.items():
            clean = strip_industry_prefix(ind_name)
            ind_list.append((clean, ind_data))

        # Sort by 10m_plus descending, take top 5
        ind_list.sort(key=lambda x: x[1]["10m_plus"], reverse=True)
        for rank, (ind_name, ind) in enumerate(ind_list[:5], 1):
            lines.append(
                f"| {rank} | {ind_name} | {ind['10m_plus']:,} "
                f"| {ind['5m_to_10m']:,} | {ind['2m_to_5m']:,} | {ind['total']:,} |"
            )

        lines.append("")

    # --- Section 6: Year-over-year trends ---
    lines.append("---")
    lines.append("")
    lines.append("## 6. Year-over-Year Trends ($10M+ businesses)")
    lines.append("")
    lines.append("| LGA | 2023 | 2024 | 2025 | Change 2023-2025 | % Change |")
    lines.append("|-----|-----:|-----:|-----:|-----------------:|---------:|")

    total_by_year = {"2023": 0, "2024": 0, "2025": 0}
    for lga in LGA_ORDER:
        vals = {}
        for yr in ["2023", "2024", "2025"]:
            vals[yr] = data["by_turnover"][lga][yr]["10m_plus"]
            total_by_year[yr] += vals[yr]
        change = vals["2025"] - vals["2023"]
        pct_change = change / vals["2023"] * 100 if vals["2023"] else 0
        sign = "+" if change >= 0 else ""
        lines.append(
            f"| {lga} | {vals['2023']:,} | {vals['2024']:,} | {vals['2025']:,} "
            f"| {sign}{change:,} | {sign}{pct_change:.1f}% |"
        )

    change_total = total_by_year["2025"] - total_by_year["2023"]
    pct_total = change_total / total_by_year["2023"] * 100 if total_by_year["2023"] else 0
    sign = "+" if change_total >= 0 else ""
    lines.append(
        f"| **Total** | **{total_by_year['2023']:,}** | **{total_by_year['2024']:,}** "
        f"| **{total_by_year['2025']:,}** | **{sign}{change_total:,}** | **{sign}{pct_total:.1f}%** |"
    )
    lines.append("")

    # --- Section 7: Employment size cross-reference ---
    if "by_employment" in data:
        lines.append("---")
        lines.append("")
        lines.append("## 7. Employment Profile of the Region")
        lines.append("")
        lines.append("Workforce size distribution across the region (all businesses).")
        lines.append("")
        lines.append("| LGA | Non-emp | 1-4 emp | 5-19 emp | 20-199 emp | 200+ emp | Total |")
        lines.append("|-----|--------:|--------:|---------:|-----------:|---------:|------:|")

        emp_totals = defaultdict(int)
        for lga in LGA_ORDER:
            e = data["by_employment"][lga][YEAR]
            lines.append(
                f"| {lga} | {e['non_employing']:,} | {e['1_to_4']:,} "
                f"| {e['5_to_19']:,} | {e['20_to_199']:,} | {e['200_plus']:,} | {e['total']:,} |"
            )
            for k, v in e.items():
                emp_totals[k] += v

        lines.append(
            f"| **Total** | **{emp_totals['non_employing']:,}** | **{emp_totals['1_to_4']:,}** "
            f"| **{emp_totals['5_to_19']:,}** | **{emp_totals['20_to_199']:,}** "
            f"| **{emp_totals['200_plus']:,}** | **{emp_totals['total']:,}** |"
        )
        lines.append("")

    # --- Section 8: AI Consulting for $10M+ ---
    lines.append("---")
    lines.append("")
    lines.append("## 8. AI Consulting Addressable Market ($10M+ Only)")
    lines.append("")
    lines.append("Enterprise businesses with $10M+ turnover and their AI consulting potential.")
    lines.append("")

    ai_fit = {
        "Construction": ("HIGH", "Project management AI, safety compliance, estimating, BIM automation"),
        "Manufacturing": ("HIGH", "Quality control, predictive maintenance, supply chain optimization, process automation"),
        "Wholesale Trade": ("HIGH", "Order processing, demand forecasting, inventory optimization, B2B automation"),
        "Retail Trade": ("HIGH", "Customer analytics, dynamic pricing, supply chain, omnichannel automation"),
        "Transport, Postal and Warehousing": ("HIGH", "Route optimization, fleet management, logistics AI, warehouse automation"),
        "Health Care and Social Assistance": ("HIGH", "Clinical decision support, scheduling, compliance, patient analytics"),
        "Professional, Scientific and Technical Services": ("HIGH", "Knowledge management, document automation, research analysis"),
        "Administrative and Support Services": ("HIGH", "Process automation, workforce management, document processing"),
        "Accommodation and Food Services": ("MEDIUM", "Revenue management, guest analytics, supply chain"),
        "Financial and Insurance Services": ("HIGH", "Risk modeling, compliance automation, fraud detection, customer service AI"),
        "Education and Training": ("HIGH", "Personalized learning, assessment automation, content generation"),
        "Information Media and Telecommunications": ("HIGH", "Content automation, network optimization, customer analytics"),
        "Electricity, Gas, Water and Waste Services": ("HIGH", "Grid optimization, predictive maintenance, demand forecasting"),
        "Public Administration and Safety": ("MEDIUM", "Document processing, citizen services, compliance"),
        "Mining": ("HIGH", "Exploration analytics, equipment maintenance, safety monitoring"),
        "Rental, Hiring and Real Estate Services": ("MEDIUM", "Property analytics, tenant management, listings automation"),
        "Other Services": ("MEDIUM", "Customer service, scheduling, marketing automation"),
        "Arts and Recreation Services": ("MEDIUM", "Content creation, marketing, ticketing analytics"),
        "Agriculture, Forestry and Fishing": ("MEDIUM", "Precision agriculture, yield prediction, supply chain"),
    }

    lines.append("| AI Fit | Industry | $10M+ Biz | $5M+ Biz | Enterprise AI Use Case |")
    lines.append("|:------:|----------|----------:|---------:|------------------------|")

    # Sort by 10m_plus descending within fit level
    high_fit = []
    medium_fit = []
    for ind_name, ind in sorted_industries:
        fit_level, use_case = ai_fit.get(ind_name, ("MEDIUM", "General automation"))
        over_5m = ind["10m_plus"] + ind["5m_to_10m"]
        entry = (fit_level, ind_name, ind["10m_plus"], over_5m, use_case)
        if fit_level == "HIGH":
            high_fit.append(entry)
        else:
            medium_fit.append(entry)

    high_fit.sort(key=lambda x: x[2], reverse=True)
    medium_fit.sort(key=lambda x: x[2], reverse=True)

    total_high_10m = 0
    total_high_5m = 0
    total_med_10m = 0
    total_med_5m = 0

    for fit, ind_name, ten_m, five_m, use_case in high_fit + medium_fit:
        lines.append(f"| **{fit}** | {ind_name} | {ten_m:,} | {five_m:,} | {use_case} |")
        if fit == "HIGH":
            total_high_10m += ten_m
            total_high_5m += five_m
        else:
            total_med_10m += ten_m
            total_med_5m += five_m

    lines.append("")
    lines.append(f"**HIGH-fit $10M+ businesses: {total_high_10m:,}** ({total_high_5m:,} over $5M)")
    lines.append(f"**MEDIUM-fit $10M+ businesses: {total_med_10m:,}** ({total_med_5m:,} over $5M)")
    lines.append(f"**Total addressable market: {total_high_10m + total_med_10m:,}** businesses with $10M+ turnover")
    lines.append("")

    # --- Section 9: Targeting Summary ---
    lines.append("---")
    lines.append("")
    lines.append("## 9. Targeting Summary: Enterprise Offer Tiers")
    lines.append("")
    lines.append("| Offer Tier | Target Revenue | Target Industries | Est. Addressable | Consulting Price Point |")
    lines.append("|-----------|---------------|-------------------|----------------:|----------------------|")
    lines.append(f"| Strategic | $10M - $50M | All HIGH fit | {total_high_10m:,} | $25,000 - $75,000 |")
    lines.append(f"| Enterprise | $50M+ | All HIGH fit | TBD | $75,000 - $250,000+ |")
    lines.append(f"| Specialist | $10M+ | MEDIUM fit | {total_med_10m:,} | $15,000 - $50,000 |")
    lines.append("")

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(lines))
    print(f"Report written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
