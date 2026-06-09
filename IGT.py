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

from psychopy import visual, core, event, gui, parallel
import numpy as np
import pandas as pd
import sys
import random
import psychopy.event

## ── Parallel port for LabChart markers ───────────────────────────────────────
## Set USE_LABCHART = True when running with ADInstruments hardware.
## Markers are sent via parallel port using PsychoPy's parallel module.
USE_LABCHART   = False
PORT_ADDRESS   = 0x03FF8   # parallel port address

# Marker values written to parallel port data lines
MARKER_TRIAL_START       = 1   # fixation cross onset — start of trial
MARKER_DECK_ONSET        = 2   # decks appear on screen, response locked
MARKER_DECK_RESPONSE_OPEN = 3  # response window opens, participant can choose
MARKER_DECK_CHOSEN       = 4   # participant presses a key
MARKER_FEEDBACK_ONSET    = 5   # feedback screen appears
MARKER_FEEDBACK_OFFSET   = 6   # feedback clears, blank screen begins
MARKER_TRIAL_END         = 7   # blank screen ends, trial over

_port = None

if USE_LABCHART:
    try:
        _port = parallel.ParallelPort(address=PORT_ADDRESS)
        _port.setData(0)
        print(f"LabChart parallel port open: {hex(PORT_ADDRESS)}")
    except Exception as e:
        print(f"WARNING: Could not open parallel port ({e}). Running without LabChart.")
        USE_LABCHART = False

def send_marker(marker_value):
    """Write marker to parallel port data lines, then reset to 0 after 10 ms."""
    if USE_LABCHART and _port is not None:
        try:
            _port.setData(marker_value)
            core.wait(0.010)
            _port.setData(0)
        except Exception as e:
            print(f"Marker send error: {e}")

# ── Participant info dialog ───────────────────────────────────────────────────
dlg = gui.Dlg(title="Iowa Gambling Task")
dlg.addField("Participant ID:")
dlg.addField("Age:",    "")
dlg.addField("Sex:", choices=["", "Male", "Female", "Prefer not to say"])
info = dlg.show()
if not dlg.OK:
    core.quit()

participant_id = info[0].strip() or "P001"
age            = info[1]
sex         = info[2]
date_str       = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# ── Output CSV ────────────────────────────────────────────────────────────────
output_dir   = "data"
os.makedirs(output_dir, exist_ok=True)
csv_filename = os.path.join(output_dir, f"IGT_{participant_id}_{date_str}.csv")

