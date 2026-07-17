<img width="1113" height="1032" alt="ScreenShot_2026-07-14_162850_354" src="https://github.com/user-attachments/assets/e056e3dc-c1da-44bf-af8d-095e0cd4d678" />
<img width="782" height="812" alt="ScreenShot_2026-07-14_162832_600" src="https://github.com/user-attachments/assets/dcee5e52-f41f-4d5f-8c7c-8845d66f5bf7" />
<img width="782" height="812" alt="ScreenShot_2026-07-14_162820_718" src="https://github.com/user-attachments/assets/57110fed-2ea5-45e3-8978-88548fa941b4" />
<img width="782" height="812" alt="ScreenShot_2026-07-14_162806_318" src="https://github.com/user-attachments/assets/3a8cd6ac-ce83-4c94-9779-9ce6b62ca8b5" />
<img width="1080" height="2340" alt="微信图片_20260704170317_8_70" src="https://github.com/user-attachments/assets/0a7ab8e1-cc98-4988-82d4-bd0b42bb7fce" />
<img width="1080" height="2340" alt="微信图片_20260704170316_7_70" src="https://github.com/user-attachments/assets/660459b5-950b-40ac-ac71-0aeba2b0b48c" />
<img width="1080" height="2340" alt="微信图片_20260717140202_10_70" src="https://github.com/user-attachments/assets/148edc09-532d-4a72-94a0-03d5aad1a429" />

# PPT 遥控

> 本地 Qt 客户端 + Python 控制端 + MediaPipe 9 事件手势控制 PPT 放映的端到端方案。

## 目录

1. 项目概览
2. 核心特性
3. 系统截图
4. 系统架构
5. 9 事件手势速查
6. 快速开始
7. 配置说明
8. 开发与测试
9. 目录结构
10. 常见问题
11. 许可与致谢
12. 相关文档

---

## 1. 项目概览

PPT 遥控 是一个跨进程 + 跨设备的 PPT 演示控制系统，设计为演讲者在台上、助手在台下用手机/平板辅助控制场景。

```
[手机/平板/Web]  <==  WebSocket  <==  [ppt_qt 客户端(本地 Qt)]  <==IPC
                                                                  ↓
                                                      [ppt_pc_client(Python 控制端)]
                                                                  ↓
                                                       键盘/鼠标 事件 → PPT
```

PPT 实际放映在本地，操作者可远程用任何能发 WebSocket 的设备控制。

## 2. 核心特性

| 类别 | 能力 |
|------|------|
| 手势控制 | 9 事件 tip-touch + 双手 interlock:拇指尖触发 4 指尖 + 双手 10 指相扣 |
| 多端控制 | 桌面/iPad/iPhone/任何 WebSocket 客户端 |
| 鼠标模拟 | pynput 跨平台鼠标事件(Win/macOS/Linux) |
| PPT 控制 | COM-first + pyautogui fallback，执行 11 个命令 |
| 截屏 | 一键截图(桌面端 + 移动端) |
| 文件传输 | 手机扫码下载本地 PPT/截图 |
| 演讲者备注 | MediaPipe/COM 读取 + WebSocket 推送到手机 |
| 双模 | 桌面(直接控制) + 远程(WS 控制) |
| 隐私 | 所有数据本地，无云端；可脱机使用 |

## 3. 系统截图

> 截图待补(主窗口 + 移动端界面 + 手势检测区域)
> 建议从 `ppt_files/screen_*.png` 中挑 1-2 张主界面图插入此处。

## 4. 系统架构

```
┌──────────────────────────────────────────────────────────┐
│  移动端/Web 客户端(任何能发 WS 的设备)                 │
└─────────────────────┬────────────────────────────────────┘
                      │ wss://
                      ▼
┌──────────────────────────────────────────────────────────┐
│  ppt_qt 客户端(PySide6 / Python 3.12)                 │
│  UI: 主窗口 + 4 个页面(连接/行为/传输/手势)        │
│  Engine: cv2 + mediapipe HandLandmarker → FrameSnapshot   │
│  Bridge: 9 事件 + 3 特征投票 → CommandDispatcher        │
│  WS Client: websockets asyncio                          │
└─────────────────────┬────────────────────────────────────┘
                      │ IPC(本地子进程 stdio)
                      ▼
┌──────────────────────────────────────────────────────────┐
│  ppt_pc_client 控制端(Python 3.12 跨平台)              │
│  pynput  → 键盘/鼠标(跨平台)                            │
│  ppt_executor → COM(PowerPoint) + pyautogui fallback    │
│  ppt_notes → COM 读演讲者备注                           │
│  mouse_render_thread → pyautogui(50Hz, pynput 序列化)  │
└──────────────────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────┐
│  PowerPoint(Win)/ Keynote(macOS)/ LibreOffice(Linux)   │
└──────────────────────────────────────────────────────────┘
```

进程职责

| 进程 | 角色 | 关键技术 |
|------|------|----------|
| ppt_qt | UI + 摄像头 + MediaPipe | PySide6, cv2, mediapipe |
| ppt_pc_client | 系统级输入模拟 + PPT COM | pynput, pyautogui, comtypes |


## 5. 9 事件手势速查

每个事件基于「拇指尖到目标指尖的归一化距离」，阈值 < tip_touch_ratio (默认 0.55 = 55% 手掌参考长度)。

| # | 事件 | 触发 | 默认动作 |
|---|------|------|----------|
| 1 | L_HAND_INDEX | 左手拇指触食指 | NEXT_PAGE |
| 2 | L_HAND_MIDDLE | 左手拇指触中指 | PREV_PAGE |
| 3 | L_HAND_RING | 左手拇指触无名指 | FULL_SCREEN |
| 4 | L_HAND_PINKY | 左手拇指触小拇指 | FROM_CURRENT |
| 5 | R_HAND_INDEX | 右手拇指触食指 | BLACK_SCREEN |
| 6 | R_HAND_MIDDLE | 右手拇指触中指 | WHITE_SCREEN |
| 7 | R_HAND_RING | 右手拇指触无名指 | EXIT |
| 8 | R_HAND_PINKY | 右手拇指触小拇指 | SCREENSHOT |
| 9 | HANDS_INTERLOCK | 双手十指相扣 (≥ 2s 持续) | OPEN_PPT |
## 💰 打赏支持
如果项目对你有帮助，可以小小打赏鼓励一下~

<img src="https://github.com/user-attachments/assets/fd7b9a58-7fa6-4f8e-b6c3-e2c40f3cb1fa" width="559" height="762" style="display:inline-block;margin-right:20px;"/>
<img src="https://github.com/user-attachments/assets/9684ab77-8cd8-475a-b44e-793091ec1885" width="540" height="809" style="display:inline-block;"/>

