"""
Professional HTML Report Generator - iOS Glassmorphism Dashboard
UPDATED WITH REACTIVE FILTERING ENGINE
"""

import os
import re
import json
from datetime import datetime


def format_currency_usd(value):
    if value >= 1000000:
        return f"${value/1000000:.2f}M"
    elif value >= 1000:
        return f"${value/1000:.1f}K"
    else:
        return f"${value:.2f}"


def get_occupancy_color(occ):

    if occ >= 60:
        return "#4ade80"

    elif occ >= 50:
        return "#fb923c"

    elif occ >= 30:
        return "#facc15"

    else:
        return "#f87171"


def get_time_category(time_str):

    try:

        clean_time = time_str.strip()

        clean_time = re.sub(
            r"(?i)\s*o'clock\s*",
            ":00 ",
            clean_time
        )

        t = datetime.strptime(
            clean_time.strip(),
            "%I:%M %p"
        )

        h = t.hour

        if 5 <= h < 9:
            return "1. Early Morning (5am-9am)"

        elif 9 <= h < 12:
            return "2. Morning (9am-12pm)"

        elif 12 <= h < 16:
            return "3. Afternoon (12pm-4pm)"

        elif 16 <= h < 20:
            return "4. Evening (4pm-8pm)"

        elif 20 <= h < 24:
            return "5. Night (8pm-12am)"

        else:
            return "6. Midnight (12am-5am)"

    except:
        return "7. Unknown Time"


def get_chain_category(theater_name):

    name = theater_name.upper()

    if "AMC" in name:
        return "AMC Theatres"

    if "CINEMARK" in name or "CENTURY" in name:
        return "Cinemark"

    if "REGAL" in name:
        return "Regal Cinemas"

    if "MARCUS" in name:
        return "Marcus Theatres"

    if "HARKINS" in name:
        return "Harkins Theatres"

    if "APPLE CINEMAS" in name:
        return "Apple Cinemas"
    
    if "LANDMARK" in name:
        return "Landmark Theatres"
    
    if "VILLAGE" in name:
        return "Village Cinemas"
    
    if "HOYTS" in name:
        return "Hoyts Cinemas"

    return "Other / Independents"


