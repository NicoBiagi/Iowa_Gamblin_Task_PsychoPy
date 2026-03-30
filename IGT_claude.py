#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Iowa Gambling Task — PsychoPy version
Participants press 1, 2, 3 or 4 to choose a deck.
Captures: trial_number, card_selected, total_before, amount_won, amount_lost,
          net_change, loss_occurred, total_after, reaction_time_ms
Sends LabChart markers via serial port (ADInstruments) for EMG/SCR synchronisation.
Data saved to CSV after every trial (append mode).
"""

import os
import csv
import random
import time
from datetime import datetime

from psychopy import visual, core, event, gui

# ── Optional: serial port for LabChart markers ────────────────────────────────
# Set USE_LABCHART = True when running with ADInstruments hardware.
# Markers are sent as single bytes over a serial (COM/USB) port.
# Install pyserial if needed:  pip install pyserial
USE_LABCHART = False
SERIAL_PORT  = "COM3"      # Windows: "COM3", Mac/Linux: "/dev/tty.usbserial-XXXX"
BAUD_RATE    = 9600

# Marker values (bytes sent to LabChart)
MARKER_TRIAL_START    = 1   # sent at the start of each trial (cards on screen)
MARKER_CARD_CHOSEN    = 2   # sent the moment participant presses a key
MARKER_FEEDBACK_START = 3   # sent when feedback screen appears
MARKER_TRIAL_END      = 4   # sent after the blank ITI, before next trial

if USE_LABCHART:
    try:
        import serial
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)
        print(f"LabChart serial port open: {SERIAL_PORT}")
    except Exception as e:
        print(f"WARNING: Could not open serial port ({e}). Running without LabChart.")
        USE_LABCHART = False

def send_marker(marker_value):
    """Send a single-byte marker to LabChart via serial."""
    if USE_LABCHART:
        try:
            ser.write(bytes([marker_value]))
        except Exception as e:
            print(f"Marker send error: {e}")

# ── Participant info dialog ───────────────────────────────────────────────────
dlg = gui.Dlg(title="Iowa Gambling Task")
dlg.addField("Participant ID:")
dlg.addField("Age:",    "")
dlg.addField("Gender:", choices=["", "Male", "Female", "Non-binary", "Prefer not to say"])
info = dlg.show()
if not dlg.OK:
    core.quit()

participant_id = info[0].strip() or "P001"
age            = info[1]
gender         = info[2]
date_str       = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# ── Output CSV ────────────────────────────────────────────────────────────────
output_dir   = "data"
os.makedirs(output_dir, exist_ok=True)
csv_filename = os.path.join(output_dir, f"IGT_{participant_id}_{date_str}.csv")

CSV_HEADERS = [
    "participant_id", "age", "gender", "date",
    "trial_number", "card_selected",
    "total_before", "amount_won", "amount_lost", "net_change",
    "loss_occurred", "total_after", "reaction_time_ms"
]

def init_csv():
    with open(csv_filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()

def append_trial(record):
    with open(csv_filename, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(record)

init_csv()

# ── Task constants ────────────────────────────────────────────────────────────
TOTAL_TRIALS   = 100
STARTING_MONEY = 2000
ITI_DURATION   = 1.0   # blank screen between trials (seconds)

DECK_LABELS = ["A", "B", "C", "D"]
KEY_MAP     = {"1": "A", "2": "B", "3": "C", "4": "D"}

# ── Deck schedule builders ────────────────────────────────────────────────────
def build_deck(win_amount, loss_template):
    schedule = []
    blocks_needed = -(-TOTAL_TRIALS // 10)  # ceiling division
    for _ in range(blocks_needed):
        block = loss_template[:]
        random.shuffle(block)
        for loss in block:
            schedule.append({"win": win_amount, "loss": loss})
    return schedule

deck_A = build_deck(100, [150, 200, 250, 300, 350, 0, 0, 0, 0, 0])
deck_B = build_deck(100, [1250, 0, 0, 0, 0, 0, 0, 0, 0, 0])
deck_C = build_deck(50,  [25, 25, 50, 50, 75, 0, 0, 0, 0, 0])
deck_D = build_deck(50,  [250, 0, 0, 0, 0, 0, 0, 0, 0, 0])
deck_schedules  = {"A": deck_A, "B": deck_B, "C": deck_C, "D": deck_D}
deck_draw_count = {"A": 0, "B": 0, "C": 0, "D": 0}

# ── PsychoPy window ───────────────────────────────────────────────────────────
win = visual.Window(
    size=[1920, 1080],
    fullscr=True,
    color=[-0.85, -0.85, -0.6],
    units="pix",
    allowGUI=False,
    allowStencil=True
)

win.mouseVisible = False

# ── Helper: draw text and wait for keypress ───────────────────────────────────
def show_text(text, wait_for_key=True, duration=None, color="white", height=30):
    stim = visual.TextStim(win, text=text, color=color, height=height,
                           wrapWidth=900, alignText="center")
    stim.draw()
    win.flip()
    if wait_for_key:
        event.waitKeys(keyList=["space", "return"])
    elif duration:
        core.wait(duration)


# ── PDF pages as images ───────────────────────────────────────────────────────
def show_pdf_pages(image_paths, title_text="Participant Information Sheet"):
    """
    Display a multi-page PDF (as PNG files) in a scrollable panel.
    Layout is calculated for a 1920x1080 screen (y range -540 to +540).
    UP/DOWN scrolls within a page; RIGHT/LEFT or N/P flip pages;
    SPACE/RETURN on the last page exits.
    """
    win.mouseVisible = True
    mouse = event.Mouse(win=win)

    # ── Layout constants (1920x1080, y: -540..+540) ───────────────────────────
    PANEL_W    = 860    # image display width in px
    PANEL_TOP  = 400    # y of top edge of the visible panel
    PANEL_BOT  = -410   # y of bottom edge (leaves ~130px for nav below)
    PANEL_H    = PANEL_TOP - PANEL_BOT          # 810 px
    PANEL_CY   = (PANEL_TOP + PANEL_BOT) / 2   # centre y of panel
    SCROLL_STEP = 80    # px per key / wheel tick

    n_pages = len(image_paths)

    # ── Pre-load and scale images ─────────────────────────────────────────────
    page_stims   = []
    page_heights = []
    for path in image_paths:
        img = visual.ImageStim(win, image=path, units="pix")
        orig_w, orig_h = img.size
        scale    = PANEL_W / orig_w
        scaled_h = orig_h * scale
        img.size = (PANEL_W, scaled_h)
        page_stims.append(img)
        page_heights.append(scaled_h)

    # ── Aperture: hard-clips image to the panel rectangle ────────────────────
    aperture = visual.Aperture(
        win,
        size=(PANEL_W, PANEL_H),
        pos=(0, PANEL_CY),
        shape="square",
        units="pix"
    )
    aperture.disable()

    # ── Static UI elements ────────────────────────────────────────────────────
    title_stim = visual.TextStim(
        win, text=title_text,
        pos=(0, 500), color=[0.94, 0.75, 0.25],
        height=40, bold=True, wrapWidth=1200
    )
    page_counter = visual.TextStim(
        win, text="",
        pos=(0, 450), color=[0.7, 0.7, 0.6],
        height=26, wrapWidth=1200
    )
    hint_last = visual.TextStim(
        win, text="\u25c0 BACK   |   SPACE to continue",
        pos=(0, PANEL_BOT - 45), color=[0.6, 0.6, 0.6], height=24
    )
    hint_mid = visual.TextStim(
        win, text="\u25c0 BACK   |   NEXT \u25b6",
        pos=(0, PANEL_BOT - 45), color=[0.6, 0.6, 0.6], height=24
    )
    hint_first = visual.TextStim(
        win, text="NEXT \u25b6",
        pos=(0, PANEL_BOT - 45), color=[0.6, 0.6, 0.6], height=24
    )
    scroll_hint = visual.TextStim(
        win, text="\u25b2 \u25bc to scroll",
        pos=(0, PANEL_BOT - 80), color=[0.7, 0.7, 0.5], height=22
    )
    bar_track = visual.Rect(
        win, width=10, height=PANEL_H,
        pos=(PANEL_W / 2 + 25, PANEL_CY),
        fillColor=[-0.6, -0.6, -0.5], lineWidth=0
    )

    cur_page = 0
    scroll_y = 0
    prev_wheel = mouse.getWheelRel()[1]

    while True:
        scaled_h   = page_heights[cur_page]
        # At scroll_y=0: top of image at PANEL_TOP
        # At scroll_y=max_scroll: bottom of image at PANEL_BOT
        max_scroll = max(0, scaled_h - PANEL_H)

        # ── Input ─────────────────────────────────────────────────────────────
        keys = event.getKeys(["up", "down", "left", "right", "n", "p",
                               "space", "return", "escape"])
        for k in keys:
            if k == "escape":
                aperture.disable(); win.close(); core.quit()
            if k == "up":
                scroll_y = max(0, scroll_y - SCROLL_STEP)
            if k == "down":
                scroll_y = min(max_scroll, scroll_y + SCROLL_STEP)
            if k in ("right", "n"):
                if cur_page < n_pages - 1:
                    cur_page += 1; scroll_y = 0
            if k in ("left", "p"):
                if cur_page > 0:
                    cur_page -= 1; scroll_y = 0
            if k in ("space", "return"):
                if cur_page == n_pages - 1:
                    aperture.disable()
                    win.mouseVisible = False
                    return
                else:
                    cur_page += 1; scroll_y = 0

        cur_wheel = mouse.getWheelRel()[1]
        delta = cur_wheel - prev_wheel
        if delta != 0:
            scroll_y = max(0, min(max_scroll, scroll_y + delta * SCROLL_STEP))
        prev_wheel = cur_wheel

        # ── Draw ──────────────────────────────────────────────────────────────
        # Image top pinned to PANEL_TOP at scroll_y=0.
        # Increasing scroll_y shifts image upward (revealing content below).
        img_centre_y = PANEL_TOP - scroll_y - scaled_h / 2
        page_stims[cur_page].pos = (0, img_centre_y)

        aperture.enable()
        page_stims[cur_page].draw()
        aperture.disable()

        title_stim.draw()
        page_counter.text = f"Page {cur_page + 1} of {n_pages}"
        page_counter.draw()

        if n_pages == 1 or cur_page == n_pages - 1:
            hint_last.draw()
        elif cur_page == 0:
            hint_first.draw()
        else:
            hint_mid.draw()

        if max_scroll > 0:
            bar_track.draw()
            frac  = scroll_y / max_scroll
            bar_h = max(40, PANEL_H * (PANEL_H / scaled_h))
            bar_y = PANEL_TOP - bar_h / 2 - frac * (PANEL_H - bar_h)
            visual.Rect(win, width=10, height=bar_h,
                        pos=(PANEL_W / 2 + 25, bar_y),
                        fillColor=[0.94, 0.75, 0.25], lineWidth=0).draw()
            scroll_hint.draw()

        win.flip()

# ── Information sheet PNG pages ───────────────────────────────────────────────
# Convert InformationSheet_VST.pdf to PNGs (one per page) and place them in
# the same folder as this script. Update the filenames below if needed.
INFO_SHEET_PAGES = [
    "InformationSheet_VST_p1.png",
    "InformationSheet_VST_p2.png",
    "InformationSheet_VST_p3.png",
]

# ── Consent form items ────────────────────────────────────────────────────────
CONSENT_ITEMS = [
    'I have read the accompanying Information Sheet for this study.',
    'I understand the purposes of the study and what will be required of me. '
    'Any questions I have had have been answered to my satisfaction.',
    'I understand what information will be collected about me, what it will be '
    'used for, who it may be shared with, how it will be kept safe, and my '
    'rights in relation to my data.',
    'I understand that participation is voluntary and that I may withdraw at '
    'any time without penalty.',
    'I understand that anonymised data from this study may be shared and reused '
    'by other researchers.',
    'I understand that the data collected will be securely stored and may be '
    'accessed by authenticated researchers.',
    'This project has received favourable ethical approval from the University '
    'Research Ethics Committee.',
    'I confirm that I have received a copy of the Information Sheet and consent '
    'to participate.',
]

# ── Consent screen with mouse-clickable checkboxes ───────────────────────────
def show_consent_form():
    """
    Display all consent items with clickable checkboxes.
    The 'I Agree' button is only enabled once all boxes are ticked.
    Returns when the participant clicks 'I Agree'.
    """
    win.mouseVisible = True
    mouse = event.Mouse(win=win)

    N          = len(CONSENT_ITEMS)
    BOX_SIZE   = 22
    ROW_H      = 60           # vertical space per item
    TEXT_X     = -390         # left edge of item text
    BOX_X      = -440         # centre of checkbox square
    START_Y    = 220          # y of first row centre
    SCROLL_STEP = 50
    VISIBLE_H  = 520

    checked    = [False] * N
    scroll_y   = 0
    max_scroll = max(0, N * ROW_H - VISIBLE_H)

    # Pre-build text stims for each item (pos updated each frame)
    item_stims = []
    for item in CONSENT_ITEMS:
        stim = visual.TextStim(
            win, text=item,
            pos=(0, 0), color="white",
            height=20, wrapWidth=740,
            alignText="left", anchorHoriz="left", anchorVert="center"
        )
        item_stims.append(stim)

    title_stim = visual.TextStim(
        win, text="Consent Form",
        pos=(0, 345), color=[0.94, 0.75, 0.25],
        height=36, bold=True
    )
    subtitle_stim = visual.TextStim(
        win, text="Please tick all boxes to confirm your agreement, then click 'I Agree'.",
        pos=(0, 295), color=[0.8, 0.8, 0.8], height=22, wrapWidth=900
    )

    # 'I Agree' button
    btn_rect = visual.Rect(win, width=200, height=50,
                           pos=(0, -360), lineWidth=2)
    btn_text = visual.TextStim(win, text="I Agree", pos=(0, -360),
                               height=26, bold=True)

    prev_buttons = mouse.getPressed()
    prev_wheel   = mouse.getWheelRel()[1]

    while True:
        all_checked = all(checked)

        # ── input ─────────────────────────────────────────────────────────────
        keys = event.getKeys(["up", "down", "escape"])
        for k in keys:
            if k == "escape":
                win.close(); core.quit()
            if k == "up":
                scroll_y = max(0, scroll_y - SCROLL_STEP)
            if k == "down":
                scroll_y = min(max_scroll, scroll_y + SCROLL_STEP)

        cur_wheel = mouse.getWheelRel()[1]
        delta = cur_wheel - prev_wheel
        if delta != 0:
            scroll_y = max(0, min(max_scroll, scroll_y + delta * SCROLL_STEP))
        prev_wheel = cur_wheel

        cur_buttons = mouse.getPressed()
        just_clicked = cur_buttons[0] and not prev_buttons[0]
        prev_buttons = cur_buttons

        if just_clicked:
            mx, my = mouse.getPos()

            # Check checkbox hits
            for i in range(N):
                row_y = START_Y - i * ROW_H + scroll_y
                if abs(mx - BOX_X) < BOX_SIZE and abs(my - row_y) < BOX_SIZE:
                    checked[i] = not checked[i]

            # Check 'I Agree' button
            if all_checked and abs(mx) < 100 and abs(my - (-360)) < 25:
                win.mouseVisible = False
                return

        # ── draw ──────────────────────────────────────────────────────────────
        # Background panel
        bg = visual.Rect(win, width=920, height=VISIBLE_H,
                         pos=(0, 0),
                         fillColor=[-0.9, -0.9, -0.8],
                         lineColor=[-0.5, -0.5, -0.4], lineWidth=2)
        bg.draw()

        for i in range(N):
            row_y = START_Y - i * ROW_H + scroll_y

            # Only draw rows within the visible band
            if row_y < -VISIBLE_H / 2 - ROW_H or row_y > VISIBLE_H / 2 + ROW_H:
                continue

            # Checkbox border
            box = visual.Rect(win, width=BOX_SIZE, height=BOX_SIZE,
                              pos=(BOX_X, row_y),
                              fillColor=[-0.7, -0.7, -0.6],
                              lineColor=[0.8, 0.8, 0.8], lineWidth=2)
            box.draw()

            # Tick mark
            if checked[i]:
                tick = visual.TextStim(win, text="✓", pos=(BOX_X, row_y),
                                       color=[0.3, 0.9, 0.3], height=20, bold=True)
                tick.draw()

            # Item text
            item_stims[i].pos = (TEXT_X, row_y)
            item_stims[i].draw()

        # Cover overflow above and below
        for cover_y, cover_h in [(320, 160), (-290, 120)]:
            cover = visual.Rect(win, width=1280, height=cover_h,
                                pos=(0, cover_y),
                                fillColor=[-0.85, -0.85, -0.6],
                                lineWidth=0)
            cover.draw()

        title_stim.draw()
        subtitle_stim.draw()

        # Scroll indicator
        if max_scroll > 0:
            frac     = scroll_y / max_scroll
            bar_y    = VISIBLE_H / 2 - frac * VISIBLE_H
            bar_stim = visual.Rect(win, width=6, height=40,
                                   pos=(470, bar_y),
                                   fillColor=[0.94, 0.75, 0.25])
            bar_stim.draw()
            scroll_hint = visual.TextStim(
                win, text="▲ ▼ to scroll",
                pos=(0, -270), color=[0.7, 0.7, 0.5], height=20
            )
            scroll_hint.draw()

        # 'I Agree' button — greyed out until all boxes ticked
        if all_checked:
            btn_rect.fillColor  = [0.94, 0.75, 0.25]
            btn_rect.lineColor  = [0.94, 0.75, 0.25]
            btn_text.color      = [-0.85, -0.85, -0.6]
        else:
            btn_rect.fillColor  = [-0.6, -0.6, -0.5]
            btn_rect.lineColor  = [-0.3, -0.3, -0.2]
            btn_text.color      = [-0.2, -0.2, -0.1]

        btn_rect.draw()
        btn_text.draw()

        win.flip()


# ── Welcome ───────────────────────────────────────────────────────────────────
show_text(
    "Iowa Gambling Task\n\n"
    "Welcome to this experiment.\n\n"
    "Press SPACE to continue.",
    wait_for_key=True
)

# ── Information sheet ─────────────────────────────────────────────────────────
show_pdf_pages(
    image_paths=INFO_SHEET_PAGES,
    title_text="Participant Information Sheet"
)

# ── Consent form ──────────────────────────────────────────────────────────────
show_consent_form()

# ── Instructions ──────────────────────────────────────────────────────────────
show_text(
    "Instructions\n\n"
    "You will see 4 decks of cards numbered 1, 2, 3 and 4.\n\n"
    "On each turn, press 1, 2, 3 or 4 to choose a deck.\n"
    "You will be told how much money you have WON and,\n"
    "sometimes, how much money you have LOST.\n\n"
    "You start with a loan of $2,000.\n"
    "Your goal is to make as much profit as possible.\n\n"
    "Some decks are better than others.\n\n"
    "Press SPACE to begin.",
    wait_for_key=True
)

# ── Build card stimuli ────────────────────────────────────────────────────────
CARD_W, CARD_H = 120, 180
CARD_GAP       = 50
total_w        = 4 * CARD_W + 3 * CARD_GAP
start_x        = -total_w / 2 + CARD_W / 2
card_positions = [
    (start_x + i * (CARD_W + CARD_GAP), 30)
    for i in range(4)
]

def make_card_rect(pos):
    return visual.Rect(win, width=CARD_W, height=CARD_H,
                       pos=pos, fillColor=[-0.6, -0.3, 0.3],
                       lineColor=[0.8, 0.8, 0.8], lineWidth=3)

def make_number_label(pos, number):
    return visual.TextStim(win, text=str(number),
                           pos=(pos[0], pos[1] - CARD_H / 2 - 25),
                           color=[0.94, 0.75, 0.25], height=36, bold=True)

def make_question(pos):
    return visual.TextStim(win, text="?", pos=pos,
                           color=[1, 1, 1], height=60, opacity=0.2)

card_rects     = [make_card_rect(p)          for p in card_positions]
card_numbers   = [make_number_label(p, i+1)  for i, p in enumerate(card_positions)]
card_questions = [make_question(p)           for p in card_positions]

hud_balance = visual.TextStim(win, text="", pos=(0, 340),
                               color=[0.94, 0.75, 0.25], height=28, bold=True)
prompt_text = visual.TextStim(win, text="Press 1, 2, 3 or 4 to choose a deck.",
                               pos=(0, -290), color=[0.8, 0.8, 0.8], height=24)

def draw_cards(balance):
    hud_balance.text = f"Balance: ${balance:,}"
    hud_balance.draw()
    prompt_text.draw()
    for rect, number, q in zip(card_rects, card_numbers, card_questions):
        rect.draw()
        q.draw()
        number.draw()

# ── Main task loop ────────────────────────────────────────────────────────────
total_money = STARTING_MONEY

for trial_num in range(1, TOTAL_TRIALS + 1):

    if event.getKeys(["escape"]):
        break

    # Flush any leftover keypresses before starting the trial
    event.clearEvents()

    draw_cards(total_money)
    win.flip()

    send_marker(MARKER_TRIAL_START)
    trial_clock = core.Clock()

    chosen_deck = None

    while chosen_deck is None:
        draw_cards(total_money)
        win.flip()

        keys = event.getKeys(keyList=["1", "2", "3", "4", "escape"])
        for key in keys:
            if key == "escape":
                core.quit()
            if key in KEY_MAP:
                chosen_deck = KEY_MAP[key]
                break

    reaction_time_ms = round(trial_clock.getTime() * 1000)
    send_marker(MARKER_CARD_CHOSEN)

    # ── Compute outcome ───────────────────────────────────────────────────────
    idx     = deck_draw_count[chosen_deck]
    outcome = deck_schedules[chosen_deck][idx]
    deck_draw_count[chosen_deck] += 1

    win_amt       = outcome["win"]
    loss_amt      = outcome["loss"]
    net           = win_amt - loss_amt
    money_before  = total_money
    total_money  += net
    loss_occurred = 1 if loss_amt > 0 else 0

    # ── Save trial to CSV immediately ─────────────────────────────────────────
    trial_record = {
        "participant_id":   participant_id,
        "age":              age,
        "gender":           gender,
        "date":             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trial_number":     trial_num,
        "card_selected":    chosen_deck,
        "total_before":     money_before,
        "amount_won":       win_amt,
        "amount_lost":      loss_amt,
        "net_change":       net,
        "loss_occurred":    loss_occurred,
        "total_after":      total_money,
        "reaction_time_ms": reaction_time_ms
    }
    append_trial(trial_record)

    # ── Feedback screen ───────────────────────────────────────────────────────
    send_marker(MARKER_FEEDBACK_START)
    
    deck_number = list(KEY_MAP.keys())[list(KEY_MAP.values()).index(chosen_deck)]
    fb_lines = [f"You chose Deck {deck_number}"]
    fb_lines.append(f"\n\nYou won: +${win_amt:,}")
    if loss_amt > 0:
        fb_lines.append(f"\n\nYou lost:  -${loss_amt:,}")
    fb_lines.append(f"\n\nNet this trial: {'+' if net >= 0 else ''}${net:,}")
    fb_lines.append(f"\n\nTotal balance: ${total_money:,}")

    fb_stim = visual.TextStim(
        win, text="\n".join(fb_lines),
        color="white", height=30, wrapWidth=700, alignText="center"
    )
    fb_stim.draw()
    win.flip()
    core.wait(4.0)

    # ── Blank ITI ─────────────────────────────────────────────────────────────
    send_marker(MARKER_TRIAL_END)
    win.flip()
    core.wait(ITI_DURATION)

# ── End screen ────────────────────────────────────────────────────────────────
show_text(
    f"Task complete!\n\n"
    f"Final balance: ${total_money:,}\n\n"
    f"Your data has been saved.\n"
    f"Thank you for participating.\n\n"
    f"Press SPACE to exit.",
    wait_for_key=True
)

# ── Cleanup ───────────────────────────────────────────────────────────────────
if USE_LABCHART:
    ser.close()

win.close()
core.quit()