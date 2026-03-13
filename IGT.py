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
TOTAL_TRIALS   = 10
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
    size=[1280, 800],
    fullscr=True,
    color=[-0.85, -0.85, -0.6],
    units="pix",
    allowGUI=False
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

# ── Welcome ───────────────────────────────────────────────────────────────────
show_text(
    "Iowa Gambling Task\n\n"
    "Welcome to this experiment.\n\n"
    "Press SPACE to read the instructions.",
    wait_for_key=True
)

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