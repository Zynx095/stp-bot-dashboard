from ultralytics import YOLO
import cv2
import time
import numpy as np
import serial

# -------- SYSTEM CONFIG --------
MISS_LIMIT = 15 # Increased to give a 0.5 second grace period
USE_ARDUINO = True  
COM_PORT = 'COM5'   # <--- DOUBLE CHECK THIS! IF USING USB CABLE, IT IS LIKELY COM3 OR COM4!
BAUD_RATE = 9600

print("[SYS] Booting Neural Net...")
model = YOLO("yolov8n.pt")
cap = cv2.VideoCapture(1) # Remember to change to 0 if using laptop webcam!

cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

# -------- HUD SETTINGS & MAPPING --------
CENTER_THRESHOLD = 60
CONF_THRESHOLD = 0.50 # Lowered slightly so it tracks easier
CLOSE_Y_PIXELS = 80 
PUMP_DURATION_FRAMES = 40

DEMO_MAP = {
    # --- HARD SLUDGE (Uses 'P' Pulse Mode) ---
    "cell phone": {"type": "PHONE", "class": "HARD SLUDGE", "chem": "ACIDIC SOLVENT V9", "auger": "P", "color": (0, 0, 255)},
    "mouse": {"type": "EARBUDS", "class": "HARD SLUDGE", "chem": "ACIDIC SOLVENT V9", "auger": "P", "color": (0, 0, 255)},
    "remote": {"type": "EARBUDS", "class": "HARD SLUDGE", "chem": "ACIDIC SOLVENT V9", "auger": "P", "color": (0, 0, 255)},
    
    # --- SOFT SLUDGE (Uses 'X' Normal Mode) ---
    "bottle": {"type": "BISLERI BOTTLE", "class": "SOFT SLUDGE", "chem": "BIO-ENZYME Q4", "auger": "X", "color": (0, 255, 0)}, 
    "cup": {"type": "REDBULL CAN", "class": "SOFT SLUDGE", "chem": "BIO-ENZYME Q4", "auger": "X", "color": (0, 255, 0)} 
}

COMMAND_MAP = {
    "LEFT": "L", "RIGHT": "R", "FORWARD": "F", "STOP": "S"
}

def draw_hud_brackets(img, x1, y1, x2, y2, color, thickness=2, length=20):
    cv2.line(img, (x1, y1), (x1 + length, y1), color, thickness)
    cv2.line(img, (x1, y1), (x1, y1 + length), color, thickness)
    cv2.line(img, (x2, y1), (x2 - length, y1), color, thickness)
    cv2.line(img, (x2, y1), (x2, y1 + length), color, thickness)
    cv2.line(img, (x1, y2), (x1 + length, y2), color, thickness)
    cv2.line(img, (x1, y2), (x1, y2 - length), color, thickness)
    cv2.line(img, (x2, y2), (x2 - length, y2), color, thickness)
    cv2.line(img, (x2, y2), (x2, y2 - length), color, thickness)

# -------- VARIABLES --------
locked_track_id = None
miss_count = 0
action_state = "SCANNING" 
pump_timer = 0
collect_timer = 0 
last_command = "S"
arduino = None
ai_auger_active = False

saved_auger_cmd = "X"
saved_chem = "NONE"

def try_connect_serial():
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"\n[SYS] >>> PORT {COM_PORT} ACQUIRED. YOLO VISION IN CONTROL <<<\n")
        time.sleep(2) # Give Arduino time to wake up
        return ser
    except serial.SerialException:
        return None

