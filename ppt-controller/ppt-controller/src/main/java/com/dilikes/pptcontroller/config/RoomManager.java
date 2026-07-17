package com.dilikes.pptcontroller.config;

import jakarta.websocket.Session;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 房间管理工具类（优化版：低延迟、高并发、无阻塞、无冗余）
 * 适用于 PPT 遥控器：小程序端发送指令 → 服务端转发 → Python 端执行鼠标/键盘
 */
public class RoomManager {

    // 线程安全的房间存储（不变更，直接final）
    public static final Map<String, RoomSession> ROOM_MAP = new ConcurrentHashMap<>();

    // ====================== 1. 加入房间（优化：原子操作，无重复创建） ======================
    public static void addSession(String roomId, String clientType, Session session) {
        // 原子获取或创建房间（比 getOrDefault + put 更高效、线程安全）
        RoomSession roomSession = ROOM_MAP.computeIfAbsent(roomId, RoomSession::new);

        if ("mini".equals(clientType)) {
            roomSession.setMiniSession(session);
            if (null != roomSession.getPythonSession() && roomSession.getPythonSession().isOpen()){
                roomSession.getPythonSession().getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"ONLINE\"}");
                session.getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"ONLINE\"}");
            }

        } else if ("python".equals(clientType)) {
            roomSession.setPythonSession(session);
            if (null != roomSession.getMiniSession() && roomSession.getMiniSession().isOpen()){
                roomSession.getMiniSession().getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"ONLINE\"}");
                session.getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"ONLINE\"}");
            }
        }else if ("mp".equals(clientType)) {
            roomSession.setMiniSession(session);
            if (null != roomSession.getPythonSession() && roomSession.getPythonSession().isOpen()){
                roomSession.getPythonSession().getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"ONLINE\"}");
                session.getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"ONLINE\"}");
            }

        }

        System.out.println("【房间】客户端连接成功：" + clientType + "，房间号：" + roomId);
    }

    // ====================== 2. 消息转发：按发送方互推（mini/mp ↔ python） ======================
    /** HTTP 等非 WebSocket 来源：只推给 Python（如 FILE_ARRIVED） */
    public static void forwardToTarget(String roomId, String message) {
        forwardToTarget(roomId, message, null);
    }

    public static void forwardToTarget(String roomId, String message, Session sender) {
        RoomSession roomSession = ROOM_MAP.get(roomId);
        if (roomSession == null) {
            System.out.println("【房间】不存在：" + roomId);
            return;
        }

        Session miniSession = roomSession.getMiniSession();
        Session pythonSession = roomSession.getPythonSession();
        try {
            if (sender == null) {
                if (pythonSession != null && pythonSession.isOpen()) {
                    pythonSession.getAsyncRemote().sendText(message);
                } else {
                    System.out.println("【转发跳过】房间：" + roomId + "，HTTP 推送但 Python 端未连接");
                }
                return;
            }
            if (miniSession != null && sender.getId().equals(miniSession.getId())) {
                if (pythonSession != null && pythonSession.isOpen()) {
                    pythonSession.getAsyncRemote().sendText(message);
                } else {
                    System.out.println("【转发跳过】房间：" + roomId + "，小程序已发消息但 Python 端未连接（请使用 /ws/python/房间号 连接）");
                }
            } else if (sender != null && pythonSession != null && sender.getId().equals(pythonSession.getId())) {
                if (miniSession != null && miniSession.isOpen()) {
                    miniSession.getAsyncRemote().sendText(message);
                } else {
                    System.out.println("【转发跳过】房间：" + roomId + "，Python 已发消息但小程序端未连接");
                }
            } else {
                System.out.println("【转发跳过】房间：" + roomId + "，发送方 Session 与房间内 mini/python 不匹配（是否两端都连成了同一 clientType？）");
            }
        } catch (Exception e) {
            System.err.println("【转发失败】房间：" + roomId + "，错误：" + e.getMessage());
        }
    }

    // ====================== 3. 断开连接（优化：原子清理、快速销毁） ======================
    public static void removeSession(String roomId, String clientType) {
        RoomSession roomSession = ROOM_MAP.get(roomId);
        if (roomSession == null) return;
        System.out.println("【房间】removeSession：" + roomId+"  "+clientType);
        // 清空对应端
        if ("mini".equals(clientType)) {
            roomSession.setMiniSession(null);
            //向python 端发送离线消息
            if (null != roomSession.getPythonSession() && roomSession.getPythonSession().isOpen()){
                roomSession.getPythonSession().getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"OFFLINE\"}");
            }


        } else if ("python".equals(clientType)) {
            roomSession.setPythonSession(null);
            //向小程序端发送离线消息
            if (null != roomSession.getMiniSession() && roomSession.getMiniSession().isOpen()){
                roomSession.getMiniSession().getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"OFFLINE\"}");
            }
        }else if ("mp".equals(clientType)) {
            roomSession.setMiniSession(null);
            //向python 端发送离线消息
            if (null != roomSession.getPythonSession() && roomSession.getPythonSession().isOpen()){
                roomSession.getPythonSession().getAsyncRemote().sendText("{\"roomId\":\""+roomId+"\",\"cmd\":\"OFFLINE\"}");
            }


        }

        // 两端都为空 → 销毁房间
        if (roomSession.getMiniSession() == null && roomSession.getPythonSession() == null) {
            roomSession.closeAll();
            ROOM_MAP.remove(roomId);
            System.out.println("【房间】已销毁：" + roomId);
        }
    }


}