def generate_fandango_html_report(
        data,
        filename,
        movie_name="Movie",
        show_date="N/A",
        previous_shows_data=None,
        last_updated_str="N/A",
        country_name=""
):

    # ========================================================
    # FRONTEND RAW DATA
    # ========================================================

    frontend_rows = []

    for row in data:

        fmt = row.get('format', 'Standard')

        if 'D-Box' in fmt and 'Premium' in fmt:
            fmt = 'Premium'

        frontend_rows.append({

            't_id': row.get('t_id', ''),
            'state': row.get('state', 'Unknown'),
            'theater': row.get('theater', 'Unknown'),
            'format': fmt,
            'language': row.get('language', 'Unknown'),
            'time': row.get('time', 'Unknown'),

            'timeCat': get_time_category(
                row.get('time', 'Unknown')
            ),

            'chain': get_chain_category(
                row.get('theater', 'Unknown')
            ),

            'status': row.get('status', 'Available'),

            'price_str': row.get(
                'price_str',
                '$0.00'
            ),

            'total': row.get('total', 0),
            'booked': row.get('booked', 0),
            'gross': row.get('gross', 0),

            'is_extra': row.get(
                'is_extra',
                False
            )

        })

    frontend_json = json.dumps(frontend_rows)

    previous_frontend_rows = []

    for row in (previous_shows_data or []):

        fmt = row.get('format', 'Standard')

        if 'D-Box' in fmt and 'Premium' in fmt:
            fmt = 'Premium'

        previous_frontend_rows.append({

            't_id': row.get('t_id', ''),
            'state': row.get('state', 'Unknown'),
            'theater': row.get('theater', 'Unknown'),
            'format': fmt,
            'language': row.get('language', 'Unknown'),
            'time': row.get('time', 'Unknown'),
            'gross': row.get('gross', 0),
            'booked': row.get('booked', 0)

        })

    previous_json = json.dumps(previous_frontend_rows)


    # ========================================================
    # GLOBAL TOTALS
    # ========================================================

    total_venues = len(
        set(
            r['t_id']
            for r in data
            if r['t_id'] != 'EXTRA'
        )
    )

    total_shows = sum(
        1
        for r in data
        if not r.get('is_extra', False)
    )

    total_tickets = sum(r['total'] for r in data)

    total_booked = sum(r['booked'] for r in data)

    total_gross = sum(r['gross'] for r in data)

    overall_occ = (
        total_booked / total_tickets * 100
    ) if total_tickets > 0 else 0

    atp = (
        total_gross / total_booked
    ) if total_booked > 0 else 0


    # ========================================================
    # PREVIOUS TOTALS
    # ========================================================

    p_total_venues = len(
        set(
            r['t_id']
            for r in previous_shows_data
            if r['t_id'] != 'EXTRA'
        )
    ) if previous_shows_data else 0

    p_total_shows = sum(
        1
        for r in previous_shows_data
        if not r.get('is_extra', False)
    ) if previous_shows_data else 0

    p_total_booked = sum(
        r['booked']
        for r in previous_shows_data
    ) if previous_shows_data else 0

    p_total_gross = sum(
        r['gross']
        for r in previous_shows_data
    ) if previous_shows_data else 0


    # ========================================================
    # DELTAS
    # ========================================================

    d_total_venues = total_venues - p_total_venues

    d_total_shows = total_shows - p_total_shows

    d_total_booked = total_booked - p_total_booked

    d_total_gross = total_gross - p_total_gross


    # ========================================================
    # HTML
    # ========================================================

    html_content = f"""

<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>
    {movie_name} - {country_name} Advance Sales Report
</title>


<link
    href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
    rel="stylesheet"
>

<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>


<style>

:root {{

    --bg-color: #020617;

    --text-main: #f8fafc;

    --text-muted: #94a3b8;

    --primary: #f58320;

    --glass-bg: rgba(255, 255, 255, 0.03);

    --glass-border: rgba(255, 255, 255, 0.06);

    --glass-highlight: rgba(255, 255, 255, 0.12);

}}


* {{

    box-sizing: border-box;

    margin: 0;

    padding: 0;

    font-family: 'Inter', sans-serif;

}}


body {{

    background-color: var(--bg-color);

    background-image:
        radial-gradient(
            circle at 10% 20%,
            rgba(37, 99, 235, 0.12),
            transparent 30%
        ),

        radial-gradient(
            circle at 90% 40%,
            rgba(245, 131, 32, 0.08),
            transparent 30%
        ),

        radial-gradient(
            circle at 50% 90%,
            rgba(139, 92, 246, 0.12),
            transparent 40%
        );

    background-attachment: fixed;

    color: var(--text-main);

    padding: 20px;

}}


.container {{

    max-width: 1400px;

    margin: 0 auto;

}}


.header {{

    display: flex;

    justify-content: space-between;

    align-items: flex-end;

    margin-bottom: 25px;

    padding-bottom: 15px;

    border-bottom: 1px solid var(--glass-border);

}}


.header h1 {{

    font-size: 26px;

    font-weight: 600;

    color: var(--text-main);

    letter-spacing: -0.5px;

}}


.header-meta {{

    text-align: right;

    color: var(--text-muted);

    font-size: 13px;

    line-height: 1.6;

}}


.header-meta strong {{

    color: var(--text-main);

    font-weight: 500;

}}


.kpi-grid {{

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(200px, 1fr)
        );

    gap: 15px;

    margin-bottom: 20px;

}}


.kpi-card {{

    background: var(--glass-bg);

    backdrop-filter: blur(16px);

    -webkit-backdrop-filter: blur(16px);

    padding: 20px;

    border-radius: 16px;

    border: 1px solid var(--glass-border);

    border-top: 1px solid var(--glass-highlight);

    border-left: 1px solid var(--glass-highlight);

    box-shadow:
        0 8px 32px 0 rgba(0, 0, 0, 0.2);

    position: relative;

    overflow: hidden;

}}


.kpi-title {{

    font-size: 12px;

    color: var(--text-muted);

    text-transform: uppercase;

    letter-spacing: 0.5px;

    font-weight: 600;

    margin-bottom: 8px;

}}


.kpi-value {{

    font-size: 26px;

    font-weight: 600;

    color: var(--text-main);

}}


.kpi-sub {{

    font-size: 12px;

    color: var(--text-muted);

    margin-top: 6px;

}}


.delta-positive {{

    color: #4ade80;

    font-weight: 500;

    font-size: 12px;

}}


.delta-negative {{

    color: #f87171;

    font-weight: 500;

    font-size: 12px;

}}


.delta-neutral {{

    color: var(--text-muted);

    font-size: 12px;

}}


.dashboard-row {{

    display: grid;

    grid-template-columns: 1fr 1fr;

    gap: 20px;

    margin-bottom: 20px;

    align-items: stretch;

}}


@media (max-width: 1000px) {{

.dashboard-row {{

    grid-template-columns: 1fr;

}}

}}


.summary-section {{

    background: var(--glass-bg);

    backdrop-filter: blur(16px);

    -webkit-backdrop-filter: blur(16px);

    border-radius: 16px;

    padding: 20px;

    border: 1px solid var(--glass-border);

    border-top: 1px solid var(--glass-highlight);

    border-left: 1px solid var(--glass-highlight);

    box-shadow:
        0 8px 32px 0 rgba(0, 0, 0, 0.2);

    overflow-x: auto;

    display: flex;

    flex-direction: column;

}}
.summary-section h2 {{

    font-size: 16px;

    margin-bottom: 15px;

    font-weight: 500;

    color: var(--text-main);

    border-bottom: 1px solid var(--glass-border);

    padding-bottom: 10px;

    display: flex;

    justify-content: space-between;

    align-items: center;

}}


table {{

    width: 100%;

    border-collapse: collapse;

    font-size: 13px;

}}


th,
td {{

    padding: 12px 10px;

    text-align: right;

    border-bottom:
        1px solid rgba(255,255,255,0.04);

}}


th {{

    background-color:
        rgba(255, 255, 255, 0.02);

    backdrop-filter: blur(10px);

    -webkit-backdrop-filter: blur(10px);

    color: var(--text-muted);

    font-weight: 600;

    text-transform: uppercase;

    letter-spacing: 0.5px;

    font-size: 11px;

    cursor: pointer;

    user-select: none;

    position: sticky;

    top: 0;

    z-index: 10;

}}


th:first-child,
td:first-child {{

    text-align: left;

}}


tr:hover td {{

    background-color:
        rgba(255,255,255,0.04);

}}


.gross-val {{

    font-weight: 600;

    color: #f8fafc;

}}


.state-col {{

    font-weight: 500;

    color: var(--text-muted);

}}


.theater-col {{

    font-weight: 400;

    color: #cbd5e1;

    white-space: nowrap;

    overflow: hidden;

    text-overflow: ellipsis;

    max-width: 200px;

}}


.format-col {{

    color: #fbbf24;

    font-weight: 500;

}}


.language-col {{

    color: #a78bfa;

    font-weight: 500;

}}


.aggregate-row td {{

    background-color: rgba(0,0,0,0.2);

    font-weight: 600;

    border-top:
        1px solid var(--glass-highlight);

    color: #cbd5e1;

}}


.status-badge {{

    padding: 4px 8px;

    border-radius: 4px;

    font-size: 10px;

    font-weight: 600;

    text-transform: uppercase;

    letter-spacing: 0.5px;

}}


.status-available {{

    background-color:
        rgba(22, 163, 74, 0.15);

    color: #4ade80;

    border:
        1px solid rgba(74, 222, 128, 0.2);

}}


.status-sold-out {{

    background-color:
        rgba(220, 38, 38, 0.15);

    color: #f87171;

    border:
        1px solid rgba(248, 113, 113, 0.2);

}}


.btn-toggle {{

    background:
        rgba(255,255,255,0.05);

    border:
        1px solid var(--glass-border);

    backdrop-filter: blur(10px);

    padding: 8px 12px;

    border-radius: 8px;

    cursor: pointer;

    font-size: 12px;

    font-weight: 500;

    color: var(--text-main);

    margin-top: auto;

    width: 100%;

    transition: all 0.2s;

}}


.btn-toggle:hover {{

    background:
        rgba(255,255,255,0.1);

    border-color: var(--glass-highlight);

}}


.footer {{

    text-align: center;

    margin-top: 30px;

    padding-top: 20px;

    border-top:
        1px solid var(--glass-border);

    color: var(--text-muted);

    font-size: 12px;

}}



/* ===================================================== */
/* FILTER PANEL */
/* ===================================================== */

.filter-panel {{

    background: var(--glass-bg);

    backdrop-filter: blur(16px);

    -webkit-backdrop-filter: blur(16px);

    border-radius: 16px;

    padding: 20px;

    border: 1px solid var(--glass-border);

    border-top: 1px solid var(--glass-highlight);

    border-left: 1px solid var(--glass-highlight);

    margin-bottom: 20px;

}}


.filter-grid {{

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(220px, 1fr)
        );

    gap: 16px;

}}


.filter-label {{

    font-size: 11px;

    text-transform: uppercase;

    letter-spacing: 0.5px;

    color: var(--text-muted);

    margin-bottom: 8px;

    font-weight: 600;

}}


.filter-select {{

    width: 100%;

    background:
        rgba(255,255,255,0.04);

    border:
        1px solid var(--glass-border);

    color: var(--text-main);

    padding: 12px;

    border-radius: 10px;

    outline: none;

    font-size: 13px;

}}


.filter-select option {{

    background: #0f172a;

    color: white;

}}


.toggle-filter-btn {{

    background:
        linear-gradient(
            135deg,
            #2563eb,
            #1d4ed8
        );

    border: none;

    color: white;

    padding: 12px 18px;

    border-radius: 10px;

    cursor: pointer;

    font-size: 13px;

    font-weight: 600;

    transition: all 0.2s;

}}


.toggle-filter-btn:hover {{

    transform: translateY(-1px);

    opacity: 0.95;

}}

</style>

</head>

<body>

<div id="app">

<div class="container">

    <!-- ================================================= -->
    <!-- HEADER -->
    <!-- ================================================= -->

    <div class="header">

        <h1>
            {movie_name} - Advance Sales Report
        </h1>

        <div class="header-meta">

            Show Date:
            <strong>{show_date}</strong>

            <br>

            Report Generated:

            <strong>
                {datetime.now().strftime("%d %b %Y, %I:%M %p")}
            </strong> IST

            <br>

            Last tracked:

            <strong>{last_updated_str}</strong> IST

        </div>

    </div>



    <!-- ================================================= -->
    <!-- FILTER TOGGLE -->
    <!-- ================================================= -->

    <div
        style="
            display:flex;
            justify-content:flex-end;
            margin-bottom:20px;
        "
    >

        <button
            @click="showFilters = !showFilters"
            class="toggle-filter-btn"
        >

            {{{{
                showFilters
                    ? 'Hide Filters'
                    : 'Show Filters'
            }}}}

        </button>

    </div>



    <!-- ================================================= -->
    <!-- FILTER PANEL -->
    <!-- ================================================= -->

    <div
        v-show="showFilters"
        class="filter-panel"
    >

        <div class="filter-grid">

            <!-- STATE -->

            <div>

                <div class="filter-label">
                    State
                </div>

                <select
                    v-model="filters.state"
                    class="filter-select"
                >

                    <option value="ALL">
                        All States
                    </option>

                    <option
                        v-for="st in uniqueStates"
                        :key="st"
                        :value="st"
                    >

                        {{{{ st }}}}

                    </option>

                </select>

            </div>



            <!-- CHAIN -->

            <div>

                <div class="filter-label">
                    Theatre Chain
                </div>

                <select
                    v-model="filters.chain"
                    class="filter-select"
                >

                    <option value="ALL">
                        All Chains
                    </option>

                    <option
                        v-for="ch in uniqueChains"
                        :key="ch"
                        :value="ch"
                    >

                        {{{{ ch }}}}

                    </option>

                </select>

            </div>



            <!-- THEATRE -->

            <div>

                <div class="filter-label">
                    Theatre
                </div>

                <select
                    v-model="filters.theater"
                    class="filter-select"
                >

                    <option value="ALL">
                        All Theatres
                    </option>

                    <option
                        v-for="th in filteredTheatersList"
                        :key="th"
                        :value="th"
                    >

                        {{{{ th }}}}

                    </option>

                </select>

            </div>



            <!-- FORMAT -->

            <div>

                <div class="filter-label">
                    Format
                </div>

                <select
                    v-model="filters.format"
                    class="filter-select"
                >

                    <option value="ALL">
                        All Formats
                    </option>

                    <option
                        v-for="fm in uniqueFormats"
                        :key="fm"
                        :value="fm"
                    >

                        {{{{ fm }}}}

                    </option>

                </select>

            </div>



            <!-- LANGUAGE -->

            <div>

                <div class="filter-label">
                    Language
                </div>

                <select
                    v-model="filters.language"
                    class="filter-select"
                >

                    <option value="ALL">
                        All Languages
                    </option>

                    <option
                        v-for="lg in uniqueLanguages"
                        :key="lg"
                        :value="lg"
                    >

                        {{{{ lg }}}}

                    </option>

                </select>

            </div>



            <!-- TIME -->

            <div>

                <div class="filter-label">
                    Time Of Day
                </div>

                <select
                    v-model="filters.timeCat"
                    class="filter-select"
                >

                    <option value="ALL">
                        All Times
                    </option>

                    <option
                        v-for="tm in uniqueTimeCats"
                        :key="tm"
                        :value="tm"
                    >

                        {{{{ tm }}}}

                    </option>

                </select>

            </div>

        </div>

    </div>



    <!-- ================================================= -->
    <!-- KPI GRID -->
    <!-- ================================================= -->

    <div class="kpi-grid">

        <div class="kpi-card">

            <div class="kpi-title">
                Total Gross
            </div>

            <div class="kpi-value">

                $
                {{{{
                    formatCurrency(kpis.gross)
                }}}}

            </div>

            <div
                class="kpi-sub"
                :style="{{
                    color:
                        kpis.grossGrowth > 0
                            ? '#4ade80'
                            : kpis.grossGrowth < 0
                                ? '#f87171'
                                : '#94a3b8'
                }}"
            >

                {{{{
                    kpis.grossGrowth > 0
                        ? '+'
                        : kpis.grossGrowth < 0
                            ? '-'
                            : ''
                }}}}${{{{ formatKPICurrency(kpis.grossGrowth) }}}}



            </div>

        </div>



        <div class="kpi-card">

            <div class="kpi-title">
                Tickets Sold
            </div>

            <div class="kpi-value">

                {{{{
                    kpis.booked.toLocaleString()
                }}}}

            </div>

            <div
                class="kpi-sub"
                :style="{{
                    color:
                        kpis.ticketGrowth > 0
                            ? '#4ade80'
                            : kpis.ticketGrowth < 0
                                ? '#f87171'
                                : '#94a3b8'
                }}"
            >

                {{{{ kpis.ticketGrowth > 0 ? '+' : '' }}}}{{{{ formatCurrency(kpis.ticketGrowth) }}}}

            </div>

        </div>



        <div class="kpi-card">

            <div class="kpi-title">
                Total Venues
            </div>

            <div class="kpi-value">

                {{{{
                    kpis.venues.toLocaleString()
                }}}}

            </div>

        </div>



        <div class="kpi-card">

            <div class="kpi-title">
                Total Shows
            </div>

            <div class="kpi-value">

                {{{{
                    kpis.shows.toLocaleString()
                }}}}

            </div>

            <div
                class="kpi-sub"
                :style="{{
                    color:
                        kpis.showGrowth > 0
                            ? '#4ade80'
                            : kpis.showGrowth < 0
                                ? '#f87171'
                                : '#94a3b8'
                }}"
            >

                {{{{ kpis.showGrowth > 0 ? '+' : '' }}}}{{{{ formatCurrency(kpis.showGrowth) }}}}

            </div>

        </div>
                <div class="kpi-card">

            <div class="kpi-title">
                Overall Occupancy
            </div>

            <div
                class="kpi-value"
                :style="{{
                    color: getOccupancyColor(
                        kpis.occupancy
                    )
                }}"
            >

                {{{{
                    kpis.occupancy.toFixed(1)
                }}}}%

            </div>

        </div>



        <div class="kpi-card">

            <div class="kpi-title">
                Avg Ticket Price
            </div>

            <div class="kpi-value">

                $
                {{{{
                    kpis.atp.toFixed(0)
                }}}}

            </div>

        </div>

    </div>



    <!-- ================================================= -->
    <!-- FORMAT + LANGUAGE -->
    <!-- ================================================= -->

    <div class="dashboard-row">

        <!-- FORMAT -->

        <div class="summary-section">

            <h2>
                Format Distribution
            </h2>

            <table>

                <thead>

                    <tr>

                        <th>Format</th>

                        <th>Shows</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="row in formatSummary"
                        :key="row.name"
                    >

                        <td class="format-col">

                            {{{{ row.name }}}}

                        </td>

                        <td>

                            {{{{
                                row.shows.toLocaleString()
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        row.occupancy
                                    )
                            }}"
                        >

                            {{{{
                                row.occupancy.toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthGross > 0
                                        ? '#4ade80'
                                        : row.growthGross < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{
                                row.growthGross > 0
                                    ? '+'
                                    : row.growthGross < 0
                                        ? '-'
                                        : ''
                            }}}} ${{{{ formatKPICurrency(row.growthGross) }}}}

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>



        <!-- LANGUAGE -->

        <div class="summary-section">

            <h2>
                Language Distribution
            </h2>

            <table>

                <thead>

                    <tr>

                        <th>Language</th>

                        <th>Shows</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="row in languageSummary"
                        :key="row.name"
                    >

                        <td class="language-col">

                            {{{{ row.name }}}}

                        </td>

                        <td>

                            {{{{
                                row.shows.toLocaleString()
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        row.occupancy
                                    )
                            }}"
                        >

                            {{{{
                                row.occupancy.toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthGross > 0
                                        ? '#4ade80'
                                        : row.growthGross < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{
                                row.growthGross > 0
                                    ? '+'
                                    : row.growthGross < 0
                                        ? '-'
                                        : ''
                            }}}} ${{{{ formatKPICurrency(row.growthGross) }}}}

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>

    </div>



    <!-- ================================================= -->
    <!-- STATES + THEATRES -->
    <!-- ================================================= -->

    <div class="dashboard-row">

        <!-- STATES -->

        <div class="summary-section">

            <h2>
                State Distribution
            </h2>

            <table>

                <thead>

                    <tr>

                        <th>State</th>

                        <th>Shows</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="row in stateSummary"
                        :key="row.name"
                    >

                        <td class="state-col">

                            {{{{ row.name }}}}

                        </td>

                        <td>

                            {{{{
                                row.shows.toLocaleString()
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        row.occupancy
                                    )
                            }}"
                        >

                            {{{{
                                row.occupancy.toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthGross > 0
                                        ? '#4ade80'
                                        : row.growthGross < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{
                                row.growthGross > 0
                                    ? '+'
                                    : row.growthGross < 0
                                        ? '-'
                                        : ''
                            }}}} ${{{{ formatKPICurrency(row.growthGross) }}}}

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>



        <!-- THEATRES -->

        <div class="summary-section">

            <h2>
                Top Theatres
            </h2>

            <table>

                <thead>

                    <tr>

                        <th>State</th>

                        <th>Theatre</th>

                        <th>Shows</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="row in displayedTheatreSummary"
                        :key="row.name"
                    >

                        <td class="state-col">

                            {{{{ row.state }}}}

                        </td>

                        <td class="theater-col">

                            {{{{ row.name }}}}

                        </td>

                        <td>

                            {{{{
                                row.shows.toLocaleString()
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        row.occupancy
                                    )
                            }}"
                        >

                            {{{{
                                row.occupancy.toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthGross > 0
                                        ? '#4ade80'
                                        : row.growthGross < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{
                                row.growthGross > 0
                                    ? '+'
                                    : row.growthGross < 0
                                        ? '-'
                                        : ''
                            }}}} ${{{{ formatKPICurrency(row.growthGross) }}}}

                        </td>

                    </tr>

                    <tr v-if="theatreSummary.length > 40">

                        <td
                            colspan="7"
                            style="
                                text-align:center;
                                padding:18px;
                                border-bottom:none;
                            "
                        >

                            <button
                                @click="
                                    showAllTheatres =
                                        !showAllTheatres
                                "
                                class="btn-toggle"
                                style="
                                    width:auto;
                                    padding:10px 18px;
                                "
                            >

                                {{{{
                                    showAllTheatres
                                        ? 'Hide Full Theatre List'
                                        : 'Show Full Theatre List'
                                }}}}

                            </button>

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>

    </div>
        <!-- ================================================= -->
    <!-- CHAIN + TIME -->
    <!-- ================================================= -->

    <div class="dashboard-row">

        <!-- CHAINS -->

        <div class="summary-section">

            <h2>
                Theatre Chain Distribution
            </h2>

            <table>

                <thead>

                    <tr>

                        <th>Chain</th>

                        <th>Shows</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="row in chainSummary"
                        :key="row.name"
                    >

                        <td class="format-col">

                            {{{{ row.name }}}}

                        </td>

                        <td>

                            {{{{
                                row.shows.toLocaleString()
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        row.occupancy
                                    )
                            }}"
                        >

                            {{{{
                                row.occupancy.toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthGross > 0
                                        ? '#4ade80'
                                        : row.growthGross < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{
                                row.growthGross > 0
                                    ? '+'
                                    : row.growthGross < 0
                                        ? '-'
                                        : ''
                            }}}} ${{{{ formatKPICurrency(row.growthGross) }}}}

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>



        <!-- TIME -->

        <div class="summary-section">

            <h2>
                Time Of Day Analysis
            </h2>

            <table>

                <thead>

                    <tr>

                        <th>Time Category</th>

                        <th>Shows</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="row in timeSummary"
                        :key="row.name"
                    >

                        <td class="state-col">

                            {{{{ row.name }}}}

                        </td>

                        <td>

                            {{{{
                                row.shows.toLocaleString()
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        row.occupancy
                                    )
                            }}"
                        >

                            {{{{
                                row.occupancy.toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthGross > 0
                                        ? '#4ade80'
                                        : row.growthGross < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{
                                row.growthGross > 0
                                    ? '+'
                                    : row.growthGross < 0
                                        ? '-'
                                        : ''
                            }}}} ${{{{ formatKPICurrency(row.growthGross) }}}}

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>

    </div>



    <!-- ================================================= -->
    <!-- ALL SHOWS -->
    <!-- ================================================= -->

    <div
        class="summary-section"
        style="margin-bottom:0;"
    >

        <h2>

            All Showtimes

            <span
                style="
                    font-size:12px;
                    font-weight:400;
                    color:var(--text-muted);
                "
            >

                (Reactive Filtering Enabled)

            </span>

        </h2>


        <div
            style="
                overflow-x:auto;
                max-height:700px;
                overflow-y:auto;
            "
        >

            <table id="showsTable">

                <thead>

                    <tr>

                        <th>St</th>

                        <th>Format</th>

                        <th>Language</th>

                        <th>Theatre Name</th>

                        <th>Time</th>

                        <th>Time Category</th>

                        <th>Status</th>

                        <th>Price</th>

                        <th>Tickets</th>

                        <th>Gross</th>

                        <th>Occ %</th>

                        <th>Growth</th>

                    </tr>

                </thead>

                <tbody>

                    <tr
                        v-for="(row, idx) in filteredShows"
                        :key="idx"
                    >

                        <td class="state-col">

                            {{{{
                                row.state.slice(0,4)
                                    .toUpperCase()
                            }}}}

                        </td>

                        <td class="format-col">

                            {{{{ row.format }}}}

                        </td>

                        <td class="language-col">

                            {{{{ row.language }}}}

                        </td>

                        <td class="theater-col">

                            {{{{ row.theater }}}}

                        </td>

                        <td>

                            {{{{ row.time }}}}

                        </td>

                        <td
                            style="
                                font-size:11px;
                                color:#94a3b8;
                            "
                        >

                            {{{{ row.timeCat }}}}

                        </td>

                        <td>

                            <span
                                class="status-badge"
                                :class="[
                                    row.status
                                        === 'Sold Out'
                                            ? 'status-sold-out'
                                            : 'status-available'
                                ]"
                            >

                                {{{{ row.status }}}}

                            </span>

                        </td>

                        <td
                            style="color:#94a3b8;"
                        >

                            {{{{
                                row.price_str
                            }}}}

                        </td>

                        <td>

                            {{{{
                                row.booked.toLocaleString()
                            }}}}

                        </td>

                        <td class="gross-val">

                            $
                            {{{{
                                formatCurrency(row.gross)
                            }}}}

                        </td>

                        <td
                            :style="{{
                                color:
                                    getOccupancyColor(
                                        (
                                            row.booked
                                            / row.total
                                        ) * 100
                                    )
                            }}"
                        >

                            {{{{
                                (
                                    (row.booked / row.total) * 100
                                ).toFixed(1)
                            }}}}%

                        </td>

                        <td
                            :style="{{
                                color:
                                    row.growthTickets > 0
                                        ? '#4ade80'
                                        : row.growthTickets < 0
                                            ? '#f87171'
                                            : '#94a3b8'
                            }}"
                        >

                            {{{{ row.growthTickets > 0 ? '+' : '' }}}}{{{{ row.growthTickets }}}}

                        </td>

                    </tr>

                </tbody>

            </table>

        </div>

    </div>



    <!-- ================================================= -->
    <!-- FOOTER -->
    <!-- ================================================= -->

    <div class="footer">

        Data Aggregation •
        Fandango Scraper Engine v4 •

        Generated

        {datetime.now().strftime("%d %b %Y, %I:%M %p")}

    </div>

</div>



<!-- ===================================================== -->
<!-- VUE ENGINE -->
<!-- ===================================================== -->

<script>

window.__MASTER_DATA__ = {frontend_json};

window.__PREVIOUS_DATA__ = {previous_json};

const {{ createApp }} = Vue;

createApp({{

    data() {{

        return {{

            rawData: window.__MASTER_DATA__,

            previousData: window.__PREVIOUS_DATA__ || [],

            showFilters: true,

            showAllTheatres: false,

            filters: {{

                state: 'ALL',

                chain: 'ALL',

                theater: 'ALL',

                format: 'ALL',

                language: 'ALL',

                timeCat: 'ALL'

            }}

        }}

    }},
        computed: {{

        // =================================================
        // UNIQUE FILTER VALUES
        // =================================================

        uniqueStates() {{

            return [

                ...new Set(
                    this.rawData.map(
                        d => d.state
                    )
                )

            ].sort();

        }},


        uniqueChains() {{

            return [

                ...new Set(
                    this.rawData.map(
                        d => d.chain
                    )
                )

            ].sort();

        }},


        uniqueFormats() {{

            return [

                ...new Set(
                    this.rawData.map(
                        d => d.format
                    )
                )

            ].sort();

        }},


        uniqueLanguages() {{

            return [

                ...new Set(
                    this.rawData.map(
                        d => d.language
                    )
                )

            ].sort();

        }},


        uniqueTimeCats() {{

            return [

                ...new Set(
                    this.rawData.map(
                        d => d.timeCat
                    )
                )

            ].sort();

        }},



        // =================================================
        // DEPENDENT THEATRE DROPDOWN
        // =================================================

        filteredTheatersList() {{

            let data = this.rawData;

            if (this.filters.state !== 'ALL') {{

                data = data.filter(
                    d =>
                        d.state
                        === this.filters.state
                );

            }}

            if (this.filters.chain !== 'ALL') {{

                data = data.filter(
                    d =>
                        d.chain
                        === this.filters.chain
                );

            }}

            return [

                ...new Set(
                    data.map(
                        d => d.theater
                    )
                )

            ].sort();

        }},



        // =================================================
        // MAIN FILTERED DATASET
        // =================================================

        filteredData() {{

            return this.rawData.filter(row => {{

                if (

                    this.filters.state !== 'ALL'

                    &&

                    row.state !== this.filters.state

                )

                    return false;



                if (

                    this.filters.chain !== 'ALL'

                    &&

                    row.chain !== this.filters.chain

                )

                    return false;



                if (

                    this.filters.theater !== 'ALL'

                    &&

                    row.theater !== this.filters.theater

                )

                    return false;



                if (

                    this.filters.format !== 'ALL'

                    &&

                    row.format !== this.filters.format

                )

                    return false;



                if (

                    this.filters.language !== 'ALL'

                    &&

                    row.language !== this.filters.language

                )

                    return false;



                if (

                    this.filters.timeCat !== 'ALL'

                    &&

                    row.timeCat !== this.filters.timeCat

                )

                    return false;



                return true;

            }});

        }},



        // =================================================
        // KPI CALCULATIONS
        // =================================================

        kpis() {{

            const total =

                this.filteredData.reduce(

                    (s, r) => s + r.total,

                    0

                );


            const booked =

                this.filteredData.reduce(

                    (s, r) => s + r.booked,

                    0

                );


            const gross =

                this.filteredData.reduce(

                    (s, r) => s + r.gross,

                    0

                );
            
            const previousFiltered =
                this.previousData.filter(row => {{

                    const chain =
                        this.getChainCategory(
                            row.theater || ''
                        );

                    const timeCat =
                        this.getTimeCategory(
                            row.time || ''
                        );

                    if (
                        this.filters.state !== 'ALL'
                        &&
                        row.state !== this.filters.state
                    )
                        return false;

                    if (
                        this.filters.theater !== 'ALL'
                        &&
                        row.theater !== this.filters.theater
                    )
                        return false;

                    if (
                        this.filters.format !== 'ALL'
                        &&
                        row.format !== this.filters.format
                    )
                        return false;

                    if (
                        this.filters.language !== 'ALL'
                        &&
                        row.language !== this.filters.language
                    )
                        return false;

                    if (
                        this.filters.chain !== 'ALL'
                        &&
                        chain !== this.filters.chain
                    )
                        return false;

                    if (
                        this.filters.timeCat !== 'ALL'
                        &&
                        timeCat !== this.filters.timeCat
                    )
                        return false;

                    return true;

                }});


            return {{

                total,

                booked,

                gross,

                shows: this.filteredData.length,

                venues: new Set(

                    this.filteredData.map(
                        r => r.t_id
                    )

                ).size,

                occupancy:

                    total > 0

                        ? (booked / total) * 100

                        : 0,

                atp:

                    booked > 0

                        ? gross / booked

                        : 0,
                
                grossGrowth:

                    gross -

                    previousFiltered.reduce(
                        (s, r) => s + (r.gross || 0),
                        0
                    ),


                ticketGrowth:

                    booked -

                    previousFiltered.reduce(
                        (s, r) => s + (r.booked || 0),
                        0
                    ),


                showGrowth:

                    this.filteredData.length -

                    previousFiltered.length,

            }}

        }},



        // =================================================
        // REACTIVE SUMMARIES
        // =================================================

        stateSummary() {{

            return this.groupByField(
                'state'
            );

        }},


        theatreSummary() {{

            return this.groupByField(
                'theater'
            );

        }},

        displayedTheatreSummary() {{

            if (this.showAllTheatres) {{

                return this.theatreSummary;

            }}

            return this.theatreSummary.slice(0, 40);

        }},

        formatSummary() {{

            return this.groupByField(
                'format'
            );

        }},


        languageSummary() {{

            return this.groupByField(
                'language'
            );

        }},


        chainSummary() {{

            return this.groupByField(
                'chain'
            );

        }},


        timeSummary() {{

            return this.groupByField(
                'timeCat'
            );

        }},



        // =================================================
        // FILTERED SHOWS
        // =================================================

        filteredShows() {{

            return [...this.filteredData]

                .map(r => {{

                    const prev =
                        this.previousData.find(p =>

                            p.t_id === r.t_id
                            &&
                            p.time === r.time
                            &&
                            p.format === r.format
                            &&
                            p.language === r.language

                        );

                    return {{

                        ...r,

                        growthTickets:

                            r.booked -
                            (prev?.booked || 0)

                    }};

                }})

                .filter(
                    r => !r.is_extra
                )

                .sort(

                    (a, b) =>

                        b.gross - a.gross

                );

        }}

    }},



    methods: {{

        // =================================================
        // FORMAT CURRENCY
        // =================================================

        formatCurrency(v) {{

            const absVal =
                Math.round(
                    Math.abs(Number(v))
                );

            const formatted =
                absVal.toLocaleString(
                    undefined,
                    {{
                        minimumFractionDigits: 0,
                        maximumFractionDigits: 0
                    }}
                );

            return v < 0
                ? '-' + formatted
                : formatted;

        }},

        formatKPICurrency(v) {{

            const absVal =
                Math.round(
                    Math.abs(Number(v))
                );

            const formatted =
                absVal.toLocaleString(
                    undefined,
                    {{
                        minimumFractionDigits: 0,
                        maximumFractionDigits: 0
                    }}
                );

            return formatted;

        }},



        // =================================================
        // OCCUPANCY COLOR
        // =================================================

        getOccupancyColor(occ) {{

            if (occ >= 60)
                return '#4ade80';

            if (occ >= 50)
                return '#fb923c';

            if (occ >= 30)
                return '#facc15';

            return '#f87171';

        }},

        getChainCategory(theaterName) {{

            const name = theaterName.toUpperCase();

            if (name.includes("AMC"))
                return "AMC Theatres";

            if (
                name.includes("CINEMARK")
                ||
                name.includes("CENTURY")
            )
                return "Cinemark";

            if (name.includes("REGAL"))
                return "Regal Cinemas";

            if (name.includes("MARCUS"))
                return "Marcus Theatres";

            if (name.includes("HARKINS"))
                return "Harkins Theatres";

            if (name.includes("APPLE CINEMAS"))
                return "Apple Cinemas";

            return "Other / Independents";

        }},

        getTimeCategory(timeStr) {{

            try {{

                const t = timeStr.toLowerCase();

                if (
                    t.includes('am')
                ) {{

                    const h =
                        parseInt(t.split(':')[0]);

                    if (h >= 5 && h < 9)
                        return "1. Early Morning (5am-9am)";

                    if (h >= 9 && h < 12)
                        return "2. Morning (9am-12pm)";

                }}

                if (
                    t.includes('pm')
                ) {{

                    let h =
                        parseInt(t.split(':')[0]);

                    if (h !== 12)
                        h += 12;

                    if (h >= 12 && h < 16)
                        return "3. Afternoon (12pm-4pm)";

                    if (h >= 16 && h < 20)
                        return "4. Evening (4pm-8pm)";

                    if (h >= 20)
                        return "5. Night (8pm-12am)";
                }}

                return "7. Unknown Time";

            }}

            catch {{

                return "7. Unknown Time";

            }}

        }},



        // =================================================
        // GENERIC GROUPER
        // =================================================

        groupByField(field) {{

            const map = {{}};

            const previousMap = {{}};

            this.filteredData.forEach(r => {{

                const key = r[field];

                if (!map[key]) {{

                    map[key] = {{

                        name: key,

                        state: r.state,

                        shows: 0,

                        total: 0,

                        booked: 0,

                        gross: 0

                    }}

                }}

                map[key].shows += 1;

                map[key].total += r.total;

                map[key].booked += r.booked;

                map[key].gross += r.gross;

            }});

            const previousFiltered =
                this.previousData.filter(row => {{

                    const chain =
                        this.getChainCategory(
                            row.theater || ''
                        );

                    const timeCat =
                        this.getTimeCategory(
                            row.time || ''
                        );

                    if (
                        this.filters.state !== 'ALL'
                        &&
                        row.state !== this.filters.state
                    )
                        return false;

                    if (
                        this.filters.theater !== 'ALL'
                        &&
                        row.theater !== this.filters.theater
                    )
                        return false;

                    if (
                        this.filters.format !== 'ALL'
                        &&
                        row.format !== this.filters.format
                    )
                        return false;

                    if (
                        this.filters.language !== 'ALL'
                        &&
                        row.language !== this.filters.language
                    )
                        return false;

                    if (
                        this.filters.chain !== 'ALL'
                        &&
                        chain !== this.filters.chain
                    )
                        return false;

                    if (
                        this.filters.timeCat !== 'ALL'
                        &&
                        timeCat !== this.filters.timeCat
                    )
                        return false;

                    return true;

                }});

            previousFiltered.forEach(r => {{

                let key = r[field];

                if (field === 'chain') {{

                    key = this.getChainCategory(
                        r.theater || ''
                    );

                }}

                if (field === 'timeCat') {{

                    key = this.getTimeCategory(
                        r.time || ''
                    );

                }}

                if (!previousMap[key]) {{

                    previousMap[key] = {{
                        booked: 0,
                        gross: 0,
                        shows: 0
                    }};

                }}

                previousMap[key].booked += r.booked || 0;
                previousMap[key].gross += r.gross || 0;
                previousMap[key].shows += 1;

            }});

            return Object.values(map)

                .map(r => ({{

                    ...r,

                    occupancy:

                        r.total > 0

                            ? (r.booked / r.total) * 100

                            : 0,



                    growthTickets:

                        r.booked -

                        (previousMap[r.name]?.booked || 0),



                    growthGross:

                        r.gross -

                        (previousMap[r.name]?.gross || 0),



                    growthShows:

                        r.shows -

                        (previousMap[r.name]?.shows || 0)

                }}))

                .sort(

                    (a, b) =>

                        b.gross - a.gross

                );

        }}

    }}

}}).mount('#app');

</script>



</body>

</html>

"""


    # ========================================================
    # SAVE HTML
    # ========================================================

    try:

        with open(
            filename,
            'w',
            encoding='utf-8'
        ) as f:

            f.write(html_content)

        print(
            f"📊 HTML report saved to {filename}"
        )

        return filename

    except Exception as e:

        print(
            f"Error saving HTML: {e}"
        )

        return None
    