# -------- MAIN LOOP --------
while True:
    ret, frame = cap.read()
    if not ret: break

    if USE_ARDUINO and arduino is None:
        arduino = try_connect_serial()

    h, w = frame.shape[:2]
    frame_center = w // 2
    hud = frame.copy()

    cv2.line(hud, (frame_center, 0), (frame_center, h), (0, 255, 209), 1)
    cv2.line(hud, (0, h//2), (w, h//2), (0, 255, 209), 1)
    cv2.circle(hud, (frame_center, h//2), CENTER_THRESHOLD, (0, 255, 209), 1)
    cv2.line(hud, (0, h - CLOSE_Y_PIXELS), (w, h - CLOSE_Y_PIXELS), (0, 0, 255), 2)
    cv2.putText(hud, "COLLECTION ZONE", (10, h - CLOSE_Y_PIXELS - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    results = model.track(frame, persist=True, imgsz=320, verbose=False)
    detections = []

    if results[0].boxes is not None:
        for box in results[0].boxes:
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD or box.id is None: continue

            label = model.names[int(box.cls[0])]
            if label not in DEMO_MAP: continue

            demo_info = DEMO_MAP[label]
            track_id = int(box.id[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cx = (x1 + x2) // 2
            
            detections.append({
                "track_id": track_id, "box": (x1, y1, x2, y2),
                "cx": cx, "y2": y2, "area": (x2 - x1) * (y2 - y1),
                "type": demo_info["type"], "class": demo_info["class"],
                "chem": demo_info["chem"], "color": demo_info["color"],
                "auger_cmd": demo_info["auger"] 
            })

    detections.sort(key=lambda d: -d["area"])

    current_locked_det = None
    if locked_track_id is not None:
        for d in detections:
            if d["track_id"] == locked_track_id:
                current_locked_det = d
                break
        
        # THE FIX: Proper Miss Counting
        if current_locked_det: 
            miss_count = 0
        else:
            miss_count += 1
            if miss_count > MISS_LIMIT: 
                locked_track_id = None

    if locked_track_id is None and detections:
        current_locked_det = detections[0]
        locked_track_id = current_locked_det["track_id"]
        miss_count = 0

    # ==========================================
    # AI CALCULATES INTENDED MOVE 
    # ==========================================
    move = "STOP"
    command = "S"
    
    in_blind_sequence = action_state in ["PUMPING", "COLLECTING_BITE", "COLLECTING_REVERSE", "COLLECTING_WAIT"]

    if in_blind_sequence:
        move = "STOP"
        
        if action_state == "PUMPING":
            pump_timer += 1
            if pump_timer < PUMP_DURATION_FRAMES: 
                command = "P" # Pumping UI
            else:
                command = "O" 
                action_state = "COLLECTING_BITE"
                collect_timer = 0
                
        elif action_state == "COLLECTING_BITE":
            collect_timer += 1
            command = saved_auger_cmd 
            ai_auger_active = True
            
            if collect_timer > 135: 
                command = "x" 
                ai_auger_active = False
                action_state = "COLLECTING_REVERSE"
                collect_timer = 0
                
        elif action_state == "COLLECTING_REVERSE":
            collect_timer += 1
            command = "B" 
            if collect_timer > 15:
                command = "S" 
                action_state = "COLLECTING_WAIT"
                collect_timer = 0
                
        elif action_state == "COLLECTING_WAIT":
            collect_timer += 1
            command = "S"
            if collect_timer > 15:
                action_state = "SCANNING" 
                locked_track_id = None 

    else:
        # THE FIX: If we have a target OR we are within the grace period buffer
        if current_locked_det or (locked_track_id is not None and miss_count <= MISS_LIMIT):
            
            # If currently visible, use the real coordinates. If in grace period, just keep last command!
            if current_locked_det:
                cx = current_locked_det["cx"]
                is_close = current_locked_det["y2"] > (h - CLOSE_Y_PIXELS)
                needs_chem = current_locked_det["chem"] != "NONE"

                if not is_close:
                    action_state = "APPROACHING"
                    if ai_auger_active:
                        command = "x"
                        ai_auger_active = False
                    else:
                        if cx < frame_center - CENTER_THRESHOLD: move = "LEFT"
                        elif cx > frame_center + CENTER_THRESHOLD: move = "RIGHT"
                        else: move = "FORWARD"
                        command = COMMAND_MAP.get(move, "S")
                else:
                    move = "STOP"
                    saved_auger_cmd = current_locked_det["auger_cmd"]
                    saved_chem = current_locked_det["chem"]
                    
                    if needs_chem:
                        action_state = "PUMPING"
                        pump_timer = 0
                    else:
                        action_state = "COLLECTING_BITE"
                        collect_timer = 0
            else:
                # WE ARE IN THE GRACE PERIOD (Camera blinked!)
                # Just repeat whatever the last physical command was!
                command = last_command
                action_state = "TRACKING THRU BLINK"

        else:
            # Fully lost target (exceeded miss limit)
            action_state = "SCANNING"
            if ai_auger_active:
                command = "x"
                ai_auger_active = False
            else:
                command = "S" 

    # ==========================================
    # SEND TO ARDUINO
    # ==========================================
    if arduino:
        try:
            if arduino.in_waiting > 0:
                arduino.reset_input_buffer()

            arduino_cmd = command
            if action_state == "PUMPING" and command == "P": 
                arduino_cmd = "S" 

            if arduino_cmd != last_command:
                arduino.write(arduino_cmd.encode())
                print(f"[CMD TX] >> {arduino_cmd}")
                last_command = arduino_cmd

        except Exception as e:
            pass

    # -------- DRAW TARGETS & TELEMETRY --------
    for d in detections:
        x1, y1, x2, y2 = d["box"]
        color = d["color"]
        is_locked = (d["track_id"] == locked_track_id)
        
        thickness = 3 if is_locked else 1
        draw_hud_brackets(hud, x1, y1, x2, y2, color, thickness, 30)
        
        if is_locked:
            cv2.line(hud, (frame_center, h), (x1 + (x2-x1)//2, y2), color, 1)

        tag_y = y1 - 25 if y1 > 30 else y2 + 20
        cv2.putText(hud, f"[{d['type']}]", (x1, tag_y), cv2.FONT_HERSHEY_PLAIN, 1.2, color, 2)
        cv2.putText(hud, f"CLS: {d['class']} | TRG: {d['track_id']}", (x1, tag_y + 15), cv2.FONT_HERSHEY_PLAIN, 1.0, color, 1)

    panel_w = 400
    cv2.rectangle(hud, (10, 10), (panel_w, 130), (10, 10, 15), -1)
    
    if arduino:
        panel_color = (0, 255, 209) 
        status_text = action_state
    else:
        panel_color = (0, 100, 255) 
        status_text = "WEB DASHBOARD IN CONTROL"
        
    cv2.rectangle(hud, (10, 10), (panel_w, 130), panel_color, 1)
    cv2.putText(hud, f"SYS_STATE : {status_text}", (20, 35), cv2.FONT_HERSHEY_PLAIN, 1.2, panel_color, 2)
    cv2.putText(hud, f"DRIVE     : {move}", (20, 60), cv2.FONT_HERSHEY_PLAIN, 1.2, (255, 255, 255), 1)
    
    if current_locked_det:
        cv2.putText(hud, f"LOCK      : {current_locked_det['type']}", (20, 85), cv2.FONT_HERSHEY_PLAIN, 1.2, current_locked_det['color'], 1)
        cv2.putText(hud, f"CHEM_REQ  : {current_locked_det['chem']}", (20, 110), cv2.FONT_HERSHEY_PLAIN, 1.2, (200, 200, 200), 1)
    elif in_blind_sequence:
        cv2.putText(hud, f"LOCK      : EXECUTING BLIND", (20, 85), cv2.FONT_HERSHEY_PLAIN, 1.2, (0, 165, 255), 1)
        cv2.putText(hud, f"CHEM_REQ  : {saved_chem}", (20, 110), cv2.FONT_HERSHEY_PLAIN, 1.2, (200, 200, 200), 1)
    else:
        cv2.putText(hud, "LOCK      : NONE", (20, 85), cv2.FONT_HERSHEY_PLAIN, 1.2, (100, 100, 100), 1)
        cv2.putText(hud, "CHEM_REQ  : STANDBY", (20, 110), cv2.FONT_HERSHEY_PLAIN, 1.2, (100, 100, 100), 1)

    if action_state == "PUMPING":
        cv2.rectangle(hud, (w//2 - 200, h//2 - 50), (w//2 + 200, h//2 + 50), (0, 0, 255), -1)
        cv2.putText(hud, f"SPRAYING: {saved_chem}", (w//2 - 180, h//2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    elif action_state == "COLLECTING_BITE":
        msg = "PULSE AUGER ENGAGED" if saved_auger_cmd == "P" else "NORMAL AUGER ENGAGED"
        ui_color = (0, 0, 255) if saved_auger_cmd == "P" else (0, 255, 0)
        
        cv2.rectangle(hud, (w//2 - 200, h//2 - 40), (w//2 + 200, h//2 + 40), ui_color, -1)
        cv2.putText(hud, msg, (w//2 - 180, h//2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 3)
    elif action_state == "COLLECTING_REVERSE":
        cv2.rectangle(hud, (w//2 - 180, h//2 - 40), (w//2 + 180, h//2 + 40), (0, 165, 255), -1)
        cv2.putText(hud, "ASSESSING CLEARANCE", (w//2 - 160, h//2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 3)

    final_frame = cv2.addWeighted(frame, 0.3, hud, 0.7, 0)
    cv2.imshow("BIO-HAZ TARGETING SYSTEM", final_frame)
    if cv2.waitKey(1) & 0xFF == 27: break

cap.release()
if arduino: arduino.close()
cv2.destroyAllWindows()