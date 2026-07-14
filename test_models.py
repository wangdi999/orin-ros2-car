"""
YOLO 双模型测试脚本 — 笔记本摄像头实时检测
person: 绿色框 | crack: 橙色框
按 q 退出
"""
import cv2
from ultralytics import YOLO

# 加载模型
person_model = YOLO("yolov8n.pt")  # 首次自动下载
crack_model = YOLO("smart_car_ws/models/crack_yolo.pt")

# Windows需要DirectShow后端
import sys
cap = None
for idx in [0, 1, 2]:
    test = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if test.isOpened():
        cap = test
        print(f"摄像头 {idx} 已打开")
        break
    test.release()
if cap is None:
    if len(sys.argv) > 1:
        # 图片模式
        img = cv2.imread(sys.argv[1])
        person_results = person_model(img, conf=0.5, classes=[0], verbose=False)
        crack_results = crack_model(img, conf=0.35, verbose=False)
        for box in (person_results[0].boxes or []):
            x1,y1,x2,y2 = map(int, box.xyxy[0])
            cv2.rectangle(img,(x1,y1),(x2,y2),(0,255,0),2)
            cv2.putText(img,f"person {float(box.conf[0]):.2f}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),1)
        for box in (crack_results[0].boxes or []):
            x1,y1,x2,y2 = map(int, box.xyxy[0])
            cv2.rectangle(img,(x1,y1),(x2,y2),(0,165,255),2)
            cv2.putText(img,f"crack {float(box.conf[0]):.2f}",(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,165,255),1)
        cv2.imshow("Result", img)
        print("按任意键退出"); cv2.waitKey(0); cv2.destroyAllWindows()
        exit(0)
    print("未找到摄像头！用图片: python test_models.py 图片.jpg")
    exit(1)
print("按 q 退出测试")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 人员检测
    pr = person_model(frame, conf=0.5, classes=[0], verbose=False)
    for box in pr[0].boxes or []:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"person {conf:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # 裂缝检测
    cr = crack_model(frame, conf=0.35, verbose=False)
    for box in cr[0].boxes or []:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
        cv2.putText(frame, f"crack {conf:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)

    cv2.imshow("YOLO Test: Green=Person  Orange=Crack", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:  # q 或 ESC
        break

cap.release()
cv2.destroyAllWindows()