CSV_HEADERS = [
    "participant_id", "age", "sex", "date",
    "trial_number", "card_selected",
    "total_before", "amount_won", "amount_lost", "net_change",
    "loss_occurred", "total_after", "reaction_time_ms",
    
    # ── Questionnaire fields ────────────────────────────────────────────────
    "questionnaire",
    "question_number",
    "question_text",
    "response_value",
    "response_label"
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
TOTAL_TRIALS          = 3
STARTING_MONEY        = 2000
FORCED_VIEW_DURATION  = 2.0   # seconds decks shown before response is allowed
FEEDBACK_DURATION     = 2.0   # seconds feedback screen shown
POST_FEEDBACK_BLANK   = 2.0   # seconds blank after feedback, before ITI
ITI_DURATION          = 6.0   # blank fixation between trials (seconds)

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

    # ── Layout constants ──────────────────────────────────────────────────────
    PANEL_W = 860
    PANEL_TOP = 400
    PANEL_BOT = -410
    PANEL_H = PANEL_TOP - PANEL_BOT
    PANEL_CY = (PANEL_TOP + PANEL_BOT) / 2
    SCROLL_STEP = 80

    n_pages = len(image_paths)

    # ── Pre-load and scale images ─────────────────────────────────────────────
    page_stims = []
    page_heights = []

    for path in image_paths:
        img = visual.ImageStim(win, image=path, units="pix")
        orig_w, orig_h = img.size
        scale = PANEL_W / orig_w
        scaled_h = orig_h * scale
        img.size = (PANEL_W, scaled_h)
        page_stims.append(img)
        page_heights.append(scaled_h)

    # ── Aperture to clip image inside the panel ───────────────────────────────
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
        win,
        text=title_text,
        pos=(0, 500),
        color=[0.94, 0.75, 0.25],
        height=40,
        bold=True,
        wrapWidth=1200
    )

    page_counter = visual.TextStim(
        win,
        text="",
        pos=(0, 450),
        color=[0.7, 0.7, 0.6],
        height=26,
        wrapWidth=1200
    )

    hint_last = visual.TextStim(
        win,
        text="\u25c0 BACK   |   SPACE to continue",
        pos=(0, PANEL_BOT - 45),
        color=[0.6, 0.6, 0.6],
        height=24
    )

    hint_mid = visual.TextStim(
        win,
        text="\u25c0 BACK   |   NEXT \u25b6",
        pos=(0, PANEL_BOT - 45),
        color=[0.6, 0.6, 0.6],
        height=24
    )

    hint_first = visual.TextStim(
        win,
        text="NEXT \u25b6",
        pos=(0, PANEL_BOT - 45),
        color=[0.6, 0.6, 0.6],
        height=24
    )

    scroll_hint = visual.TextStim(
        win,
        text="\u25b2 \u25bc to scroll",
        pos=(0, PANEL_BOT - 80),
        color=[0.7, 0.7, 0.5],
        height=22
    )

    bar_track = visual.Rect(
        win,
        width=10,
        height=PANEL_H,
        pos=(PANEL_W / 2 + 25, PANEL_CY),
        fillColor=[-0.6, -0.6, -0.5],
        lineWidth=0
    )

    cur_page = 0
    scroll_y = 0

    event.clearEvents()

    while True:
        scaled_h = page_heights[cur_page]
        max_scroll = max(0, scaled_h - PANEL_H)

        # ── Keyboard input ────────────────────────────────────────────────────
        keys = event.getKeys([
            "up", "down", "left", "right", "n", "p",
            "space", "return", "escape"
        ])

        for k in keys:
            if k == "escape":
                aperture.disable()
                win.close()
                core.quit()

            elif k == "up":
                scroll_y = max(0, scroll_y - SCROLL_STEP)

            elif k == "down":
                scroll_y = min(max_scroll, scroll_y + SCROLL_STEP)

            elif k in ("right", "n"):
                if cur_page < n_pages - 1:
                    cur_page += 1
                    scroll_y = 0

            elif k in ("left", "p"):
                if cur_page > 0:
                    cur_page -= 1
                    scroll_y = 0

            elif k in ("space", "return"):
                if cur_page == n_pages - 1:
                    aperture.disable()
                    win.mouseVisible = False
                    return
                else:
                    cur_page += 1
                    scroll_y = 0

        # ── Mouse wheel input ─────────────────────────────────────────────────
        wheel_delta = mouse.getWheelRel()[1]
        if wheel_delta != 0:
            # wheel up = move toward top, wheel down = move toward bottom
            scroll_y = max(0, min(max_scroll, scroll_y - wheel_delta * SCROLL_STEP))

        # ── Draw page ─────────────────────────────────────────────────────────
        # At scroll_y = 0, the image top is aligned with PANEL_TOP.
        # As scroll_y increases, the image moves UP, revealing the bottom.
        img_centre_y = PANEL_TOP - (scaled_h / 2) + scroll_y
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
            frac = scroll_y / max_scroll
            bar_h = max(40, PANEL_H * (PANEL_H / scaled_h))
            bar_y = PANEL_TOP - bar_h / 2 - frac * (PANEL_H - bar_h)

            scroll_bar = visual.Rect(
                win,
                width=10,
                height=bar_h,
                pos=(PANEL_W / 2 + 25, bar_y),
                fillColor=[0.94, 0.75, 0.25],
                lineWidth=0
            )
            scroll_bar.draw()
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

