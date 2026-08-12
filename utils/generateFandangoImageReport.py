"""
Premium Box Office Image Generator - Deep Space Glassmorphism UI
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from datetime import datetime
import os

W   = 2560      
PAD = 80        

WATERMARK_ENABLED = False
WATERMARK_TEXT    = "WkndCinemas"
WATERMARK_OPACITY = 90
WATERMARK_ANGLE   = 35

# Glassmorphism Text Palette
TEXT_BRIGHT = (255, 255, 255)   
TEXT        = (232, 232, 240)   
MUTED       = (160, 160, 180)   
# --- UPDATED BRIGHTNESS FOR DELTAS & OCCUPANCY ---
GREEN       = (74,  222, 128)  # Bright Emerald Green (#4ade80)
ORANGE      = (251, 146,  60)  # Vibrant Tangerine (#fb923c)
RED         = (248, 113, 113)  # Bright Coral Red (#f87171)
ACCENT      = (245, 166,  35) 

def format_currency_usd(value):
    if value >= 1000000: return f"${value/1000000:.2f}M"
    elif value >= 1000: return f"${value/1000:.1f}K"
    else: return f"${value:.2f}"

def get_font(size, bold=False):
    fonts_to_try = [
        "arialbd.ttf" if bold else "arial.ttf",
        "Helvetica-Bold.ttf" if bold else "Helvetica.ttf",
        "SFNSDisplay-Bold.ttf" if bold else "SFNSDisplay-Regular.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf", 
        "Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    ]
    for font_name in fonts_to_try:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()

def draw_glass_panel(bg_img, draw, xy, radius=16):
    x1, y1, x2, y2 = xy
    
    # 1. Extract the background region
    # To simulate backdrop-filter blur, we crop the background, blur it heavily, and paste it back.
    region = bg_img.crop((int(x1), int(y1), int(x2), int(y2)))
    blurred_region = region.filter(ImageFilter.GaussianBlur(30))
    
    # Brighten it slightly to simulate glass refraction
    enhancer = ImageEnhance.Brightness(blurred_region)
    blurred_region = enhancer.enhance(1.2)
    
    # 2. Create a rounded mask for the region
    mask = Image.new('L', blurred_region.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, x2-x1, y2-y1), radius=radius, fill=255)
    
    # 3. Paste the blurred glass back onto the main image
    bg_img.paste(blurred_region, (int(x1), int(y1)), mask)
    
    # 4. Add the translucent white tint and borders using the main draw object
    overlay = Image.new('RGBA', bg_img.size, (0,0,0,0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    # Base tint
    overlay_draw.rounded_rectangle(xy, radius=radius, fill=(255, 255, 255, 12))
    
    # Shiny reflective gradient at the top left
    overlay_draw.polygon([(x1, y1+radius), (x1+radius, y1), (x2-(x2-x1)//3, y1), (x1, y2-(y2-y1)//3)], fill=(255, 255, 255, 8))
    
    # Top and Left highlight borders (Reflecting light)
    overlay_draw.rounded_rectangle(xy, radius=radius, outline=(255, 255, 255, 45), width=2)
    
    bg_img.paste(overlay, (0,0), overlay)

def generate_fandango_image_report(data, filename, movie_name="Movie", show_date="N/A", previous_shows_data=None, last_updated_str="N/A", country_name=""):
    # 1. PREPARE DATA
    p_shows_map = {}
    if previous_shows_data:
        for r in previous_shows_data:
            fmt = r.get('format', '')
            if 'D-Box' in fmt and 'Premium' in fmt: fmt = 'Premium'
            key = f"{r.get('t_id')}_{r.get('time')}_{fmt}"
            p_shows_map[key] = r

    total_venues = len(set(r['t_id'] for r in data if r['t_id'] != 'EXTRA'))
    total_shows = sum(1 for r in data if not r.get('is_extra', False))
    total_tickets = sum(r['total'] for r in data)
    total_booked = sum(r['booked'] for r in data)
    total_gross = sum(r['gross'] for r in data)
    overall_occ = (total_booked / total_tickets * 100) if total_tickets > 0 else 0
    atp = (total_gross / total_booked) if total_booked > 0 else 0

    p_total_venues = len(set(r['t_id'] for r in previous_shows_data if r['t_id'] != 'EXTRA')) if previous_shows_data else 0
    p_total_shows = sum(1 for r in previous_shows_data if not r.get('is_extra', False)) if previous_shows_data else 0
    p_total_booked = sum(r['booked'] for r in previous_shows_data) if previous_shows_data else 0
    p_total_gross = sum(r['gross'] for r in previous_shows_data) if previous_shows_data else 0
    
    d_total_venues = total_venues - p_total_venues
    d_total_shows = total_shows - p_total_shows
    d_total_booked = total_booked - p_total_booked
    d_total_gross = total_gross - p_total_gross

    state_summary = {}
    theater_summary = {}
    lang_summary = {}
    fmt_summary = {}

    for row in data:
        t_id = row['t_id']
        st = row['state']
        lang = row.get('language', 'Unknown')
        fmt = row['format']
        if 'D-Box' in fmt and 'Premium' in fmt: fmt = 'Premium'
        is_extra = row.get('is_extra', False)
        
        show_key = f"{row['t_id']}_{row['time']}_{fmt}"
        p_show = p_shows_map.get(show_key)
        d_tix = row['booked'] if not p_show else (row['booked'] - p_show['booked'])
        d_grs = row['gross'] if not p_show else (row['gross'] - p_show['gross'])

        if st != 'EXTRA':
            if st not in state_summary: state_summary[st] = {'shows': 0, 'tickets': 0, 'booked': 0, 'gross': 0.0, 'd_tickets': 0, 'd_gross': 0.0}
            state_summary[st]['shows'] += 1
            state_summary[st]['tickets'] += row['total']
            state_summary[st]['booked'] += row['booked']
            state_summary[st]['gross'] += row['gross']
            state_summary[st]['d_tickets'] += d_tix
            state_summary[st]['d_gross'] += d_grs

        if t_id != 'EXTRA':
            if t_id not in theater_summary: theater_summary[t_id] = {'state': st, 'name': row['theater'], 'shows': 0, 'tickets': 0, 'booked': 0, 'gross': 0.0, 'd_tickets': 0, 'd_gross': 0.0}
            theater_summary[t_id]['shows'] += 1
            theater_summary[t_id]['tickets'] += row['total']
            theater_summary[t_id]['booked'] += row['booked']
            theater_summary[t_id]['gross'] += row['gross']
            theater_summary[t_id]['d_tickets'] += d_tix
            theater_summary[t_id]['d_gross'] += d_grs

        if not is_extra:
            if lang not in lang_summary: lang_summary[lang] = {'shows': 0, 'tickets': 0, 'booked': 0, 'gross': 0.0, 'd_tickets': 0, 'd_gross': 0.0}
            lang_summary[lang]['shows'] += 1
            lang_summary[lang]['tickets'] += row['total']
            lang_summary[lang]['booked'] += row['booked']
            lang_summary[lang]['gross'] += row['gross']
            lang_summary[lang]['d_tickets'] += d_tix
            lang_summary[lang]['d_gross'] += d_grs

        if not is_extra:
            if fmt not in fmt_summary: fmt_summary[fmt] = {'shows': 0, 'tickets': 0, 'booked': 0, 'gross': 0.0, 'd_tickets': 0, 'd_gross': 0.0}
            fmt_summary[fmt]['shows'] += 1
            fmt_summary[fmt]['tickets'] += row['total']
            fmt_summary[fmt]['booked'] += row['booked']
            fmt_summary[fmt]['gross'] += row['gross']
            fmt_summary[fmt]['d_tickets'] += d_tix
            fmt_summary[fmt]['d_gross'] += d_grs

    states_list = sorted([{'name': k, **v} for k, v in state_summary.items()], key=lambda x: x['gross'], reverse=True)
    theaters_list = sorted([{'id': k, **v} for k, v in theater_summary.items()], key=lambda x: x['gross'], reverse=True)
    lang_list = sorted([{'name': k, **v} for k, v in lang_summary.items()], key=lambda x: x['gross'], reverse=True)
    fmt_list = sorted([{'name': k, **v} for k, v in fmt_summary.items()], key=lambda x: x['gross'], reverse=True)

    # 2. DYNAMIC HEIGHT CALCULATION
    header_h = 160
    kpi_h = 200 
    
    max_fl_rows = max(len(lang_list), len(fmt_list))
    fl_h = 220 + (max_fl_rows * 60) 
    
    # Changed from 21 to 16 (Top 15 + 1 "Remaining" row)
    st_actual_rows = max(min(16, len(states_list)), min(16, len(theaters_list)))
    if len(states_list) > 15 or len(theaters_list) > 15: st_actual_rows = 16
    st_h = 220 + (st_actual_rows * 60)
    
    footer_h = 80
    
    H = PAD + header_h + kpi_h + fl_h + 40 + st_h + 40 + footer_h + PAD

    if W/H > 2.0:
        H = int(W / 2.0)

    # 3. BACKGROUND SETUP (Muted Obsidian Slate)
    base_bg = Image.new('RGB', (4, 4))
    base_bg.putpixel((0,0), (8, 10, 15))   # Deep Obsidian
    base_bg.putpixel((3,0), (12, 14, 20))  # Dark Slate
    base_bg.putpixel((0,3), (10, 12, 18))  # Dark Slate
    base_bg.putpixel((3,3), (15, 18, 24))  # Charcoal
    img = base_bg.resize((W, int(H)), Image.Resampling.BICUBIC)
    
    # Add subtle, desaturated glowing orbs (No heavy neon)
    orb_layer = Image.new('RGBA', (W, int(H)), (0,0,0,0))
    orb_draw = ImageDraw.Draw(orb_layer)
    
    # Soft Slate top left
    orb_draw.ellipse([-600, -600, 1200, 1200], fill=(51, 65, 85, 100)) 
    # Muted Charcoal right
    orb_draw.ellipse([W-1400, int(H)//2 - 800, W+600, int(H)//2 + 800], fill=(30, 41, 59, 120)) 
    # Extremely faint Fandango amber at the bottom (barely visible, just for warmth)
    orb_draw.ellipse([W//2 - 1000, int(H)-1000, W//2 + 1000, int(H)+1000], fill=(245, 131, 32, 12)) 
    
    orb_layer = orb_layer.filter(ImageFilter.GaussianBlur(250))
    img.paste(orb_layer, (0,0), orb_layer)

    draw = ImageDraw.Draw(img)

    # Fonts
    f_title = get_font(64, bold=True)
    f_sub = get_font(28)
    f_kpi_val = get_font(72, bold=True)
    f_kpi_lbl = get_font(22, bold=True)
    f_kpi_sub = get_font(26, bold=True)
    
    f_sec = get_font(36, bold=True)   # Slightly larger Table Titles
    f_th = get_font(24, bold=True)    # Larger Table Column Headers
    f_row = get_font(28, bold=True)   # BOLDER and LARGER normal text (numbers/names)
    f_row_b = get_font(28, bold=True) # BOLDER and LARGER highlighted text

    if WATERMARK_ENABLED:
        try:
            wm_font = get_font(180, bold=True)
            wm_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
            wm_draw = ImageDraw.Draw(wm_layer)
            tw, th = wm_draw.textbbox((0,0), WATERMARK_TEXT, font=wm_font)[2:]
            wm_x, wm_y = (W-tw)//2, (H-th)//2
            wm_draw.text((wm_x, wm_y), WATERMARK_TEXT, font=wm_font, fill=(255, 255, 255, WATERMARK_OPACITY))
            wm_layer = wm_layer.rotate(WATERMARK_ANGLE, expand=False, center=(W//2, H//2))
            img.paste(wm_layer, (0,0), wm_layer)
        except: pass

    # --- HEADER ---
    draw.text((PAD, PAD), movie_name, font=f_title, fill=TEXT_BRIGHT)
    sub_text = f"{country_name} Advance Sales • Show Date: {show_date}"
    draw.text((PAD, PAD+85), sub_text, font=f_sub, fill=ACCENT)

    meta_x = W - PAD
    draw.text((meta_x, PAD+20), f"Report: {datetime.now().strftime('%d %b %Y, %I:%M %p')} IST", font=f_sub, fill=TEXT, anchor="ra")
    draw.text((meta_x, PAD+65), f"Last tracked: {last_updated_str} IST", font=f_sub, fill=MUTED, anchor="ra")
    
    ov_line = Image.new('RGBA', img.size, (0,0,0,0))
    ImageDraw.Draw(ov_line).line([(PAD, PAD+150), (W-PAD, PAD+150)], fill=(255,255,255,40), width=3)
    img.paste(ov_line, (0,0), ov_line)

    # --- KPIs ---
    kpi_y = PAD + 180
    kpi_width = (W - (2*PAD) - (4*30)) // 5 
    
    def draw_kpi(idx, label, val, sub_val, is_delta=True):
        x = PAD + (idx * (kpi_width + 30))
        draw_glass_panel(img, draw, [x, kpi_y, x+kpi_width, kpi_y+180], radius=24)
        
        # Fandango Orange Left Strip (Drawn softly)
        ov_strip = Image.new('RGBA', img.size, (0,0,0,0))
        ImageDraw.Draw(ov_strip).rounded_rectangle([x, kpi_y, x+8, kpi_y+180], radius=6, fill=(245, 131, 32, 200))
        img.paste(ov_strip, (0,0), ov_strip)
        
        # 1. Top Left: KPI Label
        draw.text((x+40, kpi_y+35), label.upper(), font=f_kpi_lbl, fill=MUTED)
        
        # 2. Top Right: Growth / Sub-value (Floated to the right margin)
        right_margin_x = x + kpi_width - 30
        
        if is_delta:
            sv = str(sub_val)
            if sv.startswith('+'): color = GREEN
            elif sv.startswith('-') and sv != "-": color = RED
            else: color = MUTED
            draw.text((right_margin_x, kpi_y+39), sv, font=f_kpi_sub, fill=color, anchor="rt")
        else:
            # For non-delta values like Occupancy text
            draw.text((right_margin_x, kpi_y+39), str(sub_val), font=f_kpi_sub, fill=MUTED, anchor="rt")

        # 3. Bottom/Center: Main KPI Value (Pushed down slightly to center it now that the bottom is empty)
        draw.text((x+40, kpi_y+75), val, font=f_kpi_val, fill=TEXT_BRIGHT)

    draw_kpi(0, "Total Gross", format_currency_usd(total_gross), f"+{format_currency_usd(d_total_gross)}" if d_total_gross >= 0 else f"-{format_currency_usd(abs(d_total_gross))}")
    draw_kpi(1, "Tickets Sold", f"{total_booked:,}", f"+{d_total_booked:,}" if d_total_booked >= 0 else f"{d_total_booked:,}")
    draw_kpi(2, "Total Venues", f"{total_venues:,}", f"+{d_total_venues:,}" if d_total_venues >= 0 else f"{d_total_venues:,}")
    draw_kpi(3, "Total Shows", f"{total_shows:,}", f"+{d_total_shows:,}" if d_total_shows >= 0 else f"{d_total_shows:,}")
    draw_kpi(4, "Occupancy", f"{overall_occ:.1f}%", f"{total_tickets:,} seats", is_delta=False)
    # draw_kpi(5, "Avg Ticket Price", f"${atp:.2f}", f"Across {total_shows:,} shows", is_delta=False)

    # --- SHARED TABLE DRAW FUNCTION ---
    def draw_table(x, y, w, h, title, cols, data_rows, is_fmt_lang=False):
        draw_glass_panel(img, draw, [x, y, x+w, y+h], radius=24)
        draw.text((x+35, y+35), title, font=f_sec, fill=TEXT_BRIGHT)
        
        th_y = y + 90
        
        # Translucent Header Overlay
        overlay = Image.new('RGBA', img.size, (0,0,0,0))
        ov_draw = ImageDraw.Draw(overlay)
        ov_draw.rectangle([x, th_y, x+w, th_y+55], fill=(0, 0, 0, 80))
        ov_draw.line([(x, th_y), (x+w, th_y)], fill=(255,255,255,30), width=1)
        ov_draw.line([(x, th_y+55), (x+w, th_y+55)], fill=(255,255,255,30), width=1)
        img.paste(overlay, (0,0), overlay)

        for c in cols:
            anchor = "la" if c['align'] == 'left' else "ra"
            cx = x + c['pos'] if c['align'] == 'left' else x + w - c['pos']
            draw.text((cx, th_y+15), c['name'].upper(), font=f_th, fill=MUTED, anchor=anchor)

        cy = th_y + 80
        for i, row in enumerate(data_rows):
            for c in cols:
                anchor = "la" if c['align'] == 'left' else "ra"
                cx = x + c['pos'] if c['align'] == 'left' else x + w - c['pos']
                
                val = str(row[c['key']])
                color = TEXT
                font_to_use = f_row
                
                if c['key'] == 'name':
                    if is_fmt_lang: color = ACCENT
                    else: color = TEXT_BRIGHT
                    font_to_use = f_row_b
                elif c['key'] == 'gross':
                    font_to_use = f_row_b
                    color = TEXT_BRIGHT
                elif c['key'] == 'occ':
                    v = float(val.replace('%','')) if val != '0' else 0.0
                    # color = GREEN if v >= 60 else (ORANGE if v >= 30 else RED)
                    color = TEXT_BRIGHT
                elif c['key'] in ['dtix', 'dgross']:
                    if val.startswith('+'): color = GREEN
                    elif val.startswith('-') and val != "-": color = RED
                    else: color = MUTED
                elif 'Remaining' in str(row.get('name','')):
                    color = MUTED
                    
                draw.text((cx, cy), val, font=font_to_use, fill=color, anchor=anchor)
                
            ov_line = Image.new('RGBA', img.size, (0,0,0,0))
            ImageDraw.Draw(ov_line).line([(x+40, cy+45), (x+w-40, cy+45)], fill=(255,255,255,15), width=1)
            img.paste(ov_line, (0,0), ov_line)
            
            cy += 60

    # --- ROW 2: FORMAT & LANGUAGE ---
    r2_y = kpi_y + 220
    col_w = (W - (2*PAD) - 40) // 2
    
    fl_cols = [
        {'name': 'Format/Lang', 'key': 'name', 'pos': 35, 'align': 'left'},
        {'name': 'Shows', 'key': 'shows', 'pos': 600, 'align': 'right'},
        {'name': 'Booked', 'key': 'booked', 'pos': 450, 'align': 'right'},
        {'name': 'Gross', 'key': 'gross', 'pos': 300, 'align': 'right'},
        {'name': 'Occ %', 'key': 'occ', 'pos': 180, 'align': 'right'},
        {'name': 'Δ Gross', 'key': 'dgross', 'pos': 35, 'align': 'right'},
    ]

    def build_fl_rows(raw_list):
        out = []
        for r in raw_list:
            occ = (r['booked'] / r['tickets'] * 100) if r['tickets'] > 0 else 0
            dg = f"+${r['d_gross']:,.0f}" if r['d_gross'] >= 0 else f"-${abs(r['d_gross']):,.0f}"
            out.append({
                'name': str(r['name']),
                'shows': f"{r['shows']:,}",
                'booked': f"{r['booked']:,}",
                'gross': f"${r['gross']:,.0f}",
                'occ': f"{occ:.1f}%",
                'dgross': dg
            })
        return out

    draw_table(PAD, r2_y, col_w, fl_h, "Format Distribution", fl_cols, build_fl_rows(fmt_list), is_fmt_lang=True)
    draw_table(PAD + col_w + 40, r2_y, col_w, fl_h, "Language Distribution", fl_cols, build_fl_rows(lang_list), is_fmt_lang=True)

    # --- ROW 3: STATES & THEATERS ---
    r3_y = r2_y + fl_h + 40
    
    st_cols = [
        {'name': 'State/Theater', 'key': 'name', 'pos': 35, 'align': 'left'},
        {'name': 'Shows', 'key': 'shows', 'pos': 600, 'align': 'right'},
        {'name': 'Booked', 'key': 'booked', 'pos': 450, 'align': 'right'},
        {'name': 'Gross', 'key': 'gross', 'pos': 300, 'align': 'right'},
        {'name': 'Occ %', 'key': 'occ', 'pos': 180, 'align': 'right'},
        {'name': 'Δ Gross', 'key': 'dgross', 'pos': 35, 'align': 'right'},
    ]

    def build_st_rows(raw_list, is_theater=False):
        out = []
        # Changed from 20 to 15
        top_15 = raw_list[:15]
        for r in top_15:
            occ = (r['booked'] / r['tickets'] * 100) if r['tickets'] > 0 else 0
            dg = f"+${r['d_gross']:,.0f}" if r['d_gross'] >= 0 else f"-${abs(r['d_gross']):,.0f}"
            name = str(r['name'])
            if is_theater and len(name) > 35: name = name[:32] + "..."
            out.append({
                'name': name,
                'shows': f"{r['shows']:,}",
                'booked': f"{r['booked']:,}",
                'gross': f"${r['gross']:,.0f}",
                'occ': f"{occ:.1f}%",
                'dgross': dg
            })
            
        # Changed from > 20 to > 15
        if len(raw_list) > 15:
            rem = raw_list[15:]
            r_shows = sum(x['shows'] for x in rem)
            r_tix = sum(x['tickets'] for x in rem)
            r_booked = sum(x['booked'] for x in rem)
            r_gross = sum(x['gross'] for x in rem)
            r_dgross = sum(x['d_gross'] for x in rem)
            r_occ = (r_booked / r_tix * 100) if r_tix > 0 else 0
            r_dg = f"+${r_dgross:,.0f}" if r_dgross >= 0 else f"-${abs(r_dgross):,.0f}"
            
            lbl = f"Remaining {len(rem)} Theaters" if is_theater else f"Remaining {len(rem)} States"
            out.append({
                'name': lbl,
                'shows': f"{r_shows:,}",
                'booked': f"{r_booked:,}",
                'gross': f"${r_gross:,.0f}",
                'occ': f"{r_occ:.1f}%",
                'dgross': r_dg
            })
            
        return out

    draw_table(PAD, r3_y, col_w, st_h, "Top States", st_cols, build_st_rows(states_list, False))
    draw_table(PAD + col_w + 40, r3_y, col_w, st_h, "Top Theaters", st_cols, build_st_rows(theaters_list, True))

    # --- FOOTER ---
    footer_y = r3_y + st_h + 40
    
    ov_line2 = Image.new('RGBA', img.size, (0,0,0,0))
    ImageDraw.Draw(ov_line2).line([(PAD, footer_y), (W-PAD, footer_y)], fill=(255,255,255,40), width=2)
    img.paste(ov_line2, (0,0), ov_line2)
    
    footer_text = f"Wknd Cinema • Data from Fandango • Generated {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
    tw, th = draw.textbbox((0,0), footer_text, font=f_sub)[2:]
    draw.text(((W-tw)//2, footer_y+30), footer_text, font=f_sub, fill=MUTED)

    # Save
    try:
        img.save(filename, quality=95)
        print(f"📸 Visual report saved to {filename}")
        return filename
    except Exception as e:
        print(f"Error saving image: {e}")
        return None