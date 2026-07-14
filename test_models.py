"""
YOLO 双模型高精度测试 — 笔记本摄像头
person: 绿色框 (YOLOv8s + 体型过滤)
crack:  橙色框 (多帧一致性 + TTA + 后处理)
按 q / ESC 退出
"""
import cv2, sys, os, time
import numpy as np
from collections import deque
from ultralytics import YOLO

# ============================================================
# 加载模型
# ============================================================
print("加载 YOLOv8s (person)...")
person_model = YOLO("yolov8s.pt")
print("加载 crack 模型...")
crack_pt = "smart_car_ws/models/crack.pt"
if not os.path.exists(crack_pt):
    crack_pt = "smart_car_ws/models/crack_yolo.pt"
crack_model = YOLO(crack_pt)

# ============================================================
# 参数
# ============================================================
PERSON_CONF = 0.55;  PERSON_IOU = 0.45
CRACK_CONF = 0.40;   CRACK_IOU = 0.50
CRACK_MIN_ASPECT = 3.0
CRACK_MIN_AREA = 150; CRACK_MAX_AREA = 60000
CONSIST_FRAMES = 5

# ============================================================
# 后处理
# ============================================================
def filter_person(boxes):
    kept = []
    if boxes is None: return kept
    for box in boxes:
        x1,y1,x2,y2 = map(float, box.xyxy[0])
        conf = float(box.conf[0]); w,h = x2-x1, y2-y1
        aspect = w / max(h, 1e-6)
        if conf < PERSON_CONF: continue
        if aspect < 0.15 or aspect > 3.0: continue
        if w < 30 or h < 50: continue
        kept.append((x1,y1,x2,y2,conf,"person"))
    return kept

def filter_crack(boxes):
    kept = []
    if boxes is None: return kept
    for box in boxes:
        x1,y1,x2,y2 = map(float, box.xyxy[0])
        conf = float(box.conf[0]); w,h = x2-x1, y2-y1
        area = w*h
        aspect = max(w,h) / max(min(w,h), 1e-6)
        if conf < CRACK_CONF: continue
        if aspect < CRACK_MIN_ASPECT: continue
        if area < CRACK_MIN_AREA or area > CRACK_MAX_AREA: continue
        kept.append((x1,y1,x2,y2,conf,"crack"))
    return kept

def iou(a, b):
    x1=max(a[0],b[0]); y1=max(a[1],b[1])
    x2=min(a[2],b[2]); y2=min(a[3],b[3])
    inter = max(0,x2-x1)*max(0,y2-y1)
    area_a = (a[2]-a[0])*(a[3]-a[1])
    area_b = (b[2]-b[0])*(b[3]-b[1])
    return inter/max(area_a+area_b-inter, 1e-6)

def consistency(new_dets, history, iou_th=0.5, min_frames=CONSIST_FRAMES):
    if not new_dets: return []
    stable = []
    for det in new_dets:
        cnt = 1
        for past in history:
            for pd in past:
                if iou(det[:4], pd[:4]) > iou_th:
                    cnt += 1; break
        if cnt >= min_frames:
            stable.append(det)
    return stable

def tta_crack(model, frame):
    r1 = model(frame, conf=CRACK_CONF, iou=CRACK_IOU, verbose=False)
    flipped = cv2.flip(frame, 1)
    r2 = model(flipped, conf=CRACK_CONF, iou=CRACK_IOU, verbose=False)
    b1 = filter_crack(r1[0].boxes or [])
    b2_raw = r2[0].boxes or []
    fw = frame.shape[1]
    b2 = []
    for box in b2_raw:
        x1,y1,x2,y2 = map(float, box.xyxy[0])
        b2.append((fw-x2, y1, fw-x1, y2, float(box.conf[0]), "crack"))
    b2 = filter_crack(None if not b2 else None)  # manual filter
    # manual filter for flipped
    b2f = []
    for b in b2_raw:
        x1,y1,x2,y2 = map(float, b.xyxy[0])
        nx1, nx2 = fw-x2, fw-x1
        conf = float(b.conf[0]); w,h = nx2-nx1, y2-y1
        area = w*h; aspect = max(w,h)/max(min(w,h),1e-6)
        if conf < CRACK_CONF: continue
        if aspect < CRACK_MIN_ASPECT: continue
        if area < CRACK_MIN_AREA or area > CRACK_MAX_AREA: continue
        b2f.append((nx1,y1,nx2,y2,conf,"crack"))
    # TTA intersection
    final = []
    for a in b1:
        for b in b2f:
            if iou(a[:4], b[:4]) > 0.5:
                final.append((*a[:4], (a[4]+b[4])/2, "crack"))
                break
    return final

# ============================================================
# 摄像头
# ============================================================
cap = None
for idx in [0,1,2]:
    t = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if t.isOpened(): cap = t; print(f"Camera {idx} OK"); break
    t.release()

if cap is None:
    if len(sys.argv) > 1:
        img = cv2.imread(sys.argv[1])
        pr = person_model(img, conf=PERSON_CONF, iou=PERSON_IOU, classes=[0], verbose=False)
        cr = crack_model(img, conf=CRACK_CONF, iou=CRACK_IOU, verbose=False)
        pb = filter_person(pr[0].boxes or [])
        cb = filter_crack(cr[0].boxes or [])
        for b in pb+cb:
            x1,y1,x2,y2 = map(int, b[:4])
            c = (0,255,0) if b[5]=="person" else (0,165,255)
            cv2.rectangle(img,(x1,y1),(x2,y2),c,2)
            cv2.putText(img,f"{b[5]} {b[4]:.2f}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,c,1)
        cv2.imshow("Result", img)
        print(f"person:{len(pb)} crack:{len(cb)}"); cv2.waitKey(0)
        exit(0)
    print("No camera. Use: python test_models.py image.jpg"); exit(1)

# ============================================================
# 主循环
# ============================================================
print("q/ESC to quit")
ch = deque(maxlen=CONSIST_FRAMES)
fc = 0; lt = time.time()

while True:
    ret, frame = cap.read()
    if not ret: break
    fc += 1

    pr = person_model(frame, conf=PERSON_CONF, iou=PERSON_IOU, classes=[0], verbose=False)
    pb = filter_person(pr[0].boxes or [])

    cb_tta = tta_crack(crack_model, frame)
    ch.append(cb_tta)
    cb = consistency(cb_tta, ch)

    for b in pb:
        x1,y1,x2,y2 = map(int, b[:4])
        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,0),2)
        cv2.putText(frame,f"person {b[4]:.2f}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),1)
    for b in cb:
        x1,y1,x2,y2 = map(int, b[:4])
        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,165,255),2)
        cv2.putText(frame,f"crack {b[4]:.2f}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,165,255),1)

    now = time.time()
    if now - lt > 3:
        fps = fc/(now-lt)
        print(f"FPS:{fps:.0f} p:{len(pb)} c_tta:{len(cb_tta)} c_stable:{len(cb)}")
        fc=0; lt=now

    cv2.imshow("YOLO Test: Green=Person Orange=Crack", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27: break

cap.release(); cv2.destroyAllWindows()
