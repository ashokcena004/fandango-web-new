import time
from datetime import datetime, timezone, timedelta
import json
import os
import traceback
import logging
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
import random
from dotenv import load_dotenv
load_dotenv()

import firebase_admin
from firebase_admin import credentials, db

# =============================================================================
# ── 1. CONFIGURATION ─────────────────────────────────────────────────────────
# =============================================================================

MOVIE_ID = "244813" # Peddi
MOVIE_TITLE = "Peddi"
MOVIE_SLUG = "peddi-2026"
SHOW_DATE = "2026-06-23"

MAPPING_FILE = "state_theatre_mapping.json"
OVERWRITE_SNAPSHOT = os.getenv("OVERWRITE_SNAPSHOT", "false").lower() == "true" # ⚠️ Set to True to update the baseline after this run
CUMULATIVE_TRACKING_MODE = True

SEAT_COUNT_MODE = 1
# 1 = Use physical seat map count when available (more accurate but slower)
# 2 = Use cached summary data from API (faster but may be less accurate in some cases)

# 🎯 SCREEN EXCLUSION CONFIGURATION
# Format: "TheaterID_AuditoriumID"
PREFER_CACHED_SCREENS = [
    "9E1KKd3a_10", # Cinemark Merriam and XD - Aud 10
    "9E1KKd3a_25", # Cinemark Merriam and XD - Aud 25
]
PREFER_PHYSICAL_SCREENS = []

# 🔧 AUTOMATIC MULTI-TIER THEATER MERGE LIST
# Add theater IDs here that wrongly split identical shows as duplicate shows across different maps (e.g., Standard vs XD)
# This will surgically combine their seat capacities, tickets sold, and financial gross post-scrape.
MANUAL_MERGE_SHOWS_THEATRES = ["AAILI"]

# 🚫 IGNORE SOLD OUT SHOWS FOR SPECIFIC CHAINS
# If a show at these chains is "Sold Out", its tickets and gross will be zeroed out.
IGNORE_SOLDOUT_CHAINS = ["AMC"]

# 🚨 FALLBACK & PRICING CONFIGURATION
AVG_PRICE = 32.00
MAX_TIER_PRICE = 32.00 #XD D-Box Pricing
FALLBACK_SEATS = 100
PRICE_TAX_CUT = False  # If True, rounds ticket prices down to nearest multiple of 5 (e.g., $29 -> $25)
OCC_THRESHOLD_FRONTROW = 0.50  # If overall occupancy is below this, treat front row 'R' seats as blocks

# 📝 MANUAL SHOWS OVERRIDE (Fan Shows / Missing API Data)
# Format: ["State", "Theater_ID", "Showtime", Booked_Gross, Total_Gross, Booked_Tickets, Total_Tickets, Occupancy_Percentage, Format (Optional), Language (Optional)]
# For EXTRA: ["EXTRA", "", "", Booked_Gross, 0, Booked_Tickets]
MANUAL_SHOWS = [
    #["EXTRA", "", "", 3300.0, 0, 115], #2000 extra blocked in venky, 1300 for AMC River east
    # Example of a fully detailed manual normal show:
    # ["Illinois", "AABCD", "7:00 PM", 1500.0, 3000.0, 75, 150, 0.50, "IMAX", "Telugu"]
    #["New Jersey", "AAEMI", "6:20 PM", 3125.0, 3125.0, 125, 125, 1.0, "Manual", "Telugu"],
    #["New Jersey", "AAEMI", "6:35 PM", 3125.0, 3125.0, 125, 125, 1.0, "Manual", "Telugu"],
]

EXTRA_GROSS_NOTE = "Added extra gross for fans shows which are not added in fandano yet."

# 🚀 MULTI-THREADING CONFIGURATION
MAX_WORKERS = 5  # Optimal balance between speed and Akamai bot-detection

TARGET_STATES = [
    'Alaska', 'Alabama', 'Arkansas', 'Arizona', 'California', 'Colorado', 'Connecticut', 
    'District Of Columbia', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Iowa', 'Idaho', 
    'Illinois', 'Indiana', 'Kansas', 'Kentucky', 'Louisiana', 'Massachusetts', 'Maryland', 
    'Maine', 'Michigan', 'Minnesota', 'Missouri', 'Mississippi', 'Montana', 'North Carolina', 
    'North Dakota', 'Nebraska', 'New Hampshire', 'New Jersey', 'New Mexico', 'Nevada', 
    'New York', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 
    'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Virginia', 'Vermont', 'Washington', 
    'Wisconsin', 'West Virginia', 'Wyoming', 'American Samoa', 'Guam'
 ]

# =============================================================================
# ── WORKER FUNCTION ──────────────────────────────────────────────────────────
# =============================================================================