# ── Consent form PNG page ─────────────────────────────────────────────────────
CONSENT_FORM_PAGES = [
    "ConsentForm_VSI.png",
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
show_pdf_pages(
    image_paths=CONSENT_FORM_PAGES,
    title_text="Consent Form"
)

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

def make_card_rect_highlighted(pos):
    """Card rect with bright border — shown when response window opens."""
    return visual.Rect(win, width=CARD_W, height=CARD_H,
                       pos=pos, fillColor=[-0.6, -0.3, 0.3],
                       lineColor=[0.94, 0.75, 0.25], lineWidth=6)

card_rects_highlighted = [make_card_rect_highlighted(p) for p in card_positions]
card_rects             = [make_card_rect(p)             for p in card_positions]


card_numbers   = [make_number_label(p, i+1)  for i, p in enumerate(card_positions)]
card_questions = [make_question(p)           for p in card_positions]

hud_balance = visual.TextStim(win, text="", pos=(0, 340),
                               color=[0.94, 0.75, 0.25], height=28, bold=True)
prompt_text = visual.TextStim(win, text="Press 1, 2, 3 or 4 to choose a deck.",
                               pos=(0, -290), color=[0.8, 0.8, 0.8], height=24)
fixation_cross = visual.TextStim(win, text="+", pos=(0, 0),
                                  color="white", height=60, bold=True)

def draw_cards(balance, highlighted=False):
    hud_balance.text = f"Balance: ${balance:,}"
    hud_balance.draw()
    rects = card_rects_highlighted if highlighted else card_rects
    for rect, number, q in zip(rects, card_numbers, card_questions):
        rect.draw()
        q.draw()
        number.draw()
    if highlighted:
        prompt_text.draw()

# ── Main task loop ────────────────────────────────────────────────────────────
total_money = STARTING_MONEY

# Initial fixation cross before first trial
fixation_cross.draw()
win.flip()
send_marker(MARKER_TRIAL_START)
core.wait(ITI_DURATION)

for trial_num in range(1, TOTAL_TRIALS + 1):

    if event.getKeys(["escape"]):
        break

    event.clearEvents()

    # ── Deck onset: decks shown, response locked (2 s) ───────────────────────
    draw_cards(total_money, highlighted=False)
    win.flip()
    send_marker(MARKER_DECK_ONSET)
    core.wait(FORCED_VIEW_DURATION)

    # Discard any keypresses made during the forced-view period
    event.clearEvents()

    # ── Response window opens: highlight decks, accept keypresses ─────────────
    draw_cards(total_money, highlighted=True)
    win.flip()
    send_marker(MARKER_DECK_RESPONSE_OPEN)

    trial_clock = core.Clock()
    chosen_deck = None

    while chosen_deck is None:
        draw_cards(total_money, highlighted=True)
        win.flip()

        keys = event.getKeys(keyList=["1", "2", "3", "4", "escape"])
        for key in keys:
            if key == "escape":
                core.quit()
            if key in KEY_MAP:
                chosen_deck = KEY_MAP[key]
                break

    reaction_time_ms = round(trial_clock.getTime() * 1000)
    send_marker(MARKER_DECK_CHOSEN)

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
        "sex":           sex,
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

    # ── Feedback onset ────────────────────────────────────────────────────────
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
    send_marker(MARKER_FEEDBACK_ONSET)
    core.wait(FEEDBACK_DURATION)

    # ── Feedback offset: blank screen ─────────────────────────────────────────
    win.flip()
    send_marker(MARKER_FEEDBACK_OFFSET)
    core.wait(POST_FEEDBACK_BLANK)

    # ── Trial end / ITI: fixation cross (skip after final trial) ─────────────
    if trial_num < TOTAL_TRIALS:
        fixation_cross.draw()
        win.flip()
        send_marker(MARKER_TRIAL_END)
        # MARKER_TRIAL_START for next trial sent after fixation flip
        send_marker(MARKER_TRIAL_START)
        core.wait(ITI_DURATION)
    else:
        send_marker(MARKER_TRIAL_END)
    
# ── End task screen ────────────────────────────────────────────────────────────────
show_text(
    f"Task complete!\n\n"
    f"Final balance: ${total_money:,}\n\n"
    f"Your data has been saved.\n\n"
    f"Press SPACE to continue.",
    wait_for_key=True
)

# ── HSPS questionnaire ────────────────────────────────────────────────────────
HSPS_ITEMS = [
    "Are you easily overwhelmed by strong sensory input?",
    "Do you seem to be aware of subtleties in your environment?",
    "Do other people's moods affect you?",
    "Do you tend to be more sensitive to pain?",
    "Do you find yourself needing to withdraw during busy days, into bed or into a darkened room or any place where you can have some privacy and relief from stimulation?",
    "Are you particularly sensitive to the effects of caffeine?",
    "Are you easily overwhelmed by things like bright lights, strong smells, coarse fabrics, or sirens close by?",
    "Do you have a rich, complex inner life?",
    "Are you made uncomfortable by loud noises?",
    "Are you deeply moved by the arts or music?",
    "Does your nervous system sometimes feel so frazzled that you just have to go off by yourself?",
    "Are you conscientious?",
    "Do you startle easily?",
    "Do you get rattled when you have a lot to do in a short amount of time?",
    "When people are uncomfortable in a physical environment, do you tend to know what needs to be done to make it more comfortable (like changing the lighting or the seating)?",
    "Are you annoyed when people try to get you to do too many things at once?",
    "Do you try hard to avoid making mistakes or forgetting things?",
    "Do you make a point to avoid violent movies and TV shows?",
    "Do you become unpleasantly aroused when a lot is going on around you?",
    "Does being very hungry create a strong reaction in you, disrupting your concentration or mood?",
    "Do changes in your life shake you up?",
    "Do you notice and enjoy delicate or fine scents, tastes, sounds, works of art?",
    "Do you find it unpleasant to have a lot going on at once?",
    "Do you make it a high priority to arrange your life to avoid upsetting or overwhelming situations?",
    "Are you bothered by intense stimuli, like loud noises or chaotic scenes?",
    "When you must compete or be observed while performing a task, do you become so nervous or shaky that you do much worse than you would otherwise?",
    "When you were a child, did parents or teachers seem to see you as sensitive or shy?"
]

HSPS_LABELS = [
    "1\nNot at all",
    "2\nSlightly",
    "3\nSomewhat",
    "4\nModerately",
    "5\nGood amount",
    "6\nVery much",
    "7\nExtremely"
]

def run_scrollable_questionnaire(q_name, items, labels, intro_text):
    """
    Display all items on one scrollable page.
    Scale header is pinned at the top of the viewport.
    A Submit button (bottom-right) activates once every item is answered.
    Saves one CSV row per item after the participant submits.
    """
    win.mouseVisible = True
    mouse = event.Mouse(win=win)

    show_text(intro_text, wait_for_key=True)

    # ── Layout constants ──────────────────────────────────────────────────────
    # Screen is 1920×1080 (x: -960 to +960, y: -540 to +540).
    N             = len(items)
    N_OPTS        = len(labels)
    ROW_H         = 46          # pixels per question row (smaller = more items visible)
    # Question text: left portion of each row
    Q_NUM_X       = -880        # right-anchor of "N." label
    Q_TEXT_X      = -860        # left-anchor of question text
    Q_TEXT_W      = 820         # wrap width — ends ~x=-40, clear of radio cols
    Q_FONT_H      = 16          # question font size
    COL_FONT_H    = 15          # header/label font size
    CIRCLE_R      = 11          # radio button radius
    # Radio columns: right half, kept well within ±960
    COL_BAND_LEFT  =  -10       # x of leftmost column
    COL_BAND_RIGHT =  880       # x of rightmost column
    # Viewport: narrower than last time to create a contained panel feel
    VIEWPORT_TOP  =  300
    VIEWPORT_BOT  = -360
    VIEWPORT_H    = VIEWPORT_TOP - VIEWPORT_BOT
    SCROLL_STEP   = ROW_H * 2
    HEADER_Y      =  370        # bottom-anchored header labels
    TITLE_Y       =  460        # questionnaire title

    # Column x positions
    if N_OPTS > 1:
        col_xs = [COL_BAND_LEFT + i * (COL_BAND_RIGHT - COL_BAND_LEFT) / (N_OPTS - 1)
                  for i in range(N_OPTS)]
    else:
        col_xs = [(COL_BAND_LEFT + COL_BAND_RIGHT) / 2]
    col_spacing = (COL_BAND_RIGHT - COL_BAND_LEFT) / max(N_OPTS - 1, 1)

    # ── Pre-build all stimuli (positions updated each frame via scroll_y) ─────
    responses = [None] * N   # selected option index (0-based) per item

    # Question number + text stims
    q_num_stims  = []
    q_text_stims = []
    for i, item in enumerate(items):
        q_num_stims.append(visual.TextStim(
            win, text=f"{i+1}.",
            pos=(0, 0), color=[0.7, 0.7, 0.6],
            height=Q_FONT_H, bold=True, anchorHoriz="right"
        ))
        q_text_stims.append(visual.TextStim(
            win, text=item,
            pos=(0, 0), color="white",
            height=Q_FONT_H, wrapWidth=Q_TEXT_W,
            alignText="left", anchorHoriz="left", anchorVert="center"
        ))

    # Radio circles (N rows × N_OPTS columns)
    circles = []
    for i in range(N):
        row_circles = []
        for j in range(N_OPTS):
            row_circles.append(visual.Circle(
                win, radius=CIRCLE_R,
                pos=(0, 0),
                fillColor=None,
                lineColor="white", lineWidth=2
            ))
        circles.append(row_circles)

    # Pinned column headers (drawn at fixed screen position)
    header_stims = []
    for j, lab in enumerate(labels):
        header_stims.append(visual.TextStim(
            win, text=lab,
            pos=(col_xs[j], HEADER_Y),
            color=[0.94, 0.75, 0.25],
            height=COL_FONT_H, wrapWidth=max(int(col_spacing - 6), 60),
            alignText="center", anchorHoriz="center", anchorVert="bottom"
        ))

    # Title
    title_stim = visual.TextStim(
        win, text=q_name,
        pos=(0, TITLE_Y),
        color=[0.94, 0.75, 0.25],
        height=34, bold=True
    )

    # Scroll hint
    scroll_hint_stim = visual.TextStim(
        win, text="▲ ▼  or mouse wheel to scroll",
        pos=(-700, VIEWPORT_BOT - 40),
        color=[0.6, 0.6, 0.5], height=20,
        anchorHoriz="left"
    )

    # Submit button (bottom-right)
    btn_rect = visual.Rect(win, width=180, height=44,
                           pos=(820, VIEWPORT_BOT - 50), lineWidth=2)
    btn_text = visual.TextStim(win, text="Submit",
                               pos=(820, VIEWPORT_BOT - 50),
                               height=22, bold=True)

    # Aperture to clip scrolling content
    aperture = visual.Aperture(
        win,
        size=(1920, VIEWPORT_H),
        pos=(0, (VIEWPORT_TOP + VIEWPORT_BOT) / 2),
        shape="square", units="pix"
    )
    aperture.disable()

    # Cover strips to hide content that scrolls past viewport edges
    cover_top = visual.Rect(win, width=1920, height=250,
                            pos=(0, VIEWPORT_TOP + 125),
                            fillColor=[-0.85, -0.85, -0.6], lineWidth=0)
    cover_bot = visual.Rect(win, width=1920, height=200,
                            pos=(0, VIEWPORT_BOT - 100),
                            fillColor=[-0.85, -0.85, -0.6], lineWidth=0)

    # Scrollbar track
    bar_track = visual.Rect(win, width=8, height=VIEWPORT_H,
                            pos=(940, (VIEWPORT_TOP + VIEWPORT_BOT) / 2),
                            fillColor=[-0.6, -0.6, -0.5], lineWidth=0)

    # Scroll hint
    scroll_hint_stim = visual.TextStim(
        win, text="▲ ▼  or mouse wheel to scroll",
        pos=(-880, VIEWPORT_BOT - 50),
        color=[0.6, 0.6, 0.5], height=18,
        anchorHoriz="left"
    )

    scroll_y    = 0
    content_h   = N * ROW_H + 40        # total scrollable height
    max_scroll  = max(0, content_h - VIEWPORT_H)
    prev_buttons = mouse.getPressed()

    event.clearEvents()

    while True:
        all_answered = all(r is not None for r in responses)

        # ── Input ─────────────────────────────────────────────────────────────
        keys = event.getKeys(["up", "down", "escape"])
        for k in keys:
            if k == "escape":
                aperture.disable()
                win.close(); core.quit()
            if k == "up":
                scroll_y = max(0, scroll_y - SCROLL_STEP)
            if k == "down":
                scroll_y = min(max_scroll, scroll_y + SCROLL_STEP)

        wheel = mouse.getWheelRel()[1]
        if wheel != 0:
            scroll_y = max(0, min(max_scroll, scroll_y - wheel * SCROLL_STEP))

        cur_buttons = mouse.getPressed()
        just_clicked = cur_buttons[0] and not prev_buttons[0]
        prev_buttons = cur_buttons

        if just_clicked:
            mx, my = mouse.getPos()

            # Check radio buttons
            for i in range(N):
                row_y = VIEWPORT_TOP - 30 - i * ROW_H + scroll_y
                if abs(my - row_y) < ROW_H / 2:
                    for j in range(N_OPTS):
                        if abs(mx - col_xs[j]) < ROW_H / 2:
                            responses[i] = j
                            break

            # Submit button
            if all_answered:
                bx, by = 820, VIEWPORT_BOT - 50
                if abs(mx - bx) < 90 and abs(my - by) < 22:
                    break

        # ── Draw ──────────────────────────────────────────────────────────────
        aperture.enable()

        for i in range(N):
            row_y = VIEWPORT_TOP - 30 - i * ROW_H + scroll_y

            # Skip rows fully outside viewport
            if row_y < VIEWPORT_BOT - ROW_H or row_y > VIEWPORT_TOP + ROW_H:
                continue

            # Alternating row background
            row_bg = visual.Rect(
                win, width=1880, height=ROW_H - 4,
                pos=(0, row_y),
                fillColor=[-0.82, -0.82, -0.58] if i % 2 == 0 else [-0.78, -0.78, -0.54],
                lineWidth=0
            )
            row_bg.draw()

            # Highlight unanswered rows in red tint if submit was attempted
            # (passive — no explicit attempt tracking needed here)

            # Question number
            q_num_stims[i].pos  = (Q_NUM_X, row_y)
            q_num_stims[i].draw()

            # Question text
            q_text_stims[i].pos = (Q_TEXT_X, row_y)
            q_text_stims[i].draw()

            # Radio buttons
            for j, circle in enumerate(circles[i]):
                circle.pos = (col_xs[j], row_y)
                if responses[i] == j:
                    circle.fillColor = [0.94, 0.75, 0.25]
                    circle.lineColor = [0.94, 0.75, 0.25]
                else:
                    circle.fillColor = None
                    circle.lineColor = "white"
                circle.draw()

        aperture.disable()

        # Cover strips
        cover_top.draw()
        cover_bot.draw()

        # Pinned header row background
        header_bg = visual.Rect(win, width=1920, height=160,
                                pos=(0, HEADER_Y + 30),
                                fillColor=[-0.85, -0.85, -0.6], lineWidth=0)
        header_bg.draw()

        for hs in header_stims:
            hs.draw()

        title_stim.draw()
        scroll_hint_stim.draw()

        # Scrollbar
        if max_scroll > 0:
            bar_track.draw()
            frac  = scroll_y / max_scroll
            bar_h = max(40, VIEWPORT_H * (VIEWPORT_H / content_h))
            bar_y = VIEWPORT_TOP - bar_h / 2 - frac * (VIEWPORT_H - bar_h)
            visual.Rect(win, width=8, height=bar_h,
                        pos=(940, bar_y),
                        fillColor=[0.94, 0.75, 0.25], lineWidth=0).draw()

        # Submit button
        if all_answered:
            btn_rect.fillColor = [0.94, 0.75, 0.25]
            btn_rect.lineColor = [0.94, 0.75, 0.25]
            btn_text.color     = [-0.85, -0.85, -0.6]
        else:
            btn_rect.fillColor = [-0.6, -0.6, -0.5]
            btn_rect.lineColor = [-0.3, -0.3, -0.2]
            btn_text.color     = [-0.2, -0.2, -0.1]
        btn_rect.draw()
        btn_text.draw()

        win.flip()

    # ── Save all responses ────────────────────────────────────────────────────
    for i, item in enumerate(items):
        append_trial({
            "participant_id":   participant_id,
            "age":              age,
            "sex":              sex,
            "date":             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trial_number":     "",
            "card_selected":    "",
            "total_before":     "",
            "amount_won":       "",
            "amount_lost":      "",
            "net_change":       "",
            "loss_occurred":    "",
            "total_after":      "",
            "reaction_time_ms": "",
            "questionnaire":    q_name,
            "question_number":  i + 1,
            "question_text":    item,
            "response_value":   responses[i] + 1,
            "response_label":   labels[responses[i]]
        })

    aperture.disable()
    win.mouseVisible = False


def run_hsps_questionnaire():
    run_scrollable_questionnaire(
        q_name="HSPS",
        items=HSPS_ITEMS,
        labels=HSPS_LABELS,
        intro_text=(
            "Questionnaire 1\n\n"
            "A number of statements which people have used to describe themselves "
            "are given below. Read each statement and then select the response "
            "that indicates how you generally feel.\n\n"
            "There are no right or wrong answers. Do not spend too much time on "
            "any one statement, but give the answer which seems to describe how "
            "you generally feel.\n\n"
            "Thank you.\n\n"
            "Press SPACE to begin."
        )
    )

# ── run HSPS questionnaire ────────────────────────────────────────────────────────
run_hsps_questionnaire()

# ── IUS questionnaire ────────────────────────────────────────────────────────
IUS_ITEMS = [
    "Unforeseen events upset me greatly.",
    "It frustrates me not having all the information I need.",
    "Uncertainty keeps me from living a full life.",
    "One should always look ahead so as to avoid surprises.",
    "A small unforeseen event can spoil everything, even with the best of planning.",
    "When it's time to act, uncertainty paralyses me.",
    "When I am uncertain I can't function very well.",
    "I always want to know what the future has in store for me.",
    "I can't stand being taken by surprise.",
    "The smallest doubt can stop me from acting.",
    "Please select 'A little characteristic of me'.",
    "I should be able to organise everything in advance.",
    "I must get away from all uncertain situations."
]

IUS_LABELS = [
    "Not at all characteristic of me",
    "A little characteristic of me",
    "Somewhat characteristic of me",
    "Very characteristic of me",
    "Entirely characteristic of me"
]

def run_ius_questionnaire():
    run_scrollable_questionnaire(
        q_name="IUS",
        items=IUS_ITEMS,
        labels=IUS_LABELS,
        intro_text=(
            "Questionnaire 2\n\n"
            "You will find below a series of statements which describe how people "
            "may react to the uncertainties of life.\n\n"
            "Please use the scale below to describe to what extent each item is "
            "characteristic of you.\n\n"
            "Press SPACE to begin."
        )
    )

# ── run IUS questionnaire ────────────────────────────────────────────────────────
run_ius_questionnaire()

# ── End Experiment screen ────────────────────────────────────────────────────────────────
show_text(
    f"You have reached the end of the experiment.\n\n"
    f"Thank you for participating.\n\n"
    f"Press SPACE to continue.",
    wait_for_key=True
)

# ── Cleanup ───────────────────────────────────────────────────────────────────
if USE_LABCHART and _port is not None:
    _port.setData(0)

win.close()
core.quit()