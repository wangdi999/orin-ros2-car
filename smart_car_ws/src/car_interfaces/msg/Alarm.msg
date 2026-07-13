# AI报警消息定义
# 发布者: car_ai_vision/yolov8_inference
# 话题: /chassis/ai_alarm

# 危险类别枚举
string danger_type       # person_detected | abnormal_behavior | cracked_tile(预留)

# 检测置信度 [0.0, 1.0]
float32 confidence

# ISO 8601 UTC 时间戳，格式如 "2026-07-10T15:30:00Z"
string timestamp

# 目标位置坐标（优先map坐标，TF转换失败时回退odom）
float32 pos_x
float32 pos_y

# 坐标参考系标识: "map" 或 "odom"
string coord_frame

# 检测框信息（像素坐标，用于可视化参考）
float32 bbox_center_x
float32 bbox_center_y
float32 bbox_width
float32 bbox_height