def process_theaters_worker(task_queue, thread_id, total_tasks, master_hash_cache=None):
    if master_hash_cache is None: master_hash_cache = {}
    
    # Local data stores to prevent thread racing conditions
    local_shows_data = []
    local_summary_data = {}
    local_knowledge_base = {} 
    local_sold_out_queue = []
    local_ignored_shows_log = []
    local_hash_cache = {} # ✨ NEW: Stores the hashes learned in this thread

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        print(f"[Thread-{thread_id}] ⏳ Establishing Akamai Trust...")
        
        try:
            page.goto(f"https://www.fandango.com/{MOVIE_SLUG}-{MOVIE_ID}/movie-overview?date={SHOW_DATE}")
            page.wait_for_timeout(3000)
        except Exception as e:
            pass

        while not task_queue.empty():
            try:
                task_idx, target_state, t = task_queue.get_nowait()
            except queue.Empty:
                break
            time.sleep(random.uniform(0.2, 0.35))    
            t_name = t.get('theaterName', 'Unknown')
            t_id = t.get('theaterId')
            if not t_id: continue
            
            print(f"[Thread-{thread_id}] 🔍 [{task_idx}/{total_tasks}] {target_state[:4].upper()} | {t_name[:40]}")
            api_url = f"https://www.fandango.com/napi/theaterMovieShowtimes/{t_id}?chainCode=&startDate={SHOW_DATE}&isdesktop=false"
            
            try:

                raw_data = page.evaluate(f"""async () => {{
                    try {{
                        const response = await fetch('{api_url}');
                        if (!response.ok) return null;
                        return await response.json();
                    }} catch(e) {{ return null; }}
                }}""")

                if not raw_data: 
                    print(f"[Thread-{thread_id}] ⚠️ FAILED TO FETCH THEATER MASTER LIST (Akamai Block/Timeout) for {t_name}")
                    continue

                movies = raw_data.get('viewModel', {}).get('movies', [])
                target_movie = next((m for m in movies if str(m.get('id', '')) == MOVIE_ID), None)
                if not target_movie: 
                    continue
                    
                print(f"[Thread-{thread_id}] 🎬 Found shows at: {t_name[:40]}")
                
                if t_id not in local_summary_data:
                    local_summary_data[t_id] = {
                        't_id': t_id, 'state': target_state, 'name': t_name, 
                        'shows': 0, 'total': 0, 'booked': 0, 'gross': 0.0
                    }
                
                grouped_shows = {} 
                for variant in target_movie.get('variants', []):
                    raw_header = variant.get('filmFormatHeader', '') or 'Standard'
                    base_format = raw_header.replace(' Format', '').strip()
                    if not base_format: base_format = 'Standard'

                    for amenity in variant.get('amenityGroups', []):
                        show_format = base_format
                        show_language = "Unknown"
                        premium_keywords = ["XD", "IMAX", "3D", "DOLBY", "SCREENX", "4DX", "RPX", "PRIME", "BIGD", "XPLUS", "D-BOX", "70MM"]
                        language_keywords = ["TELUGU", "HINDI", "TAMIL", "MALAYALAM", "KANNADA"]
                        
                        # Extract Format & Language
                        for am in amenity.get('amenities', []):
                            am_name = am.get('name', '')
                            am_upper = am_name.upper()
                            
                            # Format Check
                            if any(k in am_upper for k in premium_keywords) and show_format == base_format:
                                show_format = am_name
                            
                            # Language Targeted Scanner
                            for lang in language_keywords:
                                # Prioritize the first matched language in our defined list.
                                # Because "TELUGU" comes before "ENGLISH" in our list, 
                                # "Telugu with English Subtitles" will safely match "TELUGU" and lock it in.
                                if lang in am_upper and show_language == "Unknown":
                                    show_language = lang.capitalize()
                                    break
                        
                        for show in amenity.get('showtimes', []):
                            show_hash = show.get('showtimeHashCode')
                            if not show_hash: continue
                                
                            show_time = show.get('screenReaderTime', 'Unknown')
                            status = show.get('type', 'Unknown')
                            
                            group_key = f"{t_id}_{show_time}"
                            if group_key not in grouped_shows:
                                grouped_shows[group_key] = {
                                    'state': target_state, 'theater': t_name,
                                    't_id': t_id, 'time': show_time, 'tiers': []
                                }
                            grouped_shows[group_key]['tiers'].append({'hash': show_hash, 'status': status, 'format': show_format, 'language': show_language})
            
            except Exception as e:
                print(f"[Thread-{thread_id}] EXCEPTION processing theater {t_name}: {e}")
                continue

            # --- PHASE 1: FETCH ALL MAPS FOR THIS THEATER ---
            for group_key, show_info in grouped_shows.items():
                show_info['valid_tiers'] = []
                show_info['failed_tiers'] = []
                for tier in show_info['tiers']:
                    tier_hash = tier['hash']
                    seat_api_url = f"https://www.fandango.com/napi/seatMap/{tier_hash}"
                    
                    try:
                        seat_response = page.evaluate(f"""async () => {{
                            try {{
                                const response = await fetch('{seat_api_url}');
                                if (!response.ok) return {{ error: response.status }};
                                return await response.json();
                            }} catch(e) {{ return {{ error: "Fetch Exception: " + e.message }}; }}
                        }}""")
                        
                        if seat_response and "error" not in seat_response:
                            show_info['valid_tiers'].append({'data': seat_response.get('data', seat_response), 'tier_info': tier})
                        else:
                            show_info['failed_tiers'].append(tier)
                    except Exception as seat_fetch_ex:
                        show_info['failed_tiers'].append(tier)
                        print(f"[Thread-{thread_id}] EXCEPTION fetching seat map {tier_hash}: {seat_fetch_ex}")

            # --- PHASE 2: PRE-PASS DEAD ROOM DETECTION ---
            aud_booked_sets = {} 
            for group_key, show_info in grouped_shows.items():
                # Unique showtimes only (combine multi-tier into single set for the time)
                time_booked_seats = {}
                for saved_tier in show_info['valid_tiers']:
                    tier_data = saved_tier['data']
                    aud_id = str(tier_data.get('auditoriumId', 'Unknown'))
                    total_dots = len(tier_data.get('seats', []))
                    booked_seats = set()
                    has_front_row = False
                    
                    for s in tier_data.get('seats', []):
                        s_id = str(s.get('id', ''))
                        status = s.get('status', '').upper()
                        row_num = s.get('row', -1)
                        if s_id and status != 'A':
                            booked_seats.add(s_id)
                            # Check if the block includes at least one front row seat
                            if row_num == 1 or (row_num == -1 and str(s_id).upper().startswith('A')):
                                has_front_row = True
                                
                    if aud_id not in time_booked_seats:
                        time_booked_seats[aud_id] = {'booked': set(), 'total_dots': total_dots, 'has_front_row': False}
                        
                    time_booked_seats[aud_id]['booked'].update(booked_seats)
                    if has_front_row:
                        time_booked_seats[aud_id]['has_front_row'] = True
                        
                for aud_id, data in time_booked_seats.items():
                    if aud_id not in aud_booked_sets:
                        aud_booked_sets[aud_id] = []
                    aud_booked_sets[aud_id].append(data)

            aud_dead_room_blocks = {}
            for aud_id, shows_list in aud_booked_sets.items():
                if len(shows_list) >= 2:
                    first_show_booked = shows_list[0]['booked']
                    first_show_total = shows_list[0]['total_dots']
                    first_show_has_front = shows_list[0]['has_front_row']
                    
                    # Check for exact identical matches across all shows for this auditorium
                    is_exact_match = all(show['booked'] == first_show_booked for show in shows_list)
                    
                    # Calculate current block occupancy
                    occupancy = len(first_show_booked) / first_show_total if first_show_total > 0 else 0
                    
                    # RULE 1: <50% Occupancy AND requires at least 1 Front Row seat
                    rule_1 = is_exact_match and (occupancy < 0.50) and first_show_booked and first_show_has_front
                    
                    # RULE 2 (NEW): <30% Occupancy (NO Front Row requirement)
                    rule_2 = is_exact_match and (occupancy < 0.30) and first_show_booked
                    
                    if rule_1 or rule_2:
                        aud_dead_room_blocks[aud_id] = first_show_booked
                        matched_rule = "Rule 1 (<50% + FrontRow)" if rule_1 else "Rule 2 (<30% Strict)"
                        print(f"[{t_id} | Aud {aud_id}] 🛑 DEAD ROOM DETECTED ({matched_rule}): {len(shows_list)} unique shows have the exact same {len(first_show_booked)} structural blocks.")
                    else:
                        aud_dead_room_blocks[aud_id] = set()
                else:
                    aud_dead_room_blocks[aud_id] = set()

            # --- PHASE 3: PROCESS EACH SHOW ---
            for group_idx, (group_key, show_info) in enumerate(grouped_shows.items(), 1):
                try:
                    show_time = show_info['time']
                    valid_tiers = show_info['valid_tiers']
                    failed_tiers = show_info['failed_tiers']
                    
                    # 🚨 MATRIX SCENARIOS 9 & 10: ALL APIs FAILED
                    if len(valid_tiers) == 0:
                        has_generic_error = any(ft.get('status', '').lower() != 'soldout' for ft in failed_tiers)
                        
                        # ✨ HASH CACHE SELF-HEALING (All Tiers Failed)
                        if len(failed_tiers) > 0 and not has_generic_error:
                            all_cached = True
                            c_total = 0
                            c_booked = 0
                            c_gross = 0.0
                            c_prices = set()
                            
                            for ft in failed_tiers:
                                h = ft.get('hash')
                                if h in master_hash_cache:
                                    cap = master_hash_cache[h]['capacity']
                                    mgross = master_hash_cache[h]['max_gross']
                                    c_total += cap
                                    if ft.get('status', '').lower() == 'soldout':
                                        c_booked += cap
                                        c_gross += mgross
                                        if cap > 0: c_prices.add(mgross / cap)
                                else:
                                    all_cached = False
                                    break
                                    
                            if all_cached:
                                final_format = " / ".join(sorted(list(set(ft['format'] for ft in failed_tiers))))
                                final_language = " / ".join(sorted(list(set(ft.get('language', 'Unknown') for ft in failed_tiers))))
                                failed_urls = [f"https://www.fandango.com/napi/seatMap/{ft.get('hash', '')}" for ft in failed_tiers if ft.get('hash')]
                                urls_str = " | ".join(failed_urls)
                                price_str = " / ".join(sorted([f"${p:.2f}" for p in c_prices])) if c_prices else "$0.00"
                                final_status = "Sold Out" if c_booked >= c_total and c_total > 0 else "Available"

                                local_shows_data.append({
                                    'state': target_state, 't_id': t_id, 'theater': t_name, 
                                    'format': final_format, 'language': final_language, 'time': show_time, 'status': final_status, 
                                    'price_str': price_str, 'total': c_total, 
                                    'booked': c_booked, 'gross': c_gross,
                                    'seat_map_urls': urls_str
                                })
                                
                                local_summary_data[t_id]['shows'] += 1
                                local_summary_data[t_id]['total'] += c_total
                                local_summary_data[t_id]['booked'] += c_booked
                                local_summary_data[t_id]['gross'] += c_gross

                                print(f"   => 🟢 SELF-HEALED (All-Failed) via Hash Cache: {t_name} at {show_time} [{final_format}]")
                                continue # Bypass standard S9/S10 failure logic!
                        
                        if has_generic_error:
                            # S10: Both APIs Fail + 'Available'
                            formats_seen = list(set(ft['format'] for ft in failed_tiers))
                            final_format = " / ".join(sorted(formats_seen)) if formats_seen else "Standard"
                            languages_seen = list(set(ft.get('language', 'Unknown') for ft in failed_tiers))
                            final_language = " / ".join(sorted(languages_seen)) if languages_seen else "Unknown"
                            
                            failed_urls = [f"https://www.fandango.com/napi/seatMap/{ft.get('hash', '')}" for ft in failed_tiers if ft.get('hash')]
                            urls_str = " | ".join(failed_urls)
                            url_log = f" URL(s): {urls_str}" if urls_str else ""
                            
                            log_msg = f"( {target_state} ) {t_name} - {show_time} [{final_format}] - This show is available but not able to fetch seats.{url_log}"
                            local_ignored_shows_log.append(log_msg)
                            
                            local_shows_data.append({
                                'state': target_state, 't_id': t_id, 'theater': t_name, 
                                'format': final_format, 'language': final_language, 'time': show_time, 'status': "Available (Map Error)", 
                                'price_str': "$0.00", 'total': 0, 
                                'booked': 0, 'gross': 0.0,
                                'seat_map_urls': urls_str
                            })
                            
                            local_summary_data[t_id]['shows'] += 1
                            continue
                        else:
                            # S9: Both APIs Fail + 'SoldOut'
                            formats_seen = list(set(ft['format'] for ft in failed_tiers))
                            final_format = " / ".join(sorted(formats_seen))
                            languages_seen = list(set(ft.get('language', 'Unknown') for ft in failed_tiers))
                            final_language = " / ".join(sorted(languages_seen)) if languages_seen else "Unknown"
                            
                            failed_urls = [f"https://www.fandango.com/napi/seatMap/{ft.get('hash', '')}" for ft in failed_tiers if ft.get('hash')]
                            urls_str = " | ".join(failed_urls)
                            
                            local_sold_out_queue.append({
                                'state': target_state, 't_id': t_id, 'theater': t_name, 
                                'format': final_format, 'language': final_language, 'time': show_time,
                                'seat_map_urls': urls_str
                            })
                            continue

                    # 🧠 PHYSICAL OVERLAP CLUSTERING
                    clusters = []
                    def get_available_seat_ids(s_array):
                        return set(s.get('id') for s in s_array if s.get('id') and s.get('status') == 'A')

                    for vt in valid_tiers:
                        seats_array = vt['data'].get('seats', [])
                        seat_ids = set(s.get('id') for s in seats_array if s.get('id'))
                        vt_available_seats = get_available_seat_ids(seats_array)
                        
                        matched = False
                        for cluster in clusters:
                            vt_svg = vt['data'].get('backgroundSvg', '')
                            cluster_svg = cluster['tiers'][0]['data'].get('backgroundSvg', '')
                            
                            has_intersection = bool(seat_ids and cluster['seat_ids'].intersection(seat_ids))
                            has_same_svg = bool(vt_svg and cluster_svg and vt_svg == cluster_svg)
                            
                            if has_intersection or has_same_svg:
                                has_collision = False
                                for existing_vt in cluster['tiers']:
                                    existing_available_seats = get_available_seat_ids(existing_vt['data'].get('seats', []))
                                    if vt_available_seats.intersection(existing_available_seats):
                                        has_collision = True
                                        break
                                        
                                if not has_collision:
                                    cluster['tiers'].append(vt)
                                    cluster['seat_ids'].update(seat_ids)
                                    matched = True
                                    break
                        
                        if not matched:
                            clusters.append({'seat_ids': seat_ids, 'tiers': [vt], 'failed_tiers': []})

                    # Assign failed tiers to the first physical cluster
                    if failed_tiers and clusters:
                        clusters[0]['failed_tiers'].extend(failed_tiers)

                    # 🎬 THE MASTER MATRIX (UNIFIED ALLOCATION ALGORITHM)
                    for c_idx, cluster in enumerate(clusters):
                        combined_total = combined_booked = 0
                        combined_gross = 0.0
                        prices_seen = set()
                        formats_seen = set()
                        languages_seen = set()
                        
                        matrix_urls = []
                        for vt in cluster['tiers']: 
                            formats_seen.add(vt['tier_info']['format'])
                            languages_seen.add(vt['tier_info']['language'])
                            if vt['tier_info'].get('hash'): matrix_urls.append(f"https://www.fandango.com/napi/seatMap/{vt['tier_info']['hash']}")
                        for ft in cluster['failed_tiers']: 
                            formats_seen.add(ft['format'])
                            if 'language' in ft: languages_seen.add(ft['language'])
                            if ft.get('hash'): matrix_urls.append(f"https://www.fandango.com/napi/seatMap/{ft['hash']}")
                            
                        matrix_urls_str = " | ".join(matrix_urls)
                        final_format = " / ".join(sorted(formats_seen))
                        final_language = " / ".join(sorted(languages_seen)) if languages_seen else "Unknown"
                        
                        uid_log = f"[{t_id} | {show_time} | {final_format}]"
                        
                        is_multi_tier = (len(cluster['tiers']) + len(cluster['failed_tiers'])) > 1

                        # Sort valid tiers by cache capacity (descending) to find the base map
                        cluster['tiers'].sort(
                            key=lambda x: int(x['data'].get('areas', [{}])[0].get('totalSeatCount', 0)) if x.get('data', {}).get('areas') else 0, 
                            reverse=True
                        )
                        base_vt = cluster['tiers'][0]
                        
                        safe_avg_price = AVG_PRICE
                        if PRICE_TAX_CUT and safe_avg_price > 0:
                            safe_avg_price = float((safe_avg_price // 5) * 5)

                        def get_price(vt):
                            try: 
                                p = float(vt['data'].get('areas', [{}])[0].get('ticketInfo', [{}])[0].get('price', 0))
                                if PRICE_TAX_CUT and p > 0: return float((p // 5) * 5)
                                return p
                            except: return 0.0

                        base_price = get_price(base_vt)

                        # Get total dots from base map to dynamically detect Under-Drawn maps
                        base_seats = base_vt['data'].get('seats', [])
                        base_phys_total_dots = sum(1 for s in base_seats if s.get('status', '').upper() in ['A', 'R'])
                        base_has_valid_area = any(s.get('areaId') for s in base_seats)
                        
                        # Calculate known cache capacity for the cluster
                        cluster_known_cache_cap = sum(sum(int(a.get('totalSeatCount', 0)) for a in vt['data'].get('areas', [])) for vt in cluster['tiers'])

                        # Check if the map is "Under-Drawn" (Missing physical dots)
                        is_underdrawn_map = cluster_known_cache_cap > base_phys_total_dots
                        if is_underdrawn_map:
                            print(f"{uid_log} ⚠️ UNDER-DRAWN MAP DETECTED: Cache Cap ({cluster_known_cache_cap}) > Phys Dots ({base_phys_total_dots}). Activating Cache Exception.")

                        # --- 🌟 THE PHANTOM SEAT SUBTRACTOR (AREA-BY-AREA) 🌟 ---
                        allocated_cap = 0
                        allocated_booked = 0
                        allocated_gross = 0.0
                        
                        for vt in cluster['tiers']:
                            vt_seats = vt['data'].get('seats', [])
                            aud_id = str(vt['data'].get('auditoriumId', 'Unknown'))
                            dead_room_seats = aud_dead_room_blocks.get(aud_id, set())
                            
                            area_stats = {}
                            for a in vt['data'].get('areas', []):
                                a_id = str(a.get('id', ''))
                                try: 
                                    p = float(a.get('ticketInfo', [{}])[0].get('price', 0))
                                    if PRICE_TAX_CUT and p > 0: p = float((p // 5) * 5)
                                except: p = 0.0
                                
                                area_stats[a_id] = {
                                    'cache_cap': int(a.get('totalSeatCount', 0)),
                                    'cache_avail': int(a.get('availableSeatCount', 0)),
                                    'price': p,
                                    'phys_total': 0,
                                    'raw_booked': 0,
                                    'explicit_blocks': 0,
                                    'front_row_blocks': 0,
                                    'explicit_in_front_row': 0,
                                    'dead_room_blocks': 0
                                }
                                
                            if vt_seats:
                                # Calculate occupancy to determine if front-row heuristic applies
                                temp_phys_total = sum(1 for s in vt_seats if s.get('status', '').upper() in ['A', 'R'])
                                temp_phys_booked = sum(1 for s in vt_seats if s.get('status', '').upper() == 'R')
                                occupancy = (temp_phys_booked / temp_phys_total) if temp_phys_total > 0 else 0.0
                                
                                for s in vt_seats:
                                    status = s.get('status', '').upper()
                                    s_id = s.get('id', '')
                                    row_num = s.get('row', -1)
                                    a_id = str(s.get('areaId', ''))
                                    
                                    if a_id not in area_stats:
                                        first_a_id = list(area_stats.keys())[0] if area_stats else 'UNKNOWN'
                                        if first_a_id not in area_stats:
                                            area_stats[first_a_id] = {'cache_cap': 0, 'cache_avail': 0, 'price': 0.0, 'phys_total': 0, 'raw_booked': 0, 'explicit_blocks': 0, 'front_row_blocks': 0, 'explicit_in_front_row': 0, 'dead_room_blocks': 0}
                                        a_id = first_a_id
                                        
                                    ast = area_stats[a_id]
                                    ast['phys_total'] += 1
                                    
                                    if status != 'A':
                                        ast['raw_booked'] += 1
                                        
                                        is_explicit = (status != 'R')
                                        is_front_row = (row_num == 1 or (row_num == -1 and str(s_id).upper().startswith('A')))
                                        
                                        if is_explicit:
                                            ast['explicit_blocks'] += 1
                                            
                                        if is_front_row and occupancy < OCC_THRESHOLD_FRONTROW:
                                            ast['front_row_blocks'] += 1
                                            
                                        if is_explicit and is_front_row and occupancy < OCC_THRESHOLD_FRONTROW:
                                            ast['explicit_in_front_row'] += 1
                                            
                                        if s_id in dead_room_seats:
                                            ast['dead_room_blocks'] += 1
                            
                            # --- FIX: Target Specific Screen Exclusion ---
                            real_t_id = vt['data'].get('theaterId', t_id) 
                            screen_id = f"{real_t_id}_{aud_id}"
                            
                            force_cached = screen_id in PREFER_CACHED_SCREENS
                            force_physical = screen_id in PREFER_PHYSICAL_SCREENS
                            
                            vt_true_cap = 0
                            vt_true_booked = 0
                            vt_gross = 0.0
                            vt_max_gross = 0.0 # ✨ NEW: Used for learning hash capacities
                            vt_phys_total = 0
                            vt_raw_booked = 0
                            seats_to_remove = 0
                            
                            if (SEAT_COUNT_MODE == 1 and vt_seats and not force_cached) or force_physical:
                                # STANDARD MODE: Trust physical dots minus the MAX() subtractor
                                for a_id, ast in area_stats.items():
                                    a_cache_cap = ast['cache_cap']
                                    a_price = ast['price']
                                    
                                    a_phantom_math = max(0, ast['phys_total'] - a_cache_cap) if a_cache_cap > 0 else 0
                                    a_visual_blocks = (ast['explicit_blocks'] + ast['front_row_blocks']) - ast['explicit_in_front_row']
                                    a_seats_to_remove = max(a_phantom_math, a_visual_blocks, ast['dead_room_blocks'])
                                    
                                    a_true_cap = a_cache_cap
                                    a_true_booked = max(0, ast['raw_booked'] - a_seats_to_remove)
                                    
                                    vt_phys_total += ast['phys_total']
                                    vt_raw_booked += ast['raw_booked']
                                    seats_to_remove += a_seats_to_remove
                                    
                                    vt_true_cap += a_true_cap
                                    vt_true_booked += a_true_booked
                                    vt_gross += (a_true_booked * a_price)
                                    vt_max_gross += (a_true_cap * a_price) # ✨ NEW
                                    if a_price > 0: prices_seen.add(a_price)
                            else:
                                # EXCEPTION MODE: Abandon dots (due to under-drawn maps) & strictly use Cache Math
                                for a_id, ast in area_stats.items():
                                    a_cache_cap = ast['cache_cap']
                                    a_price = ast['price']
                                    
                                    a_true_cap = a_cache_cap
                                    a_true_booked = max(0, a_cache_cap - ast['cache_avail'])
                                    
                                    vt_true_cap += a_true_cap
                                    vt_true_booked += a_true_booked
                                    vt_gross += (a_true_booked * a_price)
                                    vt_max_gross += (a_true_cap * a_price) # ✨ NEW
                                    if a_price > 0: prices_seen.add(a_price)

                            # Master list override
                            if vt['tier_info'].get('status', '').lower() == 'soldout':
                                vt_true_cap = 0
                                vt_true_booked = 0
                                vt_gross = 0.0
                                vt_max_gross = 0.0
                                for a_id, ast in area_stats.items():
                                    vt_true_cap += ast['cache_cap']
                                    vt_true_booked += ast['cache_cap']
                                    vt_gross += (ast['cache_cap'] * ast['price'])
                                    vt_max_gross += (ast['cache_cap'] * ast['price']) # ✨ NEW

                            vt['true_capacity'] = vt_true_cap
                            vt['true_booked'] = vt_true_booked
                            
                            allocated_cap += vt_true_cap
                            allocated_booked += vt_true_booked
                            allocated_gross += vt_gross

                            # ✨ HASH CACHE LEARNING PHASE ✨
                            tier_hash = vt['tier_info'].get('hash')
                            if tier_hash and vt_true_cap > 0:
                                local_hash_cache[tier_hash] = {
                                    'capacity': vt_true_cap,
                                    'max_gross': vt_max_gross,
                                    'format': vt['tier_info'].get('format', 'Standard')
                                }

                        # --- Assess Global Statuses ---
                        all_tiers_info = [vt['tier_info'] for vt in cluster['tiers']] + cluster['failed_tiers']
                        is_any_available = any(t.get('status', '').lower() != 'soldout' for t in all_tiers_info)
                        has_failed_tiers = len(cluster['failed_tiers']) > 0

                        # --- 🎬 MATRIX LOGIC ---
                        base_aud_id = base_vt['data'].get('auditoriumId', 'Unknown')
                        real_base_t_id = base_vt['data'].get('theaterId', t_id) # Pulls exact Fandango ID
                        base_screen_id = f"{real_base_t_id}_{base_aud_id}"
                        is_forced_cached = base_screen_id in PREFER_CACHED_SCREENS
                        
                        if not is_multi_tier and SEAT_COUNT_MODE == 1 and base_seats and base_has_valid_area and not is_forced_cached:
                            combined_total = allocated_cap
                            combined_booked = allocated_booked
                            combined_gross = allocated_gross
                            calc_method_log = "Physical Catch-All"
                        else:
                            
                            if not has_failed_tiers:
                                # GROUP 1: ALL APIs WORK
                                combined_total = allocated_cap
                                combined_booked = allocated_booked
                                combined_gross = allocated_gross
                                calc_method_log = "Per-Tier Phantom Sync"
                            else:
                                # WE HAVE FAILED TIERS
                                missing_capacity = max(0, base_phys_total_dots - allocated_cap)
                                
                                combined_total = allocated_cap
                                combined_booked = allocated_booked
                                combined_gross = allocated_gross
                                
                                # 🚨 THE FIX: Check specifically if the crashed tiers are Sold Out or Available
                                failed_tiers_soldout = all(ft.get('status', '').lower() == 'soldout' for ft in cluster['failed_tiers'])
                                
                                # ✨ HASH CACHE INJECTION (Matrix Level) ✨
                                for ft in cluster['failed_tiers']:
                                    tier_hash = ft.get('hash')
                                    is_soldout = ft.get('status', '').lower() == 'soldout'

                                    if tier_hash in master_hash_cache:
                                        c_cap = master_hash_cache[tier_hash]['capacity']
                                        c_gross = master_hash_cache[tier_hash]['max_gross']

                                        combined_total += c_cap
                                        if is_soldout:
                                            combined_booked += c_cap
                                            combined_gross += c_gross
                                            if c_cap > 0: prices_seen.add(c_gross / c_cap)
                                            
                                        missing_capacity = max(0, missing_capacity - c_cap)
                                        calc_method_log = "Matrix: Hash Healed"
                                    else:
                                        # Use old fallback logic for THIS tier
                                        combined_total += missing_capacity
                                        if is_soldout:
                                            missing_booked = missing_capacity
                                            combined_booked += missing_booked
                                            price_to_use = safe_avg_price if not is_any_available else MAX_TIER_PRICE
                                            combined_gross += (missing_booked * price_to_use)
                                            if price_to_use > 0: prices_seen.add(price_to_use)
                                        missing_capacity = 0 # Consumed so next failed tier gets 0 if it's not in cache
                                        calc_method_log = "Matrix: Math Fallback"

                        if combined_total > 0:
                            kb_key = f"{t_id}_{final_format}"
                            if kb_key not in local_knowledge_base:
                                local_knowledge_base[kb_key] = {'total_seats_sum': 0, 'count': 0, 'prices': set()}
                            local_knowledge_base[kb_key]['total_seats_sum'] += combined_total
                            local_knowledge_base[kb_key]['count'] += 1
                            for p in prices_seen: 
                                if p > 0: local_knowledge_base[kb_key]['prices'].add(p)

                        final_status = "Sold Out" if combined_booked >= combined_total and combined_total > 0 else "Available"
                        price_str = " / ".join(sorted([f"${p:.2f}" for p in prices_seen])) if prices_seen else "$0.00"
                        
                        print(f"   => 📊 Seats: {combined_total:<3} | Booked: {combined_booked:<3} | Gross: ${combined_gross:<7.2f} [{calc_method_log}]")
                        
                        local_shows_data.append({
                            'state': target_state, 't_id': t_id, 'theater': t_name, 
                            'format': final_format, 'language': final_language, 'time': show_time, 'status': final_status, 
                            'price_str': price_str, 'total': combined_total, 
                            'booked': combined_booked, 'gross': combined_gross,
                            'seat_map_urls': matrix_urls_str
                        })
                        
                        local_summary_data[t_id]['shows'] += 1
                        local_summary_data[t_id]['total'] += combined_total
                        local_summary_data[t_id]['booked'] += combined_booked
                        local_summary_data[t_id]['gross'] += combined_gross

                except Exception as e:
                    print(f"[Thread-{thread_id}] EXCEPTION processing cluster at {show_time}: {e}")

        print(f"[Thread-{thread_id}] 🛑 Queue Empty. Closing browser.")
        browser.close()

    return {
        "shows_data": local_shows_data,
        "summary_data": local_summary_data,
        "knowledge_base": local_knowledge_base,
        "sold_out_queue": local_sold_out_queue,
        "ignored_log": local_ignored_shows_log,
        "hash_cache": local_hash_cache # ✨ NEW
    }

# =============================================================================
# ── MAIN EXECUTION ───────────────────────────────────────────────────────────
# =============================================================================

if __name__ == "__main__":
    PIPELINE_START_TIME = time.time()

    print(f"🚀 MULTI-THREAD PIPELINE STARTED | Workers: {MAX_WORKERS}")

    if not os.path.exists(MAPPING_FILE):
        print(f"❌ Error: {MAPPING_FILE} not found. Please run generate_theater_map.py first!")
        exit()

    try:
        with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
            master_map = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error: {MAPPING_FILE} is corrupted or invalid JSON. ({e})")
        exit()

    # 1. FLATTEN TASK QUEUE (Theater-by-Theater Load Balancing)
    tasks_queue = queue.Queue()
    task_counter = 1
    
    for state in TARGET_STATES:
        if state in master_map:
            for theater in master_map[state]:
                tasks_queue.put((task_counter, state, theater))
                task_counter += 1
                
    total_tasks = tasks_queue.qsize()
    print(f"📦 Total Theaters to process: {total_tasks} across {len(TARGET_STATES)} States.")

    # 2. MASTER DATA STORES
    master_shows_data = []
    master_summary_data = {}
    master_knowledge_base = {} 
    master_sold_out_queue = []
    master_ignored_shows_log = []
    blind_fallback_log = []

    # =========================================================================
    # ── 3.5 FIREBASE SETUP & FETCHING PREVIOUS RUN (Replaces Excel logic) ────
    # =========================================================================
    
    firebase_creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    firebase_db_url = os.environ.get("FIREBASE_DATABASE_URL")
    firebase_initialized = False
    master_hash_cache = {} # ✨ NEW: Master Hash Database
    new_hash_entries = {}  # ✨ NEW: Tracks hashes learned this run to upload

    if not firebase_creds_json or not firebase_db_url:
        print("⚠️ Firebase Credentials or Database URL missing from Environment Variables.")
    else:
        try:
            if not firebase_admin._apps:
                creds_dict = json.loads(firebase_creds_json)
                cred = credentials.Certificate(creds_dict)
                firebase_admin.initialize_app(cred, {'databaseURL': firebase_db_url})
            firebase_initialized = True
            
            # ✨ FETCH HASH CACHE ✨
            print("📡 Fetching Global Hash Cache from Firebase...")
            try:
                hash_ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/hash_capacity_cache")
                cached_hashes = hash_ref.get()
                if cached_hashes:
                    master_hash_cache = cached_hashes
                    print(f"📈 Loaded {len(master_hash_cache)} historical tier fingerprints.")
                else:
                    print("ℹ️ No historical hash cache found.")
            except Exception as e:
                print(f"⚠️ Failed to fetch hash cache: {e}")
                
        except Exception as e:
            print(f"❌ Failed to initialize Firebase: {e}")

    previous_shows_data = []  # Specifically for OVERWRITE_SNAPSHOT baseline tracking
    last_updated_str = "First Run"
    
    recent_shows_data = []    # This replaces the Excel read. This is the run directly before this one.
    recent_shows_timestamp = None

    if firebase_initialized:
        print("\n📡 Fetching previous snapshot from Firebase for momentum tracking (last_snapshot)...")
        try:
            snap_ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/last_snapshot")
            snapshot_data = snap_ref.get()
            if snapshot_data and "data" in snapshot_data:
                previous_shows_data = snapshot_data["data"]
                last_updated_str = snapshot_data.get("timestamp", "Unknown Time")
                try:
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    dt_obj = datetime.fromisoformat(last_updated_str.replace('Z', '+00:00')).astimezone(ist_tz)
                    last_updated_str = dt_obj.strftime('%d %b %Y, %I:%M %p')
                except Exception:
                    pass
                print(f"📈 Loaded previous snapshot from {last_updated_str}.")
            else:
                print("ℹ️ No previous snapshot found in Firebase.")
        except Exception as e:
            print(f"⚠️ Failed to fetch previous snapshot from Firebase: {e}")

        print("\n📡 Fetching previous run data from Firebase (master_shows_data) for Missing Shows detection...")
        try:
            master_ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/master_shows_data")
            master_data = master_ref.get()
            if master_data and "data" in master_data:
                recent_shows_data = master_data["data"]
                recent_shows_timestamp = master_data.get("last_updated", datetime.utcnow().isoformat() + "Z")
                print(f"📈 Loaded {len(recent_shows_data)} recent shows directly from Firebase (master_shows_data).")
            else:
                print("ℹ️ No master_shows_data found in Firebase. Skipping Missing Shows check.")
        except Exception as e:
            print(f"⚠️ Failed to fetch master_shows_data from Firebase: {e}")


    # 3. EXECUTE THREAD POOL
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # ✨ PASS HASH CACHE TO WORKER
            futures = [executor.submit(process_theaters_worker, tasks_queue, i+1, total_tasks, master_hash_cache) for i in range(MAX_WORKERS)]
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    # Safely merge thread results into master lists
                    master_shows_data.extend(result["shows_data"])
                    master_sold_out_queue.extend(result["sold_out_queue"])
                    master_ignored_shows_log.extend(result["ignored_log"])
                    
                    # Merge Summary Dictionaries
                    for t_id, data in result["summary_data"].items():
                        if t_id not in master_summary_data:
                            master_summary_data[t_id] = data
                        else:
                            master_summary_data[t_id]['shows'] += data['shows']
                            master_summary_data[t_id]['total'] += data['total']
                            master_summary_data[t_id]['booked'] += data['booked']
                            master_summary_data[t_id]['gross'] += data['gross']
                            
                    # Merge Knowledge Base Dictionaries
                    for kb_key, kb_data in result["knowledge_base"].items():
                        if kb_key not in master_knowledge_base:
                            master_knowledge_base[kb_key] = kb_data
                        else:
                            master_knowledge_base[kb_key]['total_seats_sum'] += kb_data['total_seats_sum']
                            master_knowledge_base[kb_key]['count'] += kb_data['count']
                            master_knowledge_base[kb_key]['prices'].update(kb_data['prices'])
                            
                    # ✨ MERGE LEARNED HASHES
                    if "hash_cache" in result:
                        for h_key, h_data in result["hash_cache"].items():
                            if h_key not in master_hash_cache:
                                master_hash_cache[h_key] = h_data
                                new_hash_entries[h_key] = h_data
                            
                except Exception as e:
                    print(f"❌ A thread encountered a fatal error: {e}")
                    traceback.print_exc()
                    
    except KeyboardInterrupt:
        print("\n🛑 Pipeline interrupted by user. Saving partial progress...")


    # =========================================================================
    # ── 3.6 PREVIOUS RUN COMPARISON ONLY (NO RECOVERY) ───────────────────────
    # =========================================================================

    print("\n🔍 Comparing against previous run for reporting only...")

    current_shows_set = {
        f"{s['t_id']}_{s['time']}"
        for s in master_shows_data
    }

    missing_shows_count = 0

    if recent_shows_data:
        for prev_show in recent_shows_data:

            if prev_show.get("is_extra"):
                continue

            show_key = f"{prev_show['t_id']}_{prev_show['time']}"

            if show_key not in current_shows_set:
                missing_shows_count += 1

        print(
            f"ℹ️ Comparison complete. "
            f"{missing_shows_count} shows existed in previous run but are missing in current run."
        )

    # =========================================================================
    # ── 4. QUEUE PROCESSING (Cross-Referencing) ──────────────────────────────
    # =========================================================================
    if master_sold_out_queue:
        print(f"\n🔄 Processing {len(master_sold_out_queue)} Total Sold Out shows from Queue...")
        
        for item in master_sold_out_queue:
            t_id = item['t_id']
            fmt = item['format']
            kb_key = f"{t_id}_{fmt}"

            if kb_key in master_knowledge_base:
                kb_data = master_knowledge_base[kb_key]
                avg_seats = int(kb_data['total_seats_sum'] / kb_data['count'])
                est_price = min(kb_data['prices']) if kb_data['prices'] else AVG_PRICE

                if PRICE_TAX_CUT and est_price > 0:
                    est_price = float((est_price // 5) * 5)

                combined_total = avg_seats
                combined_booked = avg_seats
                combined_gross = avg_seats * est_price
                price_str = f"${est_price:.2f}"
                
                print(f"   => ✅ Recovered {item['theater']} [{fmt}] at {item['time']} via Cross-Reference.")
            else:
                combined_total = 0 #FALLBACK_SEATS
                combined_booked = 0 #FALLBACK_SEATS
                
                est_price = AVG_PRICE
                if PRICE_TAX_CUT and est_price > 0:
                    est_price = float((est_price // 5) * 5)
                    
                combined_gross = 0 #FALLBACK_SEATS * est_price
                price_str = 0 #f"${est_price:.2f}"
                
                log_entry = f"( {item['state']} ) {item['theater']} - {item['time']} [{fmt}] - Added ${combined_gross:,.2f}"
                blind_fallback_log.append(log_entry)
                
                print(f"   => ⚠️ Blind Fallback used for {item['theater']} [{fmt}] at {item['time']}. Please check this show and add gross/tickets manually!")

            master_shows_data.append({
                'state': item['state'], 't_id': t_id, 'theater': item['theater'],
                'format': fmt, 'language': item.get('language', 'Unknown'), 'time': item['time'], 'status': "Sold Out",
                'price_str': price_str, 'total': combined_total,
                'booked': combined_booked, 'gross': combined_gross,
                'seat_map_urls': item.get('seat_map_urls', '')
            })

            master_summary_data[t_id]['shows'] += 1
            master_summary_data[t_id]['total'] += combined_total
            master_summary_data[t_id]['booked'] += combined_booked
            master_summary_data[t_id]['gross'] += combined_gross

    # =========================================================================
    # ── 4.5 MANUAL SHOWS PROCESSING ──────────────────────────────────────────
    # =========================================================================
    if MANUAL_SHOWS:
        print(f"\n➕ Processing {len(MANUAL_SHOWS)} Manual/Fan/Extra Shows...")
        for ms in MANUAL_SHOWS:
            try:
                st = str(ms[0]) if len(ms) > 0 and ms[0] is not None else ""
                
                # --- EXTRA DISTRIBUTOR ADJUSTMENT HANDLER ---
                if st.upper() == "EXTRA":
                    b_gross = float(ms[3]) if len(ms) > 3 and ms[3] is not None else 0.0
                    b_seats = int(ms[5]) if len(ms) > 5 and ms[5] is not None else 0
                    
                    master_shows_data.append({
                        'state': 'EXTRA', 't_id': 'EXTRA', 'theater': 'EXTRA',
                        'format': 'EXTRA', 'language': 'EXTRA', 'time': '', 'status': 'EXTRA',
                        'price_str': '', 'total': b_seats, # Match total to booked so Occupancy is preserved
                        'booked': b_seats, 'gross': b_gross,
                        'is_extra': True, # Special flag to hide from all detailed reports
                        'seat_map_urls': "" # Explicitly empty for uniform schema
                    })
                    
                    print(f"   => ✅ Added: ( EXTRA ) {EXTRA_GROSS_NOTE}: {b_seats} Tickets | ${b_gross:,.2f}")
                    continue

                # --- STANDARD MANUAL SHOW HANDLER ---
                t_id = str(ms[1]).strip().lower() if len(ms) > 1 else ""
                time_str = ms[2] if len(ms) > 2 else ""
                b_gross = float(ms[3]) if len(ms) > 3 and ms[3] is not None else 0.0
                t_gross = float(ms[4]) if len(ms) > 4 and ms[4] is not None else 0.0
                b_seats = int(ms[5]) if len(ms) > 5 and ms[5] is not None else 0
                t_seats = int(ms[6]) if len(ms) > 6 and ms[6] is not None else 0
                occ = float(ms[7]) if len(ms) > 7 and ms[7] is not None else 0.0
                
                # ✨ NEW: Extract Format and Language if provided, otherwise use defaults
                fmt = str(ms[8]) if len(ms) > 8 and ms[8] else "Fan Event / Manual"
                lang = str(ms[9]) if len(ms) > 9 and ms[9] else "Unknown"
                
                t_name = "Unknown Theater"
                if st in master_map:
                    for t in master_map[st]:
                        if str(t.get('theaterId')).strip().lower() == t_id.lower() or t.get('theaterId') == t_id:
                            t_name = t.get('theaterName', 'Unknown')
                            break
                            
                price_str = f"${(b_gross / b_seats):.2f}" if b_seats > 0 else "$0.00"
                # Safe status calculation identical to main matrix logic
                status = "Sold Out" if b_seats >= t_seats and t_seats > 0 else "Available"
                
                master_shows_data.append({
                    'state': st, 't_id': t_id, 'theater': t_name,
                    'format': fmt, 'language': lang, 'time': time_str, 'status': status,
                    'price_str': price_str, 'total': t_seats,
                    'booked': b_seats, 'gross': b_gross,
                    'seat_map_urls': "" # Explicitly empty for uniform schema
                })

                if t_id not in master_summary_data:
                    master_summary_data[t_id] = {'t_id': t_id, 'state': st, 'name': t_name, 'shows': 0, 'total': 0, 'booked': 0, 'gross': 0.0}
                
                master_summary_data[t_id]['shows'] += 1
                master_summary_data[t_id]['total'] += t_seats
                master_summary_data[t_id]['booked'] += b_seats
                master_summary_data[t_id]['gross'] += b_gross
                
                print(f"   => ✅ Added: ( {st} ) {t_name} - {time_str} [{fmt} | {lang}] - {b_seats}/{t_seats} Booked | ${b_gross:,.2f}")
            except Exception as e:
                print(f"   => ❌ Error processing manual show {ms}: {e}")

    # =========================================================================
    # ── 4.6 DYNAMIC MULTI-TIER DATA CONSOLIDATION (GENERIC MERGE) ────────────
    # =========================================================================
    if master_shows_data and MANUAL_MERGE_SHOWS_THEATRES:
        print(f"\n🔧 Checking post-processing data consolidation rules for {len(MANUAL_MERGE_SHOWS_THEATRES)} target theaters...")
        
        cleaned_shows_list = []
        global_merger_registry = {}
        
        # Normalize the watch list to lowercase for case-insensitive matching
        target_theaters_lower = [str(tid).strip().lower() for tid in MANUAL_MERGE_SHOWS_THEATRES]
        
        for row in master_shows_data:
            current_t_id = str(row.get('t_id', '')).strip()
            
            if current_t_id.lower() not in target_theaters_lower:
                cleaned_shows_list.append(row)
                continue
                
            show_time = row.get('time')
            merge_composite_key = f"{current_t_id}_{show_time}"
            
            if merge_composite_key not in global_merger_registry:
                global_merger_registry[merge_composite_key] = row
            else:
                baseline_row = global_merger_registry[merge_composite_key]
                
                baseline_row['total'] += row.get('total', 0)
                baseline_row['booked'] += row.get('booked', 0)
                baseline_row['gross'] += row.get('gross', 0.0)
                
                current_fmt = str(row.get('format', '')).strip()
                if current_fmt and current_fmt.lower() not in str(baseline_row['format']).lower():
                    baseline_row['format'] = f"{baseline_row['format']} / {current_fmt}"
                
                current_price = str(row.get('price_str', '')).strip()
                if current_price and current_price.lower() not in str(baseline_row['price_str']).lower():
                    baseline_row['price_str'] = f"{baseline_row['price_str']} / {current_price}"
                
                if baseline_row['booked'] >= baseline_row['total'] and baseline_row['total'] > 0:
                    baseline_row['status'] = "Sold Out"
                else:
                    baseline_row['status'] = "Available"
                
                if current_t_id in master_summary_data:
                    master_summary_data[current_t_id]['shows'] -= 1
                
                print(f"   => Successfully consolidated duplicate split map for {current_t_id} at {show_time}")
        
        for merged_row in global_merger_registry.values():
            cleaned_shows_list.append(merged_row)
            
        master_shows_data = cleaned_shows_list

    # =========================================================================
    # ── 4.7 CHAIN-SPECIFIC SOLD OUT IGNORER ──────────────────────────────────
    # =========================================================================
    ignored_soldout_chain_log = []
    if IGNORE_SOLDOUT_CHAINS:
        print(f"\n🚫 Applying Sold Out filter for chains: {', '.join(IGNORE_SOLDOUT_CHAINS)}...")
        
        for show in master_shows_data:
            if show.get('status') == 'Sold Out':
                t_name_lower = show.get('theater', '').lower()
                
                # Check if theater matches any of the ignored chains
                if any(chain.lower() in t_name_lower for chain in IGNORE_SOLDOUT_CHAINS):
                    # Record the log before we wipe the data
                    log_msg = f"( {show['state']} ) {show['theater']} - {show['time']} [{show['format']}] | Removed: {show['booked']} tickets, ${show['gross']:,.2f}"
                    ignored_soldout_chain_log.append(log_msg)
                    
                    t_id = show['t_id']
                    
                    # Deduct from master summary to keep the overall math perfectly balanced
                    if t_id in master_summary_data:
                        master_summary_data[t_id]['total'] -= show['total']
                        master_summary_data[t_id]['booked'] -= show['booked']
                        master_summary_data[t_id]['gross'] -= show['gross']
                        
                    # Zero out the show data (but keep it in the array so the shows count remains)
                    show['total'] = 0
                    show['booked'] = 0
                    show['gross'] = 0.0
                    show['price_str'] = "$0.00"
                    show['status'] = "Sold Out (Ignored)"

    # =========================================================================
    # ── 4.8 CUMULATIVE TRACKING MODE (RESCUE PASSED SHOWS & PATCH ERRORS) ────
    # =========================================================================
    if CUMULATIVE_TRACKING_MODE and recent_shows_data:
        print(f"\n🛡️ Activating Cumulative Tracking Mode: Rescuing dropped shows and patching API errors...")
        print("Activating CUMULATIVE_TRACKING_MODE...")
        
        rescued_shows_count = 0
        protected_shows_count = 0
        
        def clean_str(s):
            return str(s).replace(" ", "").replace("\u202f", "").lower()
            
        # Create a dictionary of the CURRENT run for fast lookups
        current_shows_dict = {}
        for i, row in enumerate(master_shows_data):
            # Unique key: TheaterID + Time + Format
            key = f"{row.get('t_id')}_{clean_str(row.get('time'))}_{clean_str(row.get('format'))}"
            current_shows_dict[key] = {'index': i, 'data': row}
            
        for prev_show in recent_shows_data:
            # Skip manual EXTRA overrides and Manual Shows (they are freshly processed in 4.5 anyway)
            if prev_show.get('is_extra') or prev_show.get('format') == "Fan Event / Manual": 
                continue
                
            prev_t_id = prev_show.get('t_id')
            prev_key = f"{prev_t_id}_{clean_str(prev_show.get('time'))}_{clean_str(prev_show.get('format'))}"
            
            # --- SCENARIO A: The Show Disappeared (Passed Time or Fandango dropped it) ---
            if prev_key not in current_shows_dict:
                # Rescue the show
                master_shows_data.append(prev_show)
                
                # Safely patch it back into the master summary
                if prev_t_id not in master_summary_data:
                    master_summary_data[prev_t_id] = {
                        't_id': prev_t_id, 'state': prev_show.get('state', 'Unknown'), 
                        'name': prev_show.get('theater', 'Unknown'), 
                        'shows': 0, 'total': 0, 'booked': 0, 'gross': 0.0
                    }
                
                master_summary_data[prev_t_id]['shows'] += 1
                master_summary_data[prev_t_id]['total'] += prev_show.get('total', 0)
                master_summary_data[prev_t_id]['booked'] += prev_show.get('booked', 0)
                master_summary_data[prev_t_id]['gross'] += prev_show.get('gross', 0.0)
                
                rescued_shows_count += 1
                print(f"🛡️ RESCUED: {prev_show.get('theater')} at {prev_show.get('time')} - Maintained ${prev_show.get('gross', 0):.2f}")
                
            # --- SCENARIO B: The Show Exists, but LIVE data might be an API Crash ---
            else:
                curr_idx = current_shows_dict[prev_key]['index']
                curr_show = current_shows_dict[prev_key]['data']
                
                # ✨ NEW LOGIC: Only overwrite if the live data explicitly crashed (Map Error)
                is_api_crash = curr_show.get('status') == "Available (Map Error)"
                
                if is_api_crash:
                    # 1. Deduct the current bad math from the summary
                    master_summary_data[prev_t_id]['total'] -= curr_show.get('total', 0)
                    master_summary_data[prev_t_id]['booked'] -= curr_show.get('booked', 0)
                    master_summary_data[prev_t_id]['gross'] -= curr_show.get('gross', 0.0)
                    
                    # 2. Overwrite the array with the previous healthy run
                    master_shows_data[curr_idx] = prev_show
                    
                    # 3. Add the good historical math back to the summary
                    master_summary_data[prev_t_id]['total'] += prev_show.get('total', 0)
                    master_summary_data[prev_t_id]['booked'] += prev_show.get('booked', 0)
                    master_summary_data[prev_t_id]['gross'] += prev_show.get('gross', 0.0)
                    
                    protected_shows_count += 1
                    print(f"🛡️ PROTECTED: {prev_show.get('theater')} at {prev_show.get('time')}. Live was Map Error, reverted to previous valid state.")
                
                # If it's NOT an API crash, we do absolutely nothing.
                # We strictly trust the live data, even if the gross goes down due to unblocked seats.

        print(f"   => ✅ Cumulative Tracking Complete: Rescued {rescued_shows_count} dropped shows. Patched {protected_shows_count} API errors.")


    # =========================================================================
    # ── 5. UPLOAD TO FIREBASE & MOMENTUM TRACKING ────────────────────────────
    # =========================================================================
    if master_shows_data:
        print(f"\n🚀 Preparing to process momentum and upload data...")

        if blind_fallback_log:
            print("\n=====================================================================")
            print("⚠️ BLIND FALLBACK LOG (Highly Inaccurate Estimates)")
            print("The following shows were completely sold out and had no other open. Please check these shows and add gross/tickets manually!")
            print(f"shows to cross-reference. We forced {FALLBACK_SEATS} seats @ ${AVG_PRICE:.2f}.")
            print("=====================================================================")
            for log in blind_fallback_log:
                print(log)
            print("=====================================================================\n")
        
        if ignored_soldout_chain_log:
            print("\n=====================================================================")
            print("🚫 IGNORED SOLD OUT SHOWS (Specific Chains)")
            print(f"The following Sold Out shows belonged to: {', '.join(IGNORE_SOLDOUT_CHAINS)}")
            print("Their Gross and Tickets have been reverted to 0.")
            print("=====================================================================")
            for log in ignored_soldout_chain_log:
                print(log)
            print("=====================================================================\n")
            
        if master_ignored_shows_log:
            print("\n=====================================================================")
            print("⚠️ SHOWS WITH MAP ERRORS (0 Capacity Logged)")
            print("The following shows are available but we were not able to fetch seats.")
            print("They have been included in the reports to count the show, but with 0 seats/gross.")
            print("=====================================================================")
            for log in master_ignored_shows_log:
                print(log)
            print("=====================================================================\n")

        # Combine Momentum Notes (Tied to last_snapshot)
        momentum_msg = ""
        diff_gross = 0.0
        if previous_shows_data:
            prev_gross = sum(r.get("gross", 0) for r in previous_shows_data)
            prev_tickets = sum(r.get("booked", 0) for r in previous_shows_data)
            curr_gross = sum(r.get("gross", 0) for r in master_shows_data)
            curr_tickets = sum(r.get("booked", 0) for r in master_shows_data)
            
            diff_gross = curr_gross - prev_gross
            diff_tickets = curr_tickets - prev_tickets
            
            sign_t = "+" if diff_tickets >= 0 else ""
            sign_g = "+" if diff_gross >= 0 else ""
            
            momentum_msg = f"🚀 MOMENTUM UPDATE: {sign_t}{diff_tickets:,} Tickets and {sign_g}${diff_gross:,.2f} Gross added since {last_updated_str}"
            print(f"\n{momentum_msg}\n")


        # --- FIREBASE UPLOAD PIPELINE ---
        if firebase_initialized:
            
            # ✨ 0. PUSH NEW HASHES TO FIREBASE ✨
            if new_hash_entries:
                try:
                    print(f"💾 Saving {len(new_hash_entries)} newly learned Hash Blueprints to Firebase...")
                    db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/hash_capacity_cache").update(new_hash_entries)
                    print("✅ Hash Cache updated successfully.")
                except Exception as e:
                    print(f"⚠️ Failed to update Hash Cache: {e}")

            # 1. Update the Snapshot if requested (Baseline Tracking)
            if OVERWRITE_SNAPSHOT:
                try:
                    print("💾 Saving current data as the new snapshot to Firebase...")
                    snap_ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/last_snapshot")
                    snap_ref.set({
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "data": master_shows_data
                    })
                    print("✅ Snapshot updated successfully in Firebase.")
                except Exception as e:
                    print(f"⚠️ Failed to save snapshot to Firebase: {e}")
            else:
                print(f"⏭️ Skipping snapshot save (OVERWRITE_SNAPSHOT is set to False).")

            # 2. Save the PREVIOUS Run Data (Using data fetched at the start of the script)
            if recent_shows_data:
                try:
                    print("💾 Saving previous run data to Firebase (previous_run_snapshot)...")
                    prev_run_ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/previous_run_snapshot")
                    prev_run_ref.set({
                        "timestamp": recent_shows_timestamp,
                        "data": recent_shows_data
                    })
                    print(f"✅ Successfully uploaded previous_run_snapshot to Firebase (Timestamp: {recent_shows_timestamp})!")
                except Exception as e:
                    print(f"⚠️ Failed to upload previous_run_snapshot to Firebase: {e}")
            else:
                print("ℹ️ No previous run data available to upload.")

            # 3. Save the CURRENT Run Data
            try:
                print(f"Connecting to Firebase Database: {firebase_db_url}")
                ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/master_shows_data")
                
                payload = {
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "show_date": SHOW_DATE,
                    "data": master_shows_data
                }
                
                if momentum_msg:
                    payload["momentum"] = momentum_msg
                    
                ref.set(payload)
                
                print("✅ Successfully uploaded master_shows_data to Firebase!")
            except Exception as e:
                print(f"❌ Failed to upload to Firebase: {e}")
                traceback.print_exc()

            # 4. Append to History
            try:
                print("💾 Appending current run to history in Firebase...")
                history_ref = db.reference(f"movies/{MOVIE_SLUG}/{SHOW_DATE}/history")
                
                calc_shows = [r for r in master_shows_data if not r.get('is_extra')]
                venues_count = len(set(r.get('t_id') for r in calc_shows))
                shows_count = len(calc_shows)
                total_gross = sum(r.get('gross', 0) for r in master_shows_data)
                booked_tickets = sum(r.get('booked', 0) for r in master_shows_data)
                total_seats = sum(r.get('total', 0) for r in master_shows_data)
                occupancy = (booked_tickets / total_seats * 100) if total_seats > 0 else 0
                
                history_payload = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "total_gross": total_gross,
                    "booked_tickets": booked_tickets,
                    "venues": venues_count,
                    "shows": shows_count,
                    "occupancy": occupancy,
                    "growth": float(diff_gross)
                }
                
                history_ref.push(history_payload)
                print("✅ Successfully appended history data to Firebase!")
                
            except Exception as e:
                print(f"⚠️ Failed to append history to Firebase: {e}")

        pipeline_elapsed = time.time() - PIPELINE_START_TIME
        mins, secs = divmod(pipeline_elapsed, 60)
        print(f"🎉 Pipeline completely finished in {int(mins)} minutes and {int(secs)} seconds. No local files saved!")

    else:
        print("❌ No successful showtime seat maps were fetched across any state.")
